"""Standalone personnel custody records; equipment lifecycle remains unchanged."""
from alembic import op
import sqlalchemy as sa

revision = '202610080001'
down_revision = '202610070001'
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    if not sa.inspect(connection).has_table('custody_records'):
        op.create_table('custody_records',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('company_id', sa.Integer(), sa.ForeignKey('companies.id'), nullable=False),
            sa.Column('personnel_contact_id', sa.Integer(), sa.ForeignKey('personnel_contacts.id'), nullable=False),
            sa.Column('item_name', sa.String(180), nullable=False),
            sa.Column('serial_no', sa.String(100)), sa.Column('serial_key', sa.String(200)),
            sa.Column('quantity', sa.Integer(), nullable=False, server_default='1'),
            sa.Column('assigned_date', sa.Date(), nullable=False),
            sa.Column('expected_return_date', sa.Date()), sa.Column('returned_date', sa.Date()),
            sa.Column('notes', sa.Text()), sa.Column('return_note', sa.Text()),
            sa.Column('created_by_user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
            sa.Column('returned_by_user_id', sa.Integer(), sa.ForeignKey('users.id')),
            sa.Column('request_token', sa.String(36), nullable=False),
            sa.Column('version_id', sa.Integer(), nullable=False, server_default='1'),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint('company_id', 'request_token', name='uq_custody_request'),
            sa.CheckConstraint('length(trim(item_name)) BETWEEN 1 AND 180', name='ck_custody_name'),
            sa.CheckConstraint('quantity BETWEEN 1 AND 9999', name='ck_custody_quantity'),
            sa.CheckConstraint('serial_key IS NULL OR quantity = 1', name='ck_custody_serial_quantity'),
            sa.CheckConstraint('expected_return_date IS NULL OR expected_return_date >= assigned_date', name='ck_custody_due'),
            sa.CheckConstraint('returned_date IS NULL OR returned_date >= assigned_date', name='ck_custody_return_date'),
            sa.CheckConstraint('(returned_date IS NULL AND returned_by_user_id IS NULL) OR (returned_date IS NOT NULL AND returned_by_user_id IS NOT NULL)', name='ck_custody_return_actor'),
            sa.CheckConstraint('version_id > 0', name='ck_custody_version'),
        )
    indexes = {i['name'] for i in sa.inspect(connection).get_indexes('custody_records')}
    for column in ('company_id', 'personnel_contact_id', 'returned_date'):
        name = f'ix_custody_records_{column}'
        if name not in indexes:
            op.create_index(name, 'custody_records', [column])
    if 'uq_custody_open_serial' not in indexes:
        op.create_index('uq_custody_open_serial', 'custody_records', ['company_id', 'serial_key'], unique=True,
                        sqlite_where=sa.text('returned_date IS NULL AND serial_key IS NOT NULL'),
                        postgresql_where=sa.text('returned_date IS NULL AND serial_key IS NOT NULL'))
    from app.custody_schema import ensure_custody_guards
    ensure_custody_guards(connection)


def downgrade():
    from app.custody_schema import drop_custody_guards
    connection = op.get_bind()
    drop_custody_guards(connection)
    if sa.inspect(connection).has_table('custody_records'):
        op.drop_table('custody_records')
