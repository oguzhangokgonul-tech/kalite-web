"""Link quality objectives to plans without changing legacy schemas or records."""
from alembic import op
import sqlalchemy as sa


revision = '202610090001'
down_revision = '202610080001'
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    if not sa.inspect(connection).has_table('objective_plan_links'):
        op.create_table(
            'objective_plan_links',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('company_id', sa.Integer(), sa.ForeignKey('companies.id'), nullable=False),
            sa.Column('objective_id', sa.Integer(), sa.ForeignKey('quality_objectives.id'), nullable=False),
            sa.Column('kind', sa.String(10), nullable=False),
            sa.Column('project_id', sa.Integer(), sa.ForeignKey('project_records.id')),
            sa.Column('action_id', sa.Integer(), sa.ForeignKey('actions.id')),
            sa.Column('created_by_user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint('company_id', 'objective_id', 'kind', name='uq_objective_plan_links_objective_kind'),
            sa.UniqueConstraint('project_id', name='uq_objective_plan_links_project'),
            sa.UniqueConstraint('action_id', name='uq_objective_plan_links_action'),
            sa.CheckConstraint("kind IN ('project', 'action')", name='ck_objective_plan_links_kind'),
            sa.CheckConstraint(
                "(kind = 'project' AND project_id IS NOT NULL AND action_id IS NULL) OR "
                "(kind = 'action' AND action_id IS NOT NULL AND project_id IS NULL)",
                name='ck_objective_plan_links_target'),
        )
    indexes = {item['name'] for item in sa.inspect(connection).get_indexes('objective_plan_links')}
    for column in ('company_id', 'objective_id'):
        name = f'ix_objective_plan_links_{column}'
        if name not in indexes:
            op.create_index(name, 'objective_plan_links', [column])
    from app.objective_plan_schema import ensure_objective_plan_sqlite_guards
    ensure_objective_plan_sqlite_guards(connection)


def downgrade():
    from app.objective_plan_schema import drop_objective_plan_sqlite_guards
    connection = op.get_bind()
    drop_objective_plan_sqlite_guards(connection)
    if sa.inspect(connection).has_table('objective_plan_links'):
        op.drop_table('objective_plan_links')
