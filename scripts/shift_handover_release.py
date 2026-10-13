"""Targeted shift-handover release configuration and guarded checklist completion.

Run with the service environment from the deployed repository:
  python -m scripts.shift_handover_release configure
  python -m scripts.shift_handover_release mark-complete --commit <full-HEAD-hash> --verified-release

Only the release coordinator invokes mark-complete, AFTER deployed HTTP/tenant/
role smoke, backup and migration verification and release approval. The flag is
an explicit operator acknowledgement, not an automated smoke test or approval.
This script never deploys, migrates, seeds users or changes other checklist flags.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess

from sqlalchemy import text

from app import create_app
from app.audit import record_audit_event
from app.company_packages import CUSTOM_PACKAGE_KEY, PRODUCTION_PLUS_PACKAGE_KEY, normalize_package_key
from app.config import Config
from app.extensions import db
from app.models import AppSetting, Company, CompanyModule, Role, RolePermission, User
from app.seed import SHIFT_HANDOVER_ROLE_PERMISSIONS


MODULE_KEY = 'shift_handover'
CHECKLIST_ID = 'module_shift_handover'
CHECKLIST_KEY = 'sales_readiness:' + CHECKLIST_ID
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class ReleaseConfig(Config):
    MAIL_ENABLED = False
    NOTIFICATION_AUTO_REMINDERS_ENABLED = False
    AUTO_BOOTSTRAP_DATABASE = False


def _begin_transaction():
    if db.session.new or db.session.dirty or db.session.deleted:
        raise RuntimeError('Pending session changes; use a dedicated release session')
    db.session.rollback()
    if db.engine.dialect.name == 'sqlite':
        # Serialize release invocations before inspecting missing rows.
        db.session.execute(text('BEGIN IMMEDIATE'))


def configure():
    grants = dict(SHIFT_HANDOVER_ROLE_PERMISSIONS)
    permissions = {permission for values in grants.values() for permission in values}
    if len(permissions) != 6 or any(not p.startswith('shift_handover.') for p in permissions):
        raise RuntimeError('Expected exactly six shift_handover permissions in seed')
    grants['super_admin'] = tuple(sorted(permissions))
    _begin_transaction()
    try:
        changes = []
        for key, expected in grants.items():
            role = Role.query.filter_by(key=key).one()
            existing = {item.permission_key for item in role.permissions}
            for permission in sorted(set(expected) - existing):
                role.permissions.append(RolePermission(permission_key=permission))
                changes.append(f'{key}:{permission}')

        # Missing module rows default to enabled in company_module_state. Make
        # authorized rollout explicit without overwriting any customer selection.
        existing_companies = {company_id for (company_id,) in db.session.query(
            CompanyModule.company_id).filter_by(module_key=MODULE_KEY).all()}
        for company in Company.query.order_by(Company.id).all():
            if company.id in existing_companies:
                continue
            package = normalize_package_key(company.package_key)
            enabled = bool(company.is_active and package in (
                CUSTOM_PACKAGE_KEY, PRODUCTION_PLUS_PACKAGE_KEY))
            db.session.add(CompanyModule(company_id=company.id, module_key=MODULE_KEY,
                                         is_enabled=enabled))
            changes.append(f'company:{company.id}:{MODULE_KEY}:{int(enabled)}')
        if changes:
            record_audit_event('ShiftHandoverRelease', 'configured',
                               'Shift handover permissions and missing package defaults',
                               details={'changes': changes}, commit=False)
        db.session.commit()
        return changes
    except Exception:
        db.session.rollback()
        raise


def verify_release(*, commit, verified_release):
    if verified_release is not True:
        raise RuntimeError('--verified-release acknowledgement is required after deployed smoke')
    if not isinstance(commit, str) or not re.fullmatch(r'(?:[0-9a-f]{40}|[0-9a-f]{64})', commit):
        raise RuntimeError('--commit must be the explicit full git HEAD hash')
    try:
        head = subprocess.run(['git', 'rev-parse', '--verify', 'HEAD'],
                              cwd=REPOSITORY_ROOT, check=True, capture_output=True,
                              text=True, timeout=15).stdout.strip()
    except (OSError, subprocess.SubprocessError) as error:
        raise RuntimeError('Cannot verify deployed git HEAD') from error
    if commit != head:
        raise RuntimeError('--commit does not match deployed git HEAD')
    return head


def mark_complete(*, commit, verified_release):
    head = verify_release(commit=commit, verified_release=verified_release)
    _begin_transaction()
    try:
        admin = User.query.filter_by(username='superadmin', company_id=None, is_active=True).one()
        if not admin.has_role('super_admin'):
            raise RuntimeError('Active global superadmin is required')
        setting = db.session.get(AppSetting, CHECKLIST_KEY)
        old = setting.value if setting else None
        changed = old != '1'
        if changed:
            if setting is None:
                db.session.add(AppSetting(key=CHECKLIST_KEY, value='1'))
            else:
                setting.value = '1'
            record_audit_event('ShiftHandoverRelease', 'checklist_completed',
                               'Shift handover deployed release verified',
                               entity_id=CHECKLIST_ID, user_id=admin.id,
                               old_values={CHECKLIST_KEY: old},
                               new_values={CHECKLIST_KEY: '1', 'commit': head,
                                           'verified_release': True}, commit=False)
        db.session.commit()
        return {'checklist': CHECKLIST_ID, 'changed': changed, 'commit': head}
    except Exception:
        db.session.rollback()
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    steps = parser.add_subparsers(dest='step', required=True)
    steps.add_parser('configure')
    complete = steps.add_parser('mark-complete', help='Coordinator only, after deployed smoke')
    complete.add_argument('--commit', required=True, help='Full verified deployed git HEAD hash')
    complete.add_argument('--verified-release', action='store_true', required=True,
                          help='Acknowledge successful deployed smoke and release verification')
    args = parser.parse_args(argv)
    if args.step == 'mark-complete':
        # Fail before application/database initialization on invalid acknowledgement.
        verify_release(commit=args.commit, verified_release=args.verified_release)
    app = create_app(ReleaseConfig)
    with app.app_context():
        result = configure() if args.step == 'configure' else mark_complete(
            commit=args.commit, verified_release=args.verified_release)
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
