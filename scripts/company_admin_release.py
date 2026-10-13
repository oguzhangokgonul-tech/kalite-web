"""Install the company-admin role without reseeding users or other roles."""
import json

from sqlalchemy import text

from app import create_app
from app.audit import record_audit_event
from app.config import Config
from app.extensions import db
from app.models import Role, RolePermission
from app.seed import ROLE_DEFINITIONS


class ReleaseConfig(Config):
    MAIL_ENABLED = False
    NOTIFICATION_AUTO_REMINDERS_ENABLED = False
    AUTO_BOOTSTRAP_DATABASE = False


def configure():
    definition = next(item for item in ROLE_DEFINITIONS if item['key'] == 'company_admin')
    if 'roles.manage' in definition['permissions']:
        raise RuntimeError('Platform authority must not be granted to company admins')
    if db.session.new or db.session.dirty or db.session.deleted:
        raise RuntimeError('Use a dedicated, clean release session')
    db.session.rollback()
    if db.engine.dialect.name == 'sqlite':
        db.session.execute(text('BEGIN IMMEDIATE'))
    try:
        role = Role.query.filter_by(key='company_admin').one_or_none()
        created = role is None
        if created:
            role = Role(key=definition['key'], name=definition['name'],
                        description=definition['description'], hierarchy_level=5, is_system=True)
            role.permissions = [RolePermission(permission_key=key)
                                for key in definition['permissions']]
            db.session.add(role)
            db.session.flush()
            record_audit_event('CompanyAdminRelease', 'configured',
                               'Company administrator role installed without account assignments',
                               entity_id=role.id, details={'role': role.key,
                               'permission_count': len(role.permissions)}, commit=False)
        elif role.hierarchy_level != 5 or not role.is_system or role.permission_keys != set(definition['permissions']):
            raise RuntimeError('Existing company-admin role differs; review before overwriting')
        db.session.commit()
        return {'created': created, 'permission_count': len(role.permissions)}
    except Exception:
        db.session.rollback()
        raise


if __name__ == '__main__':
    app = create_app(ReleaseConfig)
    with app.app_context():
        print(json.dumps(configure(), sort_keys=True))
