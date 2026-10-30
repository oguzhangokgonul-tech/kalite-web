"""Persist action evidence ownership and deletion tombstones.

Revision ID: 202610300001
Revises: 202610270001
"""

from alembic import op
import sqlalchemy as sa


revision = "202610300001"
down_revision = "202610270001"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    for table, column in (
        ("actions", "file_stored_name"),
        ("actions", "closure_file_stored_name"),
        ("action_sub_tasks", "evidence_stored_name"),
        ("action_closure_files", "stored_name"),
    ):
        if table not in inspector.get_table_names():
            continue
        if column not in {item["name"] for item in inspector.get_columns(table)}:
            continue
        count = op.get_bind().execute(
            sa.text(f"SELECT COUNT(*) FROM {table} WHERE {column} IS NOT NULL")
        ).scalar_one()
        if count:
            raise RuntimeError(
                f"{table}.{column} has {count} existing action files; "
                "verify ownership and backfill before upgrading"
            )
    if "action_evidence_manifest" in inspector.get_table_names():
        columns = {item["name"] for item in inspector.get_columns("action_evidence_manifest")}
        expected = {
            "id", "stored_name", "company_id", "action_id", "kind", "record_id",
            "sha256", "size_bytes", "created_at", "deleted_at", "cleaned_at",
        }
        unique_columns = {
            tuple(item["column_names"])
            for item in inspector.get_unique_constraints("action_evidence_manifest")
        }
        indexes = {item["name"] for item in inspector.get_indexes("action_evidence_manifest")}
        if columns != expected or ("stored_name",) not in unique_columns or not {
            "ix_action_evidence_manifest_company_id",
            "ix_action_evidence_manifest_action_id",
        }.issubset(indexes):
            raise RuntimeError("Existing action evidence manifest schema is incomplete")
        return
    op.create_table(
        "action_evidence_manifest",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("stored_name", sa.String(255), nullable=False, unique=True),
        sa.Column("company_id", sa.Integer, nullable=False),
        sa.Column("action_id", sa.Integer, nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("record_id", sa.String(32)),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime),
        sa.Column("cleaned_at", sa.DateTime),
    )
    op.create_index("ix_action_evidence_manifest_company_id", "action_evidence_manifest", ["company_id"])
    op.create_index("ix_action_evidence_manifest_action_id", "action_evidence_manifest", ["action_id"])


def downgrade():
    connection = op.get_bind()
    if "action_evidence_manifest" not in sa.inspect(connection).get_table_names():
        return
    if connection.execute(sa.text("SELECT 1 FROM action_evidence_manifest LIMIT 1")).first():
        raise RuntimeError("Action evidence history exists; preserve the manifest and use a code-only rollback.")
    op.drop_index("ix_action_evidence_manifest_action_id", table_name="action_evidence_manifest")
    op.drop_index("ix_action_evidence_manifest_company_id", table_name="action_evidence_manifest")
    op.drop_table("action_evidence_manifest")
