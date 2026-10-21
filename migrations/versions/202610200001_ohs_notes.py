"""Company OHS observation pool, independent of action permissions."""
from alembic import op
import sqlalchemy as sa

revision = "202610200001"
down_revision = "202610140001"
branch_labels = None
depends_on = None


def upgrade():
    if sa.inspect(op.get_bind()).has_table("ohs_notes"):
        return
    op.create_table(
        "ohs_notes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("author_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("location", sa.String(200)),
        sa.Column("action_id", sa.Integer(), sa.ForeignKey("actions.id", ondelete="SET NULL"), unique=True),
        sa.Column("converted_at", sa.DateTime()),
        sa.Column("deleted_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("version_id", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_index("ix_ohs_notes_company_id", "ohs_notes", ["company_id"])


def downgrade():
    if sa.inspect(op.get_bind()).has_table("ohs_notes"):
        op.drop_table("ohs_notes")
