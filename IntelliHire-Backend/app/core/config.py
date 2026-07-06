from functools import lru_cache
from pathlib import Path
from typing import Dict
import json

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[2] / ".env",
        extra="ignore",
    )

    app_name: str = Field(default="IntelliHire API", alias="APP_NAME")
    app_env: str = Field(default="local", alias="APP_ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    database_url: str = Field(alias="DATABASE_URL")
    db_schema: str = Field(default="intellihire", alias="DB_SCHEMA")
    init_db_on_startup: bool = Field(default=False, alias="INIT_DB_ON_STARTUP")

    file_storage_mode: str = Field(default="local", alias="FILE_STORAGE_MODE")
    local_storage_root: str = Field(default="./storage", alias="LOCAL_STORAGE_ROOT")
    s3_bucket: str = Field(default="", alias="S3_BUCKET")
    aws_region: str = Field(default="ap-south-1", alias="AWS_REGION")
    aws_access_key_id: str | None = Field(default=None, alias="AWS_ACCESS_KEY_ID")
    aws_secret_access_key: str | None = Field(default=None, alias="AWS_SECRET_ACCESS_KEY")

    llm_provider: str = Field(default="mock", alias="LLM_PROVIDER")
    azure_openai_api_key: str | None = Field(default=None, alias="AZURE_OPENAI_API_KEY")
    azure_openai_endpoint: str | None = Field(default=None, alias="AZURE_OPENAI_ENDPOINT")
    azure_openai_deployment: str | None = Field(default=None, alias="AZURE_OPENAI_DEPLOYMENT")
    azure_openai_api_version: str = Field(
        default="2024-02-15-preview",
        alias="AZURE_OPENAI_API_VERSION",
    )

    azure_tenant_id: str = Field(default="", alias="AZURE_TENANT_ID")
    azure_client_id: str = Field(default="", alias="AZURE_CLIENT_ID")
    azure_redirect_uri: str = Field(
        default="http://localhost:3000/auth/callback",
        alias="AZURE_REDIRECT_URI",
    )
    azure_audience: str = Field(default="", alias="AZURE_AUDIENCE")

    screening_weights_raw: str = Field(
        default='{"experience":25,"responsibilities":15,"projects":20,"location":20,"certification":10,"education":10}',
        alias="SCREENING_WEIGHTS",
    )
    status_thresholds_raw: str = Field(
        default='{"high":80,"medium":60}',
        alias="STATUS_THRESHOLDS",
    )

    docs_url: str = Field(default="/docs", alias="DOCS_URL")
    openapi_url: str = Field(default="/openapi.json", alias="OPENAPI_URL")
    redoc_url: str | None = Field(default="/redoc", alias="REDOC_URL")

    authenticate: bool = Field(default=True, alias="AUTHENTICATE")

    # ----------------------------------------------------
    # Frontend URL
    # Used for assessment/review links in emails
    # ----------------------------------------------------
    intellihire_base_url: str = Field(
        default="http://localhost:3000",
        alias="INTELLIHIRE_BASE_URL",
    )

    # ----------------------------------------------------
    # Email / SMTP configuration
    # ----------------------------------------------------
    smtp_host: str = Field(
        default="smtp.office365.com",
        alias="SMTP_HOST",
    )
    smtp_port: int = Field(
        default=587,
        alias="SMTP_PORT",
    )
    smtp_username: str | None = Field(
        default=None,
        alias="SMTP_USERNAME",
    )
    smtp_password: str | None = Field(
        default=None,
        alias="SMTP_PASSWORD",
    )
    smtp_from_email: str = Field(
        default="no-reply@intellihire.com",
        alias="SMTP_FROM_EMAIL",
    )
    smtp_from_name: str = Field(
        default="IntelliHire Team",
        alias="SMTP_FROM_NAME",
    )

    # STARTTLS must remain enabled for secure SMTP transmission.
    # The email service should fail safely if STARTTLS is not supported.
    smtp_use_tls: bool = Field(
        default=True,
        alias="SMTP_USE_TLS",
    )

    smtp_timeout: int = Field(
        default=20,
        alias="SMTP_TIMEOUT",
    )

    @property
    def screening_weights(self) -> Dict[str, int]:
        return json.loads(self.screening_weights_raw)

    @property
    def status_thresholds(self) -> Dict[str, int]:
        return json.loads(self.status_thresholds_raw)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()