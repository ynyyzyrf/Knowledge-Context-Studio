"""Build local private engine config from existing model settings; never print secrets."""

import json
import secrets
from pathlib import Path

from kcs.config import Settings
from kcs.model_service import ModelService

s = Settings()
path = Path("runtime/engine.json")
existing = json.loads(path.read_text()) if path.exists() else {}
with ModelService(s) as model:
    dimension = len(model.embed(["dimension validation"]).vectors[0])
config = {
    "storage": {"workspace": "/data", "agfs": {"backend": "local"}, "vectordb": {"backend": "local"}},
    "embedding": {
        "dense": {
            "provider": "openai",
            "model": s.embedding_model,
            "api_key": s.resolved_embedding_api_key.get_secret_value(),
            "api_base": s.resolved_embedding_base_url,
            "dimension": dimension,
        }
    },
    "vlm": {
        "provider": "openai",
        "model": s.chat_model,
        "api_key": s.model_api_key.get_secret_value(),
        "api_base": s.model_base_url,
    },
    "server": {
        "host": "0.0.0.0",
        "port": 1933,
        "auth_mode": "api_key",
        "with_bot": False,
        "root_api_key": existing.get("server", {}).get("root_api_key", secrets.token_urlsafe(48)),
    },
    "encryption": {"api_key_hashing": {"enabled": True}},
}
path.parent.mkdir(exist_ok=True)
path.write_text(json.dumps(config), encoding="utf-8")
print(f"Private engine configuration written; embedding dimensions={dimension}.")
