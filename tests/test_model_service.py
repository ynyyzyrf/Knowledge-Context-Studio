import httpx
import pytest

from kcs.config import Settings
from kcs.model_service import ModelService, ModelServiceError


def configured(**kwargs):
    return Settings(
        _env_file=None,
        database_url="sqlite://",
        testing=True,
        model_base_url="https://provider.example.test/v1",
        model_api_key="private-key",
        chat_model="chat-model",
        embedding_model="embedding-model",
        **kwargs,
    )


def test_model_configuration_and_secret_redaction():
    settings = configured()
    assert "private-key" not in repr(settings)
    missing = Settings(database_url="sqlite://", testing=True, _env_file=None)
    with pytest.raises(ModelServiceError, match="model_not_configured"):
        ModelService(missing)


def test_chat_and_embedding_contract():
    def respond(request):
        assert request.headers["Authorization"] == "Bearer private-key"
        if request.url.path == "/v1/chat/completions":
            return httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": "答案"}}],
                    "usage": {"prompt_tokens": 12, "completion_tokens": 3},
                },
            )
        assert request.url.path == "/v1/embeddings"
        return httpx.Response(
            200, json={"data": [{"index": 0, "embedding": [0.1, 0.2]}], "usage": {"prompt_tokens": 2}}
        )

    with ModelService(configured(), transport=httpx.MockTransport(respond)) as service:
        result = service.chat([{"role": "user", "content": "問題"}])
        assert result.text == "答案" and result.input_tokens == 12 and result.output_tokens == 3
        assert service.embed(["內容"]).vectors == [[0.1, 0.2]]


def test_embedding_can_use_separate_provider_configuration():
    settings = configured(
        embedding_base_url="https://embedding.example.test/v1",
        embedding_api_key="embedding-key",
    )

    def respond(request):
        if request.url.host == "provider.example.test":
            assert request.url.path == "/v1/chat/completions"
            assert request.headers["Authorization"] == "Bearer private-key"
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": "答案"}}]},
            )
        assert request.url.host == "embedding.example.test"
        assert request.url.path == "/v1/embeddings"
        assert request.headers["Authorization"] == "Bearer embedding-key"
        return httpx.Response(
            200,
            json={"data": [{"index": 0, "embedding": [0.1, 0.2, 0.3]}]},
        )

    with ModelService(settings, transport=httpx.MockTransport(respond)) as service:
        assert service.chat([{"role": "user", "content": "問題"}]).text == "答案"
        assert service.embed(["內容"]).vectors == [[0.1, 0.2, 0.3]]


@pytest.mark.parametrize(
    "status,code", [(401, "model_auth_failed"), (429, "model_rate_limited"), (503, "model_unavailable")]
)
def test_provider_failure_is_typed_and_does_not_expose_body(status, code):
    with ModelService(
        configured(),
        transport=httpx.MockTransport(
            lambda request: httpx.Response(status, text="secret source private-key")
        ),
    ) as service:
        with pytest.raises(ModelServiceError) as caught:
            service.chat([{"role": "user", "content": "test"}])
        assert caught.value.code == code
        assert "private-key" not in str(caught.value)


def test_bad_embeddings_are_not_accepted():
    with (
        ModelService(
            configured(),
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"data": []})),
        ) as service,
        pytest.raises(ModelServiceError, match="model_invalid_response"),
    ):
        service.embed(["content"])


def test_http_exception_is_bound_to_exact_origin():
    from pydantic import ValidationError

    common = {
        "database_url": "sqlite://",
        "testing": True,
        "_env_file": None,
        "model_http_allowed_origin": "http://gateway.example.test:40000",
    }
    Settings(**common, model_base_url="http://gateway.example.test:40000/v1")
    with pytest.raises(ValidationError):
        Settings(**common, model_base_url="http://other.example.test:40000/v1")
    with pytest.raises(ValidationError):
        Settings(**common, model_base_url="http://gateway.example.test:40001/v1")


def test_chat_does_not_require_an_embedding_model():
    settings = configured().model_copy(update={"embedding_model": ""})
    with ModelService(
        settings,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"choices": [{"message": {"content": "OK"}}]})
        ),
    ) as service:
        assert service.chat([{"role": "user", "content": "test"}]).text == "OK"
        with pytest.raises(ModelServiceError, match="embedding_not_configured"):
            service.embed(["test"])
