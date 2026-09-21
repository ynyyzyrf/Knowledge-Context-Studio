"""Bounded OpenAI-compatible HTTP calls. Upstream bodies never become public errors."""

import math
from dataclasses import dataclass

import httpx

from .config import Settings


class ModelServiceError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ChatResult:
    text: str
    input_tokens: int | None
    output_tokens: int | None


@dataclass(frozen=True)
class EmbeddingResult:
    vectors: list[list[float]]
    input_tokens: int | None


def token_count(usage, key):
    value = usage.get(key)
    return value if type(value) is int and value >= 0 else None


class ModelService:
    def __init__(self, settings: Settings, *, transport=None):
        if not settings.model_base_url or not settings.model_api_key.get_secret_value():
            raise ModelServiceError("model_not_configured")
        self.settings = settings
        self.client = httpx.Client(
            base_url=settings.model_base_url.rstrip("/") + "/",
            headers={"Authorization": "Bearer " + settings.model_api_key.get_secret_value()},
            timeout=settings.model_timeout_seconds,
            follow_redirects=False,
            transport=transport,
            trust_env=False,
        )

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.client.close()

    def _post(self, path, body):
        try:
            with self.client.stream("POST", path, json=body) as response:
                if response.status_code in (401, 403):
                    raise ModelServiceError("model_auth_failed")
                if response.status_code == 429:
                    raise ModelServiceError("model_rate_limited")
                if not response.is_success:
                    raise ModelServiceError("model_unavailable")
                data = bytearray()
                for chunk in response.iter_bytes():
                    data.extend(chunk)
                    if len(data) > 8 * 1024 * 1024:
                        raise ModelServiceError("model_response_too_large")
                import json

                result = json.loads(data)
                if not isinstance(result, dict):
                    raise TypeError()
                return result
        except httpx.TimeoutException:
            raise ModelServiceError("model_timeout") from None
        except httpx.HTTPError:
            raise ModelServiceError("model_unavailable") from None
        except (ValueError, TypeError, UnicodeError):
            raise ModelServiceError("model_invalid_response") from None

    def chat(self, messages: list[dict], *, max_tokens=2048):
        if not self.settings.chat_model:
            raise ModelServiceError("chat_not_configured")
        result = self._post(
            "chat/completions",
            {
                "model": self.settings.chat_model,
                "messages": messages,
                "max_tokens": max_tokens,
                "stream": False,
            },
        )
        try:
            content = result["choices"][0]["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                raise ValueError()
            usage = result.get("usage") or {}
            if not isinstance(usage, dict):
                raise TypeError()
            return ChatResult(
                content, token_count(usage, "prompt_tokens"), token_count(usage, "completion_tokens")
            )
        except (KeyError, IndexError, TypeError, ValueError):
            raise ModelServiceError("model_invalid_response") from None

    def embed(self, texts: list[str]):
        if not self.settings.embedding_model:
            raise ModelServiceError("embedding_not_configured")
        if not texts or len(texts) > 64:
            raise ValueError("Embedding batch must contain 1 to 64 inputs")
        result = self._post("embeddings", {"model": self.settings.embedding_model, "input": texts})
        try:
            rows = sorted(result["data"], key=lambda row: row["index"])
            if len(rows) != len(texts) or [row["index"] for row in rows] != list(range(len(texts))):
                raise ValueError()
            vectors = [row["embedding"] for row in rows]
            dimensions = len(vectors[0])
            if dimensions == 0 or any(not isinstance(v, list) or len(v) != dimensions for v in vectors):
                raise ValueError()
            if any(type(n) not in (int, float) or not math.isfinite(n) for v in vectors for n in v):
                raise ValueError()
            usage = result.get("usage") or {}
            if not isinstance(usage, dict):
                raise TypeError()
            return EmbeddingResult(vectors, token_count(usage, "prompt_tokens"))
        except (KeyError, IndexError, TypeError, ValueError):
            raise ModelServiceError("model_invalid_response") from None
