import json
import subprocess
from types import SimpleNamespace

import pytest

from app.company_packages import get_package_module_keys
from app.extensions import db
from app.models import AppSetting, AuditLog, CompanyModule, Role, RolePermission, UserPermission
from app.routes import company_module_state
from app.seed import SHIFT_HANDOVER_ROLE_PERMISSIONS
from scripts import shift_handover_release as release
from tests.helpers import create_company, create_user


HEAD = 'a' * 40


def settings():
    return dict(db.session.query(AppSetting.key, AppSetting.value).all())


def role_grants():
    return {(role.key, permission.permission_key)
            for role in Role.query.all() for permission in role.permissions}


@pytest.fixture()
def verified_head(monkeypatch):
    def run(command, **kwargs):
        assert command == ['git', 'rev-parse', '--verify', 'HEAD']
        assert kwargs['cwd'] == release.REPOSITORY_ROOT
        assert kwargs['check'] and kwargs['timeout'] == 15
        return SimpleNamespace(stdout=HEAD + '\n')

    monkeypatch.setattr(release.subprocess, 'run', run)
    return HEAD


def test_configure_is_targeted_idempotent_and_preserves_custom_grants(app):
    RolePermission.query.filter(RolePermission.permission_key.startswith('shift_handover.')).delete(
        synchronize_session=False)
    viewer = Role.query.filter_by(key='viewer').one()
    viewer.permissions.append(RolePermission(permission_key='shift_handover.manage'))
    viewer.permissions.append(RolePermission(permission_key='custom.release_permission'))
    custom = Role(key='custom_release_role', name='Custom release role')
    custom.permissions.append(RolePermission(permission_key='shift_handover.export'))
    db.session.add(custom)
    db.session.add(AppSetting(key='sales_readiness:unrelated', value='0'))
    db.session.commit()
    user = create_user('custom-grant-user', role_key='viewer', permissions=('shift_handover.receive',))
    db.session.expire_all()
    before, before_settings = role_grants(), settings()
    extras = [(p.user_id, p.permission_key) for p in UserPermission.query.all()]
    expected = {(role, permission) for role, permissions in SHIFT_HANDOVER_ROLE_PERMISSIONS.items()
                for permission in permissions}
    all_permissions = {permission for _, permission in expected}
    assert len(all_permissions) == 6
    expected |= {('super_admin', permission) for permission in all_permissions}

    changes = release.configure()
    assert set(changes) == {f'{role}:{permission}' for role, permission in expected - before}
    assert role_grants() == before | expected
    assert settings() == before_settings
    assert [(p.user_id, p.permission_key) for p in UserPermission.query.all()] == extras
    assert user.has_permission('shift_handover.receive')
    audits = AuditLog.query.filter_by(entity_type='ShiftHandoverRelease', action='configured')
    assert audits.count() == 1
    assert set(json.loads(audits.one().new_values)['changes']) == set(changes)
    assert release.configure() == []
    assert audits.count() == 1
    assert role_grants() == before | expected


def test_configure_materializes_only_missing_module_defaults(app):
    companies = [create_company('release-' + package, package_key=package,
                                module_keys=get_package_module_keys(package))
                 for package in ('iso_core', 'production_plus', 'custom')]
    for company in companies:
        CompanyModule.query.filter_by(company_id=company.id, module_key='shift_handover').delete()
    explicit_on = create_company('release-explicit-on', package_key='iso_core')
    explicit_off = create_company('release-explicit-off', module_keys=())
    inactive = create_company('release-inactive', package_key='custom')
    inactive.is_active = False
    CompanyModule.query.filter_by(company_id=inactive.id, module_key='shift_handover').delete()
    db.session.commit()
    before = {(row.company_id, row.module_key): row.is_enabled for row in CompanyModule.query.all()}
    assert company_module_state(companies[0])['shift_handover'] is True
    changes = release.configure()
    expected = dict(before)
    expected[inactive.id, 'shift_handover'] = False
    for company, enabled in zip(companies, (False, True, True)):
        expected[company.id, 'shift_handover'] = enabled
        assert company_module_state(company)['shift_handover'] is enabled
        assert f'company:{company.id}:shift_handover:{int(enabled)}' in changes
    assert {(row.company_id, row.module_key): row.is_enabled
            for row in CompanyModule.query.all()} == expected
    assert company_module_state(explicit_on)['shift_handover'] is True
    assert company_module_state(explicit_off)['shift_handover'] is False
    assert company_module_state(inactive)['shift_handover'] is False
    assert release.configure() == []


@pytest.mark.parametrize('initial', [None, '0', '1'])
def test_mark_complete_changes_only_one_checklist_flag(app, verified_head, initial):
    admin = create_user('superadmin', role_key='super_admin')
    db.session.add_all([AppSetting(key='sales_readiness:module_custody_management', value='0'),
                        AppSetting(key='sales_readiness:core_package', value='1'),
                        AppSetting(key='unrelated_setting', value='unchanged')])
    if initial is not None:
        db.session.add(AppSetting(key=release.CHECKLIST_KEY, value=initial))
    db.session.commit()
    before, grants = settings(), role_grants()
    result = release.mark_complete(commit=HEAD, verified_release=True)
    assert result == {'checklist': release.CHECKLIST_ID, 'changed': initial != '1', 'commit': HEAD}
    assert settings() == dict(before, **{release.CHECKLIST_KEY: '1'})
    assert role_grants() == grants
    audits = AuditLog.query.filter_by(entity_type='ShiftHandoverRelease', action='checklist_completed')
    assert audits.count() == int(initial != '1')
    if initial != '1':
        audit = audits.one()
        assert audit.user_id == admin.id and audit.entity_id == release.CHECKLIST_ID
        assert json.loads(audit.old_values) == {release.CHECKLIST_KEY: initial}
        assert json.loads(audit.new_values) == {
            release.CHECKLIST_KEY: '1', 'commit': HEAD, 'verified_release': True}
    assert release.mark_complete(commit=HEAD, verified_release=True)['changed'] is False
    assert audits.count() == int(initial != '1')


@pytest.mark.parametrize('commit, acknowledgement', [
    (None, True), ('', True), ('HEAD', True), (HEAD[:7], True), ('b' * 40, True),
    (HEAD, False), (HEAD, None), (HEAD, 'yes'),
])
def test_mark_complete_guard_does_not_write(app, verified_head, commit, acknowledgement):
    before = settings()
    audit_count = AuditLog.query.count()
    with pytest.raises(RuntimeError):
        release.mark_complete(commit=commit, verified_release=acknowledgement)
    assert settings() == before
    assert AuditLog.query.count() == audit_count


@pytest.mark.parametrize('error', [FileNotFoundError('git'), subprocess.CalledProcessError(1, 'git'),
                                 subprocess.TimeoutExpired('git', 15)])
def test_git_verification_fails_closed(app, monkeypatch, error):
    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(release.subprocess, 'run', fail)
    with pytest.raises(RuntimeError, match='Cannot verify'):
        release.mark_complete(commit=HEAD, verified_release=True)
    assert db.session.get(AppSetting, release.CHECKLIST_KEY) is None


@pytest.mark.parametrize('step', ['configure', 'mark-complete'])
def test_audit_failure_rolls_back_release_changes(app, verified_head, monkeypatch, step):
    create_user('superadmin', role_key='super_admin')
    company = create_company('release-rollback', package_key='iso_core')
    CompanyModule.query.filter_by(company_id=company.id, module_key='shift_handover').delete()
    RolePermission.query.filter_by(permission_key='shift_handover.manage').delete()
    db.session.commit()
    db.session.expire_all()
    before, grants = settings(), role_grants()

    def fail(*args, **kwargs):
        assert kwargs['commit'] is False
        db.session.flush()
        raise RuntimeError('audit failed')

    monkeypatch.setattr(release, 'record_audit_event', fail)
    with pytest.raises(RuntimeError, match='audit failed'):
        if step == 'configure':
            release.configure()
        else:
            release.mark_complete(commit=HEAD, verified_release=True)
    assert settings() == before
    assert role_grants() == grants
    assert CompanyModule.query.filter_by(company_id=company.id, module_key='shift_handover').count() == 0
    assert AuditLog.query.filter_by(entity_type='ShiftHandoverRelease').count() == 0


@pytest.mark.parametrize('step', ['configure', 'mark-complete'])
def test_pending_unrelated_changes_are_not_committed(app, verified_head, step):
    db.session.add(AppSetting(key='sales_readiness:unrelated', value='1'))
    with pytest.raises(RuntimeError, match='Pending session changes'):
        if step == 'configure':
            release.configure()
        else:
            release.mark_complete(commit=HEAD, verified_release=True)
    db.session.rollback()
    assert settings() == {}


@pytest.mark.parametrize('argv', [[], ['mark-complete'], ['mark-complete', '--commit', HEAD],
                                 ['mark-complete', '--verified-release'],
                                 ['configure', '--verified-release']])
def test_cli_requires_explicit_command_and_acknowledgement(monkeypatch, argv):
    monkeypatch.setattr(release, 'create_app', lambda config: pytest.fail('must not initialize app'))
    with pytest.raises(SystemExit) as error:
        release.main(argv)
    assert error.value.code == 2


def test_cli_rejects_wrong_head_before_app_startup(monkeypatch, verified_head):
    monkeypatch.setattr(release, 'create_app', lambda config: pytest.fail('must not initialize app'))
    with pytest.raises(RuntimeError, match='does not match'):
        release.main(['mark-complete', '--commit', 'b' * 40, '--verified-release'])


def test_cli_configure_never_marks_complete(app, monkeypatch, capsys):
    def create(config):
        assert config.AUTO_BOOTSTRAP_DATABASE is False
        assert config.MAIL_ENABLED is False
        assert config.NOTIFICATION_AUTO_REMINDERS_ENABLED is False
        return app

    monkeypatch.setattr(release, 'create_app', create)
    monkeypatch.setattr(release, 'mark_complete', lambda **kwargs: pytest.fail('must not mark complete'))
    release.main(['configure'])
    assert isinstance(json.loads(capsys.readouterr().out), list)
    assert db.session.get(AppSetting, release.CHECKLIST_KEY) is None


def test_cli_mark_complete_with_explicit_verified_head(app, verified_head, monkeypatch, capsys):
    create_user('superadmin', role_key='super_admin')
    monkeypatch.setattr(release, 'create_app', lambda config: app)
    monkeypatch.setattr(release, 'configure', lambda: pytest.fail('must not configure'))
    release.main(['mark-complete', '--commit', HEAD, '--verified-release'])
    assert json.loads(capsys.readouterr().out) == {
        'checklist': release.CHECKLIST_ID, 'changed': True, 'commit': HEAD}
    assert settings() == {release.CHECKLIST_KEY: '1'}
