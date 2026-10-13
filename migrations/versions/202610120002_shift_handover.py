"""Standalone shift handover records and SQLite tenant guards."""
from alembic import op
import sqlalchemy as sa

revision = '202610120002'
down_revision = '202610120001'
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    if not sa.inspect(connection).has_table('shift_handovers'):
        op.create_table('shift_handovers',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('company_id', sa.Integer(), sa.ForeignKey('companies.id'), nullable=False),
            sa.Column('handover_date', sa.Date(), nullable=False),
            sa.Column('shift_name', sa.String(80), nullable=False),
            sa.Column('department_id', sa.Integer(), sa.ForeignKey('company_departments.id'), nullable=False),
            sa.Column('area', sa.String(120)),
            sa.Column('title', sa.String(180), nullable=False),
            sa.Column('summary', sa.Text(), nullable=False),
            *(sa.Column(field, sa.Text()) for field in ('pending_work', 'safety_notes', 'quality_notes', 'equipment_notes')),
            sa.Column('sender_user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
            sa.Column('receiver_user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
            sa.Column('status', sa.String(16), nullable=False, server_default='draft'),
            sa.Column('sent_at', sa.DateTime()),
            sa.Column('sent_by_user_id', sa.Integer(), sa.ForeignKey('users.id')),
            sa.Column('received_at', sa.DateTime()),
            sa.Column('received_by_user_id', sa.Integer(), sa.ForeignKey('users.id')),
            sa.Column('archived_at', sa.DateTime()),
            sa.Column('archived_by_user_id', sa.Integer(), sa.ForeignKey('users.id')),
            sa.Column('cancelled_at', sa.DateTime()),
            sa.Column('cancelled_by_user_id', sa.Integer(), sa.ForeignKey('users.id')),
            sa.Column('cancel_reason', sa.String(1000)),
            sa.Column('request_token', sa.String(36), nullable=False),
            sa.Column('version_id', sa.Integer(), nullable=False, server_default='1'),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint('company_id', 'request_token', name='uq_shift_handover_request'),
            sa.CheckConstraint("status IN ('draft', 'sent', 'received', 'cancelled')", name='ck_shift_handover_status'),
            sa.CheckConstraint('version_id > 0', name='ck_shift_handover_version'),
            sa.CheckConstraint('length(request_token) = 36', name='ck_shift_handover_token'),
            sa.CheckConstraint('length(trim(shift_name)) BETWEEN 1 AND 80', name='ck_shift_handover_shift'),
            sa.CheckConstraint('length(trim(title)) BETWEEN 1 AND 180', name='ck_shift_handover_title'),
            sa.CheckConstraint('length(trim(summary)) BETWEEN 1 AND 5000', name='ck_shift_handover_summary'),
            sa.CheckConstraint('area IS NULL OR length(area) <= 120', name='ck_shift_handover_area'),
            *(sa.CheckConstraint(f'{field} IS NULL OR length({field}) <= 5000', name=f'ck_shift_handover_{field}')
              for field in ('pending_work', 'safety_notes', 'quality_notes', 'equipment_notes')),
            sa.CheckConstraint("(status = 'draft' AND sent_at IS NULL AND sent_by_user_id IS NULL AND received_at IS NULL AND received_by_user_id IS NULL) OR "
                               "(status = 'sent' AND sent_at IS NOT NULL AND sent_by_user_id IS NOT NULL AND received_at IS NULL AND received_by_user_id IS NULL) OR "
                               "(status = 'received' AND sent_at IS NOT NULL AND sent_by_user_id IS NOT NULL AND received_at IS NOT NULL AND received_by_user_id IS NOT NULL AND received_by_user_id = receiver_user_id) OR "
                               "(status = 'cancelled' AND received_at IS NULL AND received_by_user_id IS NULL AND ((sent_at IS NULL AND sent_by_user_id IS NULL) OR (sent_at IS NOT NULL AND sent_by_user_id IS NOT NULL)))",
                               name='ck_shift_handover_lifecycle'),
            sa.CheckConstraint("(status = 'cancelled' AND cancelled_at IS NOT NULL AND cancelled_by_user_id IS NOT NULL AND cancel_reason IS NOT NULL AND length(trim(cancel_reason)) BETWEEN 1 AND 1000) OR (status != 'cancelled' AND cancelled_at IS NULL AND cancelled_by_user_id IS NULL AND cancel_reason IS NULL)", name='ck_shift_handover_cancel'),
            sa.CheckConstraint('(archived_at IS NULL AND archived_by_user_id IS NULL) OR (archived_at IS NOT NULL AND archived_by_user_id IS NOT NULL)', name='ck_shift_handover_archive'),
            sa.CheckConstraint('received_at IS NULL OR received_at >= sent_at', name='ck_shift_handover_received_time'),
        )
    indexes = {index['name'] for index in sa.inspect(connection).get_indexes('shift_handovers')}
    for column in ('company_id', 'handover_date', 'department_id', 'sender_user_id', 'receiver_user_id', 'status', 'archived_at'):
        name = f'ix_shift_handovers_{column}'
        if name not in indexes:
            op.create_index(name, 'shift_handovers', [column])
    from app.shift_handover_schema import ensure_shift_handover_guards
    ensure_shift_handover_guards(connection)


def downgrade():
    from app.shift_handover_schema import drop_shift_handover_guards
    connection = op.get_bind()
    drop_shift_handover_guards(connection)
    if sa.inspect(connection).has_table('shift_handovers'):
        op.drop_table('shift_handovers')
