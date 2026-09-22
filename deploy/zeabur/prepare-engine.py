"""Prepare a pinned OpenViking source upload; no credentials are included."""

import argparse
import hashlib
import io
import json
import shutil
import subprocess
import tarfile
from pathlib import Path

COMMIT = "20ec78a149a0889a85b038627dddc70b46dceae3"
REQUIRED = {
    "Cargo.toml", "Cargo.lock", "pyproject.toml", "uv.lock", "setup.py", "README.md",
    "LICENSE", "build_support", "bot", "crates", "openviking", "openviking_cli",
    "src", "third_party", "web-studio",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="Existing upstream Git checkout")
    parser.add_argument("--output", type=Path, required=True, help="New empty upload directory")
    args = parser.parse_args()
    source, output = args.source.resolve(), args.output.resolve()
    if output.exists() and any(output.iterdir()):
        raise SystemExit("Output must be empty; refusing to overwrite existing files")
    actual = subprocess.check_output(
        ["git", "-C", str(source), "rev-parse", COMMIT + "^{commit}"], text=True
    ).strip()
    if actual != COMMIT:
        raise SystemExit("Upstream commit mismatch")
    output.mkdir(parents=True, exist_ok=True)
    archive = output / "upstream-git.tar"
    subprocess.run(
        ["git", "-C", str(source), "archive", "--format=tar", "--output", str(archive), COMMIT],
        check=True,
    )
    manifest = {}
    # Keep native dependencies inside an archive throughout CLI upload. The first
    # loose-file upload reached CMake without LevelDB's helpers/memenv sources.
    # Verify every member in the Docker source stage before expensive compilation.
    with tarfile.open(archive) as bundle, tarfile.open(output / "source.tar", "w") as packed:
        for item in bundle.getmembers():
            if item.name.split("/")[0] not in REQUIRED or not item.isfile():
                continue
            data = bundle.extractfile(item).read()
            manifest[item.name] = hashlib.sha256(data).hexdigest()
            packed.addfile(item, io.BytesIO(data))
    if "third_party/leveldb-1.23/helpers/memenv/memenv.cc" not in manifest:
        raise SystemExit("Pinned source is missing the required LevelDB implementation")
    (output / "source-manifest.json").write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
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
