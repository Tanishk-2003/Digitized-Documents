"""P8 unit tests for persist/db.py — the DATABASE_URL-driven connection
lookup (see that module's own docstring for why this project never
hardcodes or accepts a MySQL connection string with credentials: no
credentials for the real local MySQL 8.0 server on this dev machine were
available to build against, so SQLite is the safe, zero-credential default,
with DATABASE_URL as the operator's own escape hatch to a real MySQL
instance).
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from pharma_di.persist.db import database_url, get_engine, get_session


def test_database_url_defaults_to_local_sqlite_file_when_env_var_unset(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    url = database_url()
    assert url.startswith("sqlite:///")
    assert url.endswith("pharma_di.db")


def test_database_url_reads_the_environment_variable_when_set(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "mysql+pymysql://appuser:apppass@localhost/pharma_di")
    assert database_url() == "mysql+pymysql://appuser:apppass@localhost/pharma_di"


def test_get_engine_against_a_temp_sqlite_file_is_usable(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'test.db'}")
    with Session(engine) as session:
        assert session.execute(text("SELECT 1")).scalar() == 1


def test_get_session_returns_a_working_session(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'test.db'}")
    session = get_session(engine)
    try:
        assert isinstance(session, Session)
    finally:
        session.close()
