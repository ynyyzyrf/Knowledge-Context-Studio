import pytest
from fastapi.testclient import TestClient
from test_documents import setup, upload
from test_personal_context import enable, grant, item, paths
from test_publication import Engine


def test_multilingual_lexical_recall_and_literal_wildcards():
    from kcs.personal_retrieval import lexical_score

    assert lexical_score("MAG 對週報格式有哪些要求？", "週報偏好", "週報需附來源連結。") > 0
    assert lexical_score("what are the support hours?", "Policy", "Support runs until 18:00") > 0
    assert lexical_score("% _", "Title", "arbitrary content") == 0
    assert lexical_score("the and is", "Title", "irrelevant") == 0


def test_cosine_rejects_invalid_vectors():
    from kcs.personal_retrieval import cosine

    assert cosine([1, 0], [1, 0]) == pytest.approx(1)
    for a, b in [([0, 0], [1, 0]), ([1], [1, 0]), ([float("nan")], [1])]:
        assert cosine(a, b) == 0


def test_context_budget_reserves_personal_and_counts_headers():
    from kcs.personal_retrieval import allocate

    docs = [("doc" + str(i), "d" * 1100) for i in range(10)]
    personal = [("p", "[personal:p]\n" + "p" * 450)]
    selected = allocate(docs, personal, limit=4, max_chars=4000)
    assert "p" in [key for key, _ in selected]
    assert any(key.startswith("doc") for key, _ in selected)
    assert len(selected) <= 4 and len("\n\n".join(text for _, text in selected)) <= 4000
    assert allocate(docs, personal, limit=1, max_chars=4000)[0][0] == "p"
    selected = allocate([], [("long", "x" * 5000), ("fits", "yes")], limit=2, max_chars=4000)
    assert [key for key, _ in selected] == ["fits"]


def test_valid_personal_larger_than_soft_budget_is_not_starved():
    from kcs.personal_retrieval import allocate

    selected = allocate(
        [("d1", "d" * 1400), ("d2", "d" * 1400)], [("p", "p" * 1500)], limit=3, max_chars=4000
    )
    assert "p" in [key for key, _ in selected]
    assert len("\n\n".join(text for _, text in selected)) <= 4000


def test_rank_streams_candidates_and_keeps_older_relevant_items():
    from types import SimpleNamespace

    from kcs.personal_retrieval import rank

    def rows():
        for i in range(1200):
            yield SimpleNamespace(
                id=str(i),
                kind="memories",
                title="Policy" if i == 0 else "Other",
                content="support" if i == 0 else "unrelated",
                version=1,
                embedding_version=0,
                embedding_vectors=None,
                embedding_model_key="",
            )

    ranked, stats = rank(rows(), "support", None, "model")
    assert [r.id for r in ranked] == ["0"]
    assert stats == {"readable_count": 1200, "indexed_count": 0}


def test_fused_rank_tie_prefers_semantic_relevance_over_random_id():
    from types import SimpleNamespace

    from kcs.personal_retrieval import rank

    rows = [
        SimpleNamespace(
            id="a",
            kind="memories",
            title="出差安排",
            content="搭飛機時優先安排白天起飛。",
            version=1,
            embedding_version=1,
            embedding_model_key="model",
            embedding_vectors=[[0.6, 0.8]],
        ),
        SimpleNamespace(
            id="z",
            kind="memories",
            title="餐飲偏好",
            content="我對花生過敏。",
            version=1,
            embedding_version=1,
            embedding_model_key="model",
            embedding_vectors=[[1.0, 0.0]],
        ),
    ]
    ranked, _ = rank(rows, "安排午餐需要注意哪些食物過敏？", [1.0, 0.0], "model")
    assert ranked[0].id == "z"


def test_http_chinese_paraphrase_and_full_document_budget(app):
    from kcs.document_worker import run_one

    engine = Engine()
    app.state.context_engine_factory = lambda: engine
    with TestClient(app) as admin, TestClient(app) as machine:
        _, agent, subject, space, base = setup(admin, machine)
        human, _ = paths(base, space, "memories")
        grant(admin, human, agent)
        row = enable(admin, human, item(admin, human, title="週報偏好", content="週報需附來源連結。"))
        for i in range(4):
            assert (
                upload(admin, base, ("weekly report " * 70 + str(i)).encode(), f"doc{i}.md").status_code
                == 202
            )
            assert run_one(app.state.database, app.state.settings, engine_factory=lambda: engine)
        query = {
            "subject_id": subject["id"],
            "space_ids": [space["id"]],
            "query": "MAG 對週報格式有哪些要求？",
            "limit": 3,
            "max_chars": 4000,
        }
        result = machine.post("/v1/context", json=query)
        assert result.status_code == 200, result.text
        body = result.json()
        assert [p["id"] for p in body["personal_context"]] == [row["id"]]
        assert body["documents"] and len(body["context"]) <= 4000
        assert sum(len(body[k]) for k in ("documents", "memories", "personal_context")) <= 3
        assert body["personal_context"][0]["version"] == row["version"]
        grant(admin, human, agent, read=False)
        assert machine.post("/v1/context", json=query).json()["personal_context"] == []
