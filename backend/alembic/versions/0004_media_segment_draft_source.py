"""machine-draft provenance on transcript segments (Sarvam speech-to-text)

Revision ID: 0004_segment_draft_source
Revises: 0003_hard_negatives
Create Date: 2026-09-27 16:30:00

Adds nullable columns only: existing segments (human or imported drafts) keep NULL.
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = '0004_segment_draft_source'
down_revision = '0003_hard_negatives'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("media_segment", sa.Column("draft_engine", sa.Text(), nullable=True))
    op.add_column("media_segment", sa.Column("source_file_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_media_segment_source_file", "media_segment", "file_version",
                          ["source_file_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    op.drop_constraint("fk_media_segment_source_file", "media_segment", type_="foreignkey")
    op.drop_column("media_segment", "source_file_id")
    op.drop_column("media_segment", "draft_engine")
