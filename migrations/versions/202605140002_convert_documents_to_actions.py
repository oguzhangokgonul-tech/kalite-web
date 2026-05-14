"""convert documents to actions

Revision ID: 202605140002
Revises: 202605140001
Create Date: 2026-05-14 00:02:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "202605140002"
down_revision = "202605140001"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("documents", schema=None) as batch_op:
        batch_op.add_column(sa.Column("title", sa.String(length=160), nullable=True))
        batch_op.add_column(sa.Column("responsible_owner", sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column("termin_date", sa.Date(), nullable=True))
        batch_op.add_column(
            sa.Column("is_completed", sa.Boolean(), nullable=False, server_default=sa.text("0"))
        )
        batch_op.add_column(sa.Column("completed_at", sa.Date(), nullable=True))

    op.execute(
        """
        UPDATE documents
        SET
            title = name,
            responsible_owner = responsible_person,
            termin_date = date(
                last_filled_date,
                CASE
                    WHEN period LIKE 'G%' THEN '+1 day'
                    WHEN period LIKE 'H%' THEN '+7 day'
                    ELSE '+30 day'
                END
            ),
            is_completed = CASE WHEN status LIKE 'Tamam%' THEN 1 ELSE 0 END,
            completed_at = CASE WHEN status LIKE 'Tamam%' THEN last_filled_date ELSE NULL END
        """
    )

    with op.batch_alter_table("documents", schema=None) as batch_op:
        batch_op.alter_column("title", existing_type=sa.String(length=160), nullable=False)
        batch_op.alter_column(
            "responsible_owner", existing_type=sa.String(length=120), nullable=False
        )
        batch_op.alter_column("termin_date", existing_type=sa.Date(), nullable=False)
        batch_op.drop_column("status")
        batch_op.drop_column("last_filled_date")
        batch_op.drop_column("period")
        batch_op.drop_column("responsible_person")
        batch_op.drop_column("name")

    op.rename_table("documents", "actions")


def downgrade():
    op.rename_table("actions", "documents")

    with op.batch_alter_table("documents", schema=None) as batch_op:
        batch_op.add_column(sa.Column("name", sa.String(length=160), nullable=True))
        batch_op.add_column(sa.Column("responsible_person", sa.String(length=120), nullable=True))
        batch_op.add_column(
            sa.Column("period", sa.String(length=20), nullable=False, server_default="Aylık")
        )
        batch_op.add_column(sa.Column("last_filled_date", sa.Date(), nullable=True))
        batch_op.add_column(
            sa.Column("status", sa.String(length=20), nullable=False, server_default="Beklemede")
        )

    op.execute(
        """
        UPDATE documents
        SET
            name = title,
            responsible_person = responsible_owner,
            last_filled_date = termin_date,
            status = CASE WHEN is_completed = 1 THEN 'Tamamlandı' ELSE 'Beklemede' END
        """
    )

    with op.batch_alter_table("documents", schema=None) as batch_op:
        batch_op.alter_column("name", existing_type=sa.String(length=160), nullable=False)
        batch_op.alter_column(
            "responsible_person", existing_type=sa.String(length=120), nullable=False
        )
        batch_op.alter_column("last_filled_date", existing_type=sa.Date(), nullable=False)
        batch_op.drop_column("completed_at")
        batch_op.drop_column("is_completed")
        batch_op.drop_column("termin_date")
        batch_op.drop_column("responsible_owner")
        batch_op.drop_column("title")
