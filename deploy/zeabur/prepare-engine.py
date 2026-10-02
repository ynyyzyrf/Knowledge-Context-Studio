"""Prepare a pinned OpenViking source upload; no credentials are included."""

import argparse
import hashlib
import io
import json
import shutil
import subprocess
import tarfile
import urllib.request
from pathlib import Path

COMMIT = "20ec78a149a0889a85b038627dddc70b46dceae3"
SOURCE_URL = f"https://codeload.github.com/volcengine/OpenViking/tar.gz/{COMMIT}"
SOURCE_SHA256 = "62a5346c445e17333f5307e1e2df5bdfdad0e9fcc19c46843d60ac664f956006"
REQUIRED = {
    "Cargo.toml", "Cargo.lock", "pyproject.toml", "uv.lock", "setup.py", "README.md",
    "LICENSE", "build_support", "bot", "crates", "openviking", "openviking_cli",
    "src", "third_party", "web-studio",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, help="Optional offline upstream Git checkout")
    parser.add_argument("--output", type=Path, required=True, help="New empty upload directory")
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() and any(output.iterdir()):
        raise SystemExit("Output must be empty; refusing to overwrite existing files")
    output.mkdir(parents=True, exist_ok=True)
    archive = output / "upstream-git.tar"
    prefix = ""
    if args.source:
        subprocess.run(
            ["git", "-c", "core.autocrlf=false", "-C", str(args.source.resolve()), "archive", "--format=tar",
             "--output", str(archive), COMMIT], check=True,
        )
    else:
        digest = hashlib.sha256()
        with urllib.request.urlopen(SOURCE_URL, timeout=120) as response, archive.open("wb") as destination:
            while chunk := response.read(1024 * 1024):
                destination.write(chunk)
                digest.update(chunk)
        if digest.hexdigest() != SOURCE_SHA256:
            raise SystemExit("Upstream source checksum mismatch; refusing to build")
        prefix = f"OpenViking-{COMMIT}/"
    manifest = {}
    # Keep native dependencies inside an archive throughout CLI upload. The first
    # loose-file upload reached CMake without LevelDB's helpers/memenv sources.
    # Verify every member in the Docker source stage before expensive compilation.
    with tarfile.open(archive) as bundle, tarfile.open(output / "source.tar", "w") as packed:
        for item in bundle.getmembers():
            if prefix:
                if not item.name.startswith(prefix):
                    continue
                item.name = item.name[len(prefix):]
            if item.name.split("/")[0] not in REQUIRED or not item.isfile():
                continue
            if ".." in Path(item.name).parts or item.name.startswith("/"):
                raise SystemExit("Unsafe archive path")
            data = bundle.extractfile(item).read()
            manifest[item.name] = hashlib.sha256(data).hexdigest()
            packed.addfile(item, io.BytesIO(data))
    if "third_party/leveldb-1.23/helpers/memenv/memenv.cc" not in manifest:
        raise SystemExit("Pinned source is missing the required LevelDB implementation")
    (output / "source-manifest.json").write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    (output / "source-lock.json").write_text(
        json.dumps({"commit": COMMIT, "url": SOURCE_URL, "archive_sha256": SOURCE_SHA256}), encoding="utf-8"
    )
    archive.unlink()
    here = Path(__file__).resolve().parent
    shutil.copyfile(here / "openviking.Dockerfile", output / "Dockerfile")
    shutil.copyfile(here / "engine-start.py", output / "kcs-engine-start.py")
    (output / "zbpack.json").write_text(
        json.dumps({"dockerfile": {"path": "Dockerfile"}}), encoding="utf-8"
    )
    (output / ".zeaburignore").write_text(
        ".git\n.env\n*.log\n",
        encoding="utf-8",
    )
    print(f"Prepared OpenViking {COMMIT} at {output}; no runtime configuration included")


if __name__ == "__main__":
    main()
