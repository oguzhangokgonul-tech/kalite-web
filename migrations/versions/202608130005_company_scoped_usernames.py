"""company scoped usernames

Revision ID: 202608130005
Revises: 202608130004
Create Date: 2026-08-13 00:05:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "202608130005"
down_revision = "202608130004"
branch_labels = None
depends_on = None


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


def _copy_users_without_global_username_unique(bind):
    reflected = sa.Table("users", sa.MetaData(), autoload_with=bind)
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
    return sa.Table("users", metadata, *columns)


def _assert_no_duplicate_company_usernames(bind):
    if "users" not in _table_names(bind):
        return
    existing_columns = _column_names(bind, "users")
    if not {"company_id", "username"}.issubset(existing_columns):
        return

    duplicate = bind.execute(
        sa.text(
            """
            SELECT company_id, lower(username) AS normalized_username, COUNT(*) AS duplicate_count
            FROM users
            WHERE company_id IS NOT NULL
            GROUP BY company_id, lower(username)
            HAVING COUNT(*) > 1
            LIMIT 1
            """
        )
    ).first()
    if duplicate:
        raise RuntimeError(f"Firma bazli tekrar eden kullanici adi var: {duplicate}")

    global_duplicate = bind.execute(
        sa.text(
            """
            SELECT lower(username) AS normalized_username, COUNT(*) AS duplicate_count
            FROM users
            WHERE company_id IS NULL
            GROUP BY lower(username)
            HAVING COUNT(*) > 1
            LIMIT 1
            """
        )
    ).first()
    if global_duplicate:
        raise RuntimeError(f"Global kullanicilarda tekrar eden kullanici adi var: {global_duplicate}")


def _create_indexes(bind):
    indexes = _index_names(bind, "users")
    if "ix_users_company_id" not in indexes:
        op.create_index("ix_users_company_id", "users", ["company_id"])

    if "uq_users_global_username" not in indexes:
        if bind.dialect.name == "sqlite":
            bind.execute(
                sa.text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_users_global_username "
                    "ON users (username) WHERE company_id IS NULL"
                )
            )
        else:
            op.create_index("uq_users_global_username", "users", ["username"], unique=True)


def upgrade():
    bind = op.get_bind()
    if "users" not in _table_names(bind):
        return
    if not {"company_id", "username"}.issubset(_column_names(bind, "users")):
        return

    _assert_no_duplicate_company_usernames(bind)
    copy_from = _copy_users_without_global_username_unique(bind)
    with op.batch_alter_table(
        "users",
        recreate="always",
        copy_from=copy_from,
    ) as batch_op:
        batch_op.create_unique_constraint(
            "uq_users_company_username",
            ["company_id", "username"],
        )

    _create_indexes(bind)


def downgrade():
    bind = op.get_bind()
    if "users" not in _table_names(bind):
        return

    indexes = _index_names(bind, "users")
    if "uq_users_global_username" in indexes:
        op.drop_index("uq_users_global_username", table_name="users")
    if "ix_users_company_id" in indexes:
        op.drop_index("ix_users_company_id", table_name="users")
