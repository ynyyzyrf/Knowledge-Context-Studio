"""Create new cloud-only configuration; never overwrite an initialized deployment."""

import os
import secrets
from pathlib import Path

root = Path("/app/runtime")
root.mkdir(parents=True, exist_ok=True)
if any(root.iterdir()):
    raise SystemExit("Runtime directory is not empty; refusing to replace existing configuration.")
password = secrets.token_urlsafe(32)
files = {
    "postgres.env": f"POSTGRES_USER=kcs\nPOSTGRES_DB=kcs\nPOSTGRES_PASSWORD={password}\n",
    ".env": (
        f"KCS_DATABASE_URL=postgresql+psycopg://kcs:{password}@postgres:5432/kcs\n"
        "KCS_PUBLIC_ORIGIN=http://localhost:18088\nKCS_SECURE_COOKIES=false\n"
        "KCS_ENGINE_URL=http://engine:1933\n"
        "KCS_ENGINE_HTTP_ALLOWED_ORIGIN=http://engine:1933\nKCS_ENGINE_API_KEY=\n"
        "KCS_MODEL_BASE_URL=\nKCS_MODEL_HTTP_ALLOWED_ORIGIN=\n"
        "KCS_MODEL_API_KEY=\nKCS_CHAT_MODEL=\n"
        "KCS_EMBEDDING_BASE_URL=\nKCS_EMBEDDING_HTTP_ALLOWED_ORIGIN=\n"
        "KCS_EMBEDDING_API_KEY=\nKCS_EMBEDDING_MODEL=\n"
    ),
}
for name, content in files.items():
    path = root / name
    path.write_text(content, encoding="utf-8")
    path.chmod(0o600)
    os.chown(path, 10001, 10001)
root.chmod(0o700)
os.chown(root, 10001, 10001)
print("Created isolated cloud config. Edit deploy/runtime/.env with your model settings before startup.")
