"""Private OpenViking adapter. Never accepts client-supplied engine paths or identity."""

import math
import re

import httpx


class EngineError(RuntimeError):
    pass


def subject_uri(tenant_id, agent_id, subject_id):
    if not all(re.fullmatch(r"[0-9a-f]{32}", x) for x in (tenant_id, agent_id, subject_id)):
        raise ValueError("Invalid internal identity")
    return f"viking://resources/kcs/{tenant_id}/{agent_id}/{subject_id}"


def memory_uri(memory, version=None):
    if not re.fullmatch(r"[0-9a-f]{32}", memory.id):
        raise ValueError("Invalid memory identity")
    return f"{subject_uri(memory.tenant_id, memory.agent_id, memory.subject_id)}/{memory.id}/v{version or memory.current_version}.md"


def space_uri(tenant_id, space_id):
    if not all(re.fullmatch(r"[0-9a-f]{32}", x) for x in (tenant_id, space_id)):
        raise ValueError("Invalid internal identity")
    return f"viking://resources/kcs-spaces/{tenant_id}/{space_id}"


def private_space_uri(tenant_id, space_id, person_id):
    if not all(re.fullmatch(r"[0-9a-f]{32}", x) for x in (tenant_id, space_id, person_id)):
        raise ValueError("Invalid private namespace identity")
    return f"viking://resources/kcs-private/{tenant_id}/{space_id}/{person_id}"


def document_uri(document, number):
    if not re.fullmatch(r"[0-9a-f]{32}", document.id) or type(number) is not int or number < 0:
        raise ValueError("Invalid document identity")
    root = (
        private_space_uri(document.tenant_id, document.space_id, document.owner_person_id)
        if document.owner_person_id
        else space_uri(document.tenant_id, document.space_id)
    )
    return f"{root}/{document.id}/v1-c{number}.md"


class OpenViking:
    def __init__(self, settings, *, transport=None):
        if not settings.engine_url or not settings.engine_api_key.get_secret_value():
            raise EngineError("engine_not_configured")
        self.timeout = settings.engine_timeout_seconds
        self.client = httpx.Client(
            base_url=settings.engine_url.rstrip("/"),
            headers={"X-API-Key": settings.engine_api_key.get_secret_value()},
            timeout=self.timeout,
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        )

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.client.close()

    def call(self, method, path, *, missing_ok=False, **kwargs):
        try:
            with self.client.stream(method, path, **kwargs) as response:
                if missing_ok and response.status_code == 404:
                    return None
                if response.status_code in (401, 403):
                    raise EngineError("engine_auth_failed")
                if not response.is_success:
                    raise EngineError("engine_unavailable")
                raw = bytearray()
                for chunk in response.iter_bytes():
                    raw.extend(chunk)
                    if len(raw) > 2 * 1024 * 1024:
                        raise EngineError("engine_response_too_large")
                import json

                value = json.loads(raw)
                if not isinstance(value, dict) or value.get("status") != "ok" or "result" not in value:
                    raise EngineError("engine_invalid_response")
                return value["result"]
        except httpx.TimeoutException:
            raise EngineError("engine_timeout") from None
        except httpx.HTTPError:
            raise EngineError("engine_unavailable") from None
        except (ValueError, TypeError):
            raise EngineError("engine_invalid_response") from None

    def publish(self, uri, content):
        result = self.call(
            "POST",
            "/api/v1/content/write",
            json={
                "uri": uri,
                "content": content,
                "mode": "replace",
                "wait": True,
                "timeout": self.timeout - 1,
                "processing_mode": "vectors_only",
            },
        )
        if not isinstance(result, dict) or result.get("vector_status") != "complete":
            raise EngineError("engine_index_incomplete")
        indexed = self.call("GET", "/api/v1/debug/vector/count", params={"uri": uri})
        if not isinstance(indexed, dict) or type(indexed.get("count")) is not int or indexed["count"] < 1:
            raise EngineError("engine_index_incomplete")
        if self.call("GET", "/api/v1/content/read", params={"uri": uri, "raw": True}) != content:
            raise EngineError("engine_content_mismatch")

    def delete(self, uri):
        self.call(
            "DELETE",
            "/api/v1/fs",
            missing_ok=True,
            # File/vector deletion is synchronous; parent summary refresh is independent.
            params={"uri": uri, "wait": False},
        )
        indexed = self.call("GET", "/api/v1/debug/vector/count", params={"uri": uri})
        remaining = self.call(
            "GET", "/api/v1/content/read", missing_ok=True, params={"uri": uri, "raw": True}
        )
        if not isinstance(indexed, dict) or indexed.get("count") != 0 or remaining is not None:
            raise EngineError("engine_delete_incomplete")

    def find(self, root, query, limit):
        result = self.call(
            "POST",
            "/api/v1/search/find",
            json={
                "query": query,
                "target_uri": root,
                "limit": limit,
                "level": 2,
            },
        )
        if not isinstance(result, dict) or not isinstance(result.get("resources"), list):
            raise EngineError("engine_invalid_response")
        hits = []
        for row in result["resources"][:limit]:
            if not isinstance(row, dict):
                raise EngineError("engine_invalid_response")
            uri, score = row.get("uri"), row.get("score")
            if not isinstance(uri, str) or type(score) not in (int, float) or not math.isfinite(score):
                raise EngineError("engine_invalid_response")
            hits.append((uri, score))
        return hits
