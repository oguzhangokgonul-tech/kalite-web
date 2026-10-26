"""Company-scoped receivable and payable tracking records."""

from datetime import datetime, timezone
from decimal import Decimal

from .extensions import db


class PaymentRecord(db.Model):
    __tablename__ = "payment_records"

    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey("companies.id"), nullable=False, index=True)
    direction = db.Column(db.String(12), nullable=False, index=True)
    counterparty = db.Column(db.String(180), nullable=False)
    description = db.Column(db.String(500), nullable=False)
    reference_no = db.Column(db.String(100))
    project_no = db.Column(db.String(100))
    amount = db.Column(db.Numeric(14, 2), nullable=False)
    payment_method = db.Column(db.String(20), nullable=False, default="unspecified", server_default="unspecified")
    settled_amount = db.Column(db.Numeric(14, 2), nullable=False, default=0, server_default="0")
    currency = db.Column(db.String(3), nullable=False, default="TRY", server_default="TRY")
    due_date = db.Column(db.Date, nullable=False, index=True)
    responsible_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    confirmed_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    settled_on = db.Column(db.Date)
    note = db.Column(db.Text)
    status = db.Column(db.String(12), nullable=False, default="open", server_default="open", index=True)
    closed_at = db.Column(db.DateTime)
    cancelled_at = db.Column(db.DateTime)
    archived_at = db.Column(db.DateTime, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    updated_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), onupdate=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    version_id = db.Column(db.Integer, nullable=False, default=1, server_default="1")

    __mapper_args__ = {"version_id_col": version_id}
    __table_args__ = (
        db.CheckConstraint("direction IN ('receivable', 'payable')", name="ck_payment_direction"),
        db.CheckConstraint("status IN ('open', 'closed', 'cancelled')", name="ck_payment_status"),
        db.CheckConstraint("amount > 0 AND settled_amount >= 0 AND settled_amount <= amount", name="ck_payment_amounts"),
        db.CheckConstraint("currency IN ('TRY', 'USD', 'EUR')", name="ck_payment_currency"),
        db.CheckConstraint("status != 'closed' OR settled_amount = amount", name="ck_payment_closed_amount"),
    )

    responsible_user = db.relationship("User", foreign_keys=[responsible_user_id])
    created_by_user = db.relationship("User", foreign_keys=[created_by_user_id])
    confirmed_by_user = db.relationship("User", foreign_keys=[confirmed_by_user_id])
    attachments = db.relationship("PaymentAttachment", back_populates="record", order_by="PaymentAttachment.id.desc()")
    installments = db.relationship("PaymentInstallment", back_populates="record", order_by="PaymentInstallment.sequence_no")
    transactions = db.relationship("PaymentTransaction", back_populates="record", order_by="PaymentTransaction.id.desc()")

    @property
    def remaining_amount(self):
        return (self.amount or Decimal("0")) - (self.settled_amount or Decimal("0"))

    @property
    def number_label(self):
        prefix = "AL" if self.direction == "receivable" else "OD"
        year = self.created_at.year if self.created_at else datetime.now().year
        return f"{prefix}-{year}-{self.id:05d}" if self.id else "Yeni kayıt"


class PaymentAttachment(db.Model):
    __tablename__ = "payment_attachments"

    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey("companies.id"), nullable=False, index=True)
    record_id = db.Column(db.Integer, db.ForeignKey("payment_records.id"), nullable=False, index=True)
    original_name = db.Column(db.String(255), nullable=False)
    stored_path = db.Column(db.String(500), nullable=False)
    size_bytes = db.Column(db.Integer, nullable=False)
    uploaded_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    uploaded_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    is_active = db.Column(db.Boolean, nullable=False, default=True, server_default="1")

    record = db.relationship("PaymentRecord", back_populates="attachments")
    uploaded_by_user = db.relationship("User", foreign_keys=[uploaded_by_user_id])


class PaymentInstallment(db.Model):
    __tablename__ = "payment_installments"

    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey("companies.id"), nullable=False, index=True)
    record_id = db.Column(db.Integer, db.ForeignKey("payment_records.id"), nullable=False, index=True)
    sequence_no = db.Column(db.Integer, nullable=False)
    amount = db.Column(db.Numeric(14, 2), nullable=False)
    settled_amount = db.Column(db.Numeric(14, 2), nullable=False, default=0, server_default="0")
    legacy_settled_amount = db.Column(db.Numeric(14, 2), nullable=False, default=0, server_default="0")
    legacy_settled_on = db.Column(db.Date)
    due_date = db.Column(db.Date, nullable=False, index=True)

    __table_args__ = (
        db.UniqueConstraint("record_id", "sequence_no", name="uq_payment_installment_sequence"),
        db.CheckConstraint("sequence_no > 0", name="ck_payment_installment_sequence"),
        db.CheckConstraint("amount > 0 AND settled_amount >= 0 AND settled_amount <= amount", name="ck_payment_installment_amount"),
    )

    record = db.relationship("PaymentRecord", back_populates="installments")
    transactions = db.relationship("PaymentTransaction", back_populates="installment", order_by="PaymentTransaction.id.desc()")

    @property
    def remaining_amount(self):
        return self.amount - self.settled_amount


class PaymentTransaction(db.Model):
    __tablename__ = "payment_transactions"

    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey("companies.id"), nullable=False, index=True)
    record_id = db.Column(db.Integer, db.ForeignKey("payment_records.id"), nullable=False, index=True)
    installment_id = db.Column(db.Integer, db.ForeignKey("payment_installments.id"), nullable=False, index=True)
    amount = db.Column(db.Numeric(14, 2), nullable=False)
    occurred_on = db.Column(db.Date, nullable=False)
    note = db.Column(db.String(500))
    instrument_no = db.Column(db.String(100))
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    reversal_of_id = db.Column(db.Integer, db.ForeignKey("payment_transactions.id"), unique=True)

    __table_args__ = (db.CheckConstraint("amount != 0", name="ck_payment_transaction_nonzero"),)

    record = db.relationship("PaymentRecord", back_populates="transactions")
    installment = db.relationship("PaymentInstallment", back_populates="transactions")
    created_by_user = db.relationship("User", foreign_keys=[created_by_user_id])
    reversal = db.relationship("PaymentTransaction", remote_side=[id], uselist=False)
