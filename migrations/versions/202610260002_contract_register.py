"""Add a company-scoped contract register and scanned files."""

from alembic import op
import sqlalchemy as sa


revision = "202610260002"
down_revision = "202610260001"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    if not sa.inspect(connection).has_table("contract_records"):
        op.create_table(
            "contract_records",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("company_id", sa.Integer, sa.ForeignKey("companies.id"), nullable=False),
            sa.Column("title", sa.String(180), nullable=False),
            sa.Column("counterparty", sa.String(180), nullable=False),
            sa.Column("contract_no", sa.String(100)),
            sa.Column("signed_on", sa.Date),
            sa.Column("starts_on", sa.Date),
            sa.Column("ends_on", sa.Date),
            sa.Column("note", sa.Text),
            sa.Column("created_by_user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
            sa.Column("archived_at", sa.DateTime),
            sa.Column("version_id", sa.Integer, nullable=False, server_default="1"),
            sa.CheckConstraint("length(trim(title)) BETWEEN 1 AND 180", name="ck_contract_title"),
            sa.CheckConstraint("length(trim(counterparty)) BETWEEN 1 AND 180", name="ck_contract_counterparty"),
            sa.CheckConstraint("starts_on IS NULL OR ends_on IS NULL OR ends_on >= starts_on", name="ck_contract_dates"),
        )
    if not sa.inspect(connection).has_table("contract_files"):
        op.create_table(
            "contract_files",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("company_id", sa.Integer, sa.ForeignKey("companies.id"), nullable=False),
            sa.Column("record_id", sa.Integer, sa.ForeignKey("contract_records.id"), nullable=False),
            sa.Column("original_name", sa.String(255), nullable=False),
            sa.Column("stored_path", sa.String(500), nullable=False),
            sa.Column("mime_type", sa.String(50), nullable=False),
            sa.Column("size_bytes", sa.Integer, nullable=False),
            sa.Column("uploaded_by_user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
            sa.Column("uploaded_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
            sa.Column("is_active", sa.Boolean, nullable=False, server_default="1"),
            sa.CheckConstraint("size_bytes > 0", name="ck_contract_file_size"),
        )
    for table, columns in (
        ("contract_records", ("company_id", "ends_on")),
        ("contract_files", ("company_id", "record_id")),
    ):
        indexes = {item["name"] for item in sa.inspect(connection).get_indexes(table)}
        for column in columns:
            name = f"ix_{table}_{column}"
            if name not in indexes:
                op.create_index(name, table, [column])


def downgrade():
    connection = op.get_bind()
    for table in ("contract_files", "contract_records"):
        if sa.inspect(connection).has_table(table) and connection.execute(
            sa.text(f"SELECT 1 FROM {table} LIMIT 1")
        ).first():
            raise RuntimeError("Sözleşme verisi varken geri alma için veri taşıma planı gerekir.")
    for table in ("contract_files", "contract_records"):
        if sa.inspect(connection).has_table(table):
            op.drop_table(table)
