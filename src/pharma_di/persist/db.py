"""Database connection (IMPLEMENTATION_PLAN.md P8). CLAUDE.md's tech
default is MySQL — this module can point at a real one, but does not
assume it can reach one on its own.

The connection string comes from the `DATABASE_URL` environment variable
(e.g. `mysql+pymysql://appuser:apppass@localhost/pharma_di`), read by
whoever runs this pipeline, not typed or stored by this codebase or by an
assistant acting on it — database credentials are exactly the kind of
secret that belongs in the operator's own environment, never hardcoded or
handled on someone's behalf. When `DATABASE_URL` isn't set, this defaults
to a local SQLite file (`data/interim/pharma_di.db`): this dev/test
environment has a real local MySQL 8.0 server installed and running, but
no credentials were available to this session to connect to it (root
access requires a password not provided) — SQLite lets the pipeline, its
tests, and its Alembic migrations all run against a real, schema-identical
relational database with zero setup, while keeping every model written
against SQLAlchemy's generic column types so pointing `DATABASE_URL` at a
real MySQL instance is the only change needed to switch, with no code or
migration changes.
"""
from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_SQLITE_PATH = REPO_ROOT / "data" / "interim" / "pharma_di.db"


def database_url() -> str:
    return os.environ.get("DATABASE_URL", f"sqlite:///{_DEFAULT_SQLITE_PATH}")


def get_engine(url: str | None = None) -> Engine:
    resolved = url or database_url()
    if resolved.startswith("sqlite:///"):
        _DEFAULT_SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
    connect_args = {"check_same_thread": False} if resolved.startswith("sqlite") else {}
    return create_engine(resolved, connect_args=connect_args)


def get_session(engine: Engine | None = None) -> Session:
    return Session(engine or get_engine())
