"""Project task estimates and dated milestones.

Revision ID: 202610050001
Revises: 202610030001
"""
from alembic import op
import sqlalchemy as sa

revision = "202610050001"
down_revision = "202610030001"
branch_labels = None
depends_on = None


def install_sqlite_guards():
    if op.get_bind().dialect.name != "sqlite":
        return
    predicate = (
        "EXISTS (SELECT 1 FROM project_records p WHERE p.id=NEW.project_id "
        "AND p.company_id=NEW.company_id AND NEW.target_date BETWEEN p.start_date AND p.due_date)"
    )
    for operation in ("INSERT", "UPDATE"):
        op.execute(sa.text(
            f"CREATE TRIGGER IF NOT EXISTS trg_project_milestones_tenant_{operation.lower()} "
            f"BEFORE {operation} ON project_milestones WHEN NOT ({predicate}) "
            "BEGIN SELECT RAISE(ABORT, 'project milestone tenant or date mismatch'); END"
        ))
    guards = (
        ("project_milestone_parent_update", "BEFORE UPDATE OF id,company_id,start_date,due_date ON project_records",
         "EXISTS (SELECT 1 FROM project_milestones m WHERE m.project_id=OLD.id "
         "AND ((NEW.id IS NOT OLD.id OR NEW.company_id IS NOT OLD.company_id) "
         "OR m.target_date < NEW.start_date OR m.target_date > NEW.due_date))"),
        ("project_milestone_parent_delete", "BEFORE DELETE ON project_records",
         "EXISTS (SELECT 1 FROM project_milestones m WHERE m.project_id=OLD.id)"),
    )
    for name, event, predicate in guards:
        op.execute(sa.text(f"CREATE TRIGGER IF NOT EXISTS trg_{name} {event} WHEN {predicate} "
                           "BEGIN SELECT RAISE(ABORT, 'project referenced milestone'); END"))


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "estimated_hours" not in {column["name"] for column in inspector.get_columns("project_tasks")}:
        op.add_column("project_tasks", sa.Column("estimated_hours", sa.Numeric(8, 1), nullable=True))
    if not inspector.has_table("project_milestones"):
        op.create_table("project_milestones",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("title", sa.String(240), nullable=False),
            sa.Column("target_date", sa.Date(), nullable=False),
            sa.Column("acceptance_criteria", sa.Text(), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
            sa.Column("completion_note", sa.Text()),
            sa.Column("completed_at", sa.DateTime()),
            sa.Column("version_id", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["company_id", "project_id"], ["project_records.company_id", "project_records.id"], name="fk_project_milestones_company_project"),
            sa.CheckConstraint("status IN ('pending', 'completed')", name="ck_project_milestones_status"),
        )
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("project_milestones")}
    for column in ("company_id", "project_id", "target_date", "status"):
        name = f"ix_project_milestones_{column}"
        if name not in indexes:
            op.create_index(name, "project_milestones", [column])
    install_sqlite_guards()


def downgrade():
    # Test-only rollback; production data must be backed up before removing milestones.
    if op.get_bind().dialect.name == "sqlite":
        for name in ("project_milestone_parent_update", "project_milestone_parent_delete"):
            op.execute(sa.text(f"DROP TRIGGER IF EXISTS trg_{name}"))
    op.drop_table("project_milestones")
    op.drop_column("project_tasks", "estimated_hours")
