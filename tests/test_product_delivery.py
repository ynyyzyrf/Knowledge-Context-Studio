import importlib.util
import io
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from dotenv import dotenv_values


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().parents[1] / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


delivery = load("delivery", "scripts/product.py")
config = load("product_config", "deploy/product_config.py")
prepare = load("prepare", "deploy/zeabur/prepare-engine.py")


class Model:
    calls = 0

    def __init__(self, settings):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def embed(self, texts):
        Model.calls += 1
        return SimpleNamespace(vectors=[[0.1, 0.2, 0.3]])


@pytest.fixture
def runtime(tmp_path):
    root = tmp_path / "product"
    delivery.initialize(root, 18088)
    (root / "settings.env").write_text(
        "KCS_PUBLIC_ORIGIN=http://localhost:18088\nKCS_SECURE_COOKIES=false\n"
        "KCS_MODEL_BASE_URL=https://models.example/v1\nKCS_MODEL_API_KEY='test-$key#value'\n"
        "KCS_CHAT_MODEL=chat\nKCS_EMBEDDING_MODEL=embed\n", encoding="utf-8",
    )
    return root


def test_init_refuses_to_replace_existing_credentials(runtime):
    before = (runtime / "postgres.env").read_bytes()
    with pytest.raises(ValueError, match="not empty"):
        delivery.initialize(runtime, 18088)
    assert (runtime / "postgres.env").read_bytes() == before


def test_private_configuration_preserves_credentials_and_avoids_reprobe(runtime):
    config.configure(runtime, Model)
    first = (runtime / "engine.json").read_bytes()
    count = Model.calls
    config.configure(runtime, Model)
    assert Model.calls == count
    assert (runtime / "engine.json").read_bytes() == first
    engine = json.loads(first)
    env = dotenv_values(runtime / ".env", interpolate=False)
    assert env["KCS_MODEL_API_KEY"] == "test-$key#value"
    assert env["KCS_ENGINE_API_KEY"] == ""
    assert engine["server"]["root_api_key"] not in (runtime / ".env").read_text()
    assert engine["embedding"]["dense"]["dimension"] == 3


def test_embedding_change_fails_before_modifying_existing_state(runtime):
    config.configure(runtime, Model)
    before = (runtime / "engine.json").read_bytes()
    path = runtime / "settings.env"
    path.write_text(path.read_text().replace("MODEL=embed", "MODEL=new-embed"))
    with pytest.raises(ValueError, match="migration"):
        config.configure(runtime, Model)
    assert (runtime / "engine.json").read_bytes() == before


def test_missing_models_cannot_initialize_engine(tmp_path):
    delivery.initialize(tmp_path, 18088)
    with pytest.raises(ValueError, match="Fill"):
        config.configure(tmp_path, Model)
    assert not (tmp_path / "engine.json").exists()


def test_user_cannot_override_internal_engine_credentials(runtime):
    with (runtime / "settings.env").open("a") as stream:
        stream.write("KCS_ENGINE_API_KEY=unexpected\n")
    with pytest.raises(ValueError, match="unsupported"):
        config.configure(runtime, Model)


def test_up_failure_never_starts_application_writers(runtime, monkeypatch):
    args = SimpleNamespace(runtime=runtime, port=18088, bind="127.0.0.1", project="test-product")
    product = delivery.Product(args)
    calls = []

    def compose(*args, **kwargs):
        calls.append(args)
        if "alembic" in args:
            raise subprocess.CalledProcessError(1, args)

    monkeypatch.setattr(product, "compose", compose)
    with pytest.raises(subprocess.CalledProcessError):
        product.up()
    assert calls[:2] == [("stop", "worker", "api"), ("stop", "engine")]
    assert not any(call[0] == "up" and "api" in call for call in calls)


def test_backup_rejects_missing_or_tampered_files(runtime, tmp_path):
    config.configure(runtime, Model)
    for name in ("postgres.dump", "engine.tar"):
        (runtime / name).write_bytes(b"backup fixture")
    images = {name: "sha256:" + "a" * 64 for name in ("api", "worker", "engine", "postgres")}
    manifest = {"version": 1, "engine_commit": delivery.COMMIT, "images": images,
                "files": {name: delivery.file_hash(runtime / name)
                          for name in (*delivery.CONFIG_FILES, "postgres.dump", "engine.tar")}}
    (runtime / "manifest.json").write_text(json.dumps(manifest))
    assert delivery.validate_backup(runtime) == manifest
    (runtime / "engine.tar").write_bytes(b"changed")
    with pytest.raises(ValueError, match="integrity"):
        delivery.validate_backup(runtime)


def test_restore_refuses_existing_runtime(runtime, monkeypatch):
    args = SimpleNamespace(runtime=runtime, port=18088, bind="127.0.0.1", project="test-product")
    monkeypatch.setattr(delivery, "validate_backup", lambda source: {})
    with pytest.raises(ValueError, match="empty runtime"):
        delivery.Product(args).restore(runtime)


def test_source_checksum_failure_does_not_produce_build_context(tmp_path, monkeypatch):
    monkeypatch.setattr(prepare.urllib.request, "urlopen", lambda *a, **kw: io.BytesIO(b"wrong source"))
    monkeypatch.setattr("sys.argv", ["prepare-engine.py", "--output", str(tmp_path)])
    with pytest.raises(SystemExit, match="checksum mismatch"):
        prepare.main()
    assert not (tmp_path / "Dockerfile").exists()
    assert not (tmp_path / "source.tar").exists()
    assert prepare.COMMIT == delivery.COMMIT


def test_restore_refuses_existing_project_volumes(tmp_path, monkeypatch):
    args = SimpleNamespace(runtime=tmp_path / "new", port=18088, bind="127.0.0.1", project="test-product")
    product = delivery.Product(args)
    monkeypatch.setattr(delivery, "validate_backup", lambda source: {})

    def run(*args, **kwargs):
        return SimpleNamespace(stdout=b"existing-volume" if args[1] == "volume" else b"")

    monkeypatch.setattr(product, "run", run)
    with pytest.raises(ValueError, match="new Compose project"):
        product.restore(tmp_path)
    assert not args.runtime.exists()
