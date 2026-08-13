"""repair company_id columns

Revision ID: 202608130001
Revises: 202608120005
Create Date: 2026-08-13 00:01:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "202608130001"
down_revision = "202608120005"
branch_labels = None
depends_on = None


DIRECT_COMPANY_TABLES = (
    "actions",
    "document_categories",
    "documents",
    "dofs",
    "internal_audits",
    "maintenance_machines",
    "maintenance_faults",
    "notifications",
    "orientation_nodes",
    "quality_test_records",
    "users",
)

CHILD_COMPANY_TABLES = (
    ("action_closure_files", "action_id", "actions"),
    ("action_comments", "action_id", "actions"),
    ("action_histories", "action_id", "actions"),
    ("action_sub_tasks", "parent_action_id", "actions"),
    ("dof_comments", "dof_id", "dofs"),
    ("dof_files", "dof_id", "dofs"),
    ("internal_audit_answers", "audit_id", "internal_audits"),
    ("internal_audit_questions", "audit_id", "internal_audits"),
)


def _table_names(bind):
    return set(sa.inspect(bind).get_table_names())


def _column_names(bind, table_name):
    return {
        column["name"]
        for column in sa.inspect(bind).get_columns(table_name)
    }


def _index_names(bind, table_name):
    return {
        index["name"]
        for index in sa.inspect(bind).get_indexes(table_name)
    }


def _ensure_company(bind):
    if "companies" not in _table_names(bind):
        op.create_table(
            "companies",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("code", sa.String(length=3), nullable=False),
            sa.Column("name", sa.String(length=160), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("code"),
        )

    existing_id = bind.execute(
        sa.text("SELECT id FROM companies WHERE code = '001'")
    ).scalar()
    if existing_id:
        return existing_id

    bind.execute(
        sa.text(
            """
            INSERT INTO companies (code, name, is_active)
            VALUES ('001', 'Er Prefabrik', 1)
            """
        )
    )
    return bind.execute(
        sa.text("SELECT id FROM companies WHERE code = '001'")
    ).scalar()


def _add_company_column(bind, table_name):
    if table_name not in _table_names(bind):
        return

    if "company_id" not in _column_names(bind, table_name):
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.add_column(sa.Column("company_id", sa.Integer(), nullable=True))

    index_name = f"ix_{table_name}_company_id"
    if index_name not in _index_names(bind, table_name):
        op.create_index(index_name, table_name, ["company_id"])


def _backfill_direct_table(bind, table_name, primary_company_id):
    if table_name not in _table_names(bind):
        return
    if "company_id" not in _column_names(bind, table_name):
        return

    if table_name == "users":
        bind.execute(
            sa.text(
                """
                UPDATE users
                SET company_id = :company_id
                WHERE company_id IS NULL
                  AND username != 'superadmin'
                """
            ),
            {"company_id": primary_company_id},
        )
        bind.execute(
            sa.text("UPDATE users SET company_id = NULL WHERE username = 'superadmin'")
        )
        return

    bind.execute(
        sa.text(
            f"""
            UPDATE {table_name}
            SET company_id = :company_id
            WHERE company_id IS NULL
            """
        ),
        {"company_id": primary_company_id},
    )


def _backfill_child_table(bind, table_name, link_column, parent_table, primary_company_id):
    tables = _table_names(bind)
    if table_name not in tables or parent_table not in tables:
        return
    if "company_id" not in _column_names(bind, table_name):
        return

    bind.execute(
        sa.text(
            f"""
            UPDATE {table_name}
            SET company_id = (
                SELECT {parent_table}.company_id
                FROM {parent_table}
                WHERE {parent_table}.id = {table_name}.{link_column}
            )
            WHERE company_id IS NULL
            """
        )
    )
    bind.execute(
        sa.text(
            f"""
            UPDATE {table_name}
            SET company_id = :company_id
            WHERE company_id IS NULL
            """
        ),
        {"company_id": primary_company_id},
    )


def upgrade():
    bind = op.get_bind()
    primary_company_id = _ensure_company(bind)

    for table_name in DIRECT_COMPANY_TABLES:
        _add_company_column(bind, table_name)

    for table_name, _link_column, _parent_table in CHILD_COMPANY_TABLES:
        _add_company_column(bind, table_name)

    for table_name in DIRECT_COMPANY_TABLES:
        _backfill_direct_table(bind, table_name, primary_company_id)

    for table_name, link_column, parent_table in CHILD_COMPANY_TABLES:
        _backfill_child_table(
            bind,
            table_name,
            link_column,
            parent_table,
            primary_company_id,
        )


def downgrade():
    pass
