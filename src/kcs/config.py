from urllib.parse import urlsplit

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="KCS_", env_file=".env", extra="ignore")
    database_url: str
    testing: bool = False
    public_origin: str = "http://localhost:8088"
    secure_cookies: bool = False
    session_hours: int = 12
    model_base_url: str = ""
    model_http_allowed_origin: str = ""
    model_api_key: SecretStr = SecretStr("")
    chat_model: str = ""
    embedding_model: str = ""
    model_timeout_seconds: float = Field(default=60, gt=0, le=300)

    @property
    def models_configured(self):
        return bool(
            self.model_base_url
            and self.model_api_key.get_secret_value()
            and self.chat_model
            and self.embedding_model
        )

    @model_validator(mode="after")
    def validate_runtime(self):
        if self.model_base_url:
            endpoint = urlsplit(self.model_base_url)
            if (
                endpoint.scheme not in ("http", "https")
                or not endpoint.hostname
                or endpoint.username
                or endpoint.password
                or endpoint.query
                or endpoint.fragment
            ):
                raise ValueError("Model URL must be an HTTP(S) base URL without credentials or query")
            origin = f"{endpoint.scheme}://{endpoint.netloc}"
            if (
                endpoint.scheme == "http"
                and endpoint.hostname not in ("localhost", "127.0.0.1", "::1")
                and origin != self.model_http_allowed_origin
            ):
                raise ValueError("Remote model endpoints require HTTPS")
        if not self.testing and not self.database_url.startswith("postgresql+psycopg://"):
            raise ValueError("PostgreSQL is required outside tests")
        if self.public_origin.startswith("https://") and not self.secure_cookies:
            raise ValueError("HTTPS requires secure cookies")
        if not 1 <= self.session_hours <= 168:
            raise ValueError("session_hours must be between 1 and 168")
        return self
