"""Explicit SWOT configuration, GET-only live smoke and post-verification checklist marking.

Smoke creates no SWOT business records; normal request hooks may initialize
runtime schema or user session metadata, so it is not a database read-only run.
"""
import argparse
from flask import g

from app import create_app
from app.config import Config
from app.audit import record_audit_event
from app.extensions import db
from app.models import AppSetting, Company, CompanyModule, Role, RolePermission, SwotAnalysis, User
from app.seed import SWOT_ROLE_PERMISSIONS
from app.tenant import company_primary_domain, tenant_company_from_host


def configure():
    grants = dict(SWOT_ROLE_PERMISSIONS)
    grants['super_admin'] = tuple(sorted({p for permissions in grants.values() for p in permissions}))
    changes = []
    for key, permissions in grants.items():
        role = Role.query.filter_by(key=key).first()
        if role:
            existing = {p.permission_key for p in role.permissions}
            for permission in permissions:
                if permission not in existing:
                    role.permissions.append(RolePermission(permission_key=permission))
                    changes.append(f'role:{key}:{permission}')
    for company in Company.query.all():
        if CompanyModule.query.filter_by(company_id=company.id, module_key='swot').first() is None:
            enabled = company.package_key in {'iso_core', 'production_plus'}
            db.session.add(CompanyModule(company_id=company.id, module_key='swot', is_enabled=enabled))
            changes.append(f'company:{company.id}:swot:{enabled}')
    if changes:
        record_audit_event('SwotRelease', 'configured', 'SWOT varsayılanları', details={'changes': changes}, commit=False)
    db.session.commit()
    return changes


def smoke(app):
    for role_key, expected in SWOT_ROLE_PERMISSIONS.items():
        role = Role.query.filter_by(key=role_key).one()
        actual = {permission.permission_key for permission in role.permissions}
        assert set(expected) <= actual, f'Missing SWOT defaults for role {role_key}'
    before = SwotAnalysis.query.count()
    checks, missing = 0, []
    companies = Company.query.filter_by(is_active=True).all()
    for company in companies:
        domain = company_primary_domain(company)
        assert domain and tenant_company_from_host(domain).id == company.id
        module = CompanyModule.query.filter_by(company_id=company.id, module_key='swot').one()
        company_checks = 0
        for role in ('management_representative', 'management', 'department_manager', 'department_staff', 'viewer'):
            user = User.query.filter(User.company_id == company.id, User.is_active.is_(True), User.roles.any(key=role)).first()
            if not user:
                missing.append(f'{company.id}:{role}')
                continue
            client = app.test_client()
            base = 'https://' + domain
            with client.session_transaction(base_url=base) as session:
                session['user_id'], session['company_id'] = user.id, company.id
            response = client.get('/swot', base_url=base)
            readable = any(user.has_permission(p) for p in ('swot.view', 'swot.view_all', 'swot.manage'))
            if module.is_enabled and readable:
                assert response.status_code == 200, (company.id, role, response.status_code)
                assert 'SWOT Analizi' in response.get_data(as_text=True)
                create = client.get('/swot/yeni', base_url=base)
                assert create.status_code == (200 if user.has_permission('swot.create') or user.has_permission('swot.manage') else 403)
            else:
                assert response.status_code in (403, 404)
            checks += 1
            company_checks += 1
        assert company_checks, f'No live role checks executed for company {company.id}'
        other = next((c for c in companies if c.id != company.id), None)
        if other:
            foreign = User.query.filter_by(company_id=other.id, is_active=True).first()
            assert foreign
            client = app.test_client()
            with client.session_transaction(base_url='https://' + domain) as session:
                session['user_id'], session['company_id'] = foreign.id, other.id
            denied = client.get('/swot', base_url='https://' + domain)
            assert denied.status_code == 302 and '/login' in denied.location
    assert checks and before == SwotAnalysis.query.count()
    return {'checks': checks, 'roles_without_live_users': missing}


def mark(app):
    admin = User.query.filter_by(username='superadmin', company_id=None, is_active=True).one()
    assert admin.has_role('super_admin')
    key = 'sales_readiness:module_swot_analysis'
    with app.test_request_context():
        g.current_user = admin
        setting = db.session.get(AppSetting, key)
        old = setting.value if setting else None
        if old != '1':
            if setting is None:
                db.session.add(AppSetting(key=key, value='1'))
            else:
                setting.value = '1'
            record_audit_event('SwotRelease', 'checklist_completed', 'SWOT canlı doğrulaması tamamlandı',
                old_values={key: old}, new_values={key: '1'}, commit=False)
            db.session.commit()
    assert db.session.get(AppSetting, key).value == '1'
    return 'module_swot_analysis'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('step', choices=('configure', 'smoke', 'mark'))
    args = parser.parse_args()
    class ReleaseConfig(Config):
        MAIL_ENABLED = False
        NOTIFICATION_AUTO_REMINDERS_ENABLED = False
        AUTO_BOOTSTRAP_DATABASE = False

    app = create_app(ReleaseConfig)
    with app.app_context():
        print(configure() if args.step == 'configure' else smoke(app) if args.step == 'smoke' else mark(app))
