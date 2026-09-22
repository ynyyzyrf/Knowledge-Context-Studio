"""Start with python -m kcs.worker; graceful stop leaves acknowledged jobs durable."""

import argparse
import signal
from threading import Event

from .config import Settings
from .database import Database
from .document_worker import run_one as ingest_one
from .jobs import run_one
from .publication import run_one as publish_one


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    settings = Settings()
    database = Database(settings.database_url)
    stopping = Event()
    signal.signal(signal.SIGINT, lambda *_: stopping.set())
    signal.signal(signal.SIGTERM, lambda *_: stopping.set())
    try:
        while not stopping.is_set():
            handled = run_one(database, settings)
            published = publish_one(database, settings)
            ingested = ingest_one(database, settings)
            if args.once:
                break
            if not handled and not published and not ingested:
                stopping.wait(1)
    finally:
        database.engine.dispose()


if __name__ == "__main__":
    main()
