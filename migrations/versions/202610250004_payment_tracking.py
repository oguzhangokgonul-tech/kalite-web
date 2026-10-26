"""Add company-scoped payment tracking and PDF attachments."""

from alembic import op
import sqlalchemy as sa


revision = "202610250004"
down_revision = "202610250001"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    if not sa.inspect(connection).has_table("payment_records"):
        op.create_table(
            "payment_records",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
            sa.Column("direction", sa.String(12), nullable=False),
            sa.Column("counterparty", sa.String(180), nullable=False),
            sa.Column("description", sa.String(500), nullable=False),
            sa.Column("reference_no", sa.String(100)),
            sa.Column("project_no", sa.String(100)),
            sa.Column("amount", sa.Numeric(14, 2), nullable=False),
            sa.Column("settled_amount", sa.Numeric(14, 2), nullable=False, server_default="0"),
            sa.Column("currency", sa.String(3), nullable=False, server_default="TRY"),
            sa.Column("due_date", sa.Date(), nullable=False),
            sa.Column("responsible_user_id", sa.Integer(), sa.ForeignKey("users.id")),
            sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("confirmed_by_user_id", sa.Integer(), sa.ForeignKey("users.id")),
            sa.Column("settled_on", sa.Date()),
            sa.Column("note", sa.Text()),
            sa.Column("status", sa.String(12), nullable=False, server_default="open"),
            sa.Column("closed_at", sa.DateTime()),
            sa.Column("cancelled_at", sa.DateTime()),
            sa.Column("archived_at", sa.DateTime()),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("version_id", sa.Integer(), nullable=False, server_default="1"),
            sa.CheckConstraint("direction IN ('receivable', 'payable')", name="ck_payment_direction"),
            sa.CheckConstraint("status IN ('open', 'closed', 'cancelled')", name="ck_payment_status"),
            sa.CheckConstraint("amount > 0 AND settled_amount >= 0 AND settled_amount <= amount", name="ck_payment_amounts"),
            sa.CheckConstraint("currency IN ('TRY', 'USD', 'EUR')", name="ck_payment_currency"),
            sa.CheckConstraint("status != 'closed' OR settled_amount = amount", name="ck_payment_closed_amount"),
        )
    indexes = {item["name"] for item in sa.inspect(connection).get_indexes("payment_records")}
    for name, columns in (
        ("ix_payment_records_company_id", ["company_id"]),
        ("ix_payment_records_direction", ["direction"]),
        ("ix_payment_records_status", ["status"]),
        ("ix_payment_records_due_date", ["due_date"]),
        ("ix_payment_records_responsible_user_id", ["responsible_user_id"]),
        ("ix_payment_records_archived_at", ["archived_at"]),
    ):
        if name not in indexes:
            op.create_index(name, "payment_records", columns)

    if not sa.inspect(connection).has_table("payment_attachments"):
        op.create_table(
            "payment_attachments",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
            sa.Column("record_id", sa.Integer(), sa.ForeignKey("payment_records.id"), nullable=False),
            sa.Column("original_name", sa.String(255), nullable=False),
            sa.Column("stored_path", sa.String(500), nullable=False),
            sa.Column("size_bytes", sa.Integer(), nullable=False),
            sa.Column("uploaded_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("uploaded_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
        )
    indexes = {item["name"] for item in sa.inspect(connection).get_indexes("payment_attachments")}
    for name, columns in (
        ("ix_payment_attachments_company_id", ["company_id"]),
        ("ix_payment_attachments_record_id", ["record_id"]),
    ):
        if name not in indexes:
            op.create_index(name, "payment_attachments", columns)


def downgrade():
    connection = op.get_bind()
    for table in ("payment_attachments", "payment_records"):
        if sa.inspect(connection).has_table(table) and connection.execute(
            sa.text(f"SELECT 1 FROM {table} LIMIT 1")
        ).first():
            raise RuntimeError("Ödeme kayıtları varken şema geri alınamaz; önce veri taşıma planı gerekir.")
    if sa.inspect(connection).has_table("payment_attachments"):
        op.drop_table("payment_attachments")
    if sa.inspect(connection).has_table("payment_records"):
        op.drop_table("payment_records")
