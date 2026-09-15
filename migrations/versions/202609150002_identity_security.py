"""Scope login counters by tenant and evaluations by immutable user identity."""
from alembic import op
import sqlalchemy as sa

revision = "202609150002"
down_revision = "202609150001"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("login_attempts")}
    if "company_id" not in columns:
        op.add_column("login_attempts", sa.Column("company_id", sa.Integer(), nullable=True))
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("login_attempts")}
    if "ix_login_attempts_company_id" not in indexes:
        op.create_index("ix_login_attempts_company_id", "login_attempts", ["company_id"])

    duplicates = bind.execute(sa.text(
        "SELECT suggestion_id, parameter_id, evaluator_user_id "
        "FROM suggestion_evaluations WHERE evaluator_user_id IS NOT NULL "
        "GROUP BY suggestion_id, parameter_id, evaluator_user_id HAVING COUNT(*) > 1"
    )).first()
    if duplicates:
        raise RuntimeError(
            "Duplicate evaluations for the same user/parameter require review before "
            "migration; no evaluation data has been deleted."
        )
    constraints = sa.inspect(bind).get_unique_constraints("suggestion_evaluations")
    old_constraints = [constraint for constraint in constraints if
                       constraint["column_names"] == ["suggestion_id", "parameter_id", "evaluator_department"]]
    has_new_constraint = any(constraint["name"] == "uq_suggestion_evaluations_user_parameter"
                             for constraint in constraints)
    naming = {"uq": "uq_%(table_name)s_%(column_0_name)s_%(column_1_name)s_%(column_2_name)s"}
    if old_constraints or not has_new_constraint:
        with op.batch_alter_table("suggestion_evaluations", naming_convention=naming) as batch:
            for constraint in old_constraints:
                name = constraint["name"] or "uq_suggestion_evaluations_suggestion_id_parameter_id_evaluator_department"
                batch.drop_constraint(name, type_="unique")
            if not has_new_constraint:
                batch.create_unique_constraint(
                    "uq_suggestion_evaluations_user_parameter",
                    ["suggestion_id", "parameter_id", "evaluator_user_id"],
                )


def downgrade():
    raise RuntimeError("Restore a verified backup to revert this identity migration safely.")
