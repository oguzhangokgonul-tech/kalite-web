"""Explicit CONTEXT configuration, GET-only live smoke and post-verification checklist marking.

Smoke creates no CONTEXT business records; normal request hooks may initialize
runtime schema or user session metadata, so it is not a database read-only run.
"""
import argparse
from flask import g

from app import create_app
from app.config import Config
from app.audit import record_audit_event
from app.extensions import db
from app.models import AppSetting, Company, CompanyModule, Role, RolePermission, OrganizationContext, User
from app.seed import CONTEXT_ROLE_PERMISSIONS
from app.tenant import company_primary_domain, tenant_company_from_host, tenant_base_domain


def configure():
    grants = dict(CONTEXT_ROLE_PERMISSIONS)
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
    if changes:
        record_audit_event('ContextRelease', 'configured', 'Kuruluş bağlamı varsayılanları', details={'changes': changes}, commit=False)
    db.session.commit()
    return changes


def check_unscoped_access(app, admin):
    base = 'https://' + (tenant_base_domain() or 'localhost')
    assert tenant_company_from_host(tenant_base_domain()) is None, 'Base host must not select a tenant'
    client = app.test_client()
    with client.session_transaction(base_url=base) as session:
        session['user_id'] = admin.id
    for path in ('/kurulus-baglami', '/ilgili-taraflar', '/ilgili-taraflar/excel'):
        response = client.get(path, base_url=base)
        assert response.status_code == 403, (path, response.status_code)


def smoke(app):
    for role_key, expected in CONTEXT_ROLE_PERMISSIONS.items():
        role = Role.query.filter_by(key=role_key).one()
        actual = {permission.permission_key for permission in role.permissions}
        assert set(expected) <= actual, f'Missing CONTEXT defaults for role {role_key}'
        actual_context = {permission for permission in actual if permission.startswith('context.')}
        assert actual_context == set(expected), f'Unexpected CONTEXT permissions for role {role_key}'
    before = OrganizationContext.query.count()
    checks, missing = 0, []
    companies = Company.query.filter_by(is_active=True).all()
    for company in companies:
        domain = company_primary_domain(company)
        assert domain and tenant_company_from_host(domain).id == company.id
        module = CompanyModule.query.filter_by(company_id=company.id, module_key='stakeholder_management').one()
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
            response = client.get('/kurulus-baglami', base_url=base)
            readable = any(user.has_permission(p) for p in ('context.view', 'context.view_all', 'context.manage'))
            if module.is_enabled and readable:
                assert response.status_code == 200, (company.id, role, response.status_code)
                assert 'Kuruluş Bağlamı' in response.get_data(as_text=True)
                create = client.get('/kurulus-baglami/yeni', base_url=base)
                assert create.status_code == (200 if user.has_permission('context.create') or user.has_permission('context.manage') else 403)
            else:
                assert response.status_code in (403, 404)
            checks += 1
            company_checks += 1
            party_page = client.get('/ilgili-taraflar', base_url=base)
            party_readable = any(user.has_permission(p) for p in ('stakeholder.view', 'stakeholder.manage', 'stakeholder.review'))
            assert party_page.status_code == (200 if module.is_enabled and party_readable else 403)
        assert company_checks, f'No live role checks executed for company {company.id}'
        admin = User.query.filter_by(username='superadmin', company_id=None, is_active=True).one()
        assert admin.has_role('super_admin')
        admin_client = app.test_client()
        base = 'https://' + domain
        with admin_client.session_transaction(base_url=base) as session:
            session['user_id'], session['company_id'] = admin.id, company.id
        response = admin_client.get('/kurulus-baglami', base_url=base)
        assert response.status_code == (200 if module.is_enabled else 403), (company.id, 'super_admin', response.status_code)
        checks += 1
        other = next((c for c in companies if c.id != company.id), None)
        if other:
            foreign = User.query.filter_by(company_id=other.id, is_active=True).first()
            assert foreign
            client = app.test_client()
            with client.session_transaction(base_url='https://' + domain) as session:
                session['user_id'], session['company_id'] = foreign.id, other.id
            denied = client.get('/kurulus-baglami', base_url='https://' + domain)
            assert denied.status_code == 302 and '/login' in denied.location
    admin = User.query.filter_by(username='superadmin', company_id=None, is_active=True).one()
    check_unscoped_access(app, admin)
    assert checks and before == OrganizationContext.query.count()
    return {'checks': checks, 'roles_without_live_users': missing,
            'live_role_coverage': 'partial' if missing else 'complete'}


def mark(app):
    admin = User.query.filter_by(username='superadmin', company_id=None, is_active=True).one()
    assert admin.has_role('super_admin')
    key = 'sales_readiness:module_context_stakeholders'
    try:
        with app.test_request_context():
            g.current_user = admin
            setting = db.session.get(AppSetting, key)
            old = setting.value if setting else None
            if old != '1':
                if setting is None:
                    db.session.add(AppSetting(key=key, value='1'))
                else:
                    setting.value = '1'
                record_audit_event('ContextRelease', 'checklist_completed', 'Kuruluş bağlamı canlı doğrulaması tamamlandı',
                    old_values={key: old}, new_values={key: '1'}, commit=False)
                db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    assert db.session.get(AppSetting, key).value == '1'
    return 'module_context_stakeholders'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('step', choices=('configure', 'smoke', 'mark'))
    args = parser.parse_args()
    class ReleaseConfig(Config):
        MAIL_ENABLED = False
        NOTIFICATION_AUTO_REMINDERS_ENABLED = False

    app = create_app(ReleaseConfig)
    with app.app_context():
        print(configure() if args.step == 'configure' else smoke(app) if args.step == 'smoke' else mark(app))
