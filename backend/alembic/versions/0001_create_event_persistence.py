"""Create infrastructure event history and durable deduplication keys.

Revision ID: 0001_event_persistence
Revises:
Create Date: 2026-10-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_event_persistence"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "live_event_records",
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("provider_event_id", sa.String(length=256), nullable=True),
        sa.Column("session_id", sa.String(length=256), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("viewer_data", sa.JSON(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("processing_status", sa.String(length=16), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "processing_status IN ('RECEIVED', 'PROCESSED', 'FAILED')",
            name="ck_live_event_records_processing_status",
        ),
        sa.PrimaryKeyConstraint("event_id"),
    )
    op.create_index("ix_live_event_records_received_at", "live_event_records", ["received_at"])
    op.create_index(
        "ix_live_event_records_processing_status",
        "live_event_records",
        ["processing_status"],
    )
    op.create_index("ix_live_event_records_session_id", "live_event_records", ["session_id"])

    op.create_table(
        "event_deduplication_keys",
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("provider_event_id", sa.String(length=256), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["event_id"], ["live_event_records.event_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("provider", "provider_event_id"),
    )
    op.create_index(
        "ix_event_deduplication_keys_event_id",
        "event_deduplication_keys",
        ["event_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_event_deduplication_keys_event_id", table_name="event_deduplication_keys")
    op.drop_table("event_deduplication_keys")
    op.drop_index("ix_live_event_records_session_id", table_name="live_event_records")
    op.drop_index("ix_live_event_records_processing_status", table_name="live_event_records")
    op.drop_index("ix_live_event_records_received_at", table_name="live_event_records")
    op.drop_table("live_event_records")
