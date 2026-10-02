"""One product lifecycle, including the bundled private engine. Python + Docker only."""

import argparse
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMMIT = "20ec78a149a0889a85b038627dddc70b46dceae3"
CONFIG_FILES = (".env", "postgres.env", "settings.env", "engine.json", "settings.sha256")


def private_write(path, content):
    with path.open("x", encoding="utf-8") as stream:
        path.chmod(0o600)
        stream.write(content)


def initialize(runtime, port):
    if runtime.exists() and any(runtime.iterdir()):
        raise ValueError("Runtime is not empty; refusing to replace configuration")
    runtime.mkdir(parents=True, exist_ok=True)
    runtime.chmod(0o700)
    password = secrets.token_urlsafe(32)
    private_write(runtime / "postgres.env",
                  f"POSTGRES_USER=kcs\nPOSTGRES_DB=kcs\nPOSTGRES_PASSWORD={password}\n")
    private_write(runtime / ".env",
                  f"KCS_DATABASE_URL=postgresql+psycopg://kcs:{password}@postgres:5432/kcs\n"
                  "KCS_ENGINE_URL=http://engine:1933\n"
                  "KCS_ENGINE_HTTP_ALLOWED_ORIGIN=http://engine:1933\nKCS_ENGINE_API_KEY=\n")
    private_write(runtime / "settings.env",
                  f"KCS_PUBLIC_ORIGIN=http://localhost:{port}\nKCS_SECURE_COOKIES=false\n"
                  "KCS_MODEL_BASE_URL=\nKCS_MODEL_API_KEY=\nKCS_CHAT_MODEL=\n"
                  "KCS_MODEL_HTTP_ALLOWED_ORIGIN=\nKCS_EMBEDDING_BASE_URL=\n"
                  "KCS_EMBEDDING_API_KEY=\nKCS_EMBEDDING_MODEL=\nKCS_EMBEDDING_HTTP_ALLOWED_ORIGIN=\n")
    print(f"Initialized {runtime}. Fill settings.env, then run build and up.")


class Product:
    def __init__(self, args):
        self.args = args
        self.runtime = args.runtime.resolve()
        self.env = {**os.environ, "KCS_PRODUCT_RUNTIME": self.runtime.as_posix(),
                    "KCS_PRODUCT_PORT": str(args.port), "KCS_PRODUCT_BIND": args.bind}
        # Never read a developer .env for Compose interpolation.
        self.command = ["docker", "compose", "--env-file", os.devnull, "-p", args.project,
                        "-f", str(ROOT / "compose.product.yaml")]

    def run(self, *args, capture=False, **kwargs):
        return subprocess.run(list(args), cwd=ROOT, env=self.env, check=True,
                              capture_output=capture, **kwargs)

    def compose(self, *args, **kwargs):
        return self.run(*self.command, *args, **kwargs)

    def tools(self, *args, **kwargs):
        return self.compose("run", "--rm", "--no-deps", "-T", "tools", *args, **kwargs)

    def quiesce(self):
        self.compose("stop", "worker", "api")
        self.compose("stop", "engine")

    def build(self):
        self.run("docker", "build", "--platform", "linux/amd64", "-t",
                 self.env.get("KCS_PRODUCT_IMAGE", "kcs-product:local"), ".")
        # Each build starts from an empty context and verifies the source archive.
        # Kept under ignored runtime so it can also be supplied with a release.
        parent = ROOT / "runtime" / "product-builds"
        parent.mkdir(parents=True, exist_ok=True)
        context = Path(tempfile.mkdtemp(prefix="engine-", dir=parent))
        self.run(sys.executable, "deploy/zeabur/prepare-engine.py", "--output", str(context))
        self.run("docker", "build", "--platform", "linux/amd64", "-t",
                 self.env.get("KCS_PRODUCT_ENGINE_IMAGE", "kcs-product-engine:20ec78a1"), str(context))
        print("Built product and bundled engine from pinned source.")

    def up(self):
        if not (self.runtime / "settings.env").is_file():
            raise ValueError("Run init and configure settings.env first")
        # Stop all writers before configuration, schema and index initialization.
        self.quiesce()
        self.tools("python", "deploy/product_config.py")
        self.compose("up", "-d", "--wait", "postgres")
        self.tools("alembic", "upgrade", "head")
        self.compose("up", "-d", "--force-recreate", "engine")
        deadline = time.monotonic() + 180
        while True:
            try:
                self.tools("python", "scripts/connect-engine.py", capture=True)
                self.tools("python", "scripts/check-engine.py", capture=True)
                print("Bundled engine and private publisher ready.", flush=True)
                break
            except subprocess.CalledProcessError:
                if time.monotonic() >= deadline:
                    raise RuntimeError("Bundled engine not ready; API and worker remain stopped") from None
                time.sleep(3)
        self.compose("up", "-d", "--force-recreate", "--wait", "api", "worker")
        self.compose("ps")
        print("Product started. Readiness alone is not business acceptance.")

    def backup(self, destination):
        if destination.exists():
            raise ValueError("Backup destination must not exist")
        destination.mkdir(parents=True, mode=0o700)
        self.quiesce()
        self.compose("up", "-d", "--wait", "postgres")
        with (destination / "postgres.dump").open("wb") as stream:
            self.compose("exec", "-T", "postgres", "pg_dump", "-U", "kcs", "-Fc", "kcs", stdout=stream)
        self.compose("run", "--rm", "--no-deps", "-T", "--entrypoint", "python",
                     "-v", f"{destination.as_posix()}:/backup", "engine", "-c",
                     "import tarfile; t=tarfile.open('/backup/engine.tar','w'); t.add('/data',arcname='data'); t.close()")
        for name in CONFIG_FILES:
            shutil.copyfile(self.runtime / name, destination / name)
            (destination / name).chmod(0o600)
        images = {}
        for service in ("api", "worker", "engine", "postgres"):
            container = self.compose("ps", "-a", "-q", service, capture=True).stdout.decode().strip()
            if not container:
                raise ValueError("Backups require a previously initialized full product")
            images[service] = self.run("docker", "inspect", "--format", "{{.Image}}",
                                       container, capture=True).stdout.decode().strip()
        manifest = {"version": 1, "engine_commit": COMMIT, "images": images,
                    "files": {p.name: file_hash(p) for p in destination.iterdir() if p.is_file()}}
        private_write(destination / "manifest.json", json.dumps(manifest, indent=2))
        print("Cold backup complete; contains credentials. Product remains stopped. Run up to resume.")

    def restore(self, source):
        # No overwrite path: restoration is always isolated and stays offline.
        manifest = validate_backup(source)
        if self.runtime.exists() and any(self.runtime.iterdir()):
            raise ValueError("Restore requires an empty runtime directory")
        for resource in ("container", "volume"):
            ids = self.run("docker", resource, "ls", "-q", "--filter",
                           f"label=com.docker.compose.project={self.args.project}", capture=True).stdout.strip()
            if ids:
                raise ValueError("Restore requires a new Compose project with no containers or volumes")
        for image in manifest["images"].values():
            self.run("docker", "image", "inspect", image, capture=True)
        # Force exact backed-up images, avoiding a mutable :local tag on restore.
        self.env["KCS_PRODUCT_IMAGE"] = manifest["images"]["api"]
        self.env["KCS_PRODUCT_ENGINE_IMAGE"] = manifest["images"]["engine"]
        self.env["KCS_PRODUCT_POSTGRES_IMAGE"] = manifest["images"]["postgres"]
        self.runtime.mkdir(parents=True, exist_ok=True)
        self.runtime.chmod(0o700)
        for name in CONFIG_FILES:
            shutil.copyfile(source / name, self.runtime / name)
            (self.runtime / name).chmod(0o600)
        private_write(self.runtime / "restored-images.json", json.dumps(manifest["images"]))
        self.compose("up", "-d", "--wait", "postgres")
        with (source / "postgres.dump").open("rb") as stream:
            self.compose("exec", "-T", "postgres", "pg_restore", "-U", "kcs", "-d", "kcs",
                         "--exit-on-error", "--no-owner", stdin=stream)
        self.compose("run", "--rm", "--no-deps", "-T", "--entrypoint", "python",
                     "-v", f"{source.as_posix()}:/backup:ro", "engine", "-c",
                     "import tarfile; t=tarfile.open('/backup/engine.tar'); t.extractall('/',filter='data'); t.close()")
        self.compose("stop", "postgres")
        print("Restored into an isolated, stopped project. Verify revocation/deletion policy before any cutover.")


def file_hash(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def validate_backup(source):
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    expected = set(CONFIG_FILES) | {"postgres.dump", "engine.tar"}
    if manifest.get("version") != 1 or set(manifest.get("files", {})) != expected:
        raise ValueError("Unsupported or incomplete backup")
    if manifest.get("engine_commit") != COMMIT:
        raise ValueError("Restore with the matching product release first")
    for name, digest in manifest["files"].items():
        if (source / name).is_symlink() or file_hash(source / name) != digest:
            raise ValueError("Backup integrity check failed")
    images = manifest.get("images", {})
    if set(images) != {"api", "worker", "engine", "postgres"} or images["api"] != images["worker"]:
        raise ValueError("Backup images are incomplete or inconsistent")
    if not all(re.fullmatch(r"sha256:[a-f0-9]{64}", value) for value in images.values()):
        raise ValueError("Backup images must be immutable IDs")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["init", "build", "up", "status", "stop", "admin", "backup", "restore"])
    parser.add_argument("--runtime", type=Path, default=ROOT / "runtime" / "product")
    parser.add_argument("--project", default="kcs-product")
    parser.add_argument("--port", type=int, default=18088)
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--email")
    parser.add_argument("--backup", type=Path, help="New backup destination or existing restore source")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", args.project) or not 1 <= args.port <= 65535:
        parser.error("Invalid project name or port")
    product = Product(args)
    restored = product.runtime / "restored-images.json"
    if restored.exists():
        images = json.loads(restored.read_text())
        product.env["KCS_PRODUCT_IMAGE"] = images["api"]
        product.env["KCS_PRODUCT_ENGINE_IMAGE"] = images["engine"]
        product.env["KCS_PRODUCT_POSTGRES_IMAGE"] = images["postgres"]
    if args.action == "init":
        initialize(product.runtime, args.port)
    elif args.action == "build":
        if restored.exists():
            raise ValueError("Restored environment uses immutable images; build a new release separately")
        product.build()
    elif args.action == "up":
        product.up()
    elif args.action == "status":
        product.compose("ps", "-a")
    elif args.action == "stop":
        product.quiesce()
        product.compose("stop", "postgres")
    elif args.action == "admin":
        if not args.email:
            parser.error("admin requires --email")
        product.compose("run", "--rm", "--no-deps", "tools", "python", "-m", "kcs.manage",
                        "bootstrap", "--email", args.email)
    else:
        if not args.backup:
            parser.error("backup/restore requires --backup")
        if args.action == "backup":
            product.backup(args.backup.resolve())
        else:
            product.restore(args.backup.resolve())


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError) as exc:
        raise SystemExit(str(exc)) from None
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"Product operation failed (exit {exc.returncode}); later steps were not executed.") from None
