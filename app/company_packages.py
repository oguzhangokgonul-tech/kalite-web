from flask import current_app
from sqlalchemy import inspect, text
from sqlalchemy.exc import OperationalError

from .extensions import db
from .models import COMPANY_MODULE_KEYS


ISO_CORE_PACKAGE_KEY = "iso_core"
PRODUCTION_PLUS_PACKAGE_KEY = "production_plus"
CUSTOM_PACKAGE_KEY = "custom"
DEFAULT_PACKAGE_KEY = ISO_CORE_PACKAGE_KEY

ISO_CORE_MODULE_KEYS = {
    "organization",
    "calibration",
    "human_resources",
    "suggestions",
    "if_management",
    "risk_management",
    "training",
    "internal_audit",
    "management_review",
    "supplier_management",
    "report_center",
    "documents",
}
PRODUCTION_MODULE_KEYS = {
    "maintenance",
    "vehicles",
    "quality_tests",
    "quality_test_concrete",
    "quality_test_methylene",
    "quality_test_water_absorption",
    "quality_test_sieve_analysis",
    "quality_test_rebar_tensile",
}
PRODUCTION_PLUS_MODULE_KEYS = set(COMPANY_MODULE_KEYS)

PACKAGE_CATALOG = (
    {
        "key": ISO_CORE_PACKAGE_KEY,
        "name": "ISO 9001 KYS Çekirdek",
        "description": (
            "Doküman, IF/DÖF, iç denetim, kalibrasyon, risk, eğitim, "
            "öneri/şikayet, YGG, tedarikçi ve rapor merkezi."
        ),
        "icon": "bi-patch-check",
        "module_keys": ISO_CORE_MODULE_KEYS,
    },
    {
        "key": PRODUCTION_PLUS_PACKAGE_KEY,
        "name": "Üretim Plus",
        "description": (
            "Çekirdek kalite sistemi üzerine bakım, araç yönetimi ve kalite "
            "deneyleri eklenir."
        ),
        "icon": "bi-grid",
        "module_keys": PRODUCTION_PLUS_MODULE_KEYS,
    },
    {
        "key": CUSTOM_PACKAGE_KEY,
        "name": "Özel Paket",
        "description": "Müşteriye göre elle seçilmiş modül kombinasyonu.",
        "icon": "bi-sliders",
        "module_keys": None,
    },
)
PACKAGE_KEYS = tuple(item["key"] for item in PACKAGE_CATALOG)
PACKAGE_LABELS = {item["key"]: item["name"] for item in PACKAGE_CATALOG}


def normalize_package_key(package_key):
    package_key = (package_key or DEFAULT_PACKAGE_KEY).strip()
    if package_key in PACKAGE_LABELS:
        return package_key
    return DEFAULT_PACKAGE_KEY


def get_package_module_keys(package_key):
    package_key = normalize_package_key(package_key)
    package = next(item for item in PACKAGE_CATALOG if item["key"] == package_key)
    if package["module_keys"] is None:
        return set(COMPANY_MODULE_KEYS)
    return set(package["module_keys"])


def infer_package_from_modules(module_keys):
    module_keys = set(module_keys or ())
    if module_keys == ISO_CORE_MODULE_KEYS:
        return ISO_CORE_PACKAGE_KEY
    if module_keys == PRODUCTION_PLUS_MODULE_KEYS:
        return PRODUCTION_PLUS_PACKAGE_KEY
    return CUSTOM_PACKAGE_KEY


def package_label(package_key):
    return PACKAGE_LABELS.get(normalize_package_key(package_key), PACKAGE_LABELS[DEFAULT_PACKAGE_KEY])


def is_production_module(module_key):
    return module_key in PRODUCTION_MODULE_KEYS


def ensure_company_package_schema():
    if current_app.extensions.get("company_package_schema_checked"):
        return

    try:
        inspector = inspect(db.engine)
        tables = set(inspector.get_table_names())
        if "companies" in tables:
            columns = {column["name"] for column in inspector.get_columns("companies")}
            with db.engine.begin() as connection:
                if "package_key" not in columns:
                    connection.execute(
                        text(
                            "ALTER TABLE companies "
                            "ADD COLUMN package_key VARCHAR(40) NOT NULL DEFAULT 'production_plus'"
                        )
                    )
                if "is_demo" not in columns:
                    connection.execute(
                        text(
                            "ALTER TABLE companies "
                            "ADD COLUMN is_demo BOOLEAN NOT NULL DEFAULT 0"
                        )
                    )
        current_app.extensions["company_package_schema_checked"] = True
    except OperationalError:
        db.session.rollback()
        current_app.logger.exception("Sirket paket semasi kontrol edilemedi.")
