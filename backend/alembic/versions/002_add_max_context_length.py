"""Add max_context_length to llm_models

Revision ID: 002
Revises: 001
Create Date: 2026-03-04
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "llm_models",
        sa.Column("max_context_length", sa.Integer(), nullable=False, server_default="4096"),
    )


def downgrade() -> None:
    op.drop_column("llm_models", "max_context_length")
