"""Store the reason on each document revision."""

from alembic import op
import sqlalchemy as sa


revision = "202611040002"
down_revision = "202611040001"
branch_labels = None
depends_on = None


def upgrade():
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("documents")}
    if "revision_reason" not in columns:
        op.add_column("documents", sa.Column("revision_reason", sa.Text(), nullable=True))


def downgrade():
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("documents")}
    if "revision_reason" in columns:
        op.drop_column("documents", "revision_reason")
