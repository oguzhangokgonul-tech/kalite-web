from datetime import date

from .extensions import db
from .models import AppSetting


def company_setting_key(company_id, key):
    return f"company:{company_id}:{key}"


def company_counter_defaults(year=None):
    year = year or date.today().year
    return {
        "next_action_number": "1",
        f"next_dof_number_{year}": "1",
        f"next_internal_audit_number_{year}": "1",
        "next_maintenance_fault_number": "1",
    }


def initialize_company_workspace(company, year=None):
    if company is None or company.id is None:
        raise ValueError("company_required")

    created_keys = []
    for key, value in company_counter_defaults(year).items():
        setting_key = company_setting_key(company.id, key)
        if db.session.get(AppSetting, setting_key) is None:
            db.session.add(AppSetting(key=setting_key, value=value))
            created_keys.append(setting_key)

    return created_keys


def company_workspace_status(company, year=None):
    if company is None or company.id is None:
        raise ValueError("company_required")

    expected_keys = [
        company_setting_key(company.id, key)
        for key in company_counter_defaults(year)
    ]
    existing_keys = {
        setting.key
        for setting in AppSetting.query.filter(AppSetting.key.in_(expected_keys)).all()
    }
    return {
        "expected_keys": expected_keys,
        "missing_keys": [
            key for key in expected_keys if key not in existing_keys
        ],
    }
