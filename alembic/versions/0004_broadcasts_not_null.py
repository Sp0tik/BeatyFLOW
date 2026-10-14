"""broadcasts not null

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-29

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # model (app/models.py) оголошує ці колонки обов'язковими; серверна значення
    # ставиться func.now(), тож рядків з NULL тут бути не може.
    op.alter_column(
        "broadcasts",
        "created_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
    )
    op.alter_column(
        "broadcast_sends",
        "sent_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "broadcasts",
        "created_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=True,
    )
    op.alter_column(
        "broadcast_sends",
        "sent_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=True,
    )
