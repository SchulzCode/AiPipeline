from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import ControlSettings, load_settings


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# Small, explicit compatibility migrations for the V1 control database.
# These are intentionally declarative and tested against old schemas. A future
# major schema expansion should move to Alembic rather than growing this list
# indefinitely.
_COLUMN_MIGRATIONS: tuple[tuple[str, str, str], ...] = (
    ("control_projects", "model", "VARCHAR(64)"),
    ("control_tasks", "failure_category", "VARCHAR(64)"),
    ("control_tasks", "worker_build", "VARCHAR(128)"),
)


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

    def _column_exists(self, table_name: str, column_name: str) -> bool:
        inspector = inspect(self.engine)
        if table_name not in inspector.get_table_names():
            return False
        return column_name in {
            column["name"]
            for column in inspector.get_columns(table_name)
        }

    def _ensure_column(self, table_name: str, column_name: str, ddl: str) -> None:
        if self._column_exists(table_name, column_name):
            return

        # Identifiers and DDL fragments come only from the fixed migration list
        # above; no user-controlled values are interpolated here.
        statement = text(
            f"ALTER TABLE {table_name} ADD COLUMN {column_name} {ddl}"
        )

        try:
            with self.engine.begin() as connection:
                connection.execute(statement)
        except (OperationalError, ProgrammingError):
            # API and worker can start concurrently. If another process applied
            # the same migration between our inspection and ALTER, the desired
            # end state already exists and this is safe to treat as success.
            if not self._column_exists(table_name, column_name):
                raise

    def create_all(self) -> None:
        from . import models  # noqa: F401

        Base.metadata.create_all(self.engine)

        for table_name, column_name, ddl in _COLUMN_MIGRATIONS:
            # A table absent from an intentionally partial/legacy test schema
            # will be created by metadata above. If it is still absent, there is
            # nothing useful to migrate and schema_status will report it.
            if table_name in inspect(self.engine).get_table_names():
                self._ensure_column(table_name, column_name, ddl)

        status = self.schema_status()
        if not status["ok"]:
            missing = ", ".join(status["missing"])
            raise RuntimeError(f"Control database schema is incompatible; missing: {missing}")

    def schema_status(self) -> dict[str, object]:
        from . import models  # noqa: F401

        inspector = inspect(self.engine)
        tables = set(inspector.get_table_names())
        missing: list[str] = []

        for table in Base.metadata.sorted_tables:
            if table.name not in tables:
                missing.append(f"table:{table.name}")
                continue

            actual = {
                column["name"]
                for column in inspector.get_columns(table.name)
            }
            for column in table.columns:
                if column.name not in actual:
                    missing.append(f"column:{table.name}.{column.name}")

        return {
            "ok": not missing,
            "missing": missing,
        }

    def ping(self) -> bool:
        try:
            with self.engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            return True
        except Exception:
            return False

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
