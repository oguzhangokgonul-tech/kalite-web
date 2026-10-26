"""Company-scoped contract register and scanned attachments."""

from datetime import datetime, timezone

from .extensions import db


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class ContractRecord(db.Model):
    __tablename__ = "contract_records"

    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey("companies.id"), nullable=False, index=True)
    title = db.Column(db.String(180), nullable=False)
    counterparty = db.Column(db.String(180), nullable=False)
    contract_no = db.Column(db.String(100))
    signed_on = db.Column(db.Date)
    starts_on = db.Column(db.Date)
    ends_on = db.Column(db.Date, index=True)
    note = db.Column(db.Text)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)
    updated_at = db.Column(db.DateTime, nullable=False, default=utc_now, onupdate=utc_now)
    archived_at = db.Column(db.DateTime)
    version_id = db.Column(db.Integer, nullable=False, default=1, server_default="1")

    __mapper_args__ = {"version_id_col": version_id}
    __table_args__ = (
        db.CheckConstraint("length(trim(title)) BETWEEN 1 AND 180", name="ck_contract_title"),
        db.CheckConstraint("length(trim(counterparty)) BETWEEN 1 AND 180", name="ck_contract_counterparty"),
        db.CheckConstraint("starts_on IS NULL OR ends_on IS NULL OR ends_on >= starts_on", name="ck_contract_dates"),
    )

    created_by_user = db.relationship("User", foreign_keys=[created_by_user_id])
    files = db.relationship("ContractFile", back_populates="record", order_by="ContractFile.id.desc()")


class ContractFile(db.Model):
    __tablename__ = "contract_files"

    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey("companies.id"), nullable=False, index=True)
    record_id = db.Column(db.Integer, db.ForeignKey("contract_records.id"), nullable=False, index=True)
    original_name = db.Column(db.String(255), nullable=False)
    stored_path = db.Column(db.String(500), nullable=False)
    mime_type = db.Column(db.String(50), nullable=False)
    size_bytes = db.Column(db.Integer, nullable=False)
    uploaded_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    uploaded_at = db.Column(db.DateTime, nullable=False, default=utc_now)
    is_active = db.Column(db.Boolean, nullable=False, default=True, server_default="1")

    __table_args__ = (db.CheckConstraint("size_bytes > 0", name="ck_contract_file_size"),)

    record = db.relationship("ContractRecord", back_populates="files")
    uploaded_by_user = db.relationship("User", foreign_keys=[uploaded_by_user_id])
