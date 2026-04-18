"""add multi provider foundation

Revision ID: 007_add_multi_provider_foundation
Revises: 006_add_system_prompt_to_llm_models
Create Date: 2026-04-18
"""

from alembic import op
import sqlalchemy as sa

revision = "007_add_multi_provider_foundation"
down_revision = "006_add_system_prompt_to_llm_models"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "app_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("default_provider", sa.String(length=20), nullable=False, server_default="modal"),
        sa.Column("modal_default_image", sa.String(length=255), nullable=True),
        sa.Column("runpod_default_image", sa.String(length=255), nullable=True),
        sa.Column("provider_flags", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.add_column("llm_models", sa.Column("provider_override", sa.String(length=20), nullable=True))
    op.add_column("llm_models", sa.Column("provider_config", sa.JSON(), nullable=True))
    op.add_column("llm_models", sa.Column("deployment_ref", sa.String(length=255), nullable=True))
    op.add_column("llm_models", sa.Column("provider_status", sa.String(length=50), nullable=True))

    op.execute(
        """
        INSERT INTO app_settings (id, default_provider, provider_flags)
        VALUES (1, 'modal', '{}'::json)
        ON CONFLICT (id) DO NOTHING
        """
    )
    op.execute(
        """
        UPDATE llm_models
        SET provider_override = 'runpod',
            provider_status = CASE
                WHEN status = 'active' THEN 'active'
                WHEN status = 'deploying' THEN 'deploying'
                ELSE 'inactive'
            END,
            deployment_ref = runpod_endpoint_id
        WHERE provider_override IS NULL
        """
    )


def downgrade() -> None:
    op.drop_column("llm_models", "provider_status")
    op.drop_column("llm_models", "deployment_ref")
    op.drop_column("llm_models", "provider_config")
    op.drop_column("llm_models", "provider_override")
    op.drop_table("app_settings")
