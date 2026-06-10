"""rename dof labels to if

Revision ID: 202606100001
Revises: 202606090001
Create Date: 2026-06-10 00:01:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "202606100001"
down_revision = "202606090001"
branch_labels = None
depends_on = None


def _replace_text(bind, table_name, column_name, old_value, new_value):
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if table_name not in tables:
        return
    columns = {column["name"] for column in inspector.get_columns(table_name)}
    if column_name not in columns:
        return
    bind.execute(
        sa.text(
            f"""
            UPDATE {table_name}
            SET {column_name} = REPLACE({column_name}, :old_value, :new_value)
            WHERE {column_name} LIKE :pattern
            """
        ),
        {
            "old_value": old_value,
            "new_value": new_value,
            "pattern": f"%{old_value}%",
        },
    )


def upgrade():
    bind = op.get_bind()
    _replace_text(bind, "dofs", "dof_no", "DÖF", "İF")
    _replace_text(bind, "notifications", "message", "DÖF", "İF")
    _replace_text(bind, "dof_comments", "comment", "DÖF", "İF")


def downgrade():
    bind = op.get_bind()
    _replace_text(bind, "dofs", "dof_no", "İF", "DÖF")
    _replace_text(bind, "notifications", "message", "İF", "DÖF")
    _replace_text(bind, "dof_comments", "comment", "İF", "DÖF")
