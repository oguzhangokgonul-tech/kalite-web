"""Freeze formerly runtime-only schema additions without replacing live tables."""
from alembic import op
import sqlalchemy as sa

revision = "202609150001"
down_revision = "202609120004"
branch_labels = None
depends_on = None


def _create_table(name, *columns, **kwargs):
    if name not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table(name, *columns, **kwargs)


def _add_column(table, column):
    existing = {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}
    if column.name not in existing:
        op.add_column(table, column)


def _create_index(name, table, columns, **kwargs):
    existing = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table)}
    if name not in existing:
        op.create_index(name, table, columns, **kwargs)


def upgrade():
    # Frozen additions; never import application models into historical migrations.
    _create_table('company_departments',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('company_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=160), nullable=False),
    sa.Column('sort_order', sa.Integer(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('company_id', 'name', name='uq_company_departments_company_name')
    )
    _create_index(op.f('ix_company_departments_company_id'), 'company_departments', ['company_id'], unique=False)
    _create_table('pilot_programs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('company_id', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=40), nullable=False),
    sa.Column('contact_name', sa.String(length=160), nullable=True),
    sa.Column('contact_phone', sa.String(length=80), nullable=True),
    sa.Column('contact_email', sa.String(length=255), nullable=True),
    sa.Column('start_date', sa.Date(), nullable=True),
    sa.Column('end_date', sa.Date(), nullable=True),
    sa.Column('target_modules', sa.Text(), nullable=True),
    sa.Column('success_criteria', sa.Text(), nullable=True),
    sa.Column('feedback_summary', sa.Text(), nullable=True),
    sa.Column('sales_blocker', sa.Boolean(), nullable=False),
    sa.Column('sales_blocker_note', sa.Text(), nullable=True),
    sa.Column('next_follow_up_date', sa.Date(), nullable=True),
    sa.Column('result', sa.String(length=160), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    _create_index(op.f('ix_pilot_programs_company_id'), 'pilot_programs', ['company_id'], unique=False)
    _create_index(op.f('ix_pilot_programs_next_follow_up_date'), 'pilot_programs', ['next_follow_up_date'], unique=False)
    _create_index(op.f('ix_pilot_programs_status'), 'pilot_programs', ['status'], unique=False)
    _create_table('audit_logs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('company_id', sa.Integer(), nullable=True),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('entity_type', sa.String(length=120), nullable=False),
    sa.Column('entity_id', sa.String(length=80), nullable=True),
    sa.Column('action', sa.String(length=40), nullable=False),
    sa.Column('summary', sa.String(length=255), nullable=True),
    sa.Column('old_values', sa.Text(), nullable=True),
    sa.Column('new_values', sa.Text(), nullable=True),
    sa.Column('ip_address', sa.String(length=80), nullable=True),
    sa.Column('user_agent', sa.String(length=255), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    _create_index(op.f('ix_audit_logs_action'), 'audit_logs', ['action'], unique=False)
    _create_index(op.f('ix_audit_logs_company_id'), 'audit_logs', ['company_id'], unique=False)
    _create_index(op.f('ix_audit_logs_created_at'), 'audit_logs', ['created_at'], unique=False)
    _create_index(op.f('ix_audit_logs_entity_id'), 'audit_logs', ['entity_id'], unique=False)
    _create_index(op.f('ix_audit_logs_entity_type'), 'audit_logs', ['entity_type'], unique=False)
    _create_index(op.f('ix_audit_logs_user_id'), 'audit_logs', ['user_id'], unique=False)
    _create_table('personnel_contacts',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('company_id', sa.Integer(), nullable=True),
    sa.Column('full_name', sa.String(length=180), nullable=False),
    sa.Column('phone', sa.String(length=60), nullable=True),
    sa.Column('department', sa.String(length=160), nullable=True),
    sa.Column('title', sa.String(length=160), nullable=True),
    sa.Column('email', sa.String(length=255), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_by_user_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('company_id', 'full_name', 'phone', name='uq_personnel_contacts_company_name_phone')
    )
    _create_index(op.f('ix_personnel_contacts_company_id'), 'personnel_contacts', ['company_id'], unique=False)
    _create_table('supplier_records',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('company_id', sa.Integer(), nullable=True),
    sa.Column('supplier_no', sa.String(length=30), nullable=False),
    sa.Column('name', sa.String(length=180), nullable=False),
    sa.Column('product_group', sa.String(length=160), nullable=True),
    sa.Column('department', sa.String(length=80), nullable=True),
    sa.Column('contact_person', sa.String(length=160), nullable=True),
    sa.Column('phone', sa.String(length=80), nullable=True),
    sa.Column('email', sa.String(length=160), nullable=True),
    sa.Column('status', sa.String(length=40), nullable=False),
    sa.Column('last_score', sa.Integer(), nullable=True),
    sa.Column('last_evaluation_date', sa.Date(), nullable=True),
    sa.Column('next_evaluation_date', sa.Date(), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_by_user_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('company_id', 'supplier_no', name='uq_supplier_records_company_supplier_no')
    )
    _create_index(op.f('ix_supplier_records_company_id'), 'supplier_records', ['company_id'], unique=False)
    _create_table('supplier_evaluations',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('company_id', sa.Integer(), nullable=True),
    sa.Column('supplier_id', sa.Integer(), nullable=False),
    sa.Column('evaluation_date', sa.Date(), nullable=False),
    sa.Column('evaluated_by_user_id', sa.Integer(), nullable=True),
    sa.Column('quality_score', sa.Integer(), nullable=False),
    sa.Column('delivery_score', sa.Integer(), nullable=False),
    sa.Column('cost_score', sa.Integer(), nullable=False),
    sa.Column('communication_score', sa.Integer(), nullable=False),
    sa.Column('documentation_score', sa.Integer(), nullable=False),
    sa.Column('nonconformity_score', sa.Integer(), nullable=False),
    sa.Column('total_score', sa.Integer(), nullable=False),
    sa.Column('result_status', sa.String(length=40), nullable=False),
    sa.Column('next_evaluation_date', sa.Date(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.ForeignKeyConstraint(['evaluated_by_user_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['supplier_id'], ['supplier_records.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    _create_index(op.f('ix_supplier_evaluations_company_id'), 'supplier_evaluations', ['company_id'], unique=False)
    _create_index(op.f('ix_supplier_evaluations_evaluated_by_user_id'), 'supplier_evaluations', ['evaluated_by_user_id'], unique=False)
    _create_index(op.f('ix_supplier_evaluations_supplier_id'), 'supplier_evaluations', ['supplier_id'], unique=False)
    _create_table('training_records',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('company_id', sa.Integer(), nullable=True),
    sa.Column('training_no', sa.String(length=30), nullable=False),
    sa.Column('title', sa.String(length=180), nullable=False),
    sa.Column('training_type', sa.String(length=60), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('document_id', sa.Integer(), nullable=True),
    sa.Column('document_revision_no_snapshot', sa.String(length=40), nullable=True),
    sa.Column('planned_date', sa.Date(), nullable=True),
    sa.Column('due_date', sa.Date(), nullable=True),
    sa.Column('instructor_user_id', sa.Integer(), nullable=True),
    sa.Column('status', sa.String(length=40), nullable=False),
    sa.Column('created_by_user_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ),
    sa.ForeignKeyConstraint(['instructor_user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('company_id', 'training_no', name='uq_training_records_company_training_no')
    )
    _create_index(op.f('ix_training_records_company_id'), 'training_records', ['company_id'], unique=False)
    _create_table('management_reviews',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('company_id', sa.Integer(), nullable=True),
    sa.Column('review_no', sa.String(length=30), nullable=False),
    sa.Column('title', sa.String(length=180), nullable=False),
    sa.Column('review_period', sa.String(length=80), nullable=True),
    sa.Column('meeting_date', sa.Date(), nullable=True),
    sa.Column('location', sa.String(length=160), nullable=True),
    sa.Column('status', sa.String(length=40), nullable=False),
    sa.Column('chair_user_id', sa.Integer(), nullable=True),
    sa.Column('recorder_user_id', sa.Integer(), nullable=True),
    sa.Column('participants', sa.Text(), nullable=True),
    sa.Column('agenda', sa.Text(), nullable=True),
    sa.Column('audit_results', sa.Text(), nullable=True),
    sa.Column('customer_feedback', sa.Text(), nullable=True),
    sa.Column('process_performance', sa.Text(), nullable=True),
    sa.Column('nonconformities', sa.Text(), nullable=True),
    sa.Column('corrective_actions', sa.Text(), nullable=True),
    sa.Column('monitoring_results', sa.Text(), nullable=True),
    sa.Column('supplier_performance', sa.Text(), nullable=True),
    sa.Column('resource_needs', sa.Text(), nullable=True),
    sa.Column('risk_opportunities', sa.Text(), nullable=True),
    sa.Column('decisions', sa.Text(), nullable=True),
    sa.Column('outputs', sa.Text(), nullable=True),
    sa.Column('improvement_opportunities', sa.Text(), nullable=True),
    sa.Column('action_id', sa.Integer(), nullable=True),
    sa.Column('created_by_user_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['action_id'], ['actions.id'], ),
    sa.ForeignKeyConstraint(['chair_user_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['recorder_user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('company_id', 'review_no', name='uq_management_reviews_company_review_no')
    )
    _create_index(op.f('ix_management_reviews_company_id'), 'management_reviews', ['company_id'], unique=False)
    _create_table('risk_records',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('company_id', sa.Integer(), nullable=True),
    sa.Column('risk_no', sa.String(length=30), nullable=False),
    sa.Column('title', sa.String(length=180), nullable=False),
    sa.Column('department', sa.String(length=80), nullable=True),
    sa.Column('process', sa.String(length=160), nullable=True),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('cause', sa.Text(), nullable=True),
    sa.Column('consequence', sa.Text(), nullable=True),
    sa.Column('likelihood', sa.Integer(), nullable=False),
    sa.Column('severity', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=40), nullable=False),
    sa.Column('due_date', sa.Date(), nullable=True),
    sa.Column('owner_user_id', sa.Integer(), nullable=True),
    sa.Column('action_id', sa.Integer(), nullable=True),
    sa.Column('dof_id', sa.Integer(), nullable=True),
    sa.Column('created_by_user_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['action_id'], ['actions.id'], ),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['dof_id'], ['dofs.id'], ),
    sa.ForeignKeyConstraint(['owner_user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('company_id', 'risk_no', name='uq_risk_records_company_risk_no')
    )
    _create_index(op.f('ix_risk_records_company_id'), 'risk_records', ['company_id'], unique=False)
    _create_table('training_participants',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('company_id', sa.Integer(), nullable=True),
    sa.Column('training_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('personnel_contact_id', sa.Integer(), nullable=True),
    sa.Column('status', sa.String(length=40), nullable=False),
    sa.Column('read_confirmed_at', sa.DateTime(), nullable=True),
    sa.Column('attended_at', sa.DateTime(), nullable=True),
    sa.Column('score', sa.Numeric(precision=5, scale=2), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.ForeignKeyConstraint(['personnel_contact_id'], ['personnel_contacts.id'], ),
    sa.ForeignKeyConstraint(['training_id'], ['training_records.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    _create_index(op.f('ix_training_participants_company_id'), 'training_participants', ['company_id'], unique=False)
    _create_index(op.f('ix_training_participants_personnel_contact_id'), 'training_participants', ['personnel_contact_id'], unique=False)
    _create_index(op.f('ix_training_participants_training_id'), 'training_participants', ['training_id'], unique=False)
    _create_index(op.f('ix_training_participants_user_id'), 'training_participants', ['user_id'], unique=False)
    _create_table('change_requests',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('company_id', sa.Integer(), nullable=True),
    sa.Column('change_no', sa.String(length=40), nullable=False),
    sa.Column('title', sa.String(length=180), nullable=False),
    sa.Column('change_type', sa.String(length=60), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('scope', sa.Text(), nullable=True),
    sa.Column('department', sa.String(length=80), nullable=True),
    sa.Column('process_name', sa.String(length=160), nullable=True),
    sa.Column('risk_level', sa.String(length=40), nullable=False),
    sa.Column('status', sa.String(length=40), nullable=False),
    sa.Column('planned_date', sa.Date(), nullable=True),
    sa.Column('due_date', sa.Date(), nullable=True),
    sa.Column('effective_date', sa.Date(), nullable=True),
    sa.Column('requester_user_id', sa.Integer(), nullable=True),
    sa.Column('responsible_user_id', sa.Integer(), nullable=True),
    sa.Column('approver_user_id', sa.Integer(), nullable=True),
    sa.Column('document_id', sa.Integer(), nullable=True),
    sa.Column('action_id', sa.Integer(), nullable=True),
    sa.Column('risk_id', sa.Integer(), nullable=True),
    sa.Column('dof_id', sa.Integer(), nullable=True),
    sa.Column('approval_note', sa.Text(), nullable=True),
    sa.Column('implementation_note', sa.Text(), nullable=True),
    sa.Column('effectiveness_note', sa.Text(), nullable=True),
    sa.Column('created_by_user_id', sa.Integer(), nullable=True),
    sa.Column('archived_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['action_id'], ['actions.id'], ),
    sa.ForeignKeyConstraint(['approver_user_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ),
    sa.ForeignKeyConstraint(['dof_id'], ['dofs.id'], ),
    sa.ForeignKeyConstraint(['requester_user_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['responsible_user_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['risk_id'], ['risk_records.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('company_id', 'change_no', name='uq_change_requests_company_change_no')
    )
    _create_index(op.f('ix_change_requests_change_no'), 'change_requests', ['change_no'], unique=False)
    _create_index(op.f('ix_change_requests_company_id'), 'change_requests', ['company_id'], unique=False)
    _create_table('deviation_records',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('company_id', sa.Integer(), nullable=True),
    sa.Column('deviation_no', sa.String(length=40), nullable=False),
    sa.Column('record_type', sa.String(length=80), nullable=False),
    sa.Column('source_type', sa.String(length=80), nullable=True),
    sa.Column('title', sa.String(length=180), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('detected_date', sa.Date(), nullable=False),
    sa.Column('department', sa.String(length=80), nullable=True),
    sa.Column('process_name', sa.String(length=160), nullable=True),
    sa.Column('product_name', sa.String(length=180), nullable=True),
    sa.Column('batch_no', sa.String(length=120), nullable=True),
    sa.Column('quantity', sa.String(length=80), nullable=True),
    sa.Column('severity', sa.String(length=40), nullable=False),
    sa.Column('containment_action', sa.Text(), nullable=True),
    sa.Column('quarantine_location', sa.String(length=180), nullable=True),
    sa.Column('disposition', sa.String(length=80), nullable=True),
    sa.Column('disposition_note', sa.Text(), nullable=True),
    sa.Column('root_cause', sa.Text(), nullable=True),
    sa.Column('corrective_action', sa.Text(), nullable=True),
    sa.Column('due_date', sa.Date(), nullable=True),
    sa.Column('closed_at', sa.Date(), nullable=True),
    sa.Column('status', sa.String(length=40), nullable=False),
    sa.Column('responsible_user_id', sa.Integer(), nullable=True),
    sa.Column('approver_user_id', sa.Integer(), nullable=True),
    sa.Column('document_id', sa.Integer(), nullable=True),
    sa.Column('action_id', sa.Integer(), nullable=True),
    sa.Column('risk_id', sa.Integer(), nullable=True),
    sa.Column('dof_id', sa.Integer(), nullable=True),
    sa.Column('created_by_user_id', sa.Integer(), nullable=True),
    sa.Column('archived_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['action_id'], ['actions.id'], ),
    sa.ForeignKeyConstraint(['approver_user_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ),
    sa.ForeignKeyConstraint(['dof_id'], ['dofs.id'], ),
    sa.ForeignKeyConstraint(['responsible_user_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['risk_id'], ['risk_records.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('company_id', 'deviation_no', name='uq_deviation_records_company_deviation_no')
    )
    _create_index(op.f('ix_deviation_records_company_id'), 'deviation_records', ['company_id'], unique=False)
    _create_index(op.f('ix_deviation_records_deviation_no'), 'deviation_records', ['deviation_no'], unique=False)
    _create_table('document_acknowledgements',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('company_id', sa.Integer(), nullable=True),
    sa.Column('document_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('training_participant_id', sa.Integer(), nullable=True),
    sa.Column('document_code_snapshot', sa.String(length=80), nullable=False),
    sa.Column('document_title_snapshot', sa.String(length=200), nullable=False),
    sa.Column('revision_no_snapshot', sa.String(length=40), nullable=False),
    sa.Column('acknowledged_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    sa.Column('ip_address', sa.String(length=80), nullable=True),
    sa.Column('user_agent', sa.String(length=255), nullable=True),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ),
    sa.ForeignKeyConstraint(['training_participant_id'], ['training_participants.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('company_id', 'document_id', 'user_id', 'revision_no_snapshot', name='uq_document_acknowledgements_company_doc_user_revision')
    )
    _create_index(op.f('ix_document_acknowledgements_company_id'), 'document_acknowledgements', ['company_id'], unique=False)
    _create_index(op.f('ix_document_acknowledgements_document_id'), 'document_acknowledgements', ['document_id'], unique=False)
    _create_index(op.f('ix_document_acknowledgements_training_participant_id'), 'document_acknowledgements', ['training_participant_id'], unique=False)
    _create_index(op.f('ix_document_acknowledgements_user_id'), 'document_acknowledgements', ['user_id'], unique=False)
    _create_table('process_records',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('company_id', sa.Integer(), nullable=True),
    sa.Column('process_no', sa.String(length=40), nullable=False),
    sa.Column('title', sa.String(length=180), nullable=False),
    sa.Column('category', sa.String(length=60), nullable=False),
    sa.Column('owner_user_id', sa.Integer(), nullable=True),
    sa.Column('department', sa.String(length=80), nullable=True),
    sa.Column('purpose', sa.Text(), nullable=True),
    sa.Column('scope', sa.Text(), nullable=True),
    sa.Column('inputs', sa.Text(), nullable=True),
    sa.Column('outputs', sa.Text(), nullable=True),
    sa.Column('suppliers', sa.Text(), nullable=True),
    sa.Column('customers', sa.Text(), nullable=True),
    sa.Column('kpi', sa.Text(), nullable=True),
    sa.Column('review_frequency', sa.String(length=80), nullable=True),
    sa.Column('next_review_date', sa.Date(), nullable=True),
    sa.Column('related_document_id', sa.Integer(), nullable=True),
    sa.Column('risk_id', sa.Integer(), nullable=True),
    sa.Column('action_id', sa.Integer(), nullable=True),
    sa.Column('status', sa.String(length=40), nullable=False),
    sa.Column('created_by_user_id', sa.Integer(), nullable=True),
    sa.Column('archived_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['action_id'], ['actions.id'], ),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['owner_user_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['related_document_id'], ['documents.id'], ),
    sa.ForeignKeyConstraint(['risk_id'], ['risk_records.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('company_id', 'process_no', name='uq_process_records_company_process_no')
    )
    _create_index(op.f('ix_process_records_company_id'), 'process_records', ['company_id'], unique=False)
    _create_index(op.f('ix_process_records_process_no'), 'process_records', ['process_no'], unique=False)
    _create_table('change_request_files',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('company_id', sa.Integer(), nullable=True),
    sa.Column('change_request_id', sa.Integer(), nullable=False),
    sa.Column('file_kind', sa.String(length=40), nullable=False),
    sa.Column('file_name', sa.String(length=255), nullable=False),
    sa.Column('original_file_name', sa.String(length=255), nullable=False),
    sa.Column('file_path', sa.String(length=500), nullable=False),
    sa.Column('file_type', sa.String(length=20), nullable=True),
    sa.Column('file_size', sa.Integer(), nullable=True),
    sa.Column('uploaded_by_user_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['change_request_id'], ['change_requests.id'], ),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.ForeignKeyConstraint(['uploaded_by_user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    _create_index(op.f('ix_change_request_files_change_request_id'), 'change_request_files', ['change_request_id'], unique=False)
    _create_index(op.f('ix_change_request_files_company_id'), 'change_request_files', ['company_id'], unique=False)
    _create_table('deviation_files',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('company_id', sa.Integer(), nullable=True),
    sa.Column('deviation_id', sa.Integer(), nullable=False),
    sa.Column('file_kind', sa.String(length=40), nullable=False),
    sa.Column('file_name', sa.String(length=255), nullable=False),
    sa.Column('original_file_name', sa.String(length=255), nullable=False),
    sa.Column('file_path', sa.String(length=500), nullable=False),
    sa.Column('file_type', sa.String(length=20), nullable=True),
    sa.Column('file_size', sa.Integer(), nullable=True),
    sa.Column('uploaded_by_user_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.ForeignKeyConstraint(['deviation_id'], ['deviation_records.id'], ),
    sa.ForeignKeyConstraint(['uploaded_by_user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    _create_index(op.f('ix_deviation_files_company_id'), 'deviation_files', ['company_id'], unique=False)
    _create_index(op.f('ix_deviation_files_deviation_id'), 'deviation_files', ['deviation_id'], unique=False)
    _create_table('incident_reports',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('company_id', sa.Integer(), nullable=True),
    sa.Column('incident_no', sa.String(length=40), nullable=False),
    sa.Column('report_type', sa.String(length=80), nullable=False),
    sa.Column('title', sa.String(length=180), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('incident_date', sa.Date(), nullable=False),
    sa.Column('incident_time', sa.String(length=20), nullable=True),
    sa.Column('department', sa.String(length=80), nullable=True),
    sa.Column('location', sa.String(length=180), nullable=True),
    sa.Column('process_name', sa.String(length=160), nullable=True),
    sa.Column('affected_person', sa.String(length=180), nullable=True),
    sa.Column('witness', sa.String(length=180), nullable=True),
    sa.Column('severity', sa.String(length=40), nullable=False),
    sa.Column('probability', sa.Integer(), nullable=True),
    sa.Column('risk_score', sa.Integer(), nullable=True),
    sa.Column('immediate_action', sa.Text(), nullable=True),
    sa.Column('root_cause', sa.Text(), nullable=True),
    sa.Column('decision', sa.String(length=100), nullable=True),
    sa.Column('decision_note', sa.Text(), nullable=True),
    sa.Column('corrective_action', sa.Text(), nullable=True),
    sa.Column('due_date', sa.Date(), nullable=True),
    sa.Column('closed_at', sa.Date(), nullable=True),
    sa.Column('status', sa.String(length=40), nullable=False),
    sa.Column('reported_by_user_id', sa.Integer(), nullable=True),
    sa.Column('reviewer_user_id', sa.Integer(), nullable=True),
    sa.Column('responsible_user_id', sa.Integer(), nullable=True),
    sa.Column('document_id', sa.Integer(), nullable=True),
    sa.Column('action_id', sa.Integer(), nullable=True),
    sa.Column('risk_id', sa.Integer(), nullable=True),
    sa.Column('dof_id', sa.Integer(), nullable=True),
    sa.Column('deviation_id', sa.Integer(), nullable=True),
    sa.Column('archived_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['action_id'], ['actions.id'], ),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.ForeignKeyConstraint(['deviation_id'], ['deviation_records.id'], ),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ),
    sa.ForeignKeyConstraint(['dof_id'], ['dofs.id'], ),
    sa.ForeignKeyConstraint(['reported_by_user_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['responsible_user_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['reviewer_user_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['risk_id'], ['risk_records.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('company_id', 'incident_no', name='uq_incident_reports_company_incident_no')
    )
    _create_index(op.f('ix_incident_reports_company_id'), 'incident_reports', ['company_id'], unique=False)
    _create_index(op.f('ix_incident_reports_incident_no'), 'incident_reports', ['incident_no'], unique=False)
    _create_table('process_relations',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('company_id', sa.Integer(), nullable=True),
    sa.Column('source_process_id', sa.Integer(), nullable=False),
    sa.Column('target_process_id', sa.Integer(), nullable=False),
    sa.Column('relation_type', sa.String(length=60), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.ForeignKeyConstraint(['source_process_id'], ['process_records.id'], ),
    sa.ForeignKeyConstraint(['target_process_id'], ['process_records.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    _create_index(op.f('ix_process_relations_company_id'), 'process_relations', ['company_id'], unique=False)
    _create_index(op.f('ix_process_relations_source_process_id'), 'process_relations', ['source_process_id'], unique=False)
    _create_index(op.f('ix_process_relations_target_process_id'), 'process_relations', ['target_process_id'], unique=False)
    _create_table('process_steps',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('company_id', sa.Integer(), nullable=True),
    sa.Column('process_id', sa.Integer(), nullable=False),
    sa.Column('step_order', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(length=180), nullable=False),
    sa.Column('responsible_user_id', sa.Integer(), nullable=True),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('input_note', sa.Text(), nullable=True),
    sa.Column('output_note', sa.Text(), nullable=True),
    sa.Column('control_point', sa.Text(), nullable=True),
    sa.Column('document_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ),
    sa.ForeignKeyConstraint(['process_id'], ['process_records.id'], ),
    sa.ForeignKeyConstraint(['responsible_user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    _create_index(op.f('ix_process_steps_company_id'), 'process_steps', ['company_id'], unique=False)
    _create_index(op.f('ix_process_steps_process_id'), 'process_steps', ['process_id'], unique=False)
    _create_table('quality_objectives',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('company_id', sa.Integer(), nullable=True),
    sa.Column('objective_no', sa.String(length=40), nullable=False),
    sa.Column('title', sa.String(length=180), nullable=False),
    sa.Column('bsc_perspective', sa.String(length=60), nullable=False),
    sa.Column('department', sa.String(length=80), nullable=True),
    sa.Column('owner_user_id', sa.Integer(), nullable=True),
    sa.Column('process_id', sa.Integer(), nullable=True),
    sa.Column('action_id', sa.Integer(), nullable=True),
    sa.Column('metric_name', sa.String(length=180), nullable=False),
    sa.Column('unit', sa.String(length=40), nullable=False),
    sa.Column('baseline_value', sa.Numeric(precision=14, scale=4), nullable=False),
    sa.Column('target_value', sa.Numeric(precision=14, scale=4), nullable=False),
    sa.Column('target_direction', sa.String(length=20), nullable=False),
    sa.Column('weight', sa.Numeric(precision=5, scale=2), nullable=False),
    sa.Column('period_start', sa.Date(), nullable=True),
    sa.Column('period_end', sa.Date(), nullable=False),
    sa.Column('next_measurement_date', sa.Date(), nullable=True),
    sa.Column('measurement_frequency', sa.String(length=40), nullable=False),
    sa.Column('status', sa.String(length=40), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('archived_at', sa.DateTime(), nullable=True),
    sa.Column('created_by_user_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['action_id'], ['actions.id'], ),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['owner_user_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['process_id'], ['process_records.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('company_id', 'objective_no', name='uq_quality_objectives_company_objective_no')
    )
    _create_index(op.f('ix_quality_objectives_company_id'), 'quality_objectives', ['company_id'], unique=False)
    _create_index(op.f('ix_quality_objectives_objective_no'), 'quality_objectives', ['objective_no'], unique=False)
    _create_table('fmea_records',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('company_id', sa.Integer(), nullable=True),
    sa.Column('fmea_no', sa.String(length=40), nullable=False),
    sa.Column('process_name', sa.String(length=160), nullable=False),
    sa.Column('product_or_service', sa.String(length=180), nullable=True),
    sa.Column('operation_step', sa.String(length=180), nullable=True),
    sa.Column('failure_mode', sa.String(length=180), nullable=False),
    sa.Column('failure_effect', sa.Text(), nullable=True),
    sa.Column('failure_cause', sa.Text(), nullable=True),
    sa.Column('current_controls', sa.Text(), nullable=True),
    sa.Column('severity', sa.Integer(), nullable=False),
    sa.Column('occurrence', sa.Integer(), nullable=False),
    sa.Column('detection', sa.Integer(), nullable=False),
    sa.Column('recommended_action', sa.Text(), nullable=True),
    sa.Column('due_date', sa.Date(), nullable=True),
    sa.Column('closed_at', sa.Date(), nullable=True),
    sa.Column('status', sa.String(length=40), nullable=False),
    sa.Column('responsible_user_id', sa.Integer(), nullable=True),
    sa.Column('action_id', sa.Integer(), nullable=True),
    sa.Column('risk_id', sa.Integer(), nullable=True),
    sa.Column('dof_id', sa.Integer(), nullable=True),
    sa.Column('incident_id', sa.Integer(), nullable=True),
    sa.Column('deviation_id', sa.Integer(), nullable=True),
    sa.Column('created_by_user_id', sa.Integer(), nullable=True),
    sa.Column('archived_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['action_id'], ['actions.id'], ),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['deviation_id'], ['deviation_records.id'], ),
    sa.ForeignKeyConstraint(['dof_id'], ['dofs.id'], ),
    sa.ForeignKeyConstraint(['incident_id'], ['incident_reports.id'], ),
    sa.ForeignKeyConstraint(['responsible_user_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['risk_id'], ['risk_records.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('company_id', 'fmea_no', name='uq_fmea_records_company_fmea_no')
    )
    _create_index(op.f('ix_fmea_records_company_id'), 'fmea_records', ['company_id'], unique=False)
    _create_index(op.f('ix_fmea_records_fmea_no'), 'fmea_records', ['fmea_no'], unique=False)
    _create_table('incident_files',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('company_id', sa.Integer(), nullable=True),
    sa.Column('incident_id', sa.Integer(), nullable=False),
    sa.Column('file_kind', sa.String(length=40), nullable=False),
    sa.Column('file_name', sa.String(length=255), nullable=False),
    sa.Column('original_file_name', sa.String(length=255), nullable=False),
    sa.Column('file_path', sa.String(length=500), nullable=False),
    sa.Column('file_type', sa.String(length=20), nullable=True),
    sa.Column('file_size', sa.Integer(), nullable=True),
    sa.Column('uploaded_by_user_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.ForeignKeyConstraint(['incident_id'], ['incident_reports.id'], ),
    sa.ForeignKeyConstraint(['uploaded_by_user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    _create_index(op.f('ix_incident_files_company_id'), 'incident_files', ['company_id'], unique=False)
    _create_index(op.f('ix_incident_files_incident_id'), 'incident_files', ['incident_id'], unique=False)
    _create_table('quality_objective_measurements',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('company_id', sa.Integer(), nullable=True),
    sa.Column('objective_id', sa.Integer(), nullable=False),
    sa.Column('measurement_date', sa.Date(), nullable=False),
    sa.Column('period_label', sa.String(length=80), nullable=True),
    sa.Column('actual_value', sa.Numeric(precision=14, scale=4), nullable=False),
    sa.Column('target_value_snapshot', sa.Numeric(precision=14, scale=4), nullable=False),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('entered_by_user_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.ForeignKeyConstraint(['entered_by_user_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['objective_id'], ['quality_objectives.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('company_id', 'objective_id', 'measurement_date', name='uq_quality_objective_measurements_company_objective_date')
    )
    _create_index(op.f('ix_quality_objective_measurements_company_id'), 'quality_objective_measurements', ['company_id'], unique=False)
    _create_index(op.f('ix_quality_objective_measurements_measurement_date'), 'quality_objective_measurements', ['measurement_date'], unique=False)
    _create_index(op.f('ix_quality_objective_measurements_objective_id'), 'quality_objective_measurements', ['objective_id'], unique=False)
    _add_column('actions', sa.Column('dof_id', sa.Integer(), nullable=True))
    _add_column('actions', sa.Column('capa_type', sa.String(length=60), nullable=True))
    _add_column('actions', sa.Column('effectiveness_required', sa.Boolean(), server_default=sa.text('0'), nullable=False))
    _add_column('actions', sa.Column('effectiveness_owner_user_id', sa.Integer(), nullable=True))
    _add_column('actions', sa.Column('effectiveness_due_date', sa.Date(), nullable=True))
    _add_column('actions', sa.Column('effectiveness_result', sa.String(length=40), nullable=True))
    _add_column('actions', sa.Column('effectiveness_note', sa.Text(), nullable=True))
    _add_column('actions', sa.Column('effectiveness_checked_by_user_id', sa.Integer(), nullable=True))
    _add_column('actions', sa.Column('effectiveness_checked_at', sa.DateTime(), nullable=True))
    _create_index(op.f('ix_actions_dof_id'), 'actions', ['dof_id'], unique=False)
    _add_column('companies', sa.Column('package_key', sa.String(length=40), server_default='production_plus', nullable=False))
    _add_column('companies', sa.Column('is_demo', sa.Boolean(), server_default=sa.text('0'), nullable=False))
    _add_column('dofs', sa.Column('root_cause_method', sa.String(length=80), nullable=True))
    _add_column('dofs', sa.Column('containment_action', sa.Text(), nullable=True))
    _add_column('dofs', sa.Column('effectiveness_required', sa.Boolean(), server_default=sa.text('0'), nullable=False))
    _add_column('dofs', sa.Column('effectiveness_owner_user_id', sa.Integer(), nullable=True))
    _add_column('dofs', sa.Column('effectiveness_due_date', sa.Date(), nullable=True))
    _add_column('dofs', sa.Column('effectiveness_result', sa.String(length=40), nullable=True))
    _add_column('dofs', sa.Column('effectiveness_note', sa.Text(), nullable=True))
    _add_column('dofs', sa.Column('effectiveness_checked_by_user_id', sa.Integer(), nullable=True))
    _add_column('dofs', sa.Column('effectiveness_checked_at', sa.DateTime(), nullable=True))
    _add_column('notifications', sa.Column('notification_type', sa.String(length=40), server_default='info', nullable=False))
    _add_column('notifications', sa.Column('source_key', sa.String(length=180), nullable=True))
    _add_column('notifications', sa.Column('target_url', sa.String(length=500), nullable=True))
    _add_column('notifications', sa.Column('due_date', sa.Date(), nullable=True))
    _add_column('notifications', sa.Column('email_sent_at', sa.DateTime(), nullable=True))
    _create_index(op.f('ix_notifications_source_key'), 'notifications', ['source_key'], unique=False)
    _add_column('orientation_nodes', sa.Column('personnel_contact_id', sa.Integer(), nullable=True))
    _create_index(op.f('ix_orientation_nodes_personnel_contact_id'), 'orientation_nodes', ['personnel_contact_id'], unique=False)
    _add_column('users', sa.Column('personnel_contact_id', sa.Integer(), nullable=True))
    _create_index(op.f('ix_users_personnel_contact_id'), 'users', ['personnel_contact_id'], unique=False)


def downgrade():
    raise RuntimeError(
        "This additive reconciliation cannot be safely reversed: tables may predate "
        "the migration. Restore a verified database backup instead."
    )
