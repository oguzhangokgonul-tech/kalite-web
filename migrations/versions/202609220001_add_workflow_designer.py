"""add configurable workflow designer data model

Revision ID: 202609220001
Revises: 202609210001
"""

from alembic import op
import sqlalchemy as sa


revision = "202609220001"
down_revision = "202609210001"
branch_labels = None
depends_on = None


def _index(table_name, column_name, unique=False):
    op.create_index(
        f"ix_{table_name}_{column_name}",
        table_name,
        [column_name],
        unique=unique,
    )


def _insert_sales_readiness_setting(bind):
    key = "sales_readiness:competitor_workflow_designer"
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

    if "workflow_templates" not in tables:
        op.create_table(
            "workflow_templates",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
            sa.Column("code", sa.String(40), nullable=False),
            sa.Column("name", sa.String(180), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
            sa.Column("current_version_number", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("published_version_number", sa.Integer(), nullable=True),
            sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("company_id", "code", name="uq_workflow_templates_company_code"),
            sa.CheckConstraint(
                "status IN ('draft','published','archived')",
                name="ck_workflow_templates_status",
            ),
            sa.CheckConstraint(
                "current_version_number >= 1",
                name="ck_workflow_templates_current_version_positive",
            ),
        )
        for column in ("company_id", "status"):
            _index("workflow_templates", column)

    if "workflow_versions" not in tables:
        op.create_table(
            "workflow_versions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
            sa.Column("template_id", sa.Integer(), sa.ForeignKey("workflow_templates.id"), nullable=False),
            sa.Column("source_version_id", sa.Integer(), sa.ForeignKey("workflow_versions.id"), nullable=True),
            sa.Column("version_number", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
            sa.Column("name_snapshot", sa.String(180), nullable=False),
            sa.Column("description_snapshot", sa.Text(), nullable=True),
            sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("published_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("published_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint(
                "template_id",
                "version_number",
                name="uq_workflow_versions_template_version",
            ),
            sa.CheckConstraint(
                "version_number >= 1",
                name="ck_workflow_versions_version_positive",
            ),
            sa.CheckConstraint(
                "status IN ('draft','published','archived')",
                name="ck_workflow_versions_status",
            ),
        )
        for column in ("company_id", "template_id", "source_version_id", "status"):
            _index("workflow_versions", column)

    if "workflow_steps" not in tables:
        op.create_table(
            "workflow_steps",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
            sa.Column("version_id", sa.Integer(), sa.ForeignKey("workflow_versions.id"), nullable=False),
            sa.Column("step_key", sa.String(80), nullable=False),
            sa.Column("name", sa.String(180), nullable=False),
            sa.Column("instructions", sa.Text(), nullable=True),
            sa.Column("step_type", sa.String(20), nullable=False),
            sa.Column("assignment_type", sa.String(30), nullable=False),
            sa.Column("assigned_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("assigned_role_id", sa.Integer(), sa.ForeignKey("roles.id"), nullable=True),
            sa.Column("sort_order", sa.Integer(), nullable=False),
            sa.Column("approval_policy", sa.String(10), nullable=False, server_default="any"),
            sa.Column("rejection_action", sa.String(10), nullable=False, server_default="return"),
            sa.Column("due_days", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("requires_comment", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("version_id", "step_key", name="uq_workflow_steps_version_key"),
            sa.UniqueConstraint("version_id", "sort_order", name="uq_workflow_steps_version_order"),
            sa.CheckConstraint(
                "step_type IN ('approval','task','notification')",
                name="ck_workflow_steps_type",
            ),
            sa.CheckConstraint(
                "assignment_type IN ('user','role','department_manager')",
                name="ck_workflow_steps_assignment_type",
            ),
            sa.CheckConstraint(
                "approval_policy IN ('any','all')",
                name="ck_workflow_steps_approval_policy",
            ),
            sa.CheckConstraint(
                "rejection_action IN ('return','reject')",
                name="ck_workflow_steps_rejection_action",
            ),
            sa.CheckConstraint("sort_order >= 1", name="ck_workflow_steps_order_positive"),
            sa.CheckConstraint("due_days >= 0", name="ck_workflow_steps_due_days_nonnegative"),
            sa.CheckConstraint(
                "(assignment_type = 'user' AND assigned_user_id IS NOT NULL AND assigned_role_id IS NULL) OR "
                "(assignment_type = 'role' AND assigned_user_id IS NULL AND assigned_role_id IS NOT NULL) OR "
                "(assignment_type = 'department_manager' AND assigned_user_id IS NULL AND assigned_role_id IS NULL)",
                name="ck_workflow_steps_assignment_target",
            ),
        )
        for column in (
            "company_id",
            "version_id",
            "assigned_user_id",
            "assigned_role_id",
        ):
            _index("workflow_steps", column)

    if "workflow_instances" not in tables:
        op.create_table(
            "workflow_instances",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
            sa.Column("instance_no", sa.String(40), nullable=False),
            sa.Column("version_id", sa.Integer(), sa.ForeignKey("workflow_versions.id"), nullable=False),
            sa.Column("department_id", sa.Integer(), sa.ForeignKey("company_departments.id"), nullable=True),
            sa.Column("requester_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("title", sa.String(240), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("workflow_code_snapshot", sa.String(40), nullable=False),
            sa.Column("workflow_name_snapshot", sa.String(180), nullable=False),
            sa.Column("version_number_snapshot", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(30), nullable=False, server_default="draft"),
            sa.Column("current_step_order", sa.Integer(), nullable=True),
            sa.Column("submitted_at", sa.DateTime(), nullable=True),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.Column("rejected_at", sa.DateTime(), nullable=True),
            sa.Column("cancelled_at", sa.DateTime(), nullable=True),
            sa.Column("archived_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("company_id", "instance_no", name="uq_workflow_instances_company_no"),
            sa.CheckConstraint(
                "status IN ('draft','in_progress','revision_requested','completed','rejected','cancelled','archived')",
                name="ck_workflow_instances_status",
            ),
            sa.CheckConstraint(
                "current_step_order IS NULL OR current_step_order >= 1",
                name="ck_workflow_instances_current_step_order",
            ),
        )
        for column in (
            "company_id",
            "version_id",
            "department_id",
            "requester_user_id",
            "status",
        ):
            _index("workflow_instances", column)
        op.create_index(
            "ix_workflow_instances_company_status",
            "workflow_instances",
            ["company_id", "status"],
        )

    if "workflow_instance_steps" not in tables:
        op.create_table(
            "workflow_instance_steps",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
            sa.Column("instance_id", sa.Integer(), sa.ForeignKey("workflow_instances.id"), nullable=False),
            sa.Column("source_step_id", sa.Integer(), sa.ForeignKey("workflow_steps.id"), nullable=False),
            sa.Column("step_key_snapshot", sa.String(80), nullable=False),
            sa.Column("name_snapshot", sa.String(180), nullable=False),
            sa.Column("instructions_snapshot", sa.Text(), nullable=True),
            sa.Column("step_type_snapshot", sa.String(20), nullable=False),
            sa.Column("assignment_type_snapshot", sa.String(30), nullable=False),
            sa.Column("assigned_user_id_snapshot", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("assigned_role_id_snapshot", sa.Integer(), sa.ForeignKey("roles.id"), nullable=True),
            sa.Column("assignment_label_snapshot", sa.String(180), nullable=True),
            sa.Column("sort_order", sa.Integer(), nullable=False),
            sa.Column("round_number", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("approval_policy_snapshot", sa.String(10), nullable=False),
            sa.Column("rejection_action_snapshot", sa.String(10), nullable=False),
            sa.Column("due_days_snapshot", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("requires_comment_snapshot", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
            sa.Column("due_date", sa.Date(), nullable=True),
            sa.Column("activated_at", sa.DateTime(), nullable=True),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.Column("completion_note", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint(
                "instance_id",
                "source_step_id",
                "round_number",
                name="uq_workflow_instance_steps_source_round",
            ),
            sa.CheckConstraint(
                "step_type_snapshot IN ('approval','task','notification')",
                name="ck_workflow_instance_steps_type",
            ),
            sa.CheckConstraint(
                "assignment_type_snapshot IN ('user','role','department_manager')",
                name="ck_workflow_instance_steps_assignment_type",
            ),
            sa.CheckConstraint(
                "approval_policy_snapshot IN ('any','all')",
                name="ck_workflow_instance_steps_approval_policy",
            ),
            sa.CheckConstraint(
                "rejection_action_snapshot IN ('return','reject')",
                name="ck_workflow_instance_steps_rejection_action",
            ),
            sa.CheckConstraint(
                "status IN ('pending','active','completed','returned','rejected','skipped','cancelled')",
                name="ck_workflow_instance_steps_status",
            ),
            sa.CheckConstraint(
                "sort_order >= 1 AND round_number >= 1 AND due_days_snapshot >= 0",
                name="ck_workflow_instance_steps_positive_values",
            ),
            sa.CheckConstraint(
                "(assignment_type_snapshot = 'user' AND assigned_user_id_snapshot IS NOT NULL AND assigned_role_id_snapshot IS NULL) OR "
                "(assignment_type_snapshot = 'role' AND assigned_user_id_snapshot IS NULL AND assigned_role_id_snapshot IS NOT NULL) OR "
                "(assignment_type_snapshot = 'department_manager' AND assigned_user_id_snapshot IS NULL AND assigned_role_id_snapshot IS NULL)",
                name="ck_workflow_instance_steps_assignment_target",
            ),
        )
        for column in (
            "company_id",
            "instance_id",
            "source_step_id",
            "status",
            "due_date",
        ):
            _index("workflow_instance_steps", column)
        op.create_index(
            "ix_workflow_instance_steps_company_status_due",
            "workflow_instance_steps",
            ["company_id", "status", "due_date"],
        )

    if "workflow_step_recipients" not in tables:
        op.create_table(
            "workflow_step_recipients",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
            sa.Column("instance_step_id", sa.Integer(), sa.ForeignKey("workflow_instance_steps.id"), nullable=False),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("recipient_name_snapshot", sa.String(180), nullable=False),
            sa.Column("recipient_email_snapshot", sa.String(255), nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
            sa.Column("decision", sa.String(20), nullable=True),
            sa.Column("decision_note", sa.Text(), nullable=True),
            sa.Column("assigned_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("decided_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint(
                "instance_step_id",
                "user_id",
                name="uq_workflow_step_recipients_step_user",
            ),
            sa.CheckConstraint(
                "status IN ('pending','acted','cancelled')",
                name="ck_workflow_step_recipients_status",
            ),
            sa.CheckConstraint(
                "decision IS NULL OR decision IN ('approve','complete','acknowledge','reject','return')",
                name="ck_workflow_step_recipients_decision",
            ),
            sa.CheckConstraint(
                "(status = 'pending' AND decision IS NULL AND decided_at IS NULL) OR "
                "(status = 'acted' AND decision IS NOT NULL AND decided_at IS NOT NULL) OR "
                "(status = 'cancelled' AND decision IS NULL)",
                name="ck_workflow_step_recipients_decision_state",
            ),
        )
        for column in ("company_id", "instance_step_id", "user_id", "status"):
            _index("workflow_step_recipients", column)
        op.create_index(
            "ix_workflow_step_recipients_company_user_status",
            "workflow_step_recipients",
            ["company_id", "user_id", "status"],
        )

    if "workflow_events" not in tables:
        op.create_table(
            "workflow_events",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
            sa.Column("instance_id", sa.Integer(), sa.ForeignKey("workflow_instances.id"), nullable=False),
            sa.Column("instance_step_id", sa.Integer(), sa.ForeignKey("workflow_instance_steps.id"), nullable=True),
            sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("event_type", sa.String(50), nullable=False),
            sa.Column("message", sa.Text(), nullable=False),
            sa.Column("event_data_json", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
        for column in (
            "company_id",
            "instance_id",
            "instance_step_id",
            "actor_user_id",
            "event_type",
            "created_at",
        ):
            _index("workflow_events", column)
        op.create_index(
            "ix_workflow_events_company_instance_created",
            "workflow_events",
            ["company_id", "instance_id", "created_at"],
        )

    tables = set(sa.inspect(bind).get_table_names())
    if "company_modules" in tables:
        company_columns = {
            column["name"]
            for column in sa.inspect(bind).get_columns("companies")
        }
        enabled_expression = (
            "CASE WHEN package_key = 'custom' THEN 0 ELSE 1 END"
            if "package_key" in company_columns
            else "1"
        )
        op.execute(
            sa.text(
                "INSERT INTO company_modules (company_id, module_key, is_enabled) "
                f"SELECT id, 'workflow_designer', {enabled_expression} FROM companies "
                "WHERE NOT EXISTS ("
                "SELECT 1 FROM company_modules cm "
                "WHERE cm.company_id = companies.id "
                "AND cm.module_key = 'workflow_designer'"
                ")"
            )
        )

    if "app_settings" in tables:
        _insert_sales_readiness_setting(bind)


def downgrade():
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())

    if "company_modules" in tables:
        op.execute(
            sa.text(
                "DELETE FROM company_modules WHERE module_key = 'workflow_designer'"
            )
        )
    if "app_settings" in tables:
        op.execute(
            sa.text(
                "DELETE FROM app_settings "
                "WHERE key = 'sales_readiness:competitor_workflow_designer'"
            )
        )

    for table_name in (
        "workflow_events",
        "workflow_step_recipients",
        "workflow_instance_steps",
        "workflow_instances",
        "workflow_steps",
        "workflow_versions",
        "workflow_templates",
    ):
        if table_name in tables:
            op.drop_table(table_name)
