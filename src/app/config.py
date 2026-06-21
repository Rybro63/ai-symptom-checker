"""Application configuration loaded from environment variables."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings.

    In AWS Lambda these come from environment variables set in template.yaml.
    Locally, they can be set in a .env file (never commit it).
    """

    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-5"
    dynamodb_table_name: str = "symptom-checks"
    aws_region: str = "us-east-1"

    # Confidence-threshold inference layer: if the model's top condition
    # confidence is below this value, the API withholds the differential and
    # recommends professional evaluation instead of guessing.
    confidence_threshold: float = 0.35

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()
