"""Fail readiness when native index is absent, even if the HTTP server is running."""

from kcs.config import Settings
from kcs.engine import OpenViking

with OpenViking(Settings()) as engine:
    result = engine.call("GET", "/api/v1/debug/vector/count")
    if not isinstance(result, dict) or type(result.get("count")) is not int:
        raise RuntimeError("Private vector index is not ready")
print("Private vector index ready.")
