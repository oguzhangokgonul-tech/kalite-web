"""Tenant-owned purchase requests and immutable workflow decisions."""
from sqlalchemy import event

from .extensions import db


class PurchaseRequest(db.Model):
    __tablename__ = 'purchase_requests'
    __table_args__ = (
        db.UniqueConstraint('company_id', 'request_token', name='uq_purchase_request_token'),
        db.CheckConstraint("kind IN ('material', 'service')", name='ck_purchase_kind'),
        db.CheckConstraint("status IN ('draft', 'pending_purchase', 'pending_admin', 'returned', 'rejected', 'closed')", name='ck_purchase_status'),
        db.CheckConstraint('version_id > 0', name='ck_purchase_version'),
        db.CheckConstraint('length(request_token) = 36', name='ck_purchase_token'),
        db.CheckConstraint('length(trim(title)) BETWEEN 1 AND 180', name='ck_purchase_title'),
        db.CheckConstraint('length(trim(description)) BETWEEN 1 AND 5000', name='ck_purchase_description'),
        db.CheckConstraint('length(trim(justification)) BETWEEN 1 AND 3000', name='ck_purchase_justification'),
        db.CheckConstraint('length(trim(unit)) BETWEEN 1 AND 40', name='ck_purchase_unit'),
        db.CheckConstraint('quantity > 0', name='ck_purchase_quantity'),
        db.CheckConstraint('estimated_total IS NULL OR estimated_total >= 0', name='ck_purchase_estimate'),
        db.CheckConstraint("currency IN ('TRY', 'USD', 'EUR')", name='ck_purchase_currency'),
        db.CheckConstraint('purchasing_approver_id IS NULL OR purchasing_approver_id != requester_id', name='ck_purchase_distinct_first'),
        db.CheckConstraint('admin_approver_id IS NULL OR (admin_approver_id != requester_id AND admin_approver_id != purchasing_approver_id)', name='ck_purchase_distinct_admin'),
        db.CheckConstraint("status NOT IN ('pending_admin', 'closed') OR purchasing_approver_id IS NOT NULL", name='ck_purchase_first_required'),
        db.CheckConstraint("status != 'closed' OR (admin_approver_id IS NOT NULL AND closed_at IS NOT NULL)", name='ck_purchase_closed'),
        db.CheckConstraint("status = 'closed' OR (admin_approver_id IS NULL AND closed_at IS NULL)", name='ck_purchase_not_closed'),
        db.CheckConstraint("status NOT IN ('returned', 'rejected') OR (decision_reason IS NOT NULL AND length(trim(decision_reason)) BETWEEN 1 AND 1000)", name='ck_purchase_reason'),
    )

    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('companies.id'), nullable=False, index=True)
    requester_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    kind = db.Column(db.String(16), nullable=False)
    title = db.Column(db.String(180), nullable=False)
    description = db.Column(db.Text, nullable=False)
    justification = db.Column(db.Text, nullable=False)
    quantity = db.Column(db.Numeric(12, 3), nullable=False)
    unit = db.Column(db.String(40), nullable=False)
    estimated_total = db.Column(db.Numeric(14, 2))
    currency = db.Column(db.String(3), nullable=False, default='TRY', server_default='TRY')
    needed_by = db.Column(db.Date)
    status = db.Column(db.String(24), nullable=False, default='draft', server_default='draft', index=True)
    purchasing_approver_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    admin_approver_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    decision_reason = db.Column(db.String(1000))
    submitted_at = db.Column(db.DateTime)
    closed_at = db.Column(db.DateTime)
    request_token = db.Column(db.String(36), nullable=False)
    version_id = db.Column(db.Integer, nullable=False, default=1, server_default='1')
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now(), onupdate=db.func.now())
    __mapper_args__ = {'version_id_col': version_id}

    requester = db.relationship('User', foreign_keys=[requester_id], viewonly=True)
    purchasing_approver = db.relationship('User', foreign_keys=[purchasing_approver_id], viewonly=True)
    admin_approver = db.relationship('User', foreign_keys=[admin_approver_id], viewonly=True)
    items = db.relationship('PurchaseRequestItem', back_populates='request', order_by='PurchaseRequestItem.id', viewonly=True)
    decisions = db.relationship('PurchaseDecision', back_populates='request', order_by='PurchaseDecision.id', viewonly=True)

    @property
    def record_no(self):
        return f'SAT-{self.created_at.year}-{self.id:04d}'


class PurchaseRequestItem(db.Model):
    """The current single-line request detail, ready for later multi-line forms."""
    __tablename__ = 'purchase_request_items'
    __table_args__ = (
        db.UniqueConstraint('request_id', 'line_no', name='uq_purchase_item_line'),
        db.CheckConstraint('line_no > 0', name='ck_purchase_item_line'),
        db.CheckConstraint('length(trim(description)) BETWEEN 1 AND 5000', name='ck_purchase_item_description'),
        db.CheckConstraint('quantity > 0', name='ck_purchase_item_quantity'),
        db.CheckConstraint('length(trim(unit)) BETWEEN 1 AND 40', name='ck_purchase_item_unit'),
        db.CheckConstraint('estimated_total IS NULL OR estimated_total >= 0', name='ck_purchase_item_estimate'),
    )

    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('companies.id'), nullable=False, index=True)
    request_id = db.Column(db.Integer, db.ForeignKey('purchase_requests.id'), nullable=False, index=True)
    line_no = db.Column(db.Integer, nullable=False, default=1, server_default='1')
    description = db.Column(db.Text, nullable=False)
    quantity = db.Column(db.Numeric(12, 3), nullable=False)
    unit = db.Column(db.String(40), nullable=False)
    estimated_total = db.Column(db.Numeric(14, 2))
    request = db.relationship('PurchaseRequest', back_populates='items', viewonly=True)


class PurchaseDecision(db.Model):
    __tablename__ = 'purchase_decisions'
    __table_args__ = (
        db.CheckConstraint("action IN ('submitted', 'resubmitted', 'purchasing_approved', 'admin_approved', 'returned', 'rejected')", name='ck_purchase_decision_action'),
        db.CheckConstraint("action NOT IN ('returned', 'rejected') OR (reason IS NOT NULL AND length(trim(reason)) BETWEEN 1 AND 1000)", name='ck_purchase_decision_reason'),
    )

    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('companies.id'), nullable=False, index=True)
    request_id = db.Column(db.Integer, db.ForeignKey('purchase_requests.id'), nullable=False, index=True)
    actor_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    action = db.Column(db.String(24), nullable=False)
    from_status = db.Column(db.String(24), nullable=False)
    to_status = db.Column(db.String(24), nullable=False)
    reason = db.Column(db.String(1000))
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())
    request = db.relationship('PurchaseRequest', back_populates='decisions', viewonly=True)
    actor = db.relationship('User', viewonly=True)


@event.listens_for(PurchaseRequest.__table__, 'after_create')
@event.listens_for(PurchaseRequestItem.__table__, 'after_create')
@event.listens_for(PurchaseDecision.__table__, 'after_create')
def install_guards(table, connection, **kwargs):
    from .purchase_schema import ensure_purchase_guards
    ensure_purchase_guards(connection)
