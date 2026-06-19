"""add document management

Revision ID: 202606190001
Revises: 202606170002
Create Date: 2026-06-19 00:01:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "202606190001"
down_revision = "202606170002"
branch_labels = None
depends_on = None


DOCUMENT_CATEGORIES = (
    ("01", "Kalite El Kitabı", "kalite-el-kitabi", 1, "blue", "folder"),
    ("02", "Prosesler", "prosesler", 2, "green", "folder"),
    ("03", "Prosedürler", "prosedurler", 3, "orange", "folder"),
    ("04", "Talimatlar", "talimatlar", 4, "red", "folder"),
    ("05", "Formlar", "formlar", 5, "purple", "file-earmark-text"),
    ("06", "Listeler", "listeler", 6, "cyan", "file-earmark-spreadsheet"),
    ("07", "Planlar", "planlar", 7, "lime", "calendar-check"),
    ("08", "Görev Tanımları", "gorev-tanimlari", 8, "amber", "people"),
)


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "document_categories" not in tables:
        op.create_table(
            "document_categories",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("code", sa.String(length=10), nullable=False),
            sa.Column("name", sa.String(length=120), nullable=False),
            sa.Column("slug", sa.String(length=160), nullable=False),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("color", sa.String(length=40), nullable=True),
            sa.Column("icon", sa.String(length=80), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("slug"),
        )
        tables.add("document_categories")

    if "documents" not in tables:
        op.create_table(
            "documents",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("category_id", sa.Integer(), nullable=False),
            sa.Column("document_code", sa.String(length=80), nullable=False),
            sa.Column("title", sa.String(length=200), nullable=False),
            sa.Column("revision_no", sa.String(length=40), nullable=True),
            sa.Column("publish_date", sa.Date(), nullable=True),
            sa.Column("department", sa.String(length=80), nullable=True),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("status", sa.String(length=40), nullable=False, server_default="Yayında"),
            sa.Column("file_name", sa.String(length=255), nullable=False),
            sa.Column("original_file_name", sa.String(length=255), nullable=False),
            sa.Column("file_path", sa.String(length=500), nullable=False),
            sa.Column("file_type", sa.String(length=20), nullable=True),
            sa.Column("file_size", sa.Integer(), nullable=True),
            sa.Column("uploaded_by", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
            sa.Column("archived_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["category_id"], ["document_categories.id"]),
            sa.ForeignKeyConstraint(["uploaded_by"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )

    category_table = sa.table(
        "document_categories",
        sa.column("code", sa.String),
        sa.column("name", sa.String),
        sa.column("slug", sa.String),
        sa.column("sort_order", sa.Integer),
        sa.column("color", sa.String),
        sa.column("icon", sa.String),
        sa.column("is_active", sa.Boolean),
    )
    existing_slugs = {
        row[0]
        for row in bind.execute(sa.text("SELECT slug FROM document_categories")).all()
    }
    missing_categories = [
        {
            "code": code,
            "name": name,
            "slug": slug,
            "sort_order": sort_order,
            "color": color,
            "icon": icon,
            "is_active": True,
        }
        for code, name, slug, sort_order, color, icon in DOCUMENT_CATEGORIES
        if slug not in existing_slugs
    ]
    if missing_categories:
        op.bulk_insert(category_table, missing_categories)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "documents" in tables:
        op.drop_table("documents")
    if "document_categories" in tables:
        op.drop_table("document_categories")
