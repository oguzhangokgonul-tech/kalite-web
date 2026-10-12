"""Classify customer feedback evidence without changing legacy complaints."""
from alembic import op
import sqlalchemy as sa


revision = "202610120001"
down_revision = "202610090001"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("complaint_files"):
        return
    columns = {column["name"] for column in inspector.get_columns("complaint_files")}
    if "evidence_stage" not in columns:
        op.add_column("complaint_files", sa.Column(
            "evidence_stage", sa.String(20), nullable=False, server_default="general",
        ))


def downgrade():
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("complaint_files"):
        return
    columns = {column["name"] for column in inspector.get_columns("complaint_files")}
    if "evidence_stage" in columns:
        with op.batch_alter_table("complaint_files") as batch:
            batch.drop_column("evidence_stage")
