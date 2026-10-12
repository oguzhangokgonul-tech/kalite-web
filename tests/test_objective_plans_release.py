import pytest
from sqlalchemy import text

from app.extensions import db
from app.models import AppSetting, AuditLog
from scripts.objective_plans_release import (
    CHECKLIST_ID, CHECKLIST_KEY, REVISION, checklist_values, mark_checklist,
    read_only_database, smoke,
)
from tests.helpers import create_company, create_user, login
from tests.test_quality_objectives import create_objective


def release_fixture(app):
    create_user('superadmin', role_key='super_admin')
    company = create_company('objective-release')
    company.primary_domain = 'objective-release.volkaportal.com'
    manager = create_user('objective-release-manager', company=company,
                          role_key='management_representative')
    staff = create_user('objective-release-staff', company=company,
                        role_key='department_staff')
    create_objective(company, staff, manager)
    db.session.execute(text('CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) PRIMARY KEY)'))
    db.session.execute(text('DELETE FROM alembic_version'))
    db.session.execute(text('INSERT INTO alembic_version VALUES (:revision)'), {'revision': REVISION})
    db.session.add(AppSetting(key='sales_readiness:module_management_calendar', value='0'))
    db.session.commit()
    app.config.update(MAIL_ENABLED=False, NOTIFICATION_AUTO_REMINDERS_ENABLED=False)
    client = app.test_client()
    login(client, manager, company)
    assert client.get('/').status_code == 200
    app.extensions.pop('company_department_schema_checked', None)
    return company


def test_mark_is_explicit_idempotent_and_preserves_other_flags(app):
    release_fixture(app)
    before = checklist_values()
    with pytest.raises(RuntimeError, match='confirmation'):
        mark_checklist(app, confirmation='wrong')
    assert checklist_values() == before
    assert mark_checklist(app, confirmation=CHECKLIST_ID)['changed'] is True
    assert checklist_values() == dict(before, **{CHECKLIST_KEY: '1'})
    assert mark_checklist(app, confirmation=CHECKLIST_ID)['changed'] is False
    assert AuditLog.query.filter_by(entity_type='ObjectivePlansRelease',
                                    action='checklist_completed').count() == 1


def test_mark_rolls_back_when_audit_fails(app, monkeypatch):
    release_fixture(app)
    before = checklist_values()

    def fail(*args, **kwargs):
        raise RuntimeError('audit unavailable')

    monkeypatch.setattr('scripts.objective_plans_release.record_audit_event', fail)
    with pytest.raises(RuntimeError, match='audit unavailable'):
        mark_checklist(app, confirmation=CHECKLIST_ID)
    assert checklist_values() == before


def test_release_smoke_is_read_only_and_reports_missing_role_coverage(app):
    release_fixture(app)
    db.session.remove()
    result = smoke(app)
    assert result['checks'] > 0
    assert result['coverage'] == 'partial'
    assert result['revision'] == REVISION


def test_release_smoke_guard_rejects_even_caught_write(app):
    release_fixture(app)
    db.session.remove()
    with pytest.raises(RuntimeError, match='blocked database writes'):
        with read_only_database():
            try:
                with pytest.raises(Exception):
                    db.session.execute(text("UPDATE app_settings SET value='1' WHERE key=:key"),
                                       {'key': CHECKLIST_KEY})
            finally:
                db.session.rollback()
                db.session.remove()
    assert db.session.get(AppSetting, CHECKLIST_KEY) is None
