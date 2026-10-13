import pytest

from app.extensions import db
from app.models import AuditLog, Role, RolePermission, User
from scripts.company_admin_release import configure
from tests.test_company_admin import app, create_user


def test_release_adds_only_new_role_and_is_idempotent(app):
    admin_role = Role.query.filter_by(key='company_admin').one()
    db.session.delete(admin_role)
    representative = Role.query.filter_by(key='management_representative').one()
    representative.permissions.append(RolePermission(permission_key='custom.existing'))
    user = create_user('ordinary', 'management_representative')
    db.session.commit()
    roles = {r.key: (r.name, r.hierarchy_level, r.permission_keys) for r in Role.query.all()}
    user_state = (user.role_keys, user.password_hash, user.is_active)
    assert configure()['created'] is True
    assert configure()['created'] is False
    for key, expected in roles.items():
        role = Role.query.filter_by(key=key).one()
        assert (role.name, role.hierarchy_level, role.permission_keys) == expected
    assert (user.role_keys, user.password_hash, user.is_active) == user_state
    assert User.query.count() == 1
    assert AuditLog.query.filter_by(entity_type='CompanyAdminRelease', action='configured').count() == 1


def test_release_refuses_to_overwrite_customized_admin_role(app):
    role = Role.query.filter_by(key='company_admin').one()
    role.permissions.append(RolePermission(permission_key='custom.admin'))
    db.session.commit()
    expected = role.permission_keys.copy()
    with pytest.raises(RuntimeError, match='differs'):
        configure()
    db.session.expire_all()
    assert role.permission_keys == expected
