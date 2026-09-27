"""staff metadata tags + versioning, curated Constitution article links

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-27 11:30:00
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    for col in ("subjects", "people", "places"):
        op.add_column("archival_item", sa.Column(col, postgresql.ARRAY(sa.Text()), nullable=False,
                                                 server_default="{}"))
        op.create_index(f"ix_archival_item_{col}", "archival_item", [col], postgresql_using="gin")
    op.add_column("archival_item", sa.Column("metadata_version", sa.Integer(), nullable=False, server_default="1"))

    op.create_table(
        "metadata_revision",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("before", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("after", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["item_id"], ["archival_item.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("item_id", "version"),
    )

    op.create_table(
        "constitution_article",
        sa.Column("number", sa.String(length=20), nullable=False),
        sa.Column("titles", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("part", sa.String(length=20), nullable=True),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("number"),
    )

    op.create_table(
        "constitution_link",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("article_number", sa.String(length=20), nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("page_id", sa.Integer(), nullable=True),
        sa.Column("media_segment_id", sa.Integer(), nullable=True),
        sa.Column("passage_id", sa.Integer(), nullable=True),
        sa.Column("text_hash", sa.String(length=64), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("removed_by", sa.Text(), nullable=True),
        sa.Column("removal_reason", sa.Text(), nullable=True),
        sa.CheckConstraint("(page_id IS NOT NULL) OR (media_segment_id IS NOT NULL)",
                           name="ck_constitution_link_anchor"),
        sa.ForeignKeyConstraint(["article_number"], ["constitution_article.number"]),
        sa.ForeignKeyConstraint(["item_id"], ["archival_item.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["page_id"], ["page.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["media_segment_id"], ["media_segment.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["passage_id"], ["passage.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_constitution_link_article", "constitution_link", ["article_number"])
    op.create_index("ix_constitution_link_item", "constitution_link", ["item_id"])


def downgrade() -> None:
    op.drop_index("ix_constitution_link_item", table_name="constitution_link")
    op.drop_index("ix_constitution_link_article", table_name="constitution_link")
    op.drop_table("constitution_link")
    op.drop_table("constitution_article")
    op.drop_table("metadata_revision")
    op.drop_column("archival_item", "metadata_version")
    for col in ("places", "people", "subjects"):
        op.drop_index(f"ix_archival_item_{col}", table_name="archival_item")
        op.drop_column("archival_item", col)
