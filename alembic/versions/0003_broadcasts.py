"""add broadcasts

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-29

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "broadcasts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("interval_days", sa.SmallInteger(), nullable=False, server_default="15"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "broadcast_sends",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "broadcast_id",
            sa.Integer(),
            sa.ForeignKey("broadcasts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "client_id",
            sa.Integer(),
            sa.ForeignKey("clients.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("broadcast_id", "client_id", "sent_at", name="uq_broadcast_send"),
    )
    op.create_index("ix_broadcast_sends_client", "broadcast_sends", ["client_id"])


def downgrade() -> None:
    op.drop_index("ix_broadcast_sends_client", table_name="broadcast_sends")
    op.drop_table("broadcast_sends")
    op.drop_table("broadcasts")