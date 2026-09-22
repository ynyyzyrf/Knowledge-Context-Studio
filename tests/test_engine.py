import httpx
import pytest

from kcs.config import Settings
from kcs.engine import EngineError, OpenViking


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
