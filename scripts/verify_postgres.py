from __future__ import annotations

import os

from ky_jarvis_core.persistence.schema import REQUIRED_TABLES
from sqlalchemy import create_engine, inspect, text


def main() -> None:
    database_url = os.environ["KY_JARVIS_DATABASE_URL"]
    engine = create_engine(database_url)
    with engine.connect() as connection:
        extension_version = connection.execute(
            text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
        ).scalar_one()
        column_type = connection.execute(
            text(
                "SELECT udt_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = 'embeddings' "
                "AND column_name = 'embedding'"
            )
        ).scalar_one()
    table_count = len(set(REQUIRED_TABLES) & set(inspect(engine).get_table_names()))
    engine.dispose()
    if table_count != len(REQUIRED_TABLES) or column_type != "vector":
        raise RuntimeError("PostgreSQL schema or pgvector column is incomplete")
    print(f"verified_tables={table_count} pgvector={extension_version}")


if __name__ == "__main__":
    main()
