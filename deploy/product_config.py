"""Compile one user configuration into private product settings. Runs inside tools."""

import hashlib
import json
import os
import secrets
from pathlib import Path

from dotenv import dotenv_values

from kcs.config import Settings
from kcs.model_service import ModelService, ModelServiceError

USER_KEYS = {
    "KCS_PUBLIC_ORIGIN", "KCS_SECURE_COOKIES", "KCS_MODEL_BASE_URL", "KCS_MODEL_API_KEY",
    "KCS_CHAT_MODEL", "KCS_MODEL_HTTP_ALLOWED_ORIGIN", "KCS_EMBEDDING_BASE_URL",
    "KCS_EMBEDDING_API_KEY", "KCS_EMBEDDING_MODEL", "KCS_EMBEDDING_HTTP_ALLOWED_ORIGIN",
}


def write_private(path, text):
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        temporary.chmod(0o600)
        stream.write(text)
    if hasattr(os, "chown"):
        os.chown(temporary, 10001, 10001)
    temporary.replace(path)


def configure(root=Path("/app/runtime"), model_factory=ModelService):
    inputs = dict(dotenv_values(root / "settings.env", interpolate=False))
    if set(inputs) - USER_KEYS:
        raise ValueError("settings.env contains unsupported settings")
    existing = dict(dotenv_values(root / ".env", interpolate=False))
    values = {**existing, **inputs}
    settings = Settings(_env_file=None, **{key[4:].lower(): value for key, value in values.items()})
    if not settings.models_configured:
        raise ValueError("Fill chat and embedding model settings before starting the product")
    engine_path = root / "engine.json"
    engine = json.loads(engine_path.read_text(encoding="utf-8")) if engine_path.exists() else {}
    if engine:
        old = engine["embedding"]["dense"]
        if (old["model"], old["api_base"]) != (
            settings.embedding_model, settings.resolved_embedding_base_url,
        ):
            raise ValueError("Embedding model/endpoint changed; explicit index migration is required")
    digest = hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()
    marker = root / "settings.sha256"
    if engine and marker.exists() and marker.read_text() == digest:
        if hasattr(os, "chown"):
            os.chown(root / ".env", 10001, 10001)
        (root / ".env").chmod(0o600)
        print("Product configuration unchanged; internal credentials preserved.")
        return
    with model_factory(settings) as model:
        dimension = len(model.embed(["product embedding dimension check"]).vectors[0])
    if engine and engine["embedding"]["dense"]["dimension"] != dimension:
        raise ValueError("Embedding dimension changed; explicit index migration is required")
    engine = {
        "storage": {"workspace": "/data", "agfs": {"backend": "local"}, "vectordb": {"backend": "local"}},
        "embedding": {"dense": {
            "provider": "openai", "model": settings.embedding_model,
            "api_key": settings.resolved_embedding_api_key.get_secret_value(),
            "api_base": settings.resolved_embedding_base_url, "dimension": dimension,
        }},
        "vlm": {"provider": "openai", "model": settings.chat_model,
                "api_key": settings.model_api_key.get_secret_value(), "api_base": settings.model_base_url},
        "server": {"host": "0.0.0.0", "port": 1933, "auth_mode": "api_key", "with_bot": False,
                   "root_api_key": engine.get("server", {}).get("root_api_key") or secrets.token_urlsafe(48)},
        "encryption": {"api_key_hashing": {"enabled": True}},
    }
    # dotenv's single quoted values preserve $, # and other key characters.
    def quote(value):
        return "'" + str(value).replace("\\", "\\\\").replace("'", "\\'") + "'"
    write_private(root / ".env", "".join(f"{key}={quote(value)}\n" for key, value in values.items()))
    write_private(engine_path, json.dumps(engine))
    write_private(marker, digest)
    print(f"Product configuration ready; embedding dimensions={dimension}.")


if __name__ == "__main__":
    try:
        configure()
    except (ValueError, OSError, KeyError, ModelServiceError) as exc:
        # Validation errors can echo input credentials; never dump them to logs.
        raise SystemExit(f"Product configuration failed ({type(exc).__name__}); check settings and model access.")
