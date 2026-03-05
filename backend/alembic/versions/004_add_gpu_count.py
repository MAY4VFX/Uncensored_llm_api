"""Add gpu_count column to llm_models for multi-GPU endpoints

Revision ID: 004
Revises: 003
Create Date: 2026-03-05
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "llm_models",
        sa.Column("gpu_count", sa.Integer(), nullable=False, server_default="1"),
    )


def downgrade() -> None:
    op.drop_column("llm_models", "gpu_count")
