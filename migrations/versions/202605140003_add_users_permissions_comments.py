"""add users permissions comments

Revision ID: 202605140003
Revises: 202605140002
Create Date: 2026-05-14 00:03:00.000000

"""
from alembic import op
import sqlalchemy as sa
from werkzeug.security import generate_password_hash


revision = "202605140003"
down_revision = "202605140002"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(length=80), nullable=False),
        sa.Column("full_name", sa.String(length=160), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=True),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("can_create_actions", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("can_edit_actions", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("can_delete_actions", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("can_comment_assigned_actions", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("can_close_assigned_actions", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("can_manage_users", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username"),
    )

    users_table = sa.table(
        "users",
        sa.column("username", sa.String),
        sa.column("full_name", sa.String),
        sa.column("title", sa.String),
        sa.column("password_hash", sa.String),
        sa.column("is_active", sa.Boolean),
        sa.column("can_create_actions", sa.Boolean),
        sa.column("can_edit_actions", sa.Boolean),
        sa.column("can_delete_actions", sa.Boolean),
        sa.column("can_comment_assigned_actions", sa.Boolean),
        sa.column("can_close_assigned_actions", sa.Boolean),
        sa.column("can_manage_users", sa.Boolean),
    )
    op.bulk_insert(
        users_table,
        [
            {
                "username": "oguzhan",
                "full_name": "Oğuzhan Gökgönül",
                "title": "Yönetici Asistanı",
                "password_hash": generate_password_hash("kysoguzhan"),
                "is_active": True,
                "can_create_actions": True,
                "can_edit_actions": True,
                "can_delete_actions": True,
                "can_comment_assigned_actions": True,
                "can_close_assigned_actions": True,
                "can_manage_users": True,
            },
            {
                "username": "ufuk",
                "full_name": "Ufuk Yaşayan",
                "title": "Prefabrik Proje Müdürü",
                "password_hash": generate_password_hash("kysufuk"),
                "is_active": True,
                "can_create_actions": False,
                "can_edit_actions": False,
                "can_delete_actions": False,
                "can_comment_assigned_actions": True,
                "can_close_assigned_actions": True,
                "can_manage_users": False,
            },
        ],
    )

    with op.batch_alter_table("actions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("responsible_user_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_actions_responsible_user_id_users",
            "users",
            ["responsible_user_id"],
            ["id"],
        )

    op.execute(
        """
        UPDATE actions
        SET responsible_user_id = (
            SELECT id FROM users WHERE users.full_name = actions.responsible_owner
        )
        WHERE responsible_owner IN (SELECT full_name FROM users)
        """
    )

    op.create_table(
        "action_comments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("action_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(["action_id"], ["actions.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade():
    op.drop_table("action_comments")

    with op.batch_alter_table("actions", schema=None) as batch_op:
        batch_op.drop_constraint("fk_actions_responsible_user_id_users", type_="foreignkey")
        batch_op.drop_column("responsible_user_id")

    op.drop_table("users")
