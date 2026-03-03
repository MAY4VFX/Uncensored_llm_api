"""Initial migration - create all tables

Revision ID: 001
Revises:
Create Date: 2026-03-03
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create enums
    user_tier = postgresql.ENUM("free", "starter", "pro", "business", name="user_tier", create_type=False)
    user_tier.create(op.get_bind(), checkfirst=True)

    model_status = postgresql.ENUM("pending", "deploying", "active", "inactive", name="model_status", create_type=False)
    model_status.create(op.get_bind(), checkfirst=True)

    # Users table
    op.create_table(
        "users",
        sa.Column("id", sa.UUID(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("credits", sa.Numeric(12, 6), nullable=False, server_default="0"),
        sa.Column("tier", user_tier, nullable=False, server_default="free"),
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    # API Keys table
    op.create_table(
        "api_keys",
        sa.Column("id", sa.UUID(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", sa.UUID(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("key_prefix", sa.String(16), nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False),
        sa.Column("name", sa.String(100), nullable=False, server_default="Default"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_api_keys_key_hash", "api_keys", ["key_hash"], unique=True)

    # LLM Models table
    op.create_table(
        "llm_models",
        sa.Column("id", sa.UUID(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("slug", sa.String(200), nullable=False),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("hf_repo", sa.String(300), nullable=False),
        sa.Column("params_b", sa.Float(), nullable=False),
        sa.Column("quantization", sa.String(10), nullable=False, server_default="Q4"),
        sa.Column("gpu_type", sa.String(50), nullable=False),
        sa.Column("runpod_endpoint_id", sa.String(100), nullable=True),
        sa.Column("status", model_status, nullable=False, server_default="pending"),
        sa.Column("cost_per_1m_input", sa.Numeric(10, 4), nullable=False, server_default="0"),
        sa.Column("cost_per_1m_output", sa.Numeric(10, 4), nullable=False, server_default="0"),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("hf_downloads", sa.Integer(), nullable=True),
        sa.Column("hf_likes", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_llm_models_slug", "llm_models", ["slug"], unique=True)

    # Usage Logs table
    op.create_table(
        "usage_logs",
        sa.Column("id", sa.UUID(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", sa.UUID(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("api_key_id", sa.UUID(), sa.ForeignKey("api_keys.id"), nullable=False),
        sa.Column("model_id", sa.UUID(), sa.ForeignKey("llm_models.id"), nullable=False),
        sa.Column("tokens_in", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_out", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost", sa.Numeric(12, 6), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_usage_logs_user_id", "usage_logs", ["user_id"])
    op.create_index("ix_usage_logs_created_at", "usage_logs", ["created_at"])


def downgrade() -> None:
    op.drop_table("usage_logs")
    op.drop_table("llm_models")
    op.drop_table("api_keys")
    op.drop_table("users")
    op.execute("DROP TYPE IF EXISTS model_status")
    op.execute("DROP TYPE IF EXISTS user_tier")
