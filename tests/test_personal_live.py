"""Opt-in live embedding retrieval on synthetic, isolated product rows."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_documents import setup
from test_personal_context import enable, grant, item, paths
from test_publication import Engine

from kcs.model_service import ModelService
from kcs.models import NamespaceEntry
from kcs.personal_index import configured, run_one
from kcs.personal_retrieval import cosine, lexical_score


def test_live_personal_paraphrases(app, request):
    if not request.config.getoption("--live-model"):
        pytest.skip("Explicit --live-model required; makes billed embedding requests")
    assert configured(app.state.settings), "Real embedding configuration is required"
    app.state.context_engine_factory = lambda: Engine()
    observed = []

    class QueryModel(ModelService):
        def embed(self, texts):
            result = super().embed(texts)
            observed.append(result.vectors[0])
            return result

    app.state.personal_model_factory = lambda: QueryModel(app.state.settings)
    examples = [
        ("週報偏好", "週報需附上可點擊的來源連結，方便核對每項結論。", "每週工作總結的格式有什麼要求？"),
        ("出差安排", "我不喜歡夜間搭飛機，請優先安排白天起飛。", "替我訂機票時，紅眼航班合適嗎？"),
        ("餐飲偏好", "我對花生過敏，訂餐時必須避開花生及花生油。", "安排午餐需要注意哪些食物過敏？"),
    ]
    with TestClient(app) as admin, TestClient(app) as machine:
        _, agent, subject, space, base = setup(admin, machine)
        human, _ = paths(base, space, "memories")
        grant(admin, human, agent)
        rows = [
            enable(admin, human, item(admin, human, key=str(i), title=title, content=content))
            for i, (title, content, _) in enumerate(examples)
        ]
        for _ in rows:
            assert run_one(app.state.database, app.state.settings)
        for row, (_, _, query) in zip(rows, examples):
            response = machine.post(
                "/v1/context",
                json={"subject_id": subject["id"], "space_ids": [space["id"]], "query": query, "limit": 1},
            )
            assert response.status_code == 200, response.text
            result = response.json()
            assert result["personal_context_retrieval"] == "hybrid", result["personal_retrieval"]
            diagnostics = []
            with app.state.database.sessions() as db:
                for stored in db.scalars(select(NamespaceEntry)):
                    diagnostics.append(
                        {
                            "title": stored.title,
                            "lexical": lexical_score(query, stored.title, stored.content),
                            "cosine": max(
                                cosine(observed[-1], vector) for vector in stored.embedding_vectors
                            ),
                        }
                    )
            assert [r["id"] for r in result["personal_context"]] == [row["id"]], {
                "query": query,
                "returned_titles": [r["title"] for r in result["personal_context"]],
                "scores": diagnostics,
            }
