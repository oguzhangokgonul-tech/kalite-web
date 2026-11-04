"""Store calibration certificate PDFs per device and company."""

from alembic import op
import sqlalchemy as sa


revision = "202611040004"
down_revision = "202611040003"
branch_labels = None
depends_on = None


def upgrade():
    if "calibration_certificates" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "calibration_certificates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("calibration_record_id", sa.Integer(), sa.ForeignKey("calibration_records.id"), nullable=False),
        sa.Column("original_name", sa.String(length=255), nullable=False),
        sa.Column("stored_path", sa.String(length=500), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("uploaded_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_calibration_certificates_company_id", "calibration_certificates", ["company_id"])
    op.create_index("ix_calibration_certificates_calibration_record_id", "calibration_certificates", ["calibration_record_id"])


def downgrade():
    if "calibration_certificates" in sa.inspect(op.get_bind()).get_table_names():
        if op.get_bind().execute(sa.text("SELECT 1 FROM calibration_certificates LIMIT 1")).first():
            raise RuntimeError("Kalibrasyon PDF kayıtları varken geri alma için önce doğrulanmış yedeği geri yükleyin.")
        op.drop_index("ix_calibration_certificates_calibration_record_id", table_name="calibration_certificates")
        op.drop_index("ix_calibration_certificates_company_id", table_name="calibration_certificates")
        op.drop_table("calibration_certificates")
