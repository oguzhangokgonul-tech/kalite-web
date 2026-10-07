from datetime import date
import pytest

from flask import g

from app.extensions import db
from app.models import CompanyModule, ReportDefinition, OrganizationContext, UserPermission
from tests.helpers import create_company, create_user, login


def test_scoped_standard_custom_period_reports_and_permission_revocation(client):
    from app.routes import build_custom_report_data, report_center_export_data, report_definition_access_allowed, REPORT_CENTER_REPORTS
    from app.reporting import resolve_report_period
    company = create_company('CONTEXT-reports')
    owner = create_user('context-report-owner', company=company, role_key='department_manager')
    other = create_user('context-report-other', company=company, role_key='department_manager', full_name=owner.full_name)
    for user, title, month in [(owner, 'Visible CONTEXT', 10), (owner, 'Prior CONTEXT', 9), (other, 'Hidden CONTEXT', 10)]:
        db.session.add(OrganizationContext(company_id=company.id, title=title, scope='Scope',
            owner_user_id=user.id, created_by_user_id=user.id, analysis_date=date(2026, month, 5), review_date=date(2027, 1, 5)))
    db.session.commit()
    report = ReportDefinition(name='CONTEXT Report', source_key='context', configuration_json='{}')
    with client.application.test_request_context():
        g.current_user, g.current_company = owner, company
        g.enabled_company_modules = {'stakeholder_management': True}
        for result in (report_center_export_data('context'), build_custom_report_data(report, export=True)):
            assert any('Visible CONTEXT' in row for row in result['rows'])
            assert not any('Hidden CONTEXT' in row for row in result['rows'])
        period = resolve_report_period('month', '2026-10-05', today=date(2026, 10, 5))
        result = report_center_export_data('context', period=period)
        assert len(result['rows']) == 1
        assert 'Visible CONTEXT' in result['rows'][0]
        owner.roles.clear()
        owner.extra_permissions.extend(UserPermission(permission_key=p) for p in ('context.view', 'reports.manage', 'reports.export'))
        db.session.commit()
        definition = next(item for item in REPORT_CENTER_REPORTS if item['key'] == 'context')
        assert not report_definition_access_allowed(definition, export=True)
        assert report_center_export_data('context') is None


def test_release_configuration_is_idempotent_and_preserves_explicit_module_settings(client):
    from scripts.context_release import configure
    company = create_company('CONTEXT-config')
    company.package_key = 'iso_core'
    module = CompanyModule.query.filter_by(company_id=company.id, module_key='stakeholder_management').first()
    if module is None:
        module = CompanyModule(company_id=company.id, module_key='stakeholder_management', is_enabled=False)
        db.session.add(module)
    else:
        module.is_enabled = False
    db.session.commit()
    configure()
    assert configure() == []
    db.session.refresh(module)
    assert not module.is_enabled


def test_admin_without_company_can_open_report_center_but_not_context(client):
    user = create_user('superadmin', role_key='super_admin')
    login(client, user)
    assert client.get('/kurulus-baglami').status_code == 403
    assert client.get('/rapor-merkezi').status_code == 200


def test_release_mark_only_updates_context_flag_and_is_idempotent(app):
    from app.models import AppSetting, AuditLog
    from scripts.context_release import mark
    create_user('superadmin', role_key='super_admin')
    db.session.add(AppSetting(key='sales_readiness:module_pestle_analysis', value='0'))
    db.session.add(AppSetting(key='sales_readiness:module_project_gantt', value='1'))
    db.session.add(AppSetting(key='sales_readiness:module_swot_analysis', value='1'))
    db.session.commit()
    assert mark(app) == 'module_context_stakeholders'
    assert mark(app) == 'module_context_stakeholders'
    assert db.session.get(AppSetting, 'sales_readiness:module_pestle_analysis').value == '0'
    assert db.session.get(AppSetting, 'sales_readiness:module_project_gantt').value == '1'
    assert db.session.get(AppSetting, 'sales_readiness:module_swot_analysis').value == '1'
    assert AuditLog.query.filter_by(entity_type='ContextRelease', action='checklist_completed').count() == 1


def test_release_mark_rolls_back_on_audit_failure(app, monkeypatch):
    from app.models import AppSetting
    from scripts import context_release
    create_user('superadmin', role_key='super_admin')
    def fail(*args, **kwargs):
        raise RuntimeError('Audit failure')
    monkeypatch.setattr(context_release, 'record_audit_event', fail)
    with pytest.raises(RuntimeError, match='Audit failure'):
        context_release.mark(app)
    assert db.session.get(AppSetting, 'sales_readiness:module_context_stakeholders') is None


def test_release_smoke_rejects_missing_default_role_permission(app):
    from app.models import Role
    from scripts.context_release import smoke
    role = Role.query.filter_by(key='department_manager').one()
    role.permissions[:] = [p for p in role.permissions if p.permission_key != 'context.create']
    db.session.commit()
    with pytest.raises(AssertionError, match='Missing CONTEXT defaults'):
        smoke(app)


def test_release_smoke_rejects_excess_default_role_permission(app):
    from app.models import Role, RolePermission
    from scripts.context_release import smoke
    role = Role.query.filter_by(key='viewer').one()
    role.permissions.append(RolePermission(permission_key='context.manage'))
    db.session.commit()
    with pytest.raises(AssertionError, match='Unexpected CONTEXT permissions'):
        smoke(app)


@pytest.mark.parametrize('path,method', [
    ('/ilgili-taraflar', 'get'), ('/ilgili-taraflar/excel', 'get'),
    ('/ilgili-taraflar/1', 'get'), ('/ilgili-taraflar/yeni', 'post'),
    ('/ilgili-taraflar/1/duzenle', 'post'), ('/ilgili-taraflar/1/arsivle', 'post'),
    ('/ilgili-taraflar/1/aktiflestir', 'post'), ('/ilgili-taraflar/1/degerlendir', 'post'),
])
def test_stakeholder_workspace_requires_selected_company(client, path, method):
    user = create_user('superadmin', role_key='super_admin')
    login(client, user)
    assert getattr(client, method)(path).status_code == 403


def test_workspace_tabs_keep_permissions_separate(client):
    company = create_company('context-tabs')
    context_user = create_user('context-only', company=company, permissions=('context.view',))
    login(client, context_user)
    html = client.get('/kurulus-baglami').get_data(as_text=True)
    assert 'href="/ilgili-taraflar"' not in html
    assert client.get('/ilgili-taraflar').status_code == 403
    party_user = create_user('stakeholder-only', company=company, permissions=('stakeholder.view',))
    login(client, party_user)
    html = client.get('/ilgili-taraflar').get_data(as_text=True)
    assert 'href="/kurulus-baglami"' not in html
    assert client.get('/kurulus-baglami').status_code == 403


def test_global_stakeholder_query_has_no_cross_company_rows(app):
    from app.stakeholders import party_query, requirement_query
    admin = create_user('superadmin', role_key='super_admin')
    with app.test_request_context():
        g.current_user, g.current_company, g.current_user_is_super_admin = admin, None, True
        assert 'stakeholder_parties.company_id IS NULL' in str(party_query().statement)
        assert 'stakeholder_requirements.company_id IS NULL' in str(requirement_query().statement)
