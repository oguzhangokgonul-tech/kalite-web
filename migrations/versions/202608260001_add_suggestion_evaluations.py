"""add suggestion evaluations

Revision ID: 202608260001
Revises: 202608250001
Create Date: 2026-08-26 09:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "202608260001"
down_revision = "202608250001"
branch_labels = None
depends_on = None


def _table_names(bind):
    return set(sa.inspect(bind).get_table_names())


def upgrade():
    bind = op.get_bind()
    tables = _table_names(bind)
    if "suggestion_evaluations" not in tables:
        op.create_table(
            "suggestion_evaluations",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("company_id", sa.Integer(), nullable=True),
            sa.Column("suggestion_id", sa.Integer(), nullable=False),
            sa.Column("parameter_id", sa.Integer(), nullable=False),
            sa.Column("parameter_name", sa.String(length=160), nullable=False),
            sa.Column("parameter_multiplier", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("evaluator_department", sa.String(length=80), nullable=False),
            sa.Column("evaluator_user_id", sa.Integer(), nullable=True),
            sa.Column("rating", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("comment", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
            sa.ForeignKeyConstraint(["evaluator_user_id"], ["users.id"]),
            sa.ForeignKeyConstraint(["parameter_id"], ["suggestion_score_parameters.id"]),
            sa.ForeignKeyConstraint(["suggestion_id"], ["suggestions.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "suggestion_id",
                "parameter_id",
                "evaluator_department",
                name="uq_suggestion_evaluations_department_parameter",
            ),
        )
        op.create_index("ix_suggestion_evaluations_company_id", "suggestion_evaluations", ["company_id"])
        op.create_index("ix_suggestion_evaluations_suggestion_id", "suggestion_evaluations", ["suggestion_id"])
        op.create_index("ix_suggestion_evaluations_parameter_id", "suggestion_evaluations", ["parameter_id"])


def downgrade():
    bind = op.get_bind()
    tables = _table_names(bind)
    if "suggestion_evaluations" in tables:
        indexes = {index["name"] for index in sa.inspect(bind).get_indexes("suggestion_evaluations")}
        for index_name in (
            "ix_suggestion_evaluations_parameter_id",
            "ix_suggestion_evaluations_suggestion_id",
            "ix_suggestion_evaluations_company_id",
        ):
            if index_name in indexes:
                op.drop_index(index_name, table_name="suggestion_evaluations")
        op.drop_table("suggestion_evaluations")
