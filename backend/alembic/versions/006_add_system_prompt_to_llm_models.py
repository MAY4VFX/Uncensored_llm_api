"""add system_prompt to llm_models

Revision ID: 006_add_system_prompt_to_llm_models
Revises: 005_add_gpu_time_billing
Create Date: 2026-04-15
"""

from alembic import op
import sqlalchemy as sa

revision = "006_add_system_prompt_to_llm_models"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("llm_models", sa.Column("system_prompt", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("llm_models", "system_prompt")
