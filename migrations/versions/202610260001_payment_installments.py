"""Add installment plans and dated payment movements."""

from alembic import op
import sqlalchemy as sa


revision = "202610260001"
down_revision = "202610250004"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    columns = {column["name"] for column in sa.inspect(connection).get_columns("payment_records")}
    if "payment_method" not in columns:
        op.add_column("payment_records", sa.Column(
            "payment_method", sa.String(20), nullable=False, server_default="unspecified"))

    if not sa.inspect(connection).has_table("payment_installments"):
        op.create_table(
            "payment_installments",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("company_id", sa.Integer, sa.ForeignKey("companies.id"), nullable=False),
            sa.Column("record_id", sa.Integer, sa.ForeignKey("payment_records.id"), nullable=False),
            sa.Column("sequence_no", sa.Integer, nullable=False),
            sa.Column("amount", sa.Numeric(14, 2), nullable=False),
            sa.Column("settled_amount", sa.Numeric(14, 2), nullable=False, server_default="0"),
            sa.Column("legacy_settled_amount", sa.Numeric(14, 2), nullable=False, server_default="0"),
            sa.Column("legacy_settled_on", sa.Date),
            sa.Column("due_date", sa.Date, nullable=False),
            sa.UniqueConstraint("record_id", "sequence_no", name="uq_payment_installment_sequence"),
            sa.CheckConstraint("sequence_no > 0", name="ck_payment_installment_sequence"),
            sa.CheckConstraint("amount > 0 AND settled_amount >= 0 AND settled_amount <= amount", name="ck_payment_installment_amount"),
        )
    indexes = {item["name"] for item in sa.inspect(connection).get_indexes("payment_installments")}
    for name, columns in (
        ("ix_payment_installments_company_id", ["company_id"]),
        ("ix_payment_installments_record_id", ["record_id"]),
        ("ix_payment_installments_due_date", ["due_date"]),
    ):
        if name not in indexes:
            op.create_index(name, "payment_installments", columns)
    if "legacy_settled_on" not in {column["name"] for column in sa.inspect(connection).get_columns("payment_installments")}:
        op.add_column("payment_installments", sa.Column("legacy_settled_on", sa.Date))

    if not sa.inspect(connection).has_table("payment_transactions"):
        op.create_table(
            "payment_transactions",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("company_id", sa.Integer, sa.ForeignKey("companies.id"), nullable=False),
            sa.Column("record_id", sa.Integer, sa.ForeignKey("payment_records.id"), nullable=False),
            sa.Column("installment_id", sa.Integer, sa.ForeignKey("payment_installments.id"), nullable=False),
            sa.Column("amount", sa.Numeric(14, 2), nullable=False),
            sa.Column("occurred_on", sa.Date, nullable=False),
            sa.Column("note", sa.String(500)),
            sa.Column("instrument_no", sa.String(100)),
            sa.Column("created_by_user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
            sa.Column("reversal_of_id", sa.Integer, sa.ForeignKey("payment_transactions.id"), unique=True),
            sa.CheckConstraint("amount != 0", name="ck_payment_transaction_nonzero"),
        )
    indexes = {item["name"] for item in sa.inspect(connection).get_indexes("payment_transactions")}
    for name, columns in (
        ("ix_payment_transactions_company_id", ["company_id"]),
        ("ix_payment_transactions_record_id", ["record_id"]),
        ("ix_payment_transactions_installment_id", ["installment_id"]),
    ):
        if name not in indexes:
            op.create_index(name, "payment_transactions", columns)

    connection.execute(sa.text("""
        INSERT INTO payment_installments
            (company_id, record_id, sequence_no, amount, settled_amount, legacy_settled_amount, legacy_settled_on, due_date)
        SELECT p.company_id, p.id, 1, p.amount, p.settled_amount, p.settled_amount, p.settled_on, p.due_date
        FROM payment_records AS p
        WHERE NOT EXISTS (
            SELECT 1 FROM payment_installments AS i WHERE i.record_id = p.id
        )
    """))
    connection.execute(sa.text("""
        UPDATE payment_installments
        SET legacy_settled_on = (
            SELECT p.settled_on FROM payment_records AS p WHERE p.id = payment_installments.record_id
        )
        WHERE legacy_settled_amount > 0 AND legacy_settled_on IS NULL
          AND NOT EXISTS (
              SELECT 1 FROM payment_transactions AS t
              WHERE t.record_id = payment_installments.record_id
          )
    """))


def downgrade():
    connection = op.get_bind()
    for table in ("payment_transactions", "payment_installments"):
        if sa.inspect(connection).has_table(table) and connection.execute(
            sa.text(f"SELECT 1 FROM {table} LIMIT 1")
        ).first():
            raise RuntimeError("Taksit veya hareket verisi varken geri alma veri taşıma planı gerektirir.")
    if sa.inspect(connection).has_table("payment_transactions"):
        op.drop_table("payment_transactions")
    if sa.inspect(connection).has_table("payment_installments"):
        op.drop_table("payment_installments")
    if "payment_method" in {column["name"] for column in sa.inspect(connection).get_columns("payment_records")}:
        op.drop_column("payment_records", "payment_method")
