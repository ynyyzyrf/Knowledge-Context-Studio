import httpx
import pytest

from kcs.config import Settings
from kcs.engine import EngineError, OpenViking


def test_private_docker_engine_http_requires_exact_explicit_origin():
    from pydantic import ValidationError

    common = {"_env_file": None, "testing": True, "database_url": "sqlite://"}
    with pytest.raises(ValidationError):
        Settings(**common, engine_url="http://engine:1933")
    Settings(**common, engine_url="http://engine:1933", engine_http_allowed_origin="http://engine:1933")
    for url in ("http://other:1933", "http://engine:1934", "http://engine:1933/path"):
        with pytest.raises(ValidationError):
            Settings(**common, engine_url=url, engine_http_allowed_origin="http://engine:1933")


def test_reported_completion_without_index_never_publishes():
    settings = Settings(
        _env_file=None,
        testing=True,
        database_url="sqlite://",
        engine_url="http://localhost:1933",
        engine_api_key="test",
    )

    def respond(request):
        result = {"vector_status": "complete"} if request.method == "POST" else {"count": 0}
        return httpx.Response(200, json={"status": "ok", "result": result})

    with (
        OpenViking(settings, transport=httpx.MockTransport(respond)) as engine,
        pytest.raises(EngineError, match="engine_index_incomplete"),
    ):
        engine.publish("viking://resources/test/v1.md", "canary")
