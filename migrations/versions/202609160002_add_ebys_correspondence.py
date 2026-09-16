"""add official correspondence and archive

Revision ID: 202609160002
Revises: 202609160001
"""

from alembic import op
import sqlalchemy as sa


revision = "202609160002"
down_revision = "202609160001"
branch_labels = None
depends_on = None


def upgrade():
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "official_correspondences" not in tables:
        op.create_table(
            "official_correspondences",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
            sa.Column("registration_no", sa.String(40), nullable=False),
            sa.Column("direction", sa.String(20), nullable=False),
            sa.Column("document_date", sa.Date(), nullable=False),
            sa.Column("external_reference_no", sa.String(120)),
            sa.Column("subject", sa.String(255), nullable=False),
            sa.Column("sender", sa.String(255), nullable=False),
            sa.Column("recipient", sa.String(255), nullable=False),
            sa.Column("department", sa.String(160)),
            sa.Column("security_level", sa.String(30), nullable=False, server_default="Normal"),
            sa.Column("status", sa.String(30), nullable=False, server_default="Kayıtlı"),
            sa.Column("due_date", sa.Date()),
            sa.Column("notes", sa.Text()),
            sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("archived_at", sa.DateTime()),
            sa.Column("archived_by_user_id", sa.Integer(), sa.ForeignKey("users.id")),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint(
                "company_id", "registration_no",
                name="uq_official_correspondence_company_no",
            ),
        )
        for column in (
            "company_id", "registration_no", "direction", "document_date",
            "subject", "department", "status", "due_date",
        ):
            op.create_index(
                f"ix_official_correspondences_{column}",
                "official_correspondences", [column],
            )

    if "official_correspondence_files" not in tables:
        op.create_table(
            "official_correspondence_files",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
            sa.Column(
                "correspondence_id", sa.Integer(),
                sa.ForeignKey("official_correspondences.id"), nullable=False,
            ),
            sa.Column("original_name", sa.String(255), nullable=False),
            sa.Column("stored_path", sa.String(500), nullable=False),
            sa.Column("mime_type", sa.String(160)),
            sa.Column("file_size", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("sha256_hash", sa.String(64), nullable=False),
            sa.Column("uploaded_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
        op.create_index(
            "ix_official_correspondence_files_company_id",
            "official_correspondence_files", ["company_id"],
        )
        op.create_index(
            "ix_official_correspondence_files_correspondence_id",
            "official_correspondence_files", ["correspondence_id"],
        )

    if "official_correspondence_distributions" not in tables:
        op.create_table(
            "official_correspondence_distributions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
            sa.Column(
                "correspondence_id", sa.Integer(),
                sa.ForeignKey("official_correspondences.id"), nullable=False,
            ),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("status", sa.String(30), nullable=False, server_default="Bekliyor"),
            sa.Column("assigned_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("read_at", sa.DateTime()),
            sa.Column("completed_at", sa.DateTime()),
            sa.UniqueConstraint(
                "correspondence_id", "user_id",
                name="uq_official_distribution_record_user",
            ),
        )
        for column in ("company_id", "correspondence_id", "user_id", "status"):
            op.create_index(
                f"ix_official_correspondence_distributions_{column}",
                "official_correspondence_distributions", [column],
            )

    if "app_settings" in set(sa.inspect(op.get_bind()).get_table_names()):
        op.execute(sa.text(
            "INSERT OR IGNORE INTO app_settings (key, value) "
            "VALUES ('sales_readiness:competitor_ebys', '1')"
        ))


def downgrade():
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    for table in (
        "official_correspondence_distributions",
        "official_correspondence_files",
        "official_correspondences",
    ):
        if table in tables:
            op.drop_table(table)
    if "app_settings" in tables:
        op.execute(sa.text(
            "DELETE FROM app_settings WHERE key='sales_readiness:competitor_ebys'"
        ))
