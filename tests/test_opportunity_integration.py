from datetime import date

from flask import g
import pytest

from app.extensions import db
from app.models import AppSetting, AuditLog, CompanyModule, Opportunity, ReportDefinition, Role, UserPermission
from tests.helpers import create_company, create_user, login


def opportunity(company, owner, title, month=10):
    record = Opportunity(company_id=company.id, title=title, owner_user_id=owner.id,
                         created_by_user_id=owner.id, likelihood=3, benefit=4,
                         analysis_date=date(2026, month, 7), due_date=date(2026, 12, 1),
                         review_date=date(2026, 12, 2))
    db.session.add(record)
    db.session.commit()
    return record


def test_standard_period_and_custom_reports_use_ids_not_names(client):
    from app.reporting import resolve_report_period
    from app.routes import build_custom_report_data, report_center_export_data
    company = create_company('OP-reports')
    owner = create_user('op-report-owner', company=company, role_key='department_manager')
    other = create_user('op-report-other', company=company, role_key='department_manager', full_name=owner.full_name)
    opportunity(company, owner, 'Görünür Fırsat')
    opportunity(company, owner, 'Önceki Dönem', month=9)
    opportunity(company, other, 'Gizli Fırsat')
    report = ReportDefinition(name='Fırsatlar', source_key='opportunities', configuration_json='{}')
    with client.application.test_request_context():
        g.current_user, g.current_company = owner, company
        g.enabled_company_modules = {'risk_management': True}
        for data in (report_center_export_data('opportunities'), build_custom_report_data(report, export=True)):
            assert any('Görünür Fırsat' in row for row in data['rows'])
            assert not any('Gizli Fırsat' in row for row in data['rows'])
        period = resolve_report_period('month', '2026-10-07', today=date(2026, 10, 7))
        data = report_center_export_data('opportunities', period=period)
        assert len(data['rows']) == 1
        assert 'Görünür Fırsat' in data['rows'][0]
        owner.roles.clear()
        owner.extra_permissions.extend(UserPermission(permission_key=p) for p in ('opportunity.view', 'reports.manage', 'reports.export'))
        db.session.commit()
        assert report_center_export_data('opportunities') is None
        assert build_custom_report_data(report, export=True) is None


@pytest.mark.parametrize('role,can_create', [
    ('super_admin', True), ('management_representative', True), ('management', True),
    ('department_manager', True), ('department_staff', False), ('viewer', False),
])
def test_navigation_and_six_role_form_access(client, role, can_create):
    company = create_company('OP-roles')
    user = create_user('op-role', company=None if role == 'super_admin' else company, role_key=role)
    login(client, user, company=company)
    response = client.get('/risk-firsat-portfoyu')
    assert response.status_code == 200
    assert 'href="/risk-firsat-portfoyu"' in response.get_data(as_text=True)
    response = client.get('/risk-firsat-portfoyu/firsat/yeni')
    assert response.status_code == (200 if can_create else 403)


@pytest.mark.parametrize('role', ['super_admin', 'management_representative', 'management', 'department_manager', 'department_staff', 'viewer'])
def test_company_module_off_blocks_each_role(client, role):
    company = create_company('OP-disabled', module_keys=[])
    user = create_user('op-disabled', company=None if role == 'super_admin' else company, role_key=role)
    login(client, user, company=company)
    for path in ('/risk-firsat-portfoyu', '/risk-firsat-portfoyu/firsat/yeni'):
        assert client.get(path).status_code == 403


def test_unscoped_admin_cannot_read_portfolio_or_export(app, client):
    from app.routes import report_center_export_data
    admin = create_user('superadmin', role_key='super_admin')
    login(client, admin)
    assert client.get('/risk-firsat-portfoyu').status_code == 403
    with app.test_request_context():
        g.current_user, g.current_company = admin, None
        assert report_center_export_data('opportunities') is None


def test_release_configuration_preserves_modules_and_is_idempotent(app):
    from scripts.opportunity_release import configure
    company = create_company('OP-config', module_keys=[])
    before = [(m.module_key, m.is_enabled) for m in CompanyModule.query.filter_by(company_id=company.id)]
    configure()
    assert configure() == []
    assert before == [(m.module_key, m.is_enabled) for m in CompanyModule.query.filter_by(company_id=company.id)]


def test_release_mark_single_key_and_audit(app):
    from scripts.opportunity_release import mark
    create_user('superadmin', role_key='super_admin')
    db.session.add(AppSetting(key='sales_readiness:module_quality_objective_projects', value='0'))
    db.session.commit()
    for _ in range(2):
        assert mark(app) == 'sales_readiness:module_risk_opportunity_portfolio'
    assert db.session.get(AppSetting, 'sales_readiness:module_risk_opportunity_portfolio').value == '1'
    assert db.session.get(AppSetting, 'sales_readiness:module_quality_objective_projects').value == '0'
    assert AuditLog.query.filter_by(entity_type='OpportunityRelease', action='checklist_completed').count() == 1


def test_release_mark_rolls_back_when_audit_fails(app, monkeypatch):
    from scripts import opportunity_release
    create_user('superadmin', role_key='super_admin')
    def fail(*args, **kwargs):
        raise RuntimeError('Audit failure')
    monkeypatch.setattr(opportunity_release, 'record_audit_event', fail)
    with pytest.raises(RuntimeError, match='Audit failure'):
        opportunity_release.mark(app)
    assert db.session.get(AppSetting, 'sales_readiness:module_risk_opportunity_portfolio') is None


def test_release_smoke_checks_exact_default_permissions(app):
    from scripts.opportunity_release import smoke
    role = Role.query.filter_by(key='department_manager').one()
    role.permissions[:] = [p for p in role.permissions if p.permission_key != 'opportunity.create']
    db.session.commit()
    with pytest.raises(AssertionError, match='defaults mismatch'):
        smoke(app)


@pytest.mark.parametrize('module_enabled', [True, False])
def test_linked_action_delete_preserves_record_and_all_evidence(app, client, module_enabled):
    from app.models import Action, ActionClosureFile, ActionSubTask
    from tests.helpers import stored_upload_path, write_stored_upload
    company = create_company('OP-delete')
    owner = create_user('op-delete-owner', company=company, role_key='management_representative')
    paths = [f'company-{company.id:03d}/op-{kind}.txt' for kind in ('attachment', 'legacy-closure', 'closure', 'subtask')]
    for path in paths:
        write_stored_upload(app, path, b'preserve evidence')
    action = Action(company_id=company.id, action_number=1, title='Linked action',
                    responsible_user_id=owner.id, responsible_owner=owner.full_name,
                    termin_date=date(2026, 12, 1),
                    file_stored_name=paths[0], closure_file_stored_name=paths[1])
    db.session.add(action)
    db.session.flush()
    evidence = ActionClosureFile(company_id=company.id, action_id=action.id, original_name='closure.txt', stored_name=paths[2])
    subtask = ActionSubTask(company_id=company.id, parent_action_id=action.id, title='Subtask', evidence_stored_name=paths[3])
    db.session.add_all([evidence, subtask])
    item = opportunity(company, owner, 'Linked opportunity')
    item.action_id = action.id
    db.session.commit()
    if not module_enabled:
        module = CompanyModule.query.filter_by(company_id=company.id, module_key='risk_management').one()
        module.is_enabled = False
        db.session.commit()
    login(client, owner)
    if not module_enabled:
        assert client.get('/risk-firsat-portfoyu').status_code == 403
    for method in ('get', 'post'):
        assert getattr(client, method)(f'/actions/{action.id}/delete').status_code == 409
        assert db.session.get(Action, action.id) is not None
        assert db.session.get(ActionSubTask, subtask.id) is not None
        assert db.session.get(ActionClosureFile, evidence.id) is not None
        for path in paths:
            assert stored_upload_path(app, path).read_bytes() == b'preserve evidence'


def test_action_detail_access_rechecked_before_link_or_disclosure(client, monkeypatch):
    from app import routes
    from app.models import Action
    from tests.test_opportunities import form_data
    company = create_company('OP-link-guard')
    owner = create_user('op-link-owner', company=company, role_key='management_representative')
    action = Action(company_id=company.id, action_number=1, title='HIDDEN-ACTION-TITLE',
                    responsible_user_id=owner.id, responsible_owner=owner.full_name, termin_date=date(2026, 12, 1))
    db.session.add(action)
    db.session.commit()
    item = opportunity(company, owner, 'Visible opportunity')
    item.action_id = action.id
    db.session.commit()
    login(client, owner)
    monkeypatch.setattr(routes, 'can_view_action', lambda record: False)
    for path in ('/risk-firsat-portfoyu/firsat/yeni', f'/risk-firsat-portfoyu/firsat/{item.id}',
                 f'/risk-firsat-portfoyu/firsat/{item.id}/duzenle'):
        response = client.get(path)
        assert response.status_code == 200
        assert action.title not in response.get_data(as_text=True)
    response = client.post('/risk-firsat-portfoyu/firsat/yeni', data=form_data(owner, action_id=action.id))
    assert response.status_code == 400
    assert Opportunity.query.count() == 1
    from tests.helpers import sheet_values
    headers, row = sheet_values(client.get(f'/risk-firsat-portfoyu/firsat/{item.id}/rapor').data)
    assert dict(zip(headers, row))['Bağlı Aksiyon'] == ''


@pytest.mark.parametrize('commit_fails', [False, True])
def test_action_files_deleted_only_after_successful_database_commit(app, client, monkeypatch, commit_fails):
    from app.models import Action, ActionClosureFile, ActionSubTask
    from sqlalchemy.exc import IntegrityError
    from tests.helpers import stored_upload_path, write_stored_upload
    company = create_company('OP-delete-order')
    user = create_user('op-delete-order', company=company, role_key='management_representative')
    paths = [f'company-{company.id:03d}/order-{i}.txt' for i in range(4)]
    for path in paths:
        write_stored_upload(app, path, b'evidence')
    action = Action(company_id=company.id, action_number=1, title='Deletion order', termin_date=date(2026, 12, 1),
                    responsible_user_id=user.id, responsible_owner=user.full_name,
                    file_stored_name=paths[0], closure_file_stored_name=paths[1])
    db.session.add(action)
    db.session.flush()
    db.session.add(ActionClosureFile(company_id=company.id, action_id=action.id, original_name='closure.txt', stored_name=paths[2]))
    db.session.add(ActionSubTask(company_id=company.id, parent_action_id=action.id, title='Subtask', evidence_stored_name=paths[3]))
    db.session.commit()
    action_id = action.id
    real_commit = db.session.commit
    def checked_commit():
        if any(isinstance(item, Action) for item in db.session.deleted):
            assert all(stored_upload_path(app, path).exists() for path in paths)
            if commit_fails:
                raise IntegrityError('DELETE actions', {}, RuntimeError('Concurrent reference'))
        return real_commit()
    monkeypatch.setattr(db.session, 'commit', checked_commit)
    login(client, user)
    response = client.post(f'/actions/{action_id}/delete')
    assert response.status_code == (409 if commit_fails else 302)
    assert (db.session.get(Action, action_id) is not None) == commit_fails
    for path in paths:
        assert stored_upload_path(app, path).exists() == commit_fails


def test_portfolio_does_not_offer_unavailable_legacy_risk_archive_filter(client):
    company = create_company('OP-archive-filter')
    user = create_user('op-archive-filter', company=company, role_key='management_representative')
    login(client, user)
    response = client.get('/risk-firsat-portfoyu?type=risk')
    assert response.status_code == 200
    assert '<option value="Arşiv"' not in response.get_data(as_text=True)
    response = client.get('/risk-firsat-portfoyu?type=opportunity')
    assert '<option value="archived"' in response.get_data(as_text=True)
