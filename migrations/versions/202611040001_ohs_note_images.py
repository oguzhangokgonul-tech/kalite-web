"""Add company-scoped images to OHS notes."""

from alembic import op
import sqlalchemy as sa


revision = "202611040001"
down_revision = "202610300002"
branch_labels = None
depends_on = None


def upgrade():
    if sa.inspect(op.get_bind()).has_table("ohs_note_images"):
        return
    op.create_table(
        "ohs_note_images",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("note_id", sa.Integer(), sa.ForeignKey("ohs_notes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("uploaded_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("original_name", sa.String(255), nullable=False),
        sa.Column("stored_path", sa.String(500), nullable=False),
        sa.Column("mime_type", sa.String(30), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime()),
    )
    op.create_index("ix_ohs_note_images_company_id", "ohs_note_images", ["company_id"])
    op.create_index("ix_ohs_note_images_note_id", "ohs_note_images", ["note_id"])


def downgrade():
    if sa.inspect(op.get_bind()).has_table("ohs_note_images"):
        op.drop_table("ohs_note_images")
