"""Tenant-scoped project planning.

Revision ID: 202610030001
Revises: 202610020002
"""
from alembic import op
import sqlalchemy as sa

revision = "202610030001"
down_revision = "202610020002"
branch_labels = None
depends_on = None


def install_sqlite_guards():
    if op.get_bind().dialect.name != "sqlite":
        return
    predicates = {
        "project_records": (
            "EXISTS (SELECT 1 FROM companies c WHERE c.id=NEW.company_id) "
            "AND EXISTS (SELECT 1 FROM users u WHERE u.id=NEW.owner_user_id AND u.company_id=NEW.company_id) "
            "AND EXISTS (SELECT 1 FROM users u WHERE u.id=NEW.created_by_user_id "
            "AND (u.company_id=NEW.company_id OR u.company_id IS NULL))"
        ),
        "project_tasks": (
            "EXISTS (SELECT 1 FROM project_records p WHERE p.id=NEW.project_id AND p.company_id=NEW.company_id) "
            "AND EXISTS (SELECT 1 FROM users u WHERE u.id=NEW.owner_user_id AND u.company_id=NEW.company_id)"
        ),
    }
    for table, predicate in predicates.items():
        for operation in ("INSERT", "UPDATE"):
            op.execute(sa.text(
                f"CREATE TRIGGER IF NOT EXISTS trg_{table}_tenant_{operation.lower()} "
                f"BEFORE {operation} ON {table} WHEN NOT ({predicate}) "
                "BEGIN SELECT RAISE(ABORT, 'project tenant mismatch'); END"
            ))
    guards = (
        ("project_parent_update", "BEFORE UPDATE OF id,company_id ON project_records",
         "(NEW.id != OLD.id OR NEW.company_id != OLD.company_id) AND EXISTS (SELECT 1 FROM project_tasks t WHERE t.project_id=OLD.id)"),
        ("project_parent_delete", "BEFORE DELETE ON project_records",
         "EXISTS (SELECT 1 FROM project_tasks t WHERE t.project_id=OLD.id)"),
        ("project_user_delete", "BEFORE DELETE ON users",
         "EXISTS (SELECT 1 FROM project_records p WHERE p.owner_user_id=OLD.id OR p.created_by_user_id=OLD.id) OR EXISTS (SELECT 1 FROM project_tasks t WHERE t.owner_user_id=OLD.id)"),
        ("project_user_update", "BEFORE UPDATE OF id,company_id ON users",
         "(NEW.id IS NOT OLD.id OR NEW.company_id IS NOT OLD.company_id) AND (EXISTS (SELECT 1 FROM project_records p WHERE p.owner_user_id=OLD.id OR p.created_by_user_id=OLD.id) OR EXISTS (SELECT 1 FROM project_tasks t WHERE t.owner_user_id=OLD.id))"),
        ("project_company_delete", "BEFORE DELETE ON companies",
         "EXISTS (SELECT 1 FROM project_records p WHERE p.company_id=OLD.id)"),
        ("project_company_update", "BEFORE UPDATE OF id ON companies",
         "NEW.id != OLD.id AND EXISTS (SELECT 1 FROM project_records p WHERE p.company_id=OLD.id)"),
    )
    for name, event, predicate in guards:
        op.execute(sa.text(f"CREATE TRIGGER IF NOT EXISTS trg_{name} {event} WHEN {predicate} "
                           "BEGIN SELECT RAISE(ABORT, 'project referenced record'); END"))


def upgrade():
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if "project_records" not in existing:
        op.create_table("project_records",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
            sa.Column("title", sa.String(240), nullable=False),
            sa.Column("description", sa.Text()),
            sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("start_date", sa.Date(), nullable=False),
            sa.Column("due_date", sa.Date(), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
            sa.Column("completion_note", sa.Text()),
            sa.Column("archive_note", sa.Text()),
            sa.Column("completed_at", sa.DateTime()),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("version_id", sa.Integer(), nullable=False, server_default="1"),
            sa.UniqueConstraint("company_id", "id", name="uq_project_records_company_id"),
            sa.CheckConstraint("status IN ('draft', 'active', 'completed', 'archived')", name="ck_project_records_status"),
            sa.CheckConstraint("due_date >= start_date", name="ck_project_records_dates"),
        )
        for column in ("company_id", "owner_user_id", "due_date", "status"):
            op.create_index(f"ix_project_records_{column}", "project_records", [column])
    if "project_tasks" not in existing:
        op.create_table("project_tasks",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("title", sa.String(240), nullable=False),
            sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("start_date", sa.Date(), nullable=False),
            sa.Column("due_date", sa.Date(), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
            sa.Column("completion_note", sa.Text()),
            sa.Column("completed_at", sa.DateTime()),
            sa.Column("version_id", sa.Integer(), nullable=False, server_default="1"),
            sa.ForeignKeyConstraint(["company_id", "project_id"], ["project_records.company_id", "project_records.id"], name="fk_project_tasks_company_project"),
            sa.CheckConstraint("status IN ('pending', 'in_progress', 'completed', 'cancelled')", name="ck_project_tasks_status"),
            sa.CheckConstraint("due_date >= start_date", name="ck_project_tasks_dates"),
        )
        for column in ("company_id", "project_id", "owner_user_id", "due_date", "status"):
            op.create_index(f"ix_project_tasks_{column}", "project_tasks", [column])
    install_sqlite_guards()


def downgrade():
    if op.get_bind().dialect.name == "sqlite":
        for name in ("project_user_delete", "project_user_update", "project_company_delete", "project_company_update"):
            op.execute(sa.text(f"DROP TRIGGER IF EXISTS trg_{name}"))
    for table in ("project_tasks", "project_records"):
        op.drop_table(table)
