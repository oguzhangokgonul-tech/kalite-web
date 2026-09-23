"""upgrade parametric form designer data model

Revision ID: 202609230001
Revises: 202609220001
"""

from alembic import op
import sqlalchemy as sa


revision = "202609230001"
down_revision = "202609220001"
branch_labels = None
depends_on = None


def _column_names(inspector, table_name):
    return {column["name"] for column in inspector.get_columns(table_name)}


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "dynamic_form_fields" in tables:
        columns = _column_names(inspector, "dynamic_form_fields")
        additions = (
            sa.Column("help_text", sa.Text(), nullable=True),
            sa.Column("placeholder", sa.String(length=255), nullable=True),
            sa.Column("validation_json", sa.Text(), nullable=True),
            sa.Column("visibility_rule_json", sa.Text(), nullable=True),
            sa.Column(
                "layout_width",
                sa.Integer(),
                nullable=False,
                server_default="12",
            ),
        )
        missing = [column for column in additions if column.name not in columns]
        if missing:
            with op.batch_alter_table("dynamic_form_fields") as batch:
                for column in missing:
                    batch.add_column(column)

    if "dynamic_form_submissions" in tables:
        columns = _column_names(
            sa.inspect(bind),
            "dynamic_form_submissions",
        )
        if "lock_version" not in columns:
            with op.batch_alter_table("dynamic_form_submissions") as batch:
                batch.add_column(
                    sa.Column(
                        "lock_version",
                        sa.Integer(),
                        nullable=False,
                        server_default="1",
                    )
                )
        op.execute(
            sa.text(
                "UPDATE dynamic_form_submissions "
                "SET lock_version = 1 WHERE lock_version IS NULL"
            )
        )

    if "app_settings" in tables:
        key = "sales_readiness:competitor_form_designer"
        exists = bind.execute(
            sa.text("SELECT 1 FROM app_settings WHERE key = :key"),
            {"key": key},
        ).scalar()
        if not exists:
            bind.execute(
                sa.text(
                    "INSERT INTO app_settings (key, value) VALUES (:key, '1')"
                ),
                {"key": key},
            )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "app_settings" in tables:
        op.execute(
            sa.text(
                "DELETE FROM app_settings "
                "WHERE key = 'sales_readiness:competitor_form_designer'"
            )
        )

    if "dynamic_form_submissions" in tables:
        columns = _column_names(inspector, "dynamic_form_submissions")
        if "lock_version" in columns:
            with op.batch_alter_table("dynamic_form_submissions") as batch:
                batch.drop_column("lock_version")

    if "dynamic_form_fields" in tables:
        columns = _column_names(
            sa.inspect(bind),
            "dynamic_form_fields",
        )
        removable = (
            "layout_width",
            "visibility_rule_json",
            "validation_json",
            "placeholder",
            "help_text",
        )
        existing = [name for name in removable if name in columns]
        if existing:
            with op.batch_alter_table("dynamic_form_fields") as batch:
                for name in existing:
                    batch.drop_column(name)
