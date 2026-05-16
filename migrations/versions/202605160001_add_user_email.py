"""add user email

Revision ID: 202605160001
Revises: 202605140004
Create Date: 2026-05-16 00:01:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "202605160001"
down_revision = "202605140004"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("users")}

    if "email" not in columns:
        with op.batch_alter_table("users", schema=None) as batch_op:
            batch_op.add_column(sa.Column("email", sa.String(length=255), nullable=True))

    op.execute(
        """
        UPDATE users
        SET email = 'oguzhangokgonul@erprefabrik.com.tr'
        WHERE username = 'oguzhan'
        """
    )
    op.execute(
        """
        UPDATE users
        SET email = 'seymainci@erprefabrik.com.tr'
        WHERE username = 'seyma'
        """
    )
    op.execute(
        """
        UPDATE users
        SET email = 'turgutpekyilmaz@erprefabrik.com.tr'
        WHERE username = 'turgut'
        """
    )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("users")}

    if "email" in columns:
        with op.batch_alter_table("users", schema=None) as batch_op:
            batch_op.drop_column("email")
