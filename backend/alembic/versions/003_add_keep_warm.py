"""Add keep_warm table and gpu_hourly_cost/keep_warm_price to llm_models

Revision ID: 003
Revises: 002
Create Date: 2026-03-05
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "llm_models",
        sa.Column("gpu_hourly_cost", sa.Numeric(10, 4), nullable=False, server_default="0"),
    )
    op.add_column(
        "llm_models",
        sa.Column("keep_warm_price", sa.Numeric(10, 4), nullable=False, server_default="0"),
    )

    op.create_table(
        "keep_warm",
        sa.Column("id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", sa.UUID(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("model_id", sa.UUID(), sa.ForeignKey("llm_models.id"), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("activated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_billed_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "model_id"),
    )
    op.create_index(
        "ix_keep_warm_active",
        "keep_warm",
        ["model_id"],
        postgresql_where=sa.text("is_active = true"),
    )


def downgrade() -> None:
    op.drop_index("ix_keep_warm_active", table_name="keep_warm")
    op.drop_table("keep_warm")
    op.drop_column("llm_models", "keep_warm_price")
    op.drop_column("llm_models", "gpu_hourly_cost")
