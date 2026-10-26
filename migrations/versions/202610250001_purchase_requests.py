"""Tenant-owned purchase requests and decision history."""
from alembic import op
import sqlalchemy as sa

revision = '202610250001'
down_revision = '202610250003'
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    if not sa.inspect(connection).has_table('purchase_requests'):
        op.create_table(
            'purchase_requests',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('company_id', sa.Integer(), sa.ForeignKey('companies.id'), nullable=False),
            sa.Column('requester_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
            sa.Column('kind', sa.String(16), nullable=False),
            sa.Column('title', sa.String(180), nullable=False),
            sa.Column('description', sa.Text(), nullable=False),
            sa.Column('justification', sa.Text(), nullable=False),
            sa.Column('quantity', sa.Numeric(12, 3), nullable=False),
            sa.Column('unit', sa.String(40), nullable=False),
            sa.Column('estimated_total', sa.Numeric(14, 2)),
            sa.Column('currency', sa.String(3), nullable=False, server_default='TRY'),
            sa.Column('needed_by', sa.Date()),
            sa.Column('status', sa.String(24), nullable=False, server_default='draft'),
            sa.Column('purchasing_approver_id', sa.Integer(), sa.ForeignKey('users.id')),
            sa.Column('admin_approver_id', sa.Integer(), sa.ForeignKey('users.id')),
            sa.Column('decision_reason', sa.String(1000)),
            sa.Column('submitted_at', sa.DateTime()),
            sa.Column('closed_at', sa.DateTime()),
            sa.Column('request_token', sa.String(36), nullable=False),
            sa.Column('version_id', sa.Integer(), nullable=False, server_default='1'),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint('company_id', 'request_token', name='uq_purchase_request_token'),
            sa.CheckConstraint("kind IN ('material', 'service')", name='ck_purchase_kind'),
            sa.CheckConstraint("status IN ('draft', 'pending_purchase', 'pending_admin', 'returned', 'rejected', 'closed')", name='ck_purchase_status'),
            sa.CheckConstraint('version_id > 0', name='ck_purchase_version'),
            sa.CheckConstraint('length(request_token) = 36', name='ck_purchase_token'),
            sa.CheckConstraint('length(trim(title)) BETWEEN 1 AND 180', name='ck_purchase_title'),
            sa.CheckConstraint('length(trim(description)) BETWEEN 1 AND 5000', name='ck_purchase_description'),
            sa.CheckConstraint('length(trim(justification)) BETWEEN 1 AND 3000', name='ck_purchase_justification'),
            sa.CheckConstraint('length(trim(unit)) BETWEEN 1 AND 40', name='ck_purchase_unit'),
            sa.CheckConstraint('quantity > 0', name='ck_purchase_quantity'),
            sa.CheckConstraint('estimated_total IS NULL OR estimated_total >= 0', name='ck_purchase_estimate'),
            sa.CheckConstraint("currency IN ('TRY', 'USD', 'EUR')", name='ck_purchase_currency'),
            sa.CheckConstraint('purchasing_approver_id IS NULL OR purchasing_approver_id != requester_id', name='ck_purchase_distinct_first'),
            sa.CheckConstraint('admin_approver_id IS NULL OR (admin_approver_id != requester_id AND admin_approver_id != purchasing_approver_id)', name='ck_purchase_distinct_admin'),
            sa.CheckConstraint("status NOT IN ('pending_admin', 'closed') OR purchasing_approver_id IS NOT NULL", name='ck_purchase_first_required'),
            sa.CheckConstraint("status != 'closed' OR (admin_approver_id IS NOT NULL AND closed_at IS NOT NULL)", name='ck_purchase_closed'),
            sa.CheckConstraint("status = 'closed' OR (admin_approver_id IS NULL AND closed_at IS NULL)", name='ck_purchase_not_closed'),
            sa.CheckConstraint("status NOT IN ('returned', 'rejected') OR (decision_reason IS NOT NULL AND length(trim(decision_reason)) BETWEEN 1 AND 1000)", name='ck_purchase_reason'),
        )
    indexes = {item['name'] for item in sa.inspect(connection).get_indexes('purchase_requests')}
    for column in ('company_id', 'requester_id', 'status'):
        name = f'ix_purchase_requests_{column}'
        if name not in indexes:
            op.create_index(name, 'purchase_requests', [column])
    if not sa.inspect(connection).has_table('purchase_request_items'):
        op.create_table(
            'purchase_request_items',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('company_id', sa.Integer(), sa.ForeignKey('companies.id'), nullable=False),
            sa.Column('request_id', sa.Integer(), sa.ForeignKey('purchase_requests.id'), nullable=False),
            sa.Column('line_no', sa.Integer(), nullable=False, server_default='1'),
            sa.Column('description', sa.Text(), nullable=False),
            sa.Column('quantity', sa.Numeric(12, 3), nullable=False),
            sa.Column('unit', sa.String(40), nullable=False),
            sa.Column('estimated_total', sa.Numeric(14, 2)),
            sa.UniqueConstraint('request_id', 'line_no', name='uq_purchase_item_line'),
            sa.CheckConstraint('line_no > 0', name='ck_purchase_item_line'),
            sa.CheckConstraint('length(trim(description)) BETWEEN 1 AND 5000', name='ck_purchase_item_description'),
            sa.CheckConstraint('quantity > 0', name='ck_purchase_item_quantity'),
            sa.CheckConstraint('length(trim(unit)) BETWEEN 1 AND 40', name='ck_purchase_item_unit'),
            sa.CheckConstraint('estimated_total IS NULL OR estimated_total >= 0', name='ck_purchase_item_estimate'),
        )
    indexes = {item['name'] for item in sa.inspect(connection).get_indexes('purchase_request_items')}
    for column in ('company_id', 'request_id'):
        name = f'ix_purchase_request_items_{column}'
        if name not in indexes:
            op.create_index(name, 'purchase_request_items', [column])
    if not sa.inspect(connection).has_table('purchase_decisions'):
        op.create_table(
            'purchase_decisions',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('company_id', sa.Integer(), sa.ForeignKey('companies.id'), nullable=False),
            sa.Column('request_id', sa.Integer(), sa.ForeignKey('purchase_requests.id'), nullable=False),
            sa.Column('actor_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
            sa.Column('action', sa.String(24), nullable=False),
            sa.Column('from_status', sa.String(24), nullable=False),
            sa.Column('to_status', sa.String(24), nullable=False),
            sa.Column('reason', sa.String(1000)),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.CheckConstraint("action IN ('submitted', 'resubmitted', 'purchasing_approved', 'admin_approved', 'returned', 'rejected')", name='ck_purchase_decision_action'),
            sa.CheckConstraint("action NOT IN ('returned', 'rejected') OR (reason IS NOT NULL AND length(trim(reason)) BETWEEN 1 AND 1000)", name='ck_purchase_decision_reason'),
        )
    indexes = {item['name'] for item in sa.inspect(connection).get_indexes('purchase_decisions')}
    for column in ('company_id', 'request_id'):
        name = f'ix_purchase_decisions_{column}'
        if name not in indexes:
            op.create_index(name, 'purchase_decisions', [column])
    from app.purchase_schema import ensure_purchase_guards
    ensure_purchase_guards(connection)


def downgrade():
    from app.purchase_schema import drop_purchase_guards
    connection = op.get_bind()
    for table in ('purchase_decisions', 'purchase_request_items', 'purchase_requests'):
        if sa.inspect(connection).has_table(table) and connection.execute(
            sa.text(f'SELECT 1 FROM {table} LIMIT 1')
        ).first():
            raise RuntimeError('Satın alma kayıtları varken şema geri alınamaz; önce doğrulanmış yedek ve veri taşıma planı gerekir.')
    drop_purchase_guards(connection)
    if sa.inspect(connection).has_table('purchase_decisions'):
        op.drop_table('purchase_decisions')
    if sa.inspect(connection).has_table('purchase_request_items'):
        op.drop_table('purchase_request_items')
    if sa.inspect(connection).has_table('purchase_requests'):
        op.drop_table('purchase_requests')
