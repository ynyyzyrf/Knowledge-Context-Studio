"""Start with python -m kcs.worker; graceful stop leaves acknowledged jobs durable."""

import argparse
import signal
from threading import Event

from .config import Settings
from .database import Database
from .jobs import run_one


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
            if args.once:
                break
            if not handled:
                stopping.wait(1)
    finally:
        database.engine.dispose()


if __name__ == "__main__":
    main()
