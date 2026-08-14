from dataclasses import dataclass

from sqlalchemy import inspect, text

from .company_onboarding import company_workspace_status
from .extensions import db
from .models import Company, User


EXPECTED_HEAD = "202608130005"

REQUIRED_TABLES = (
    "companies",
    "users",
    "actions",
    "action_sub_tasks",
    "action_comments",
    "action_histories",
    "action_closure_files",
    "dofs",
    "dof_files",
    "dof_comments",
    "internal_audits",
    "internal_audit_questions",
    "internal_audit_answers",
    "documents",
    "document_categories",
    "maintenance_machines",
    "maintenance_faults",
    "quality_test_records",
    "orientation_nodes",
    "notifications",
    "app_settings",
)

COMPANY_ID_TABLES = (
    "users",
    "actions",
    "action_sub_tasks",
    "action_comments",
    "action_histories",
    "action_closure_files",
    "dofs",
    "dof_files",
    "dof_comments",
    "internal_audits",
    "internal_audit_questions",
    "internal_audit_answers",
    "documents",
    "document_categories",
    "maintenance_machines",
    "maintenance_faults",
    "quality_test_records",
    "orientation_nodes",
    "notifications",
)

COMPANY_SCOPED_UNIQUES = (
    ("users", ("company_id", "username")),
    ("actions", ("company_id", "action_number")),
    ("dofs", ("company_id", "dof_no")),
    ("internal_audits", ("company_id", "audit_no")),
    ("maintenance_faults", ("company_id", "fault_number")),
    ("maintenance_machines", ("company_id", "code")),
    ("document_categories", ("company_id", "slug")),
    ("quality_test_records", ("company_id", "test_type", "record_number")),
)

TENANT_ROW_TABLES = (
    "actions",
    "dofs",
    "internal_audits",
    "documents",
    "maintenance_machines",
    "maintenance_faults",
    "quality_test_records",
    "orientation_nodes",
    "notifications",
)


@dataclass(frozen=True)
class HealthCheck:
    status: str
    message: str


def _table_columns(inspector, table_name):
    return {column["name"] for column in inspector.get_columns(table_name)}


def _unique_columns(inspector, table_name):
    uniques = set()
    for constraint in inspector.get_unique_constraints(table_name):
        columns = constraint.get("column_names") or ()
        uniques.add(tuple(columns))
    return uniques


def _sqlite_unique_columns(table_name):
    sql_rows = db.session.execute(
        text(
            """
            SELECT sql
            FROM sqlite_master
            WHERE type IN ('table', 'index')
              AND tbl_name = :table_name
              AND sql IS NOT NULL
            """
        ),
        {"table_name": table_name},
    ).scalars()

    found = set()
    for sql in sql_rows:
        compact_sql = " ".join(sql.replace("\n", " ").split()).lower()
        for _table_name, columns in COMPANY_SCOPED_UNIQUES:
            expected = ", ".join(columns).lower()
            bracket_expected = ", ".join(f'"{column}"' for column in columns).lower()
            if "unique" in compact_sql and (expected in compact_sql or bracket_expected in compact_sql):
                found.add(tuple(columns))
    return found


def _count_null_company_rows(table_name):
    return db.session.execute(
        text(f"SELECT COUNT(*) FROM {table_name} WHERE company_id IS NULL")
    ).scalar_one()


def collect_tenant_health_checks():
    inspector = inspect(db.engine)
    existing_tables = set(inspector.get_table_names())
    checks = []

    def add(status, message):
        checks.append(HealthCheck(status, message))

    missing_tables = sorted(set(REQUIRED_TABLES) - existing_tables)
    if missing_tables:
        add("FAIL", f"Eksik tablo var: {', '.join(missing_tables)}")
    else:
        add("OK", "Beklenen temel tablolar mevcut.")

    if "alembic_version" in existing_tables:
        version = db.session.execute(text("SELECT version_num FROM alembic_version")).scalar()
        if version == EXPECTED_HEAD:
            add("OK", f"Migration head dogru: {version}")
        else:
            add("FAIL", f"Migration head beklenen degil: {version or 'bos'} / beklenen {EXPECTED_HEAD}")
    else:
        add("FAIL", "alembic_version tablosu bulunamadi.")

    for table_name in COMPANY_ID_TABLES:
        if table_name not in existing_tables:
            continue
        columns = _table_columns(inspector, table_name)
        if "company_id" in columns:
            add("OK", f"{table_name}.company_id mevcut.")
        else:
            add("FAIL", f"{table_name}.company_id eksik.")

    for table_name, columns in COMPANY_SCOPED_UNIQUES:
        if table_name not in existing_tables:
            continue
        unique_columns = _unique_columns(inspector, table_name) | _sqlite_unique_columns(table_name)
        if tuple(columns) in unique_columns:
            add("OK", f"{table_name} firma bazli unique mevcut: {', '.join(columns)}")
        else:
            add("WARN", f"{table_name} firma bazli unique dogrulanamadi: {', '.join(columns)}")

    er_prefabrik = Company.query.filter_by(code="001").first()
    if er_prefabrik:
        add("OK", f"001 firma kaydi mevcut: {er_prefabrik.name}")
    else:
        add("FAIL", "001 Er Prefabrik firma kaydi bulunamadi.")

    demo_company = Company.query.filter_by(code="000").first()
    if demo_company:
        add("OK", f"000 deneme firma kaydi mevcut: {demo_company.name}")
    else:
        add("WARN", "000 deneme firma kaydi bulunamadi.")

    superadmin = User.query.filter_by(username="superadmin").first()
    if not superadmin:
        add("FAIL", "superadmin kullanicisi bulunamadi.")
    elif superadmin.company_id is not None:
        add("FAIL", "superadmin bir firmaya bagli gorunuyor; company_id NULL olmali.")
    else:
        add("OK", "superadmin ortak/global kullanici olarak ayarli.")

    active_without_domain = Company.query.filter(
        Company.is_active.is_(True),
        Company.primary_domain.is_(None),
    ).count()
    if active_without_domain:
        add("WARN", f"{active_without_domain} aktif firmada primary_domain bos.")
    else:
        add("OK", "Aktif firmalarin primary_domain alanlari dolu.")

    for company in Company.query.filter_by(is_active=True).order_by(Company.code.asc()).all():
        status = company_workspace_status(company)
        missing_keys = status["missing_keys"]
        if missing_keys:
            add(
                "WARN",
                f"{company.label} icin eksik baslangic sayaci var: {', '.join(missing_keys)}",
            )
        else:
            add("OK", f"{company.label} baslangic sayaclari hazir.")

    for table_name in TENANT_ROW_TABLES:
        if table_name not in existing_tables or "company_id" not in _table_columns(inspector, table_name):
            continue
        null_count = _count_null_company_rows(table_name)
        if null_count:
            add("WARN", f"{table_name} tablosunda company_id bos {null_count} kayit var.")
        else:
            add("OK", f"{table_name} kayitlari firmaya bagli.")

    return checks


def tenant_health_has_failures(checks):
    return any(check.status == "FAIL" for check in checks)
