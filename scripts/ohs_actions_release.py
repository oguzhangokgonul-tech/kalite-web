"""Targeted OHS actions module configuration; deployment remains coordinator-owned.

Run with the service environment from the deployed repository, after migration:
  python -m scripts.ohs_actions_release configure

Only missing ohs_actions rows for active companies are inserted, enabled for
every package. Existing toggles and inactive companies are untouched. Existing
actions.* permissions are reused; this does not seed, migrate or mark complete.
"""
import argparse
import json

from sqlalchemy import text

from app import create_app
from app.audit import record_audit_event
from app.config import Config
from app.extensions import db
from app.models import Company, CompanyModule


MODULE_KEY = 'ohs_actions'


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
    _begin_transaction()
    try:
        changes = []
        existing_companies = {company_id for (company_id,) in db.session.query(
            CompanyModule.company_id).filter_by(module_key=MODULE_KEY).all()}
        # This coordinator-only operation intentionally spans active tenants.
        for company in Company.query.filter_by(is_active=True).order_by(Company.id).all():
            if company.id in existing_companies:
                continue
            db.session.add(CompanyModule(company_id=company.id, module_key=MODULE_KEY,
                                         is_enabled=True))
            changes.append(f'company:{company.id}:{MODULE_KEY}:1')
        if changes:
            record_audit_event('OhsActionsRelease', 'configured',
                               'Missing OHS actions module defaults for active companies',
                               details={'changes': changes}, commit=False)
        db.session.commit()
        return changes
    except Exception:
        db.session.rollback()
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    steps = parser.add_subparsers(dest='step', required=True)
    steps.add_parser('configure')
    parser.parse_args(argv)
    app = create_app(ReleaseConfig)
    with app.app_context():
        result = configure()
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
