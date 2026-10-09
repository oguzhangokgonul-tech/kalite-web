"""Explicit custody permission setup and read-only business-data release smoke."""
import argparse

from app import create_app
from app.audit import record_audit_event
from app.config import Config
from app.extensions import db
from app.models import Company, CustodyRecord, Role, RolePermission, User
from app.seed import CUSTODY_ROLE_PERMISSIONS
from app.tenant import company_primary_domain, tenant_base_domain, tenant_company_from_host


def configure():
    grants = dict(CUSTODY_ROLE_PERMISSIONS)
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
        record_audit_event('CustodyRelease', 'configured', 'Zimmet permission defaults',
                           details={'changes': changes}, commit=False)
    db.session.commit()
    return changes


def smoke(app):
    from app.routes import company_module_state
    for key, expected in CUSTODY_ROLE_PERMISSIONS.items():
        role = Role.query.filter_by(key=key).one()
        actual = {p.permission_key for p in role.permissions if p.permission_key.startswith('custody.')}
        assert actual == set(expected), f'Custody defaults mismatch: {key}'
    before = CustodyRecord.query.count()
    admin = User.query.filter_by(username='superadmin', company_id=None, is_active=True).one()
    assert admin.has_role('super_admin')
    assert not any('__preview' in rule.rule or '__ui/' in rule.rule for rule in app.url_map.iter_rules())
    companies = Company.query.filter_by(is_active=True).all()
    checks, missing = 0, []
    for company in companies:
        domain = company_primary_domain(company)
        assert domain and tenant_company_from_host(domain).id == company.id
        enabled = company_module_state(company)['custody_management']
        for key in ('super_admin', *CUSTODY_ROLE_PERMISSIONS):
            user = admin if key == 'super_admin' else User.query.filter(
                User.company_id == company.id, User.is_active.is_(True), User.roles.any(key=key)).first()
            if user is None:
                missing.append(f'{company.id}:{key}')
                continue
            base = 'https://' + domain
            client = app.test_client()
            with client.session_transaction(base_url=base) as session:
                session['user_id'], session['company_id'] = user.id, company.id
            can_read = any(user.has_permission(p) for p in ('custody.view', 'custody.view_all', 'custody.manage'))
            visible = enabled and can_read
            page = client.get('/zimmet-yonetimi', base_url=base)
            assert page.status_code == (200 if visible else 403), (company.id, key, page.status_code)
            form = client.get('/zimmet-yonetimi/yeni', base_url=base)
            assert form.status_code == (200 if visible and user.has_permission('custody.manage') else 403)
            mobile = client.get('/mobil', base_url=base)
            assert mobile.status_code == 200
            assert ('href="/zimmet-yonetimi"' in mobile.get_data(as_text=True)) == visible
            checks += 1
        other = next((c for c in companies if c.id != company.id), None)
        if other:
            foreign = User.query.filter_by(company_id=other.id, is_active=True).first()
            if foreign:
                client = app.test_client()
                base = 'https://' + domain
                with client.session_transaction(base_url=base) as session:
                    session['user_id'], session['company_id'] = foreign.id, other.id
                response = client.get('/zimmet-yonetimi', base_url=base)
                assert response.status_code == 302 and '/login' in response.location
    base = 'https://' + tenant_base_domain()
    assert tenant_company_from_host(tenant_base_domain()) is None
    client = app.test_client()
    with client.session_transaction(base_url=base) as session:
        session['user_id'] = admin.id
    assert client.get('/zimmet-yonetimi', base_url=base).status_code == 403
    assert CustodyRecord.query.count() == before
    assert checks
    return {'checks': checks, 'roles_without_live_users': missing, 'coverage': 'partial' if missing else 'complete'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('step', choices=('configure', 'smoke'))
    args = parser.parse_args()

    class ReleaseConfig(Config):
        MAIL_ENABLED = False
        NOTIFICATION_AUTO_REMINDERS_ENABLED = False

    app = create_app(ReleaseConfig)
    with app.app_context():
        print(configure() if args.step == 'configure' else smoke(app))
