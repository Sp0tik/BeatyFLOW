"""production hardening and crm fields

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-01
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Поля CRM / маркетингу / історичної ціни.
    op.add_column("clients", sa.Column("marketing_opt_in", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("master_services", sa.Column("buffer_min", sa.SmallInteger(), nullable=False, server_default="0"))
    op.add_column("bookings", sa.Column("price_snapshot", sa.Numeric(10, 2), nullable=True))
    op.add_column("broadcast_sends", sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("broadcast_sends", sa.Column("error_code", sa.String(64), nullable=True))

    # Заповнюємо історичну ціну настільки точно, наскільки дозволяє стара схема.
    op.execute(
        """
        UPDATE bookings b
           SET price_snapshot = ms.price
          FROM master_services ms
         WHERE ms.master_id = b.master_id
           AND ms.service_id = b.service_id
           AND b.price_snapshot IS NULL
        """
    )

    # Кілька робочих інтервалів на один weekday (перерва посеред дня).
    op.drop_constraint("uq_master_weekday", "working_hours", type_="unique")
    op.create_unique_constraint(
        "uq_master_weekday_interval",
        "working_hours",
        ["master_id", "weekday", "start_time", "end_time"],
    )

    # Гарантія від race condition саме на рівні PostgreSQL. Два конкурентні
    # INSERT/UPDATE, що перетинаються для одного майстра, фізично не пройдуть.
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.execute(
        """
        ALTER TABLE bookings
        ADD CONSTRAINT ex_bookings_master_time_overlap
        EXCLUDE USING gist (
            master_id WITH =,
            tstzrange(start_at, end_at, '[)') WITH &&
        )
        WHERE (status IN ('pending'::booking_status, 'confirmed'::booking_status))
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE bookings DROP CONSTRAINT IF EXISTS ex_bookings_master_time_overlap")
    op.drop_constraint("uq_master_weekday_interval", "working_hours", type_="unique")
    # Якщо є >1 інтервал на день, downgrade свідомо зупиниться на unique constraint,
    # замість тихого видалення даних.
    op.create_unique_constraint("uq_master_weekday", "working_hours", ["master_id", "weekday"])
    op.drop_column("broadcast_sends", "error_code")
    op.drop_column("broadcast_sends", "success")
    op.drop_column("bookings", "price_snapshot")
    op.drop_column("master_services", "buffer_min")
    op.drop_column("clients", "marketing_opt_in")
