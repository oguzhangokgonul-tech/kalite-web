from app.extensions import db
from app.models import CompanyModule, Role, RolePermission
from scripts.custody_release import configure, smoke
from tests.helpers import create_company, create_user


def test_release_configure_idempotence_and_read_only_smoke(app):
    first = create_company('custody-release-a')
    second = create_company('custody-release-b')
    create_user('superadmin', role_key='super_admin')
    for company in (first, second):
        create_user('representative', company=company, role_key='management_representative')
    role = Role.query.filter_by(key='management_representative').one()
    RolePermission.query.filter_by(role_id=role.id, permission_key='custody.manage').delete()
    db.session.commit()
    db.session.expire_all()
    assert 'management_representative:custody.manage' in configure()
    assert configure() == []
    result = smoke(app)
    assert result['checks'] == 4
    assert result['coverage'] == 'partial'
    flag = CompanyModule.query.filter_by(company_id=second.id, module_key='custody_management').one()
    flag.is_enabled = False
    db.session.commit()
    assert smoke(app)['checks'] == 4
