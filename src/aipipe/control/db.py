from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import ControlSettings, load_settings


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Database:
    def __init__(self, settings: ControlSettings | None = None):
        self.settings = settings or load_settings()

        kwargs = {"pool_pre_ping": True}

        if self.settings.database_url.startswith("sqlite"):
            kwargs["connect_args"] = {
                "check_same_thread": False,
            }

        self.engine = create_engine(
            self.settings.database_url,
            **kwargs,
        )

        self.SessionLocal = sessionmaker(
            bind=self.engine,
            expire_on_commit=False,
        )

    def create_all(self) -> None:
        from . import models  # noqa: F401

        # Create tables that do not exist yet.
        Base.metadata.create_all(self.engine)

        # Backward-compatible lightweight migration for databases created
        # before Project.model was added.
        inspector = inspect(self.engine)

        if "projects" not in inspector.get_table_names():
            return

        columns = {
            column["name"]
            for column in inspector.get_columns("projects")
        }

        if "model" not in columns:
            with self.engine.begin() as connection:
                connection.execute(
                    text(
                        "ALTER TABLE projects "
                        "ADD COLUMN model VARCHAR(64)"
                    )
                )

    @contextmanager
    def session(self) -> Iterator[Session]:
        db = self.SessionLocal()

        try:
            yield db
            db.commit()

        except Exception:
            db.rollback()
            raise

        finally:
            db.close()