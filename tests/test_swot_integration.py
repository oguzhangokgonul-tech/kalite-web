from datetime import date

from flask import g

from app.extensions import db
from app.models import CompanyModule, ReportDefinition, SwotAnalysis, UserPermission
from tests.helpers import create_company, create_user, login


def test_scoped_standard_custom_period_reports_and_permission_revocation(client):
    from app.routes import build_custom_report_data, report_center_export_data, report_definition_access_allowed, REPORT_CENTER_REPORTS
    from app.reporting import resolve_report_period
    company = create_company('SWOT-reports')
    owner = create_user('swot-report-owner', company=company, role_key='department_manager')
    other = create_user('swot-report-other', company=company, role_key='department_manager', full_name=owner.full_name)
    for user, title, month in [(owner, 'Visible SWOT', 10), (owner, 'Prior SWOT', 9), (other, 'Hidden SWOT', 10)]:
        db.session.add(SwotAnalysis(company_id=company.id, title=title, scope='Scope',
            owner_user_id=user.id, created_by_user_id=user.id, analysis_date=date(2026, month, 5), review_date=date(2027, 1, 5)))
    db.session.commit()
    report = ReportDefinition(name='SWOT Report', source_key='swot', configuration_json='{}')
    with client.application.test_request_context():
        g.current_user, g.current_company = owner, company
        g.enabled_company_modules = {'swot': True}
        for result in (report_center_export_data('swot'), build_custom_report_data(report, export=True)):
            assert any('Visible SWOT' in row for row in result['rows'])
            assert not any('Hidden SWOT' in row for row in result['rows'])
        period = resolve_report_period('month', '2026-10-05', today=date(2026, 10, 5))
        result = report_center_export_data('swot', period=period)
        assert len(result['rows']) == 1
        assert 'Visible SWOT' in result['rows'][0]
        owner.roles.clear()
        owner.extra_permissions.extend(UserPermission(permission_key=p) for p in ('swot.view', 'reports.manage', 'reports.export'))
        db.session.commit()
        definition = next(item for item in REPORT_CENTER_REPORTS if item['key'] == 'swot')
        assert not report_definition_access_allowed(definition, export=True)
        assert report_center_export_data('swot') is None


def test_release_configuration_is_idempotent_and_preserves_explicit_module_settings(client):
    from scripts.swot_release import configure
    company = create_company('SWOT-config')
    company.package_key = 'iso_core'
    module = CompanyModule.query.filter_by(company_id=company.id, module_key='swot').first()
    if module is None:
        module = CompanyModule(company_id=company.id, module_key='swot', is_enabled=False)
        db.session.add(module)
    else:
        module.is_enabled = False
    db.session.commit()
    configure()
    assert configure() == []
    db.session.refresh(module)
    assert not module.is_enabled


def test_admin_without_company_can_open_report_center_but_not_swot(client):
    user = create_user('superadmin', role_key='super_admin')
    login(client, user)
    assert client.get('/swot').status_code == 403
    assert client.get('/rapor-merkezi').status_code == 200


def test_release_mark_only_updates_swot_flag_and_is_idempotent(app):
    from app.models import AppSetting, AuditLog
    from scripts.swot_release import mark
    create_user('superadmin', role_key='super_admin')
    db.session.add(AppSetting(key='sales_readiness:module_pestle_analysis', value='0'))
    db.session.add(AppSetting(key='sales_readiness:module_project_gantt', value='1'))
    db.session.commit()
    assert mark(app) == 'module_swot_analysis'
    assert mark(app) == 'module_swot_analysis'
    assert db.session.get(AppSetting, 'sales_readiness:module_pestle_analysis').value == '0'
    assert db.session.get(AppSetting, 'sales_readiness:module_project_gantt').value == '1'
    assert AuditLog.query.filter_by(entity_type='SwotRelease', action='checklist_completed').count() == 1
