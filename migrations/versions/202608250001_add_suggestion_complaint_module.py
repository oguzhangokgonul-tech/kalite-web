"""add suggestion complaint module

Revision ID: 202608250001
Revises: 202608240001
Create Date: 2026-08-25 00:01:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "202608250001"
down_revision = "202608240001"
branch_labels = None
depends_on = None


DEFAULT_PARAMETERS = (
    ("Önerinin Kritikliği", 15, 10),
    ("Maliyet/Malzeme Azaltımı", 15, 20),
    ("Zaman Tasarrufu", 15, 30),
    ("İSG Risklerinin Ortadan Kaldırılması", 10, 40),
    ("5S Temizlik Düzen", 10, 50),
    ("Enerji Tasarrufu", 5, 60),
    ("Atık Azaltımı", 5, 70),
    ("Enerji Kullanım Artışı", -5, 80),
    ("Atık Oluşum Artışı", -5, 90),
    ("Yatırım İhtiyacı", -10, 100),
    ("Birim Üründe Maliyet Arttırımı", -15, 110),
    ("Hayata Geçirilebilirlik", -20, 120),
)


def _table_names(bind):
    return set(sa.inspect(bind).get_table_names())


def upgrade():
    bind = op.get_bind()
    tables = _table_names(bind)

    if "suggestion_score_parameters" not in tables:
        op.create_table(
            "suggestion_score_parameters",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("company_id", sa.Integer(), nullable=True),
            sa.Column("name", sa.String(length=160), nullable=False),
            sa.Column("score", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "company_id",
                "name",
                name="uq_suggestion_score_parameters_company_name",
            ),
        )
        op.create_index(
            "ix_suggestion_score_parameters_company_id",
            "suggestion_score_parameters",
            ["company_id"],
        )

    if "suggestions" not in tables:
        op.create_table(
            "suggestions",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("company_id", sa.Integer(), nullable=True),
            sa.Column("suggestion_number", sa.Integer(), nullable=True),
            sa.Column("suggestion_date", sa.Date(), nullable=True),
            sa.Column("evaluation_month", sa.String(length=20), nullable=True),
            sa.Column("department", sa.String(length=80), nullable=True),
            sa.Column("owner_name", sa.String(length=160), nullable=False),
            sa.Column("definition", sa.Text(), nullable=False),
            sa.Column("status", sa.String(length=40), nullable=False, server_default="Değerlendirmede"),
            sa.Column("unit_comment", sa.Text(), nullable=True),
            sa.Column("qdms_no", sa.String(length=80), nullable=True),
            sa.Column("action_responsible", sa.String(length=160), nullable=True),
            sa.Column("action_status", sa.String(length=80), nullable=True),
            sa.Column("detail", sa.Text(), nullable=True),
            sa.Column("attachment_original_name", sa.String(length=255), nullable=True),
            sa.Column("attachment_stored_name", sa.String(length=255), nullable=True),
            sa.Column("attachment_mime_type", sa.String(length=120), nullable=True),
            sa.Column("created_by_user_id", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
            sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "company_id",
                "suggestion_number",
                name="uq_suggestions_company_number",
            ),
        )
        op.create_index("ix_suggestions_company_id", "suggestions", ["company_id"])

    if "suggestion_scores" not in tables:
        op.create_table(
            "suggestion_scores",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("company_id", sa.Integer(), nullable=True),
            sa.Column("suggestion_id", sa.Integer(), nullable=False),
            sa.Column("parameter_id", sa.Integer(), nullable=True),
            sa.Column("parameter_name", sa.String(length=160), nullable=False),
            sa.Column("score_value", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("is_selected", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
            sa.ForeignKeyConstraint(["parameter_id"], ["suggestion_score_parameters.id"]),
            sa.ForeignKeyConstraint(["suggestion_id"], ["suggestions.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "suggestion_id",
                "parameter_id",
                name="uq_suggestion_scores_suggestion_parameter",
            ),
        )
        op.create_index("ix_suggestion_scores_company_id", "suggestion_scores", ["company_id"])
        op.create_index("ix_suggestion_scores_suggestion_id", "suggestion_scores", ["suggestion_id"])
        op.create_index("ix_suggestion_scores_parameter_id", "suggestion_scores", ["parameter_id"])

    if "company_modules" in _table_names(bind):
        company_ids = [
            row[0]
            for row in bind.execute(sa.text("SELECT id FROM companies")).fetchall()
        ]
        for company_id in company_ids:
            bind.execute(
                sa.text(
                    """
                    INSERT INTO company_modules (company_id, module_key, is_enabled)
                    SELECT :company_id, 'suggestions', 1
                    WHERE NOT EXISTS (
                        SELECT 1 FROM company_modules
                        WHERE company_id = :company_id
                          AND module_key = 'suggestions'
                    )
                    """
                ),
                {"company_id": company_id},
            )
            for name, score, sort_order in DEFAULT_PARAMETERS:
                bind.execute(
                    sa.text(
                        """
                        INSERT INTO suggestion_score_parameters
                            (company_id, name, score, sort_order, is_active)
                        SELECT :company_id, :name, :score, :sort_order, 1
                        WHERE NOT EXISTS (
                            SELECT 1 FROM suggestion_score_parameters
                            WHERE company_id = :company_id
                              AND name = :name
                        )
                        """
                    ),
                    {
                        "company_id": company_id,
                        "name": name,
                        "score": score,
                        "sort_order": sort_order,
                    },
                )


def downgrade():
    bind = op.get_bind()
    tables = _table_names(bind)

    if "suggestion_scores" in tables:
        indexes = {index["name"] for index in sa.inspect(bind).get_indexes("suggestion_scores")}
        for index_name in (
            "ix_suggestion_scores_parameter_id",
            "ix_suggestion_scores_suggestion_id",
            "ix_suggestion_scores_company_id",
        ):
            if index_name in indexes:
                op.drop_index(index_name, table_name="suggestion_scores")
        op.drop_table("suggestion_scores")
    if "suggestions" in tables:
        indexes = {index["name"] for index in sa.inspect(bind).get_indexes("suggestions")}
        if "ix_suggestions_company_id" in indexes:
            op.drop_index("ix_suggestions_company_id", table_name="suggestions")
        op.drop_table("suggestions")
    if "suggestion_score_parameters" in tables:
        indexes = {
            index["name"]
            for index in sa.inspect(bind).get_indexes("suggestion_score_parameters")
        }
        if "ix_suggestion_score_parameters_company_id" in indexes:
            op.drop_index(
                "ix_suggestion_score_parameters_company_id",
                table_name="suggestion_score_parameters",
            )
        op.drop_table("suggestion_score_parameters")
    if "company_modules" in _table_names(bind):
        bind.execute(sa.text("DELETE FROM company_modules WHERE module_key = 'suggestions'"))
