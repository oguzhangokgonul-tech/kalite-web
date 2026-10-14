"""Classify general and OHS actions without rebuilding legacy action records."""
from alembic import op
import sqlalchemy as sa


revision = "202610140001"
down_revision = "202610120002"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("actions"):
        return
    columns = {column["name"] for column in inspector.get_columns("actions")}
    if "action_category" not in columns:
        op.add_column("actions", sa.Column(
            "action_category", sa.String(16), nullable=False, server_default="general",
        ))
    op.execute(sa.text(
        "UPDATE actions SET action_category = 'general' "
        "WHERE action_category IS NULL OR trim(action_category) = ''"
    ))
    indexes = {index["name"] for index in inspector.get_indexes("actions")}
    if "ix_actions_action_category" not in indexes:
        op.create_index("ix_actions_action_category", "actions", ["action_category"])


def downgrade():
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("actions"):
        return
    indexes = {index["name"] for index in inspector.get_indexes("actions")}
    if "ix_actions_action_category" in indexes:
        op.drop_index("ix_actions_action_category", table_name="actions")
    columns = {column["name"] for column in inspector.get_columns("actions")}
    if "action_category" in columns:
        # Native DROP (SQLite >= 3.35) retains action triggers and incoming FKs.
        op.drop_column("actions", "action_category")
