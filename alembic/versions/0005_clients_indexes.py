"""align clients indexes and created_at not null

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-29

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # model (app/models.py) оголошує created_at обов'язковим; значення ставиться
    # server_default=func.now(), тож рядків з NULL немає (перевірено перед міграцією).
    op.alter_column(
        "clients",
        "created_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
    )
    op.alter_column(
        "bookings",
        "created_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
    )

    # tg_id у моделі — `unique=True, index=True`, тобто ОДИН унікальний індекс.
    # У базі ж унікальність тримав constraint clients_tg_id_key, а поруч лежав
    # окремий дублюючий неунікальний ix_clients_tg_id — зводимо до стану моделі.
    op.drop_constraint("clients_tg_id_key", "clients", type_="unique")
    op.drop_index("ix_clients_tg_id", table_name="clients")
    op.create_index("ix_clients_tg_id", "clients", ["tg_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_clients_tg_id", table_name="clients")
    op.create_index("ix_clients_tg_id", "clients", ["tg_id"])
    op.create_unique_constraint("clients_tg_id_key", "clients", ["tg_id"])

    op.alter_column(
        "bookings",
        "created_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=True,
    )
    op.alter_column(
        "clients",
        "created_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=True,
    )
