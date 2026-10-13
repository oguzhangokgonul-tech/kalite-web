from sqlalchemy import event

from .extensions import db


def handover_today():
    from .notification_policy import local_now
    return local_now().date()


class ShiftHandover(db.Model):
    __tablename__ = 'shift_handovers'
    __table_args__ = (
        db.UniqueConstraint('company_id', 'request_token', name='uq_shift_handover_request'),
        db.CheckConstraint("status IN ('draft', 'sent', 'received', 'cancelled')", name='ck_shift_handover_status'),
        db.CheckConstraint('version_id > 0', name='ck_shift_handover_version'),
        db.CheckConstraint('length(request_token) = 36', name='ck_shift_handover_token'),
        db.CheckConstraint('length(trim(shift_name)) BETWEEN 1 AND 80', name='ck_shift_handover_shift'),
        db.CheckConstraint('length(trim(title)) BETWEEN 1 AND 180', name='ck_shift_handover_title'),
        db.CheckConstraint('length(trim(summary)) BETWEEN 1 AND 5000', name='ck_shift_handover_summary'),
        db.CheckConstraint('area IS NULL OR length(area) <= 120', name='ck_shift_handover_area'),
        *(db.CheckConstraint(f'{field} IS NULL OR length({field}) <= 5000', name=f'ck_shift_handover_{field}')
          for field in ('pending_work', 'safety_notes', 'quality_notes', 'equipment_notes')),
        db.CheckConstraint("(status = 'draft' AND sent_at IS NULL AND sent_by_user_id IS NULL AND received_at IS NULL AND received_by_user_id IS NULL) OR "
                           "(status = 'sent' AND sent_at IS NOT NULL AND sent_by_user_id IS NOT NULL AND received_at IS NULL AND received_by_user_id IS NULL) OR "
                           "(status = 'received' AND sent_at IS NOT NULL AND sent_by_user_id IS NOT NULL AND received_at IS NOT NULL AND received_by_user_id IS NOT NULL AND received_by_user_id = receiver_user_id) OR "
                           "(status = 'cancelled' AND received_at IS NULL AND received_by_user_id IS NULL AND ((sent_at IS NULL AND sent_by_user_id IS NULL) OR (sent_at IS NOT NULL AND sent_by_user_id IS NOT NULL)))",
                           name='ck_shift_handover_lifecycle'),
        db.CheckConstraint("(status = 'cancelled' AND cancelled_at IS NOT NULL AND cancelled_by_user_id IS NOT NULL AND cancel_reason IS NOT NULL AND length(trim(cancel_reason)) BETWEEN 1 AND 1000) OR (status != 'cancelled' AND cancelled_at IS NULL AND cancelled_by_user_id IS NULL AND cancel_reason IS NULL)", name='ck_shift_handover_cancel'),
        db.CheckConstraint('(archived_at IS NULL AND archived_by_user_id IS NULL) OR (archived_at IS NOT NULL AND archived_by_user_id IS NOT NULL)', name='ck_shift_handover_archive'),
        db.CheckConstraint('received_at IS NULL OR received_at >= sent_at', name='ck_shift_handover_received_time'),
    )
    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('companies.id'), nullable=False, index=True)
    handover_date = db.Column(db.Date, nullable=False, index=True)
    shift_name = db.Column(db.String(80), nullable=False)
    department_id = db.Column(db.Integer, db.ForeignKey('company_departments.id'), nullable=False, index=True)
    area = db.Column(db.String(120))
    title = db.Column(db.String(180), nullable=False)
    summary = db.Column(db.Text, nullable=False)
    pending_work = db.Column(db.Text)
    safety_notes = db.Column(db.Text)
    quality_notes = db.Column(db.Text)
    equipment_notes = db.Column(db.Text)
    sender_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    receiver_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    status = db.Column(db.String(16), nullable=False, default='draft', server_default='draft', index=True)
    sent_at = db.Column(db.DateTime)
    sent_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    received_at = db.Column(db.DateTime)
    received_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    archived_at = db.Column(db.DateTime, index=True)
    archived_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    cancelled_at = db.Column(db.DateTime)
    cancelled_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    cancel_reason = db.Column(db.String(1000))
    request_token = db.Column(db.String(36), nullable=False)
    version_id = db.Column(db.Integer, nullable=False, default=1, server_default='1')
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now(), onupdate=db.func.now())
    __mapper_args__ = {'version_id_col': version_id}
    department = db.relationship('CompanyDepartment', viewonly=True)
    sender = db.relationship('User', foreign_keys=[sender_user_id], viewonly=True)
    receiver = db.relationship('User', foreign_keys=[receiver_user_id], viewonly=True)

    @property
    def record_no(self):
        return f'VDT-{self.created_at.year}-{self.id:04d}'


@event.listens_for(ShiftHandover.__table__, 'after_create')
def install_guards(table, connection, **kwargs):
    from .shift_handover_schema import ensure_shift_handover_guards
    ensure_shift_handover_guards(connection)


@event.listens_for(ShiftHandover.__table__, 'before_drop')
def remove_guards(table, connection, **kwargs):
    from .shift_handover_schema import drop_shift_handover_guards
    drop_shift_handover_guards(connection)
