import json

import pytest

from app.company_packages import PACKAGE_KEYS
from app.extensions import db
from app.models import AppSetting, AuditLog, CompanyModule, Role, RolePermission
from scripts import ohs_actions_release as release
from tests.helpers import create_company, create_user


def module_snapshot():
    return {row.id: (row.company_id, row.module_key, row.is_enabled,
                     row.created_at, row.updated_at)
            for row in CompanyModule.query.all()}


def unrelated_snapshot():
    return {name: db.session.execute(table.select()).all()
            for name, table in db.metadata.tables.items()
            if name not in {'company_modules', 'audit_logs'}}


def remove_module(company):
    CompanyModule.query.filter_by(company_id=company.id, module_key=release.MODULE_KEY).delete()
    db.session.commit()


def test_configure_only_missing_active_modules_for_all_packages(app):
    expected_ids = []
    for package in PACKAGE_KEYS:
        for active in (True, False):
            for toggle in (None, True, False):
                company = create_company(f'{package}-{active}-{toggle}', package_key=package)
                company.is_active = active
                module = CompanyModule.query.filter_by(
                    company_id=company.id, module_key=release.MODULE_KEY).one()
                if toggle is None:
                    db.session.delete(module)
                    if active:
                        expected_ids.append(company.id)
                else:
                    module.is_enabled = toggle
                db.session.commit()

    # Custom grants and checklist values must not be normalized by a broad seed.
    viewer = Role.query.filter_by(key='viewer').one()
    viewer.permissions.append(RolePermission(permission_key='custom.release_permission'))
    db.session.add_all([AppSetting(key='sales_readiness:module_ohs_actions', value='0'),
                        AppSetting(key='sales_readiness:unrelated', value='1')])
    db.session.commit()
    create_user('release-viewer', role_key='viewer', permissions=('actions.manage',))
    before_modules, before_unrelated = module_snapshot(), unrelated_snapshot()
    before_audits = AuditLog.query.count()

    changes = release.configure()

    assert changes == [f'company:{company_id}:ohs_actions:1' for company_id in sorted(expected_ids)]
    after_modules = module_snapshot()
    assert {key: after_modules[key] for key in before_modules} == before_modules
    added = [values for key, values in after_modules.items() if key not in before_modules]
    assert sorted(values[:3] for values in added) == [
        (company_id, 'ohs_actions', True) for company_id in sorted(expected_ids)]
    assert unrelated_snapshot() == before_unrelated
    audits = AuditLog.query.filter_by(entity_type='OhsActionsRelease', action='configured')
    assert audits.count() == 1
    assert json.loads(audits.one().new_values) == {'changes': changes}
    assert AuditLog.query.count() == before_audits + len(expected_ids) + 1
    for values in added:
        assert AuditLog.query.filter_by(entity_type='CompanyModule', action='created',
                                        company_id=values[0]).count() >= 1

    audit_count = AuditLog.query.count()
    assert release.configure() == []
    assert module_snapshot() == after_modules
    assert unrelated_snapshot() == before_unrelated
    assert AuditLog.query.count() == audit_count


def test_empty_database_is_noop_without_audit(app):
    before = unrelated_snapshot()
    audit_count = AuditLog.query.count()
    assert release.configure() == []
    assert module_snapshot() == {}
    assert unrelated_snapshot() == before
    assert AuditLog.query.count() == audit_count


@pytest.mark.parametrize('failure', ['audit', 'commit'])
def test_failure_rolls_back_all_module_and_audit_changes(app, monkeypatch, failure):
    for code in ('rollback-one', 'rollback-two'):
        remove_module(create_company(code))
    before_modules, before_unrelated = module_snapshot(), unrelated_snapshot()
    before_audits = AuditLog.query.count()

    def fail(*args, **kwargs):
        if failure == 'audit':
            assert kwargs['commit'] is False
        db.session.flush()
        raise RuntimeError('release failed')

    if failure == 'audit':
        monkeypatch.setattr(release, 'record_audit_event', fail)
    else:
        monkeypatch.setattr(db.session, 'commit', fail)
    with pytest.raises(RuntimeError, match='release failed'):
        release.configure()
    assert module_snapshot() == before_modules
    assert unrelated_snapshot() == before_unrelated
    assert AuditLog.query.count() == before_audits


@pytest.mark.parametrize('pending', ['new', 'dirty', 'deleted'])
def test_pending_changes_are_not_committed_or_discarded(app, pending):
    setting = AppSetting(key='unrelated', value='original')
    db.session.add(setting)
    db.session.commit()
    before_audits = AuditLog.query.count()
    if pending == 'new':
        setting = AppSetting(key='pending', value='new')
        db.session.add(setting)
    elif pending == 'dirty':
        setting.value = 'changed'
    else:
        db.session.delete(setting)
    with pytest.raises(RuntimeError, match='Pending session changes'):
        release.configure()
    assert setting in getattr(db.session, pending)
    db.session.rollback()
    assert db.session.get(AppSetting, 'unrelated').value == 'original'
    assert db.session.get(AppSetting, 'pending') is None
    assert AuditLog.query.count() == before_audits


@pytest.mark.parametrize('argv', [[], ['mark-complete'], ['configure', '--verified-release'],
                                 ['configure', '--commit', 'a' * 40]])
def test_cli_requires_only_explicit_configure(monkeypatch, argv):
    monkeypatch.setattr(release, 'create_app', lambda config: pytest.fail('must not initialize app'))
    with pytest.raises(SystemExit) as error:
        release.main(argv)
    assert error.value.code == 2


def test_cli_configure_uses_guarded_config_and_returns_actual_changes(app, monkeypatch, capsys):
    company = create_company('cli')
    company_id = company.id
    remove_module(company)

    def create(config):
        assert config.AUTO_BOOTSTRAP_DATABASE is False
        assert config.MAIL_ENABLED is False
        assert config.NOTIFICATION_AUTO_REMINDERS_ENABLED is False
        return app

    monkeypatch.setattr(release, 'create_app', create)
    before = unrelated_snapshot()
    release.main(['configure'])
    assert json.loads(capsys.readouterr().out) == [f'company:{company_id}:ohs_actions:1']
    assert unrelated_snapshot() == before
    release.main(['configure'])
    assert json.loads(capsys.readouterr().out) == []
