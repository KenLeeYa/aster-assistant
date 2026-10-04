from __future__ import annotations

from alembic import command
from alembic.config import Config
from ky_jarvis_core.persistence.schema import REQUIRED_TABLES
from sqlalchemy import create_engine, inspect


def test_initial_migration_upgrades_and_downgrades(tmp_path, monkeypatch) -> None:
    database_path = tmp_path / "migration.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("KY_JARVIS_DATABASE_URL", database_url)

    config = Config("alembic.ini")
    command.upgrade(config, "head")

    engine = create_engine(database_url)
    assert set(REQUIRED_TABLES) <= set(inspect(engine).get_table_names())
    engine.dispose()

    command.downgrade(config, "base")

    engine = create_engine(database_url)
    assert inspect(engine).get_table_names() == ["alembic_version"]
    engine.dispose()
