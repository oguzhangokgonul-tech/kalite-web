from sqlalchemy import event, text
from .extensions import db


def custody_today():
    from .notification_policy import local_now
    return local_now().date()


class CustodyRecord(db.Model):
    __tablename__ = 'custody_records'
    __table_args__ = (
        db.UniqueConstraint('company_id', 'request_token', name='uq_custody_request'),
        db.CheckConstraint('length(trim(item_name)) BETWEEN 1 AND 180', name='ck_custody_name'),
        db.CheckConstraint('quantity BETWEEN 1 AND 9999', name='ck_custody_quantity'),
        db.CheckConstraint('serial_key IS NULL OR quantity = 1', name='ck_custody_serial_quantity'),
        db.CheckConstraint('expected_return_date IS NULL OR expected_return_date >= assigned_date', name='ck_custody_due'),
        db.CheckConstraint('returned_date IS NULL OR returned_date >= assigned_date', name='ck_custody_return_date'),
        db.CheckConstraint('(returned_date IS NULL AND returned_by_user_id IS NULL) OR (returned_date IS NOT NULL AND returned_by_user_id IS NOT NULL)', name='ck_custody_return_actor'),
        db.CheckConstraint('version_id > 0', name='ck_custody_version'),
        db.Index('uq_custody_open_serial', 'company_id', 'serial_key', unique=True,
                 sqlite_where=text('returned_date IS NULL AND serial_key IS NOT NULL'),
                 postgresql_where=text('returned_date IS NULL AND serial_key IS NOT NULL')),
    )
    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('companies.id'), nullable=False, index=True)
    personnel_contact_id = db.Column(db.Integer, db.ForeignKey('personnel_contacts.id'), nullable=False, index=True)
    item_name = db.Column(db.String(180), nullable=False)
    serial_no = db.Column(db.String(100))
    serial_key = db.Column(db.String(200))
    quantity = db.Column(db.Integer, nullable=False, default=1, server_default='1')
    assigned_date = db.Column(db.Date, nullable=False)
    expected_return_date = db.Column(db.Date)
    returned_date = db.Column(db.Date, index=True)
    notes = db.Column(db.Text)
    return_note = db.Column(db.Text)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    returned_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    request_token = db.Column(db.String(36), nullable=False)
    version_id = db.Column(db.Integer, nullable=False, default=1, server_default='1')
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now(), onupdate=db.func.now())
    __mapper_args__ = {'version_id_col': version_id}
    personnel = db.relationship('PersonnelContact', primaryjoin='and_(CustodyRecord.personnel_contact_id == PersonnelContact.id, CustodyRecord.company_id == PersonnelContact.company_id)')

    @property
    def record_no(self):
        return f'ZMT-{self.created_at.year if self.created_at else custody_today().year}-{self.id:04d}'

    @property
    def is_overdue(self):
        return bool(not self.returned_date and self.expected_return_date and self.expected_return_date < custody_today())


@event.listens_for(CustodyRecord.__table__, 'after_create')
def install_guards(table, connection, **kwargs):
    from .custody_schema import ensure_custody_guards
    ensure_custody_guards(connection)


@event.listens_for(CustodyRecord.__table__, 'before_drop')
def remove_guards(table, connection, **kwargs):
    from .custody_schema import drop_custody_guards
    drop_custody_guards(connection)
