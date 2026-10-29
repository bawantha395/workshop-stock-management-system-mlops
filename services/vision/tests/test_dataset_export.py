from datetime import datetime, timezone

import fakeredis
import redis
from fastapi.testclient import TestClient

from app import dataset_export
from app.config import Settings
from app.main import create_app


def test_confirmed_photos_are_exported_once_a_week_on_sunday_night(tmp_path, monkeypatch):
    shared = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(redis.Redis, 'from_url', lambda *args, **kwargs: shared)
    calls = []
    monkeypatch.setattr(dataset_export, 'export', lambda store, s3, bucket: calls.append(bucket) or {'exported': True})
    settings = Settings(environment='local', auth_mode='local', internal_token='x' * 32,
        database_url='sqlite:///' + str(tmp_path / 'vision.db'), files_root=str(tmp_path / 'photos'),
        model_dir=str(tmp_path / 'no-model'), training_export=True, model_bucket='models')
    with TestClient(create_app(settings)) as client:
        export = client.app.state.weekly_export
        sunday_night = datetime(2026, 10, 31, 20, 0, tzinfo=timezone.utc)      # Sunday 01:30 in Colombo
        assert export(datetime(2026, 10, 31, 18, 0, tzinfo=timezone.utc)) is None  # Saturday 23:30 in Colombo
        assert export(sunday_night) == {'exported': True}
        assert export(datetime(2026, 11, 1, 3, 0, tzinfo=timezone.utc)) is None    # same week: already done
        assert calls == ['models']
