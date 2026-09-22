"""Real pinned OpenViking HTTP/native storage; explicit offline model fixtures only."""

import asyncio
from types import SimpleNamespace

import pytest
from pydantic import SecretStr
from test_http_contract import live_server, ok

from kcs.engine import OpenViking, subject_uri


@pytest.mark.asyncio
async def test_adapter_publish_find_delete_against_native_engine(tmp_path):
    async with live_server(tmp_path, 'api_key') as client:
        account = await ok(client, 'POST', '/api/v1/admin/accounts',
                           json={'account_id': 'kcs', 'admin_user_id': 'publisher'})
        settings = SimpleNamespace(engine_url=str(client.base_url),
                                   engine_api_key=SecretStr(account['user_key']), engine_timeout_seconds=60)
        root = subject_uri('a' * 32, 'b' * 32, 'c' * 32)
        uri = root + '/' + 'd' * 32 + '/v1.md'
        other = subject_uri('a' * 32, 'b' * 32, 'e' * 32)
        def exercise():
            with OpenViking(settings) as engine:
                engine.publish(uri, 'KCS adapter native memory canary jasmine tea')
                engine.publish(uri, 'KCS adapter native memory canary jasmine tea')
                found = engine.find(root, 'KCS adapter native memory canary jasmine tea', 10)
                assert uri in [hit[0] for hit in found]
                assert uri not in [hit[0] for hit in engine.find(other, 'jasmine tea', 10)]
                engine.delete(uri)
                engine.delete(uri)
                assert uri not in [hit[0] for hit in engine.find(root, 'jasmine tea', 10)]
        await asyncio.to_thread(exercise)
