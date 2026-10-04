"""add pgvector-backed embeddings

Revision ID: 20260901_0002
Revises: 20260901_0001
Create Date: 2026-09-01 01:35:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import VECTOR

revision: str = "20260901_0002"
down_revision: str | None = "20260901_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.add_column("embeddings", sa.Column("document_chunk_id", sa.Uuid(), nullable=True))
    op.add_column("embeddings", sa.Column("memory_id", sa.Uuid(), nullable=True))
    op.add_column("embeddings", sa.Column("model_id", sa.String(length=160), nullable=False))
    op.add_column(
        "embeddings",
        sa.Column("dimensions", sa.Integer(), server_default="768", nullable=False),
    )
    embedding_type: sa.types.TypeEngine[object]
    embedding_type = VECTOR(768) if dialect == "postgresql" else sa.JSON()
    op.add_column("embeddings", sa.Column("embedding", embedding_type, nullable=False))
    op.add_column("embeddings", sa.Column("content_hash", sa.String(length=64), nullable=False))
    op.create_index(
        op.f("ix_embeddings_document_chunk_id"),
        "embeddings",
        ["document_chunk_id"],
        unique=False,
    )
    op.create_index(op.f("ix_embeddings_memory_id"), "embeddings", ["memory_id"], unique=False)
    op.create_index(
        op.f("ix_embeddings_content_hash"), "embeddings", ["content_hash"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_embeddings_content_hash"), table_name="embeddings")
    op.drop_index(op.f("ix_embeddings_memory_id"), table_name="embeddings")
    op.drop_index(op.f("ix_embeddings_document_chunk_id"), table_name="embeddings")
    op.drop_column("embeddings", "content_hash")
    op.drop_column("embeddings", "embedding")
    op.drop_column("embeddings", "dimensions")
    op.drop_column("embeddings", "model_id")
    op.drop_column("embeddings", "memory_id")
    op.drop_column("embeddings", "document_chunk_id")
