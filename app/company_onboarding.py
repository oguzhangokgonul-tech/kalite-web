from datetime import date

from flask import current_app
from sqlalchemy import inspect, text
from sqlalchemy.exc import OperationalError

from .extensions import db
from .models import (
    AppSetting,
    CompanyDepartment,
    DEPARTMENTS,
    DocumentCategory,
    DOCUMENT_CATEGORY_DEFAULTS,
)


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


def ensure_company_department_schema():
    if current_app.extensions.get("company_department_schema_checked"):
        return

    try:
        inspector = inspect(db.engine)
        tables = set(inspector.get_table_names())
        with db.engine.begin() as connection:
            if "company_departments" not in tables:
                connection.execute(
                    text(
                        """
                        CREATE TABLE company_departments (
                            id INTEGER NOT NULL PRIMARY KEY,
                            company_id INTEGER NOT NULL,
                            name VARCHAR(160) NOT NULL,
                            sort_order INTEGER NOT NULL DEFAULT 0,
                            is_active BOOLEAN NOT NULL DEFAULT 1,
                            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            FOREIGN KEY(company_id) REFERENCES companies (id),
                            UNIQUE(company_id, name)
                        )
                        """
                    )
                )
            else:
                columns = {
                    column["name"]
                    for column in inspector.get_columns("company_departments")
                }
                department_columns = {
                    "company_id": "ALTER TABLE company_departments ADD COLUMN company_id INTEGER NOT NULL DEFAULT 0",
                    "name": "ALTER TABLE company_departments ADD COLUMN name VARCHAR(160) NOT NULL DEFAULT ''",
                    "sort_order": "ALTER TABLE company_departments ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0",
                    "is_active": "ALTER TABLE company_departments ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT 1",
                    "created_at": "ALTER TABLE company_departments ADD COLUMN created_at DATETIME",
                    "updated_at": "ALTER TABLE company_departments ADD COLUMN updated_at DATETIME",
                }
                for column_name, statement in department_columns.items():
                    if column_name not in columns:
                        connection.execute(text(statement))

            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_company_departments_company_id "
                    "ON company_departments (company_id)"
                )
            )
            connection.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_company_departments_company_name "
                    "ON company_departments (company_id, name)"
                )
            )
        current_app.extensions["company_department_schema_checked"] = True
    except OperationalError:
        db.session.rollback()
        current_app.logger.exception("Şirket departman şeması kontrol edilemedi.")


def normalize_department_names(department_names=None):
    source_names = department_names or DEPARTMENTS
    names = []
    seen = set()
    for name in source_names:
        clean_name = (name or "").strip()
        if not clean_name:
            continue
        key = clean_name.casefold()
        if key in seen:
            continue
        seen.add(key)
        names.append(clean_name[:160])
    return names


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


def initialize_company_departments(company, department_names=None):
    if company is None or company.id is None:
        raise ValueError("company_required")

    ensure_company_department_schema()
    created_names = []
    existing = {
        department.name.casefold(): department
        for department in CompanyDepartment.query.filter_by(company_id=company.id).all()
    }
    for index, department_name in enumerate(normalize_department_names(department_names), start=1):
        key = department_name.casefold()
        department = existing.get(key)
        if department is None:
            db.session.add(
                CompanyDepartment(
                    company_id=company.id,
                    name=department_name,
                    sort_order=index,
                    is_active=True,
                )
            )
            created_names.append(department_name)
            continue
        department.name = department_name
        department.sort_order = index
        department.is_active = True
    return created_names


def initialize_company_document_categories(company):
    if company is None or company.id is None:
        raise ValueError("company_required")

    created_slugs = []
    for category_data in DOCUMENT_CATEGORY_DEFAULTS:
        category = DocumentCategory.query.filter_by(
            company_id=company.id,
            slug=category_data["slug"],
        ).first()
        if category is None:
            category = DocumentCategory(company_id=company.id, **category_data)
            db.session.add(category)
            created_slugs.append(category_data["slug"])
            continue

        for key, value in category_data.items():
            setattr(category, key, value)
        category.is_active = True
    return created_slugs


def initialize_company_onboarding(
    company,
    year=None,
    include_document_categories=True,
    department_names=None,
):
    created_items = {
        "settings": initialize_company_workspace(company, year=year),
        "departments": [],
        "document_categories": [],
    }
    created_items["departments"] = initialize_company_departments(
        company,
        department_names=department_names,
    )
    if include_document_categories:
        created_items["document_categories"] = initialize_company_document_categories(company)
    return created_items


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
    category_count = DocumentCategory.query.filter_by(
        company_id=company.id,
        is_active=True,
    ).count()
    try:
        ensure_company_department_schema()
        department_count = CompanyDepartment.query.filter_by(
            company_id=company.id,
            is_active=True,
        ).count()
    except OperationalError:
        db.session.rollback()
        department_count = 0
    return {
        "expected_keys": expected_keys,
        "missing_keys": [
            key for key in expected_keys if key not in existing_keys
        ],
        "department_count": department_count,
        "departments_ready": department_count > 0,
        "document_category_count": category_count,
        "document_categories_ready": category_count >= len(DOCUMENT_CATEGORY_DEFAULTS),
    }
