"""add master auth_code

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-04

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("masters", sa.Column("auth_code", sa.String(32), nullable=True))
    op.create_unique_constraint("uq_masters_auth_code", "masters", ["auth_code"])


def downgrade() -> None:
    op.drop_constraint("uq_masters_auth_code", "masters", type_="unique")
    op.drop_column("masters", "auth_code")
