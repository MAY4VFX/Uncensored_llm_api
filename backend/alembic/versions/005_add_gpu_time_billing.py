"""Add gpu_seconds to usage_logs and margin_multiplier to llm_models

Revision ID: 005
Revises: 004
Create Date: 2026-03-05
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "usage_logs",
        sa.Column("gpu_seconds", sa.Float(), nullable=False, server_default="0"),
    )
    op.add_column(
        "llm_models",
        sa.Column("margin_multiplier", sa.Float(), nullable=False, server_default="1.5"),
    )


def downgrade() -> None:
    op.drop_column("usage_logs", "gpu_seconds")
    op.drop_column("llm_models", "margin_multiplier")
