from pathlib import Path
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def validate_http_base_url(name: str, value: str, allowed_http_origin: str):
    endpoint = urlsplit(value)
    if (
        endpoint.scheme not in ("http", "https")
        or not endpoint.hostname
        or endpoint.username
        or endpoint.password
        or endpoint.query
        or endpoint.fragment
    ):
        raise ValueError(f"{name} must be an HTTP(S) base URL without credentials or query")
    origin = f"{endpoint.scheme}://{endpoint.netloc}"
    if (
        endpoint.scheme == "http"
        and endpoint.hostname not in ("localhost", "127.0.0.1", "::1")
        and origin != allowed_http_origin
    ):
        raise ValueError(f"Remote {name} endpoints require HTTPS")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="KCS_", env_file=".env", extra="ignore")
    database_url: str
    testing: bool = False
    public_origin: str = "http://localhost:8088"
    secure_cookies: bool = False
    session_hours: int = 12
    frontend_dist: Path = Path(__file__).resolve().parents[2] / "web" / "dist"
    model_base_url: str = ""
    model_http_allowed_origin: str = ""
    model_api_key: SecretStr = SecretStr("")
    chat_model: str = ""
    embedding_base_url: str = ""
    embedding_http_allowed_origin: str = ""
    embedding_api_key: SecretStr = SecretStr("")
    embedding_model: str = ""
    engine_url: str = ""
    engine_http_allowed_origin: str = ""
    engine_api_key: SecretStr = SecretStr("")
    engine_timeout_seconds: float = Field(default=60, gt=1, le=300)
    model_timeout_seconds: float = Field(default=60, gt=0, le=300)

    @property
    def models_configured(self):
        return bool(
            self.model_base_url
            and self.model_api_key.get_secret_value()
            and self.chat_model
            and self.resolved_embedding_base_url
            and self.resolved_embedding_api_key.get_secret_value()
            and self.embedding_model
        )

    @property
    def resolved_embedding_base_url(self):
        return self.embedding_base_url or self.model_base_url

    @property
    def resolved_embedding_api_key(self):
        if self.embedding_base_url:
            return self.embedding_api_key
        return self.embedding_api_key or self.model_api_key

    @model_validator(mode="after")
    def validate_runtime(self):
        if self.engine_url:
            endpoint = urlsplit(self.engine_url)
            if (
                endpoint.scheme not in ("http", "https")
                or not endpoint.hostname
                or endpoint.username
                or endpoint.password
                or endpoint.query
                or endpoint.fragment
                or endpoint.path not in ("", "/")
            ):
                raise ValueError("Engine URL must be an origin without credentials or paths")
            if (
                endpoint.scheme == "http"
                and endpoint.hostname not in ("localhost", "127.0.0.1", "::1")
                and f"{endpoint.scheme}://{endpoint.netloc}" != self.engine_http_allowed_origin
            ):
                raise ValueError("Remote engine requires HTTPS")
        if self.model_base_url:
            validate_http_base_url("model", self.model_base_url, self.model_http_allowed_origin)
        if self.embedding_base_url:
            validate_http_base_url(
                "embedding model",
                self.embedding_base_url,
                self.embedding_http_allowed_origin,
            )
        if not self.testing and not self.database_url.startswith("postgresql+psycopg://"):
            raise ValueError("PostgreSQL is required outside tests")
        if self.public_origin.startswith("https://") and not self.secure_cookies:
            raise ValueError("HTTPS requires secure cookies")
        if not 1 <= self.session_hours <= 168:
            raise ValueError("session_hours must be between 1 and 168")
        return self
