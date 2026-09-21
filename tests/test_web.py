from fastapi.testclient import TestClient

from kcs.app import create_app


def test_frontend_deep_links_and_api_boundary(app, tmp_path):
    static = tmp_path / "web"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<html>Studio frontend</html>", encoding="utf-8")
    (static / "assets" / "test.js").write_text("export const test = 1;", encoding="utf-8")
    settings = app.state.settings.model_copy(update={"frontend_dist": static})
    with TestClient(create_app(settings)) as client:
        assert "Studio frontend" in client.get("/").text
        assert "Studio frontend" in client.get("/cognition").text
        assert client.get("/assets/test.js").status_code == 200
        assert client.get("/v1/nonexistent").status_code == 404
        assert client.get("/health/nonexistent").status_code == 404
        assert client.get("/openapi.json").json()["info"]["title"] == "Knowledge Context Studio"
