"""Local operator commands; credentials are never printed."""

import argparse
import getpass
import secrets
from pathlib import Path

from .bootstrap import bootstrap_admin
from .config import Settings
from .database import Database
from .model_service import ModelService, ModelServiceError


def init_config():
    root = Path.cwd()
    runtime = root / "runtime"
    if (root / ".env").exists() or (runtime / "postgres.env").exists():
        raise SystemExit("Configuration already exists; refusing to overwrite")
    runtime.mkdir(exist_ok=True)
    password = secrets.token_urlsafe(32)
    (runtime / "postgres.env").write_text(
        f"POSTGRES_USER=kcs\nPOSTGRES_DB=kcs\nPOSTGRES_PASSWORD={password}\n", encoding="utf-8"
    )
    (root / ".env").write_text(
        f"KCS_DATABASE_URL=postgresql+psycopg://kcs:{password}@127.0.0.1:55488/kcs\n"
        "KCS_PUBLIC_ORIGIN=http://localhost:8088\nKCS_SECURE_COOKIES=false\n"
        "KCS_MODEL_BASE_URL=\nKCS_MODEL_API_KEY=\nKCS_CHAT_MODEL=\nKCS_EMBEDDING_MODEL=\n",
        encoding="utf-8",
    )
    print("Local configuration created. Model settings can be edited in .env.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["init-config", "bootstrap", "check-models", "check-chat"])
    parser.add_argument("--email")
    parser.add_argument("--team", default="內部團隊")
    args = parser.parse_args()
    if args.command == "init-config":
        init_config()
    elif args.command in ("check-models", "check-chat"):
        try:
            with ModelService(Settings()) as service:
                chat = service.chat([{"role": "user", "content": "Reply with OK."}], max_tokens=16)
                if args.command == "check-chat":
                    print(f"Chat check passed; reported tokens={chat.input_tokens}/{chat.output_tokens}.")
                    return
                embedding = service.embed(["Knowledge Context Studio connectivity check"])
            print(
                f"Model checks passed: chat returned text; embedding dimensions={len(embedding.vectors[0])}; "
                f"reported chat tokens={chat.input_tokens}/{chat.output_tokens}."
            )
        except ModelServiceError as error:
            raise SystemExit(f"Model check failed: {error.code}") from None
    else:
        bootstrap_admin(
            Database(Settings().database_url),
            email=args.email or input("Email: "),
            password=getpass.getpass("Password (16+ characters): "),
            tenant_name=args.team,
        )
        print("Administrator created.")


if __name__ == "__main__":
    main()
