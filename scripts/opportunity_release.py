"""Explicit role setup, non-business-writing smoke, and post-verification checklist mark."""
import argparse

from flask import g

from app import create_app
from app.audit import record_audit_event
from app.config import Config
from app.extensions import db
from app.models import AppSetting, Company, CompanyModule, Opportunity, Role, RolePermission, User
from app.seed import OPPORTUNITY_ROLE_PERMISSIONS
from app.tenant import company_primary_domain, tenant_base_domain, tenant_company_from_host


def configure():
    grants = dict(OPPORTUNITY_ROLE_PERMISSIONS)
    grants['super_admin'] = tuple(sorted({p for values in grants.values() for p in values}))
    changes = []
    for key, permissions in grants.items():
        role = Role.query.filter_by(key=key).one()
        existing = {p.permission_key for p in role.permissions}
        for permission in permissions:
            if permission not in existing:
                role.permissions.append(RolePermission(permission_key=permission))
                changes.append(f'{key}:{permission}')
    if changes:
        record_audit_event('OpportunityRelease', 'configured', 'Fırsat portföyü yetkileri',
                           details={'changes': changes}, commit=False)
    db.session.commit()
    return changes


def smoke(app):
    from app.routes import company_module_state
    for key, expected in OPPORTUNITY_ROLE_PERMISSIONS.items():
        role = Role.query.filter_by(key=key).one()
        actual = {p.permission_key for p in role.permissions if p.permission_key.startswith('opportunity.')}
        assert actual == set(expected), f'Opportunity role defaults mismatch: {key}'
    before = Opportunity.query.count()
    admin = User.query.filter_by(username='superadmin', company_id=None, is_active=True).one()
    assert admin.has_role('super_admin')
    companies = Company.query.filter_by(is_active=True).all()
    checks, missing = 0, []
    for company in companies:
        domain = company_primary_domain(company)
        assert domain and tenant_company_from_host(domain).id == company.id
        enabled = company_module_state(company)['risk_management']
        for role_key in ('super_admin', *OPPORTUNITY_ROLE_PERMISSIONS):
            user = admin if role_key == 'super_admin' else User.query.filter(
                User.company_id == company.id, User.is_active.is_(True), User.roles.any(key=role_key)).first()
            if user is None:
                missing.append(f'{company.id}:{role_key}')
                continue
            base = 'https://' + domain
            client = app.test_client()
            with client.session_transaction(base_url=base) as session:
                session['user_id'], session['company_id'] = user.id, company.id
            page = client.get('/risk-firsat-portfoyu', base_url=base)
            assert page.status_code == (200 if enabled else 403), (company.id, role_key, page.status_code)
            if enabled:
                form = client.get('/risk-firsat-portfoyu/firsat/yeni', base_url=base)
                allowed = user.has_permission('opportunity.create') or user.has_permission('opportunity.manage')
                assert form.status_code == (200 if allowed else 403), (company.id, role_key, form.status_code)
            checks += 1
        other = next((c for c in companies if c.id != company.id), None)
        if other:
            foreign = User.query.filter_by(company_id=other.id, is_active=True).first()
            assert foreign
            client = app.test_client()
            base = 'https://' + domain
            with client.session_transaction(base_url=base) as session:
                session['user_id'], session['company_id'] = foreign.id, other.id
            response = client.get('/risk-firsat-portfoyu', base_url=base)
            assert response.status_code == 302 and '/login' in response.location
    base = 'https://' + (tenant_base_domain() or 'localhost')
    assert tenant_company_from_host(tenant_base_domain()) is None
    client = app.test_client()
    with client.session_transaction(base_url=base) as session:
        session['user_id'] = admin.id
    assert client.get('/risk-firsat-portfoyu', base_url=base).status_code == 403
    assert before == Opportunity.query.count()
    assert checks
    return {'checks': checks, 'roles_without_live_users': missing, 'coverage': 'partial' if missing else 'complete'}


def mark(app):
    admin = User.query.filter_by(username='superadmin', company_id=None, is_active=True).one()
    assert admin.has_role('super_admin')
    key = 'sales_readiness:module_risk_opportunity_portfolio'
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
                record_audit_event('OpportunityRelease', 'checklist_completed', 'Riskler ve fırsatlar canlı doğrulaması',
                                   old_values={key: old}, new_values={key: '1'}, commit=False)
                db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    assert db.session.get(AppSetting, key).value == '1'
    return key


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
