"""Synthetic (made-up) data must never reach the live application."""
import hashlib
import io
import json
import sys
from datetime import date
from pathlib import Path
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'mlops'))
from forecast import train  # noqa: E402
from review_model import review  # noqa: E402
from upload_dataset import upload  # noqa: E402
from app.encoder import Encoder  # noqa: E402
from test_forecast import module, snapshot  # noqa: E402


def synthetic_history(days=35):
    data = snapshot(days)
    data['synthetic'] = True
    return data


def test_synthetic_photos_cannot_be_uploaded_as_workshop_data(tmp_path):
    (tmp_path / 'dataset-metadata.json').write_text(json.dumps({'synthetic': True}))
    s3 = Mock()
    with pytest.raises(ValueError, match='Synthetic data'):
        upload(tmp_path, 'owned', 'ap-southeast-2', s3)
    s3.put_object.assert_not_called()


def test_registry_cannot_approve_a_synthetic_package():
    config = {'region': 'ap-southeast-2', 'account_id': '123456789012', 'model_package_group': 'stocklane-visual-sku'}
    sm = Mock()
    sm.describe_model_package.return_value = {'ModelPackageStatus': 'Completed',
                                              'CustomerMetadataProperties': {'syntheticData': 'true'}}
    arn = 'arn:aws:sagemaker:ap-southeast-2:123456789012:model-package/stocklane-visual-sku/1'
    with pytest.raises(ValueError, match='cannot be approved'):
        review(arn, 'Approved', config, sm)
    sm.update_model_package.assert_not_called()


def test_live_vision_cannot_load_a_synthetic_encoder(tmp_path):
    (tmp_path / 'model.json').write_text(json.dumps({'syntheticData': True}))
    with pytest.raises(RuntimeError, match='live workshop'):
        Encoder(tmp_path)


def test_live_forecast_cannot_serve_synthetic_projections():
    model = train(synthetic_history())
    with pytest.raises(ValueError, match='Synthetic demo'):
        module().projection(model, [], date(2026, 10, 27))


def test_forecast_runner_refuses_synthetic_data_before_training_or_publication(monkeypatch):
    import run_forecast
    raw = json.dumps(synthetic_history(200)).encode()
    pointer = {'key': 'forecast/datasets/example/history.json', 'sha256': hashlib.sha256(raw).hexdigest()}
    s3 = Mock()
    s3.get_object.side_effect = [{'Body': io.BytesIO(json.dumps(pointer).encode())}, {'Body': io.BytesIO(raw)}]
    sm = Mock()
    sts = Mock()
    sts.get_caller_identity.return_value = {'Account': '123456789012'}
    monkeypatch.setattr(run_forecast.boto3, 'client', lambda name, **kwargs: {'s3': s3, 'sagemaker': sm, 'sts': sts}[name])
    with pytest.raises(ValueError, match='live forecast'):
        run_forecast.execute({'region': 'ap-southeast-2', 'model_bucket': 'owned', 'account_id': '123456789012'}, True)
    sm.create_training_job.assert_not_called()
    s3.put_object.assert_not_called()
