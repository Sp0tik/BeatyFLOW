"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-09-03

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

booking_status = sa.Enum(
    "pending",
    "confirmed",
    "cancelled_client",
    "cancelled_master",
    "completed",
    "no_show",
    name="booking_status",
)


def upgrade() -> None:
    op.create_table(
        "clients",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tg_id", sa.BigInteger(), nullable=False, unique=True),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("phone", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_clients_tg_id", "clients", ["tg_id"])

    op.create_table(
        "masters",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tg_id", sa.BigInteger(), nullable=True, unique=True),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )

    op.create_table(
        "services",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )

    op.create_table(
        "master_services",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("master_id", sa.Integer(), sa.ForeignKey("masters.id", ondelete="CASCADE"), nullable=False),
        sa.Column("service_id", sa.Integer(), sa.ForeignKey("services.id", ondelete="CASCADE"), nullable=False),
        sa.Column("duration_min", sa.SmallInteger(), nullable=False),
        sa.Column("price", sa.Numeric(10, 2), nullable=False),
        sa.UniqueConstraint("master_id", "service_id", name="uq_master_service"),
    )

    op.create_table(
        "working_hours",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("master_id", sa.Integer(), sa.ForeignKey("masters.id", ondelete="CASCADE"), nullable=False),
        sa.Column("weekday", sa.SmallInteger(), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False),
        sa.UniqueConstraint("master_id", "weekday", name="uq_master_weekday"),
    )

    op.create_table(
        "days_off",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("master_id", sa.Integer(), sa.ForeignKey("masters.id", ondelete="CASCADE"), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("reason", sa.String(255), nullable=True),
        sa.UniqueConstraint("master_id", "date", name="uq_master_dayoff"),
    )

    op.create_table(
        "bookings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("master_id", sa.Integer(), sa.ForeignKey("masters.id", ondelete="CASCADE"), nullable=False),
        sa.Column("service_id", sa.Integer(), sa.ForeignKey("services.id"), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", booking_status, nullable=False, server_default="confirmed"),
        sa.Column("reminder_sent", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_bookings_start_at", "bookings", ["start_at"])


def downgrade() -> None:
    op.drop_table("bookings")
    op.drop_table("days_off")
    op.drop_table("working_hours")
    op.drop_table("master_services")
    op.drop_table("services")
    op.drop_table("masters")
    op.drop_table("clients")
    booking_status.drop(op.get_bind(), checkfirst=True)
