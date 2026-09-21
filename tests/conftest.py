import uuid

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from kcs.app import create_app
from kcs.bootstrap import bootstrap_admin
from kcs.config import Settings


def pytest_addoption(parser):
    parser.addoption(
        "--postgres", action="store_true", help="Run against isolated migrated PostgreSQL schemas"
    )


@pytest.fixture
def app(tmp_path, request, monkeypatch):
    engine = None
    if request.config.getoption("--postgres"):
        url = make_url(Settings().database_url).set(database="kcs_test")
        engine = create_engine(url)
        schema = "test_" + uuid.uuid4().hex
        with engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        scoped = url.update_query_dict({"options": f"-csearch_path={schema}"})
        database_url = scoped.render_as_string(hide_password=False)
        monkeypatch.setenv("KCS_DATABASE_URL", database_url)
        command.upgrade(Config("alembic.ini"), "head")
        settings = Settings(database_url=database_url)
    else:
        settings = Settings(database_url=f"sqlite:///{tmp_path}/test.db", testing=True)
    application = create_app(settings)
    bootstrap_admin(
        application.state.database,
        email="admin@example.test",
        password="correct-horse-battery-123",
        tenant_name="Team",
    )
    try:
        yield application
    finally:
        application.state.database.engine.dispose()
        if engine:
            with engine.begin() as connection:
                connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            engine.dispose()
