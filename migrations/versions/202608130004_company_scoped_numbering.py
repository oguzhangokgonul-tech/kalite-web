"""company scoped numbering

Revision ID: 202608130004
Revises: 202608130003
Create Date: 2026-08-13 00:04:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "202608130004"
down_revision = "202608130003"
branch_labels = None
depends_on = None


UNIQUE_TABLES = (
    ("actions", "action_number", "uq_actions_company_action_number"),
    ("dofs", "dof_no", "uq_dofs_company_dof_no"),
    ("internal_audits", "audit_no", "uq_internal_audits_company_audit_no"),
    ("maintenance_faults", "fault_number", "uq_maintenance_faults_company_fault_number"),
    ("document_categories", "slug", "uq_document_categories_company_slug"),
    ("maintenance_machines", "code", "uq_maintenance_machines_company_code"),
)

QUALITY_UNIQUE = (
    "quality_test_records",
    ("test_type", "record_number"),
    "uq_quality_test_records_company_test_number",
)

INDEXES = {
    "actions": (("ix_actions_company_id", ("company_id",), False),),
    "dofs": (("ix_dofs_company_id", ("company_id",), False),),
    "internal_audits": (("ix_internal_audits_company_id", ("company_id",), False),),
    "maintenance_faults": (
        ("ix_maintenance_faults_company_id", ("company_id",), False),
        ("ix_maintenance_faults_machine_id", ("machine_id",), False),
        ("ix_maintenance_faults_status", ("status",), False),
    ),
    "document_categories": (
        ("ix_document_categories_company_id", ("company_id",), False),
    ),
    "maintenance_machines": (
        ("ix_maintenance_machines_company_id", ("company_id",), False),
    ),
    "quality_test_records": (
        ("ix_quality_test_records_company_id", ("company_id",), False),
        ("ix_quality_test_records_test_type", ("test_type",), False),
    ),
}


def _table_names(bind):
    return set(sa.inspect(bind).get_table_names())


def _column_names(bind, table_name):
    return {column["name"] for column in sa.inspect(bind).get_columns(table_name)}


def _index_names(bind, table_name):
    return {index["name"] for index in sa.inspect(bind).get_indexes(table_name)}


def _foreign_key_args(column):
    args = []
    for foreign_key in column.foreign_keys:
        kwargs = {}
        if foreign_key.ondelete:
            kwargs["ondelete"] = foreign_key.ondelete
        if foreign_key.onupdate:
            kwargs["onupdate"] = foreign_key.onupdate
        args.append(sa.ForeignKey(foreign_key.target_fullname, **kwargs))
    return args


def _copy_from_without_uniques(bind, table_name):
    reflected = sa.Table(table_name, sa.MetaData(), autoload_with=bind)
    metadata = sa.MetaData()
    columns = []
    for column in reflected.columns:
        columns.append(
            sa.Column(
                column.name,
                column.type,
                *_foreign_key_args(column),
                primary_key=column.primary_key,
                nullable=column.nullable,
                server_default=column.server_default,
                autoincrement=column.autoincrement,
            )
        )
    return sa.Table(table_name, metadata, *columns)


def _assert_no_company_duplicates(bind, table_name, columns):
    if table_name not in _table_names(bind):
        return
    existing_columns = _column_names(bind, table_name)
    if "company_id" not in existing_columns or any(column not in existing_columns for column in columns):
        return

    not_null_clause = " AND ".join(f"{column} IS NOT NULL" for column in columns)
    grouped_columns = ", ".join(["company_id", *columns])
    duplicate = bind.execute(
        sa.text(
            f"""
            SELECT {grouped_columns}, COUNT(*) AS duplicate_count
            FROM {table_name}
            WHERE company_id IS NOT NULL AND {not_null_clause}
            GROUP BY {grouped_columns}
            HAVING COUNT(*) > 1
            LIMIT 1
            """
        )
    ).first()
    if duplicate:
        raise RuntimeError(
            f"{table_name} tablosunda firma bazli unique gecisi icin "
            f"tekrar eden kayit var: {duplicate}"
        )


def _create_missing_indexes(bind, table_name):
    if table_name not in _table_names(bind):
        return
    existing_indexes = _index_names(bind, table_name)
    for index_name, columns, unique in INDEXES.get(table_name, ()):
        if index_name not in existing_indexes and all(
            column in _column_names(bind, table_name) for column in columns
        ):
            op.create_index(index_name, table_name, list(columns), unique=unique)


def _rebuild_with_company_unique(bind, table_name, columns, unique_name):
    if table_name not in _table_names(bind):
        return
    existing_columns = _column_names(bind, table_name)
    if "company_id" not in existing_columns or any(column not in existing_columns for column in columns):
        return

    _assert_no_company_duplicates(bind, table_name, columns)
    copy_from = _copy_from_without_uniques(bind, table_name)
    with op.batch_alter_table(
        table_name,
        recreate="always",
        copy_from=copy_from,
    ) as batch_op:
        batch_op.create_unique_constraint(unique_name, ["company_id", *columns])

    _create_missing_indexes(bind, table_name)


def upgrade():
    bind = op.get_bind()
    for table_name, column, unique_name in UNIQUE_TABLES:
        _rebuild_with_company_unique(bind, table_name, (column,), unique_name)

    table_name, columns, unique_name = QUALITY_UNIQUE
    _rebuild_with_company_unique(bind, table_name, columns, unique_name)


def downgrade():
    bind = op.get_bind()
    for table_name in [item[0] for item in UNIQUE_TABLES] + [QUALITY_UNIQUE[0]]:
        _create_missing_indexes(bind, table_name)
