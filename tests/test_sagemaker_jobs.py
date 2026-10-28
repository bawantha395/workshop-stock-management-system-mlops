import io
import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path
from unittest.mock import Mock

import botocore.session
import pytest
from botocore.exceptions import ClientError
from botocore.validate import validate_parameters

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'mlops'))
import sagemaker_jobs as jobs  # noqa: E402

SCHEMA = botocore.session.get_session().get_service_model('sagemaker')
IMAGE = '123456789012.dkr.ecr.ap-southeast-2.amazonaws.com/stocklane-dev/ml-training@sha256:' + 'a' * 64
ROLE = 'arn:aws:iam::123456789012:role/stocklane-dev-sagemaker-training'


def test_processing_is_the_default_and_uses_the_t3_processing_quota(monkeypatch):
    monkeypatch.delenv('SAGEMAKER_JOB_TYPE', raising=False)
    monkeypatch.delenv('SAGEMAKER_INSTANCE_TYPE', raising=False)
    sm = Mock()
    sm.create_processing_job.return_value = {'ProcessingJobArn': 'arn:processing'}
    kind, arn = jobs.start(sm, 'stocklane-dev-20261028-120000', ROLE, IMAGE,
        [('dataset', 's3://owned/datasets/abc/'), ('encoder', 's3://owned/encoders/def/')],
        's3://owned/training/', {'task': 'visual_sku'})
    assert (kind, arn) == ('processing', 'arn:processing')
    sm.create_training_job.assert_not_called()
    request = sm.create_processing_job.call_args.kwargs
    validate_parameters(request, SCHEMA.operation_model('CreateProcessingJob').input_shape)
    assert request['ProcessingResources']['ClusterConfig']['InstanceType'] == 'ml.t3.large'
    assert request['NetworkConfig'] == {'EnableNetworkIsolation': True}
    assert request['AppSpecification']['ImageUri'] == IMAGE
    assert [i['S3Input']['LocalPath'] for i in request['ProcessingInputs']] == [
        '/opt/ml/processing/input/dataset', '/opt/ml/processing/input/encoder']
    assert request['ProcessingOutputConfig']['Outputs'][0]['S3Output']['S3Uri'] == \
        's3://owned/training/stocklane-dev-20261028-120000/output'
    assert json.loads(request['Environment']['STOCKLANE_HYPERPARAMETERS']) == {'task': 'visual_sku'}
    assert json.loads(request['Environment']['STOCKLANE_CHANNELS']) == ['dataset', 'encoder']
    assert all(len(v) <= 256 for k, v in request['Environment'].items() if k != 'STOCKLANE_HYPERPARAMETERS')


def test_training_mode_keeps_the_original_training_job_request(monkeypatch):
    monkeypatch.setenv('SAGEMAKER_JOB_TYPE', 'training')
    sm = Mock()
    sm.create_training_job.return_value = {'TrainingJobArn': 'arn:training'}
    kind, _ = jobs.start(sm, 'job', ROLE, IMAGE, [('dataset', 's3://owned/d/')], 's3://owned/training',
                         {'task': 'stock_forecast'}, ['precision'])
    request = sm.create_training_job.call_args.kwargs
    validate_parameters(request, SCHEMA.operation_model('CreateTrainingJob').input_shape)
    assert kind == 'training' and request['ResourceConfig']['InstanceType'] == 'ml.m5.large'
    assert request['StoppingCondition'] == {'MaxRuntimeInSeconds': 600}
    assert request['EnableNetworkIsolation'] is True and request['HyperParameters'] == {'task': 'stock_forecast'}


def test_instance_type_override_and_invalid_mode(monkeypatch):
    monkeypatch.setenv('SAGEMAKER_INSTANCE_TYPE', 'ml.t3.xlarge')
    assert jobs.instance_type() == 'ml.t3.xlarge'
    monkeypatch.setenv('SAGEMAKER_JOB_TYPE', 'spot')
    with pytest.raises(ValueError):
        jobs.job_type()


def test_processing_status_is_returned_in_training_job_shape():
    sm = Mock()
    sm.describe_processing_job.return_value = {'ProcessingJobStatus': 'Completed', 'ProcessingOutputConfig': {
        'Outputs': [{'OutputName': 'model', 'S3Output': {'S3Uri': 's3://owned/training/job/output'}}]}}
    job = jobs.wait(sm, 'processing', 'job', sleep=lambda _: None)
    assert job['TrainingJobStatus'] == 'Completed'
    assert job['ModelArtifacts']['S3ModelArtifacts'] == 's3://owned/training/job/output/model.tar.gz'


def test_failed_processing_job_names_the_log_group_and_requests_stop():
    sm = Mock()
    sm.describe_processing_job.return_value = {'ProcessingJobStatus': 'Failed', 'FailureReason': 'x'}
    sm.stop_processing_job.side_effect = ClientError({'Error': {'Code': 'ValidationException'}}, 'StopProcessingJob')
    with pytest.raises(RuntimeError, match='ProcessingJobs'):
        jobs.wait(sm, 'processing', 'job', sleep=lambda _: None)
    sm.stop_processing_job.assert_called_once_with(ProcessingJobName='job')


def run_wrapper(tmp_path, entrypoint, channels=('dataset',), parameters=None):
    root = tmp_path / 'ml'
    program = tmp_path / 'program'
    program.mkdir()
    (program / 'entrypoint.py').write_text(entrypoint)
    for channel in channels:
        data = root / 'processing' / 'input' / channel
        data.mkdir(parents=True)
        (data / 'rows.txt').write_text(channel)
    env = dict(os.environ, STOCKLANE_ML_ROOT=str(root), STOCKLANE_PROGRAM_DIR=str(program),
               STOCKLANE_CHANNELS=json.dumps(list(channels)),
               STOCKLANE_HYPERPARAMETERS=json.dumps(parameters or {}))
    result = subprocess.run([sys.executable, '-c', jobs.WRAPPER], env=env, capture_output=True, text=True)
    return root, result


ENTRYPOINT = '''
import json,sys
from pathlib import Path
p=json.loads(Path('{root}/input/config/hyperparameters.json').read_text())
rows=Path('{root}/input/data/dataset/rows.txt').read_text()
Path('{root}/model/metrics.json').write_text(json.dumps({{'task':p['task'],'rows':rows,'qualityGatePassed':True}}))
sys.exit({code})
'''


def test_wrapper_maps_inputs_and_packs_model_like_a_training_job(tmp_path):
    root, result = run_wrapper(tmp_path, ENTRYPOINT.format(root=tmp_path / 'ml', code=0),
                               parameters={'task': 'monthly_car_parts_benchmark'})
    assert result.returncode == 0, result.stderr
    with tarfile.open(root / 'processing' / 'output' / 'model.tar.gz') as archive:
        assert archive.getnames() == ['metrics.json']
        metrics = json.load(archive.extractfile('metrics.json'))
    assert metrics == {'task': 'monthly_car_parts_benchmark', 'rows': 'dataset', 'qualityGatePassed': True}


def test_wrapper_fails_when_training_fails(tmp_path):
    root, result = run_wrapper(tmp_path, ENTRYPOINT.format(root=tmp_path / 'ml', code=3),
                               parameters={'task': 'x'})
    assert result.returncode == 3
    assert not (root / 'processing' / 'output' / 'model.tar.gz').exists()


def test_github_training_role_can_run_processing_jobs():
    source = (ROOT / 'infra/aws/ml-observability.tf').read_text()
    assert '"sagemaker:CreateProcessingJob", "sagemaker:DescribeProcessingJob", "sagemaker:StopProcessingJob"' in source
    assert 'processing-job/${var.name}-*' in source


def test_training_image_runs_as_root_so_the_wrapper_can_write_opt_ml():
    dockerfile = (ROOT / 'deploy/docker/Training.Dockerfile').read_text()
    assert 'USER ' not in dockerfile and 'python:3.12' in dockerfile
    assert 'entrypoint.py' in dockerfile
