"""Run the ml-training image as a SageMaker job and return its model archive.

SageMaker training jobs need a per-instance training quota (for example
ml.m5.large). New accounts often have 0 for every training instance while
processing-job quotas (ml.t3.*) are already available. A processing job runs
the same container on SageMaker, so by default this module runs training as a
processing job:

* inputs are mounted where the training entrypoint expects them
  (/opt/ml/input/data/<channel>),
* hyperparameters are written to /opt/ml/input/config/hyperparameters.json,
* /opt/ml/model is packed into model.tar.gz at
  <output_path>/<job name>/output/model.tar.gz, the same layout a training
  job produces, so evaluation and Model Registry code stay unchanged.

Set SAGEMAKER_JOB_TYPE=training to use real training jobs once a training
instance quota is approved. SAGEMAKER_INSTANCE_TYPE overrides the instance.
"""
import json
import os
import signal
import time

from botocore.exceptions import ClientError

TERMINAL = {'Completed', 'Failed', 'Stopped'}
DEFAULTS = {
    'processing': {'instance': 'ml.t3.large', 'runtime': 1800, 'deadline': 2400},
    'training': {'instance': 'ml.m5.large', 'runtime': 600, 'deadline': 1200},
}

# Runs inside the container (python:3.12-slim, root). Kept dependency-free.
WRAPPER = r'''
import json,os,runpy,sys,tarfile
from pathlib import Path
root=Path(os.environ.get('STOCKLANE_ML_ROOT','/opt/ml'))
program=os.environ.get('STOCKLANE_PROGRAM_DIR','/opt/program')
for channel in json.loads(os.environ.get('STOCKLANE_CHANNELS','[]')):
    target=root/'input'/'data'/channel
    target.parent.mkdir(parents=True,exist_ok=True)
    if not target.exists():target.symlink_to(root/'processing'/'input'/channel,target_is_directory=True)
config=root/'input'/'config';config.mkdir(parents=True,exist_ok=True)
(config/'hyperparameters.json').write_text(os.environ.get('STOCKLANE_HYPERPARAMETERS','{}'))
model=root/'model';model.mkdir(parents=True,exist_ok=True)
sys.argv=[program+'/entrypoint.py'];sys.path.insert(0,program)
try:runpy.run_path(program+'/entrypoint.py',run_name='__main__')
except SystemExit as stop:
    if stop.code not in (0,None):raise
output=root/'processing'/'output';output.mkdir(parents=True,exist_ok=True)
with tarfile.open(output/'model.tar.gz','w:gz') as archive:
    for item in sorted(model.iterdir()):archive.add(item,arcname=item.name)
print('Packed',len(list(model.iterdir())),'model file(s) into model.tar.gz',flush=True)
'''


def job_type():
    value = os.environ.get('SAGEMAKER_JOB_TYPE', 'processing').strip().lower()
    if value not in DEFAULTS:
        raise ValueError('SAGEMAKER_JOB_TYPE must be processing or training')
    return value


def instance_type(kind=None):
    return os.environ.get('SAGEMAKER_INSTANCE_TYPE') or DEFAULTS[kind or job_type()]['instance']


def start(sm, name, role, image, channels, output_path, hyperparameters=None, metric_names=None):
    """Create the job and return (job type, ARN). channels is [(name, s3 uri)]."""
    kind = job_type()
    parameters = dict(hyperparameters or {})
    output_path = output_path.rstrip('/')
    if kind == 'training':
        algorithm = {'TrainingImage': image, 'TrainingInputMode': 'File'}
        if metric_names:
            algorithm['MetricDefinitions'] = [{'Name': 'benchmark:' + key, 'Regex': '"' + key + '":\\s*([0-9.eE+-]+)'}
                                              for key in metric_names]
        request = dict(TrainingJobName=name, RoleArn=role, AlgorithmSpecification=algorithm,
            InputDataConfig=[{'ChannelName': channel, 'DataSource': {'S3DataSource': {
                'S3DataType': 'S3Prefix', 'S3Uri': uri, 'S3DataDistributionType': 'FullyReplicated'}}}
                for channel, uri in channels],
            OutputDataConfig={'S3OutputPath': output_path},
            ResourceConfig={'InstanceType': instance_type(kind), 'InstanceCount': 1, 'VolumeSizeInGB': 10},
            StoppingCondition={'MaxRuntimeInSeconds': DEFAULTS[kind]['runtime']}, EnableNetworkIsolation=True)
        if parameters:
            request['HyperParameters'] = parameters
        return kind, sm.create_training_job(**request).get('TrainingJobArn')
    response = sm.create_processing_job(ProcessingJobName=name, RoleArn=role,
        AppSpecification={'ImageUri': image, 'ContainerEntrypoint': ['python', '-c', WRAPPER]},
        Environment={'STOCKLANE_CHANNELS': json.dumps([channel for channel, _ in channels]),
                     'STOCKLANE_HYPERPARAMETERS': json.dumps(parameters), 'TRAINING_JOB_NAME': name},
        ProcessingInputs=[{'InputName': channel, 'S3Input': {'S3Uri': uri,
            'LocalPath': '/opt/ml/processing/input/' + channel, 'S3DataType': 'S3Prefix',
            'S3InputMode': 'File', 'S3DataDistributionType': 'FullyReplicated'}} for channel, uri in channels],
        ProcessingOutputConfig={'Outputs': [{'OutputName': 'model', 'S3Output': {
            'S3Uri': output_path + '/' + name + '/output', 'LocalPath': '/opt/ml/processing/output',
            'S3UploadMode': 'EndOfJob'}}]},
        ProcessingResources={'ClusterConfig': {'InstanceCount': 1, 'InstanceType': instance_type(kind),
                                               'VolumeSizeInGB': 10}},
        StoppingCondition={'MaxRuntimeInSeconds': DEFAULTS[kind]['runtime']},
        NetworkConfig={'EnableNetworkIsolation': True})
    return kind, response.get('ProcessingJobArn')


def describe(sm, kind, name):
    """Return a training-job shaped summary for either job type."""
    if kind == 'training':
        job = sm.describe_training_job(TrainingJobName=name)
        return {'TrainingJobStatus': job['TrainingJobStatus'], 'SecondaryStatus': job.get('SecondaryStatus', ''),
                'ModelArtifacts': job.get('ModelArtifacts', {}), 'FailureReason': job.get('FailureReason'),
                'JobType': 'training'}
    job = sm.describe_processing_job(ProcessingJobName=name)
    outputs = job.get('ProcessingOutputConfig', {}).get('Outputs', [])
    uri = next((o['S3Output']['S3Uri'] for o in outputs if o['OutputName'] == 'model'), None)
    return {'TrainingJobStatus': job['ProcessingJobStatus'], 'SecondaryStatus': '',
            'ModelArtifacts': {'S3ModelArtifacts': uri.rstrip('/') + '/model.tar.gz'} if uri else {},
            'FailureReason': job.get('FailureReason'), 'JobType': 'processing'}


def stop(sm, kind, name):
    try:
        if kind == 'training':
            sm.stop_training_job(TrainingJobName=name)
        else:
            sm.stop_processing_job(ProcessingJobName=name)
    except ClientError:
        pass


def wait(sm, kind, name, sleep=time.sleep):
    """Poll until the job ends; stop it on timeout or interruption."""
    deadline = time.monotonic() + DEFAULTS[kind]['deadline']
    def interrupted(*_):
        raise InterruptedError('Training interrupted')
    try:
        previous = signal.signal(signal.SIGTERM, interrupted)
    except ValueError:  # not the main thread
        previous = None
    last = None
    try:
        while time.monotonic() < deadline:
            job = describe(sm, kind, name)
            state = (job['TrainingJobStatus'], job['SecondaryStatus'])
            if state != last:
                print('SageMaker', kind, 'job state:', name, *state, flush=True)
                last = state
            if job['TrainingJobStatus'] in TERMINAL:
                if job['TrainingJobStatus'] != 'Completed':
                    group = 'TrainingJobs' if kind == 'training' else 'ProcessingJobs'
                    raise RuntimeError('SageMaker job ' + job['TrainingJobStatus'] + '; inspect /aws/sagemaker/'
                                       + group + ' for ' + name)
                return job
            sleep(15)
        raise TimeoutError('SageMaker job wall-clock limit exceeded')
    except BaseException:
        stop(sm, kind, name)
        raise
    finally:
        if previous is not None:
            signal.signal(signal.SIGTERM, previous)
