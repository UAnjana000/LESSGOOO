"""hard-negative candidates with human review (spec 7.3 step 2)

Revision ID: 0003_hard_negatives
Revises: 0002
Create Date: 2026-09-27 12:00:00

Chained after 0002 (visitor features). Apply only after 0002 is applied.
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = '0003_hard_negatives'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "hard_negative_candidate",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("training_example_id", sa.Integer(), nullable=False),
        sa.Column("passage_id", sa.Integer(), nullable=False),
        sa.Column("text_sha256", sa.String(length=64), nullable=False),
        sa.Column("relation", sa.String(length=20), nullable=False),
        sa.Column("retriever", sa.Text(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("provenance", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("mined_by", sa.Text(), nullable=False),
        sa.Column("mined_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_by", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.CheckConstraint("status IN ('candidate', 'confirmed', 'false_negative', 'rejected')",
                           name="ck_hard_negative_status"),
        sa.ForeignKeyConstraint(["training_example_id"], ["training_example.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["passage_id"], ["passage.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("training_example_id", "passage_id"),
    )
    op.create_index("ix_hard_negative_candidate_status", "hard_negative_candidate", ["status"])


def downgrade() -> None:
    op.drop_index("ix_hard_negative_candidate_status", table_name="hard_negative_candidate")
    op.drop_table("hard_negative_candidate")
