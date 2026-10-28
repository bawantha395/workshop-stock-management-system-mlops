from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')
    environment: str = 'cloud'
    auth_mode: str = 'cognito'
    internal_token: str = ''
    inventory_read_token: str = ''
    vision_read_token: str = ''
    cognito_issuer: str = ''
    cognito_client_ids: str = ''
    web_origin: str = 'http://localhost:4173'
    database_url: str = 'sqlite:///.data/vision.db'
    files_root: str = '.data/images'
    model_dir: str = 'models/baseline'
    media_bucket: str = ''
    redis_url: str = 'redis://localhost:6379/0'
    inventory_url: str = 'http://localhost:8081'
    bedrock_model_id: str = ''
    bedrock_daily_request_limit: int = 50
    bedrock_region: str = ''
    aws_region: str = 'eu-west-1'
    catalogue_queue_url: str = ''
    match_threshold: float = 0.92
    match_margin: float = 0.08
    max_upload_bytes: int = 8 * 1024 * 1024

    def check(self):
        if self.auth_mode == 'local' and self.environment != 'local':
            raise RuntimeError('Local authentication requires ENVIRONMENT=local')
        if len(self.internal_token) < 32:
            raise RuntimeError('INTERNAL_TOKEN must contain at least 32 characters')
        if self.auth_mode != 'local' and (not self.cognito_issuer or not self.cognito_client_ids):
            raise RuntimeError('Configure Cognito issuer and allowed clients')
        if self.auth_mode != 'local' and min(len(self.inventory_read_token),len(self.vision_read_token))<32:
            raise RuntimeError('Configure scoped inventory-read and capture-read capability tokens')
        Path(self.files_root).mkdir(parents=True, exist_ok=True)
