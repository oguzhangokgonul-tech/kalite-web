"""add secure customer feedback portal

Revision ID: 202609120004
Revises: 202609120003
"""

from alembic import op
import sqlalchemy as sa


revision = "202609120004"
down_revision = "202609120003"
branch_labels = None
depends_on = None


NEW_COMPLAINT_COLUMNS = (
    sa.Column("contact_email", sa.String(255)),
    sa.Column("record_type", sa.String(40), nullable=False, server_default="Şikayet"),
    sa.Column("source", sa.String(40), nullable=False, server_default="İç Kayıt"),
    sa.Column("customer_reference", sa.String(120)),
    sa.Column("product_reference", sa.String(180)),
    sa.Column("public_status", sa.String(40), nullable=False, server_default="Alındı"),
    sa.Column("email_verified_at", sa.DateTime()),
    sa.Column("first_response_due_at", sa.DateTime()),
    sa.Column("resolution_due_at", sa.DateTime()),
    sa.Column("first_response_at", sa.DateTime()),
    sa.Column("resolved_at", sa.DateTime()),
    sa.Column("customer_solution_summary", sa.Text()),
    sa.Column("customer_rating", sa.Integer()),
    sa.Column("customer_rating_comment", sa.Text()),
    sa.Column("consent_text", sa.Text()),
    sa.Column("consent_version", sa.String(40)),
    sa.Column("consented_at", sa.DateTime()),
    sa.Column("last_customer_message_at", sa.DateTime()),
    sa.Column("is_archived", sa.Boolean(), nullable=False, server_default=sa.false()),
    sa.Column("archived_at", sa.DateTime()),
    sa.Column(
        "archived_by_user_id",
        sa.Integer(),
        sa.ForeignKey(
            "users.id",
            name="fk_complaint_records_archived_by_user_id",
        ),
    ),
)


def _tables():
    return set(sa.inspect(op.get_bind()).get_table_names())


def _indexes(table_name):
    return {item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table_name)}


def upgrade():
    tables = _tables()
    if "complaint_records" not in tables:
        op.create_table(
            "complaint_records",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), index=True),
            sa.Column("complaint_no", sa.String(30), nullable=False),
            sa.Column("customer_name", sa.String(180), nullable=False),
            sa.Column("contact_name", sa.String(160)),
            sa.Column("contact_phone", sa.String(80)),
            sa.Column("department", sa.String(80)),
            sa.Column("subject", sa.String(180), nullable=False),
            sa.Column("description", sa.Text()),
            sa.Column("root_cause", sa.Text()),
            sa.Column("corrective_action", sa.Text()),
            sa.Column("closing_note", sa.Text()),
            sa.Column("received_date", sa.Date()),
            sa.Column("due_date", sa.Date()),
            sa.Column("closed_at", sa.DateTime()),
            sa.Column("status", sa.String(40), nullable=False, server_default="Açık"),
            sa.Column("priority", sa.String(40), nullable=False, server_default="Orta"),
            sa.Column("responsible_user_id", sa.Integer(), sa.ForeignKey("users.id")),
            sa.Column("action_id", sa.Integer(), sa.ForeignKey("actions.id")),
            sa.Column("dof_id", sa.Integer(), sa.ForeignKey("dofs.id")),
            sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id")),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            *NEW_COMPLAINT_COLUMNS,
            sa.UniqueConstraint("company_id", "complaint_no", name="uq_complaint_records_company_complaint_no"),
        )
    else:
        existing = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("complaint_records")}
        with op.batch_alter_table("complaint_records") as batch:
            for column in NEW_COMPLAINT_COLUMNS:
                if column.name not in existing:
                    batch.add_column(column)

    for column in ("contact_email", "record_type", "source", "public_status", "email_verified_at", "first_response_due_at", "resolution_due_at", "is_archived"):
        name = f"ix_complaint_records_{column}"
        if name not in _indexes("complaint_records"):
            op.create_index(name, "complaint_records", [column])

    tables = _tables()
    if "customer_portal_settings" not in tables:
        op.create_table(
            "customer_portal_settings",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False, unique=True),
            sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("welcome_text", sa.Text()),
            sa.Column("consent_text", sa.Text(), nullable=False, server_default="Kişisel verilerimin talebimin yönetilmesi amacıyla işlenmesini kabul ediyorum."),
            sa.Column("consent_version", sa.String(40), nullable=False, server_default="1.0"),
            sa.Column("verification_hours", sa.Integer(), nullable=False, server_default="24"),
            sa.Column("tracking_days", sa.Integer(), nullable=False, server_default="90"),
            sa.Column("submission_limit_hour", sa.Integer(), nullable=False, server_default="5"),
            sa.Column("max_file_mb", sa.Integer(), nullable=False, server_default="10"),
            sa.Column("first_response_hours", sa.Integer(), nullable=False, server_default="24"),
            sa.Column("resolution_hours", sa.Integer(), nullable=False, server_default="168"),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_customer_portal_settings_company_id", "customer_portal_settings", ["company_id"])

    if "customer_portal_tokens" not in tables:
        op.create_table(
            "customer_portal_tokens",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
            sa.Column("complaint_id", sa.Integer(), sa.ForeignKey("complaint_records.id"), nullable=False),
            sa.Column("purpose", sa.String(30), nullable=False),
            sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("used_at", sa.DateTime()),
            sa.Column("revoked_at", sa.DateTime()),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
        for column in ("company_id", "complaint_id", "purpose", "token_hash", "expires_at"):
            op.create_index(f"ix_customer_portal_tokens_{column}", "customer_portal_tokens", [column])

    if "complaint_messages" not in tables:
        op.create_table(
            "complaint_messages",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
            sa.Column("complaint_id", sa.Integer(), sa.ForeignKey("complaint_records.id"), nullable=False),
            sa.Column("sender_type", sa.String(20), nullable=False),
            sa.Column("sender_user_id", sa.Integer(), sa.ForeignKey("users.id")),
            sa.Column("sender_name", sa.String(160)),
            sa.Column("body", sa.Text(), nullable=False),
            sa.Column("visibility", sa.String(20), nullable=False, server_default="public"),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
        for column in ("company_id", "complaint_id", "sender_user_id", "visibility"):
            op.create_index(f"ix_complaint_messages_{column}", "complaint_messages", [column])

    if "complaint_files" not in tables:
        op.create_table(
            "complaint_files",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
            sa.Column("complaint_id", sa.Integer(), sa.ForeignKey("complaint_records.id"), nullable=False),
            sa.Column("message_id", sa.Integer(), sa.ForeignKey("complaint_messages.id")),
            sa.Column("visibility", sa.String(20), nullable=False, server_default="public"),
            sa.Column("original_name", sa.String(255), nullable=False),
            sa.Column("stored_path", sa.String(500), nullable=False),
            sa.Column("mime_type", sa.String(160)),
            sa.Column("file_size", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("sha256_hash", sa.String(64), nullable=False),
            sa.Column("uploaded_by_user_id", sa.Integer(), sa.ForeignKey("users.id")),
            sa.Column("uploaded_by_customer", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
        for column in ("company_id", "complaint_id", "message_id", "visibility", "is_active"):
            op.create_index(f"ix_complaint_files_{column}", "complaint_files", [column])

    if "complaint_status_history" not in tables:
        op.create_table(
            "complaint_status_history",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
            sa.Column("complaint_id", sa.Integer(), sa.ForeignKey("complaint_records.id"), nullable=False),
            sa.Column("internal_status", sa.String(40), nullable=False),
            sa.Column("public_status", sa.String(40), nullable=False),
            sa.Column("changed_by_user_id", sa.Integer(), sa.ForeignKey("users.id")),
            sa.Column("source", sa.String(30), nullable=False, server_default="system"),
            sa.Column("note", sa.String(255)),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
        for column in ("company_id", "complaint_id"):
            op.create_index(f"ix_complaint_status_history_{column}", "complaint_status_history", [column])

    if "customer_portal_attempts" not in tables:
        op.create_table(
            "customer_portal_attempts",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
            sa.Column("action", sa.String(30), nullable=False),
            sa.Column("ip_hash", sa.String(64), nullable=False),
            sa.Column("email_hash", sa.String(64)),
            sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_customer_portal_attempt_scope_created", "customer_portal_attempts", ["company_id", "action", "ip_hash", "created_at"])

    if "company_modules" in _tables():
        company_columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("companies")}
        enabled_expression = "CASE WHEN package_key = 'custom' THEN 0 ELSE 1 END" if "package_key" in company_columns else "1"
        op.execute(sa.text(
            "INSERT INTO company_modules (company_id, module_key, is_enabled) "
            f"SELECT id, 'customer_feedback_portal', {enabled_expression} FROM companies "
            "WHERE NOT EXISTS (SELECT 1 FROM company_modules cm WHERE cm.company_id=companies.id AND cm.module_key='customer_feedback_portal')"
        ))


def downgrade():
    if "company_modules" in _tables():
        op.execute("DELETE FROM company_modules WHERE module_key='customer_feedback_portal'")
    for table in ("customer_portal_attempts", "complaint_status_history", "complaint_files", "complaint_messages", "customer_portal_tokens", "customer_portal_settings"):
        if table in _tables():
            op.drop_table(table)
    if "complaint_records" in _tables():
        existing = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("complaint_records")}
        with op.batch_alter_table("complaint_records") as batch:
            for column in reversed(NEW_COMPLAINT_COLUMNS):
                if column.name in existing:
                    batch.drop_column(column.name)
