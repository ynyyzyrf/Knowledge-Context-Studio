from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from .models import Base


class Database:
    def __init__(self, url: str, *, testing=False):
        arguments = {"check_same_thread": False} if url.startswith("sqlite:") else {}
        self.engine = create_engine(url, pool_pre_ping=True, connect_args=arguments)
        if url.startswith("sqlite:"):

            @event.listens_for(self.engine, "connect")
            def foreign_keys(connection, _):
                connection.execute("PRAGMA foreign_keys=ON")

        self.sessions = sessionmaker(self.engine, expire_on_commit=False)
        if testing:
            Base.metadata.create_all(self.engine)
