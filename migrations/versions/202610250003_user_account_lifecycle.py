"""Track deleted user accounts and invalidate sessions after password changes."""

from alembic import op
import sqlalchemy as sa
import unicodedata


revision = "202610250003"
down_revision = "202610200001"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    columns = {item["name"] for item in sa.inspect(connection).get_columns("users")}
    if "session_version" not in columns:
        op.add_column("users", sa.Column(
            "session_version", sa.Integer(), nullable=False, server_default="0"))
    if "username_search_key" not in columns:
        op.add_column("users", sa.Column(
            "username_search_key", sa.String(length=160), nullable=False, server_default=""))
    if "full_name_search_key" not in columns:
        op.add_column("users", sa.Column(
            "full_name_search_key", sa.String(length=160), nullable=False, server_default=""))
    if "deleted_at" not in columns:
        op.add_column("users", sa.Column("deleted_at", sa.DateTime(), nullable=True))
    indexes = {item["name"] for item in sa.inspect(connection).get_indexes("users")}
    if "ix_users_username_search_key" not in indexes:
        op.create_index("ix_users_username_search_key", "users", ["username_search_key"])
    if "ix_users_full_name_search_key" not in indexes:
        op.create_index("ix_users_full_name_search_key", "users", ["full_name_search_key"])
    if "ix_users_deleted_at" not in indexes:
        op.create_index("ix_users_deleted_at", "users", ["deleted_at"])
    rows = connection.execute(sa.text("SELECT id, username, full_name FROM users")).all()
    updates = []
    for row in rows:
        username = unicodedata.normalize("NFKD", (row.username or "").strip().casefold())
        full_name = unicodedata.normalize("NFKD", (row.full_name or "").strip().casefold())
        updates.append({
            "id": row.id,
            "username_key": "".join(char for char in username if not unicodedata.combining(char)),
            "full_name_key": "".join(char for char in full_name if not unicodedata.combining(char)),
        })
    if updates:
        connection.execute(sa.text(
            "UPDATE users SET username_search_key=:username_key, "
            "full_name_search_key=:full_name_key WHERE id=:id"
        ), updates)
    connection.execute(sa.text(
        "UPDATE users SET deleted_at=COALESCE(updated_at, created_at, CURRENT_TIMESTAMP) "
        "WHERE is_active=0 AND deleted_at IS NULL AND "
        "substr(username, 1, length('silindi_' || id || '_')) = 'silindi_' || id || '_'"
    ))


def downgrade():
    connection = op.get_bind()
    indexes = {item["name"] for item in sa.inspect(connection).get_indexes("users")}
    if "ix_users_username_search_key" in indexes:
        op.drop_index("ix_users_username_search_key", table_name="users")
    if "ix_users_full_name_search_key" in indexes:
        op.drop_index("ix_users_full_name_search_key", table_name="users")
    if "ix_users_deleted_at" in indexes:
        op.drop_index("ix_users_deleted_at", table_name="users")
    columns = {item["name"] for item in sa.inspect(connection).get_columns("users")}
    if "deleted_at" in columns:
        op.drop_column("users", "deleted_at")
    if "session_version" in columns:
        op.drop_column("users", "session_version")
    if "username_search_key" in columns:
        op.drop_column("users", "username_search_key")
    if "full_name_search_key" in columns:
        op.drop_column("users", "full_name_search_key")
