"""add report designer data model

Revision ID: 202609240001
Revises: 202609230001
"""

from alembic import op
import sqlalchemy as sa


revision = "202609240001"
down_revision = "202609230001"
branch_labels = None
depends_on = None


def _index(table_name, index_name, columns):
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {item["name"] for item in inspector.get_indexes(table_name)}
    if index_name not in existing:
        op.create_index(index_name, table_name, columns, unique=False)


def _insert_sales_readiness_setting(bind):
    key = "sales_readiness:competitor_report_designer"
    exists = bind.execute(
        sa.text("SELECT 1 FROM app_settings WHERE key = :key"),
        {"key": key},
    ).scalar()
    if not exists:
        bind.execute(
            sa.text("INSERT INTO app_settings (key, value) VALUES (:key, '1')"),
            {"key": key},
        )


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "report_definitions" not in tables:
        op.create_table(
            "report_definitions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "company_id",
                sa.Integer(),
                sa.ForeignKey("companies.id"),
                nullable=False,
            ),
            sa.Column("name", sa.String(length=160), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("source_key", sa.String(length=80), nullable=False),
            sa.Column("configuration_json", sa.Text(), nullable=False),
            sa.Column(
                "visibility",
                sa.String(length=20),
                nullable=False,
                server_default="private",
            ),
            sa.Column(
                "status",
                sa.String(length=20),
                nullable=False,
                server_default="active",
            ),
            sa.Column(
                "created_by_user_id",
                sa.Integer(),
                sa.ForeignKey("users.id"),
                nullable=False,
            ),
            sa.Column(
                "updated_by_user_id",
                sa.Integer(),
                sa.ForeignKey("users.id"),
                nullable=True,
            ),
            sa.Column(
                "revision_no",
                sa.Integer(),
                nullable=False,
                server_default="1",
            ),
            sa.Column(
                "lock_version",
                sa.Integer(),
                nullable=False,
                server_default="1",
            ),
            sa.Column("configuration_hash", sa.String(length=64), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.UniqueConstraint(
                "company_id",
                "name",
                "status",
                name="uq_report_definitions_company_name_status",
            ),
            sa.CheckConstraint(
                "visibility IN ('private','company')",
                name="ck_report_definitions_visibility",
            ),
            sa.CheckConstraint(
                "status IN ('active','archived')",
                name="ck_report_definitions_status",
            ),
            sa.CheckConstraint(
                "revision_no >= 1",
                name="ck_report_definitions_revision_positive",
            ),
            sa.CheckConstraint(
                "lock_version >= 1",
                name="ck_report_definitions_lock_positive",
            ),
        )

    if "report_definitions" in set(sa.inspect(bind).get_table_names()):
        indexes = (
            ("ix_report_definitions_company_id", ("company_id",)),
            ("ix_report_definitions_source_key", ("source_key",)),
            ("ix_report_definitions_status", ("status",)),
            ("ix_report_definitions_created_by_user_id", ("created_by_user_id",)),
            ("ix_report_definitions_updated_by_user_id", ("updated_by_user_id",)),
            (
                "ix_report_definitions_company_status",
                ("company_id", "status"),
            ),
        )
        for index_name, columns in indexes:
            _index("report_definitions", index_name, list(columns))

    if "app_settings" in tables:
        _insert_sales_readiness_setting(bind)


def downgrade():
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())

    if "app_settings" in tables:
        op.execute(
            sa.text(
                "DELETE FROM app_settings "
                "WHERE key = 'sales_readiness:competitor_report_designer'"
            )
        )

    if "report_definitions" in tables:
        op.drop_table("report_definitions")
