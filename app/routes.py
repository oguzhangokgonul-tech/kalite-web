from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from functools import wraps
import json
from pathlib import Path
import re
import shutil
import subprocess
from uuid import uuid4

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
from werkzeug.utils import secure_filename
from sqlalchemy import inspect, or_, text
from sqlalchemy.exc import OperationalError

from .extensions import db
from .internal_audit_data import INTERNAL_AUDIT_RESULTS
from .mail import (
    send_action_notification_email,
    send_dof_notification_email,
    send_vehicle_reminder_email,
)
from .models import (
    Action,
    ActionComment,
    ActionClosureFile,
    ActionHistory,
    ActionSubTask,
    ACTION_SUB_TASK_PRIORITIES,
    ACTION_SUB_TASK_STATUSES,
    AppSetting,
    Company,
    CompanyModule,
    COMPANY_MODULE_CATALOG,
    COMPANY_MODULE_KEYS,
    DEPARTMENTS,
    DOCUMENT_CATEGORY_DEFAULTS,
    DOCUMENT_STATUSES,
    DOF_APPROVAL_STEPS,
    DOF_PRIORITIES,
    DOF_SOURCES,
    Document,
    DocumentCategory,
    Dof,
    DofComment,
    DofFile,
    InternalAudit,
    InternalAuditAnswer,
    InternalAuditQuestion,
    LoginAttempt,
    MAINTENANCE_MACHINE_STATUSES,
    MaintenanceFault,
    MaintenanceMachine,
    Notification,
    ORGANIZATION_NODE_TYPES,
    OrientationNode,
    QUALITY_TEST_MODULE_BY_SLUG,
    DEFAULT_SUGGESTION_SCORE_PARAMETERS,
    QualityTestRecord,
    Role,
    RolePermission,
    SUGGESTION_STATUSES,
    Suggestion,
    SuggestionEvaluation,
    SuggestionScore,
    SuggestionScoreParameter,
    User,
    UserPermission,
    Vehicle,
    VehicleFuelEntry,
    VehicleOperation,
)
from .tenant import (
    assign_current_company,
    current_company_id,
    ensure_same_company,
    host_looks_local,
    scoped_query,
    tenant_base_url,
    tenant_company_from_host,
    tenant_url_for_company,
)


bp = Blueprint("main", __name__)
HEX_COLOR_PATTERN = re.compile(r"^#[0-9a-fA-F]{6}$")
ALLOWED_EXTENSIONS = {
    "pdf",
    "doc",
    "docx",
    "xls",
    "xlsx",
    "jpg",
    "jpeg",
    "png",
    "webp",
}
DOF_EVIDENCE_EXTENSIONS = {"pdf", "jpg", "jpeg", "png"}
DOF_OPENING_FILE_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
DOF_EVIDENCE_MAX_BYTES = 10 * 1024 * 1024
SUB_ACTION_EVIDENCE_EXTENSIONS = {"pdf", "jpg", "jpeg", "png", "docx", "xlsx"}
DOCUMENT_ALLOWED_EXTENSIONS = {
    "pdf",
    "doc",
    "docx",
    "xls",
    "xlsx",
    "ppt",
    "pptx",
    "png",
    "jpg",
    "jpeg",
}
DOCUMENT_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg"}
DOCUMENT_OFFICE_EXTENSIONS = {"doc", "docx", "xls", "xlsx", "ppt", "pptx"}
DOCUMENT_PREVIEW_STATUSES = {"pending", "ready", "failed", "not_supported"}
DOCUMENT_MAX_BYTES = 25 * 1024 * 1024
DOCUMENT_DEPARTMENTS = ("Tüm Departmanlar", *DEPARTMENTS)
INTERNAL_AUDIT_RESULT_MAP = {
    value: {"label": label, "tone": tone}
    for value, label, tone in INTERNAL_AUDIT_RESULTS
}
INTERNAL_AUDIT_FINDING_REQUIRED_RESULTS = {"Kısmen Uygun", "Uygun Değil"}
DEFAULT_INTERNAL_AUDIT_OPTION_TEXT = ", ".join(
    value for value, _label, _tone in INTERNAL_AUDIT_RESULTS
)
INTERNAL_AUDIT_LOCKED_DEPARTMENT = "Kalite Yönetim Departmanı"
INTERNAL_AUDIT_STANDARD_CHOICES = (
    "ISO 9001:2015 - Kalite Yönetim Sistemi",
    (
        "ISO 9001:2015 - Kalite Yönetim Sistemi + "
        "TSE K 118:2018 - Ön Dökümlü Betonarme Yapı Elemanları Kalite Yönetim Sistemi"
    ),
    "TSE K 118:2018 - Ön Dökümlü Betonarme Yapı Elemanları Kalite Yönetim Sistemi",
)
UNPLANNED_MAINTENANCE_VALUE = "__unplanned__"
UNPLANNED_MAINTENANCE_CODE = "PLANSIZ-BAKIM"
UNPLANNED_MAINTENANCE_LABEL = "Plansız Bakım Talebi"
QUALITY_TESTS = (
    {"slug": "beton-deneyi", "title": "Beton Deneyi", "icon": "bi-box-seam"},
    {"slug": "metilen-deneyi", "title": "Metilen Deneyi", "icon": "bi-droplet"},
    {"slug": "su-emme-deneyi", "title": "Su Emme Deneyi", "icon": "bi-moisture"},
    {"slug": "elek-analizi-deneyi", "title": "Elek Analizi Deneyi", "icon": "bi-grid-3x3-gap"},
    {"slug": "demir-cekme-deneyi", "title": "Demir Çekme Deneyi", "icon": "bi-bezier2"},
)
QUALITY_TEST_ELEMENT_OPTIONS = (
    "Öngermeli Makas",
    "Öngermeli Aşık",
    "Öngermeli TT Plak",
    "Kolon",
    "Kiriş",
)
QUALITY_TEST_CONCRETE_CLASS_OPTIONS = ("C30", "C35", "C40", "C45", "C50", "C55")
CONCRETE_STRENGTH_TONES = (
    ("success", "Yeşil", "bi-check-circle-fill"),
    ("warning", "Turuncu", "bi-exclamation-circle-fill"),
    ("danger", "Kırmızı", "bi-x-circle-fill"),
)
CONCRETE_STRENGTH_OPERATOR_OPTIONS = (
    ("gte", ">= Büyük eşit"),
    ("gt", "> Büyük"),
    ("lte", "<= Küçük eşit"),
    ("lt", "< Küçük"),
    ("between", "Arasında"),
    ("plus_minus", "+/- Tolerans aralığı"),
)
CONCRETE_STRENGTH_OPERATOR_VALUES = {
    value for value, _label in CONCRETE_STRENGTH_OPERATOR_OPTIONS
}
CONCRETE_STRENGTH_RULE_FIELDS = ("operator", "value", "value_to")
DEFAULT_CONCRETE_STRENGTH_PARAMETERS = {
    "C30": {
        "success": {"operator": "gte", "value": 30.0, "value_to": None},
        "warning": {"operator": "between", "value": 27.0, "value_to": 29.99},
        "danger": {"operator": "lte", "value": 26.99, "value_to": None},
    },
    "C35": {
        "success": {"operator": "gte", "value": 35.0, "value_to": None},
        "warning": {"operator": "between", "value": 31.5, "value_to": 34.99},
        "danger": {"operator": "lte", "value": 31.49, "value_to": None},
    },
    "C40": {
        "success": {"operator": "gte", "value": 40.0, "value_to": None},
        "warning": {"operator": "between", "value": 36.0, "value_to": 39.99},
        "danger": {"operator": "lte", "value": 35.99, "value_to": None},
    },
    "C45": {
        "success": {"operator": "gte", "value": 45.0, "value_to": None},
        "warning": {"operator": "between", "value": 40.5, "value_to": 44.99},
        "danger": {"operator": "lte", "value": 40.49, "value_to": None},
    },
    "C50": {
        "success": {"operator": "gte", "value": 50.0, "value_to": None},
        "warning": {"operator": "between", "value": 45.0, "value_to": 49.99},
        "danger": {"operator": "lte", "value": 44.99, "value_to": None},
    },
    "C55": {
        "success": {"operator": "gte", "value": 55.0, "value_to": None},
        "warning": {"operator": "between", "value": 49.5, "value_to": 54.99},
        "danger": {"operator": "lte", "value": 49.49, "value_to": None},
    },
}


@bp.app_errorhandler(403)
def forbidden(error):
    return render_template("403.html"), 403


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def assigned_tasks_badge_count():
    if g.current_user is None:
        return 0

    user_id = g.current_user.id
    return (
        scoped_query(Action.query, Action).filter_by(responsible_user_id=user_id).count()
        + scoped_query(ActionSubTask.query, ActionSubTask)
        .filter_by(responsible_id=user_id)
        .count()
        + scoped_query(Dof.query, Dof).filter_by(responsible_id=user_id).count()
        + scoped_query(MaintenanceFault.query, MaintenanceFault)
        .filter_by(responsible_user_id=user_id)
        .count()
        + scoped_query(InternalAudit.query, InternalAudit)
        .filter(
            or_(
                InternalAudit.auditor_id == user_id,
                InternalAudit.audited_user_id == user_id,
            )
        ).count()
    )


@bp.before_app_request
def load_logged_in_user():
    user_id = session.get("user_id")
    g.current_user = User.query.get(user_id) if user_id else None
    g.current_company = None
    g.tenant_company = tenant_company_from_host(request.host)
    session.pop("company_code", None)
    g.current_user_initials = ""
    g.unread_notification_count = 0
    g.latest_notifications = []
    g.assigned_tasks_count = 0
    g.current_user_is_super_admin = False
    g.enabled_company_modules = default_company_module_state(True)
    g.company_module_enabled = company_module_enabled
    ensure_login_attempt_schema()
    if g.current_user is not None:
        g.current_user_initials = user_initials(g.current_user)
        g.current_user_is_super_admin = has_role(g.current_user, "super_admin")
        session_company_id = session.get("company_id")
        if g.tenant_company is not None and session_company_id != g.tenant_company.id:
            g.current_company = g.tenant_company
            session["company_id"] = g.tenant_company.id
        elif session_company_id:
            g.current_company = db.session.get(Company, session_company_id)
        elif g.tenant_company is not None:
            g.current_company = g.tenant_company
            session["company_id"] = g.tenant_company.id
        elif g.current_user.company_id and not g.current_user_is_super_admin:
            g.current_company = db.session.get(Company, g.current_user.company_id)
            if g.current_company is not None:
                session["company_id"] = g.current_company.id
        g.enabled_company_modules = company_module_state(g.current_company)
        enforce_company_module_access()
        ensure_notification_dof_column()
        ensure_dof_rejection_schema()
        ensure_dof_files_schema()
        ensure_internal_audit_schema()
        ensure_action_sub_task_schema()
        ensure_document_schema()
        ensure_maintenance_schema()
        ensure_quality_test_schema()
        ensure_suggestion_schema()
        try:
            notification_query = scoped_query(
                Notification.query,
                Notification,
            ).filter_by(user_id=g.current_user.id)
            g.unread_notification_count = notification_query.filter_by(
                is_read=False
            ).count()
            g.latest_notifications = (
                notification_query.order_by(Notification.created_at.desc())
                .limit(5)
                .all()
            )
            g.assigned_tasks_count = assigned_tasks_badge_count()
        except OperationalError:
            db.session.rollback()
            current_app.logger.exception("Bildirimler yüklenemedi.")


def ensure_notification_dof_column():
    if current_app.extensions.get("notification_dof_column_checked"):
        return

    try:
        inspector = inspect(db.engine)
        if "notifications" in inspector.get_table_names():
            columns = {
                column["name"] for column in inspector.get_columns("notifications")
            }
            if "dof_id" not in columns:
                with db.engine.begin() as connection:
                    connection.execute(
                        text("ALTER TABLE notifications ADD COLUMN dof_id INTEGER")
                    )
        current_app.extensions["notification_dof_column_checked"] = True
    except OperationalError as error:
        if "duplicate column name" in str(error).lower():
            current_app.extensions["notification_dof_column_checked"] = True
            return
        db.session.rollback()
        current_app.logger.exception("İF bildirim kolonu kontrol edilemedi.")


def ensure_login_attempt_schema():
    if current_app.extensions.get("login_attempt_schema_checked"):
        return

    try:
        inspector = inspect(db.engine)
        tables = set(inspector.get_table_names())
        with db.engine.begin() as connection:
            if "login_attempts" not in tables:
                connection.execute(
                    text(
                        """
                        CREATE TABLE login_attempts (
                            id INTEGER NOT NULL PRIMARY KEY,
                            username VARCHAR(160),
                            ip_address VARCHAR(45),
                            user_agent VARCHAR(255),
                            success BOOLEAN NOT NULL DEFAULT 0,
                            reason VARCHAR(40) NOT NULL,
                            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                        )
                        """
                    )
                )
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_login_attempts_username_created_at "
                    "ON login_attempts (username, created_at)"
                )
            )
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_login_attempts_ip_created_at "
                    "ON login_attempts (ip_address, created_at)"
                )
            )
        current_app.extensions["login_attempt_schema_checked"] = True
    except OperationalError:
        db.session.rollback()
        current_app.logger.exception("Login deneme semasi kontrol edilemedi.")


def ensure_dof_rejection_schema():
    if current_app.extensions.get("dof_rejection_schema_checked"):
        return

    try:
        inspector = inspect(db.engine)
        tables = set(inspector.get_table_names())
        if "dofs" in tables:
            columns = {column["name"] for column in inspector.get_columns("dofs")}
            column_sql = {
                "rejection_reason": "ALTER TABLE dofs ADD COLUMN rejection_reason TEXT",
                "rejected_by_user_id": "ALTER TABLE dofs ADD COLUMN rejected_by_user_id INTEGER",
                "rejected_at": "ALTER TABLE dofs ADD COLUMN rejected_at DATETIME",
                "rejected_step": "ALTER TABLE dofs ADD COLUMN rejected_step VARCHAR(40)",
            }
            with db.engine.begin() as connection:
                for column_name, statement in column_sql.items():
                    if column_name not in columns:
                        connection.execute(text(statement))
                if "dof_comments" not in tables:
                    connection.execute(
                        text(
                            """
                            CREATE TABLE dof_comments (
                                id INTEGER PRIMARY KEY,
                                dof_id INTEGER NOT NULL,
                                user_id INTEGER,
                                comment TEXT NOT NULL,
                                comment_type VARCHAR(40) NOT NULL DEFAULT 'note',
                                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                            )
                            """
                        )
                    )
        current_app.extensions["dof_rejection_schema_checked"] = True
    except OperationalError:
        db.session.rollback()
        current_app.logger.exception("İF red/revizyon şeması kontrol edilemedi.")


def ensure_dof_files_schema():
    if current_app.extensions.get("dof_files_schema_checked"):
        return

    try:
        inspector = inspect(db.engine)
        tables = set(inspector.get_table_names())
        if "dofs" in tables and "dof_files" not in tables:
            with db.engine.begin() as connection:
                connection.execute(
                    text(
                        """
                        CREATE TABLE dof_files (
                            id INTEGER PRIMARY KEY,
                            dof_id INTEGER NOT NULL,
                            original_name VARCHAR(255) NOT NULL,
                            stored_name VARCHAR(255) NOT NULL,
                            mime_type VARCHAR(120),
                            file_type VARCHAR(40) NOT NULL DEFAULT 'opening',
                            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                        )
                        """
                    )
                )
        current_app.extensions["dof_files_schema_checked"] = True
    except OperationalError:
        db.session.rollback()
        current_app.logger.exception("İF dosya şeması kontrol edilemedi.")


def ensure_internal_audit_schema():
    if current_app.extensions.get("internal_audit_schema_checked"):
        return

    try:
        inspector = inspect(db.engine)
        tables = set(inspector.get_table_names())
        with db.engine.begin() as connection:
            if "internal_audits" not in tables:
                connection.execute(
                    text(
                        """
                        CREATE TABLE internal_audits (
                            id INTEGER PRIMARY KEY,
                            company_id INTEGER,
                            audit_no VARCHAR(30) NOT NULL,
                            title VARCHAR(160) NOT NULL,
                            auditor_id INTEGER,
                            evaluated_department VARCHAR(80),
                            audited_user_id INTEGER,
                            planned_date DATE,
                            status VARCHAR(40) NOT NULL DEFAULT 'Devam Ediyor',
                            active_question_order INTEGER NOT NULL DEFAULT 1,
                            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            UNIQUE(company_id, audit_no)
                        )
                        """
                    )
                )
                tables.add("internal_audits")
            else:
                columns = {
                    column["name"]
                    for column in inspector.get_columns("internal_audits")
                }
                if "evaluated_department" not in columns:
                    connection.execute(
                        text(
                            "ALTER TABLE internal_audits "
                            "ADD COLUMN evaluated_department VARCHAR(80)"
                        )
                    )
                if "audited_user_id" not in columns:
                    connection.execute(
                        text(
                            "ALTER TABLE internal_audits "
                            "ADD COLUMN audited_user_id INTEGER"
                        )
                    )
                if "internal_audit_questions" in tables:
                    connection.execute(
                        text(
                            """
                            UPDATE internal_audits
                            SET evaluated_department = (
                                SELECT q.evaluated_department
                                FROM internal_audit_questions q
                                WHERE q.audit_id = internal_audits.id
                                  AND q.evaluated_department IS NOT NULL
                                  AND q.evaluated_department != ''
                                ORDER BY q.order_no ASC, q.id ASC
                                LIMIT 1
                            )
                            WHERE evaluated_department IS NULL
                               OR evaluated_department = ''
                            """
                        )
                    )

            if "internal_audit_questions" not in tables:
                connection.execute(
                    text(
                        """
                        CREATE TABLE internal_audit_questions (
                            id INTEGER PRIMARY KEY,
                            audit_id INTEGER NOT NULL,
                            order_no INTEGER NOT NULL,
                            standard VARCHAR(160) NOT NULL,
                            audit_topic VARCHAR(200) NOT NULL,
                            audit_subject TEXT,
                            question_text TEXT NOT NULL,
                            evaluated_department VARCHAR(80),
                            evaluator_department VARCHAR(80),
                            answer_options TEXT,
                            expected_answer TEXT,
                            is_required BOOLEAN NOT NULL DEFAULT 1,
                            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                        )
                        """
                    )
                )
                tables.add("internal_audit_questions")
            else:
                columns = {
                    column["name"]
                    for column in inspector.get_columns("internal_audit_questions")
                }
                if "answer_options" not in columns:
                    connection.execute(
                        text(
                            "ALTER TABLE internal_audit_questions "
                            "ADD COLUMN answer_options TEXT"
                        )
                    )
                if "expected_answer" not in columns:
                    connection.execute(
                        text(
                            "ALTER TABLE internal_audit_questions "
                            "ADD COLUMN expected_answer TEXT"
                        )
                    )
                if "evaluator_department" not in columns:
                    connection.execute(
                        text(
                            "ALTER TABLE internal_audit_questions "
                            "ADD COLUMN evaluator_department VARCHAR(80)"
                        )
                    )
                if "audit_subject" not in columns:
                    connection.execute(
                        text(
                            "ALTER TABLE internal_audit_questions "
                            "ADD COLUMN audit_subject TEXT"
                        )
                    )

            if "internal_audit_answers" not in tables:
                connection.execute(
                    text(
                        """
                        CREATE TABLE internal_audit_answers (
                            id INTEGER PRIMARY KEY,
                            audit_id INTEGER NOT NULL,
                            question_id INTEGER NOT NULL,
                            standard VARCHAR(160) NOT NULL,
                            audit_topic VARCHAR(200) NOT NULL,
                            audit_subject TEXT,
                            question_text TEXT NOT NULL,
                            evaluated_department VARCHAR(80),
                            evaluator_department VARCHAR(80),
                            technical_findings TEXT,
                            result VARCHAR(40),
                            previous_nonconformity_id INTEGER,
                            dof_id INTEGER,
                            answered_by_user_id INTEGER,
                            answered_at DATETIME,
                            is_draft BOOLEAN NOT NULL DEFAULT 1,
                            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                        )
                        """
                    )
                )
            else:
                columns = {
                    column["name"]
                    for column in inspector.get_columns("internal_audit_answers")
                }
                if "evaluator_department" not in columns:
                    connection.execute(
                        text(
                            "ALTER TABLE internal_audit_answers "
                            "ADD COLUMN evaluator_department VARCHAR(80)"
                        )
                    )
                if "audit_subject" not in columns:
                    connection.execute(
                        text(
                            "ALTER TABLE internal_audit_answers "
                            "ADD COLUMN audit_subject TEXT"
                        )
                    )
        current_app.extensions["internal_audit_schema_checked"] = True
    except OperationalError:
        db.session.rollback()
        current_app.logger.exception("İç denetim şeması kontrol edilemedi.")


def ensure_action_sub_task_schema():
    if current_app.extensions.get("action_sub_task_schema_checked"):
        return

    try:
        inspector = inspect(db.engine)
        tables = set(inspector.get_table_names())
        with db.engine.begin() as connection:
            if "action_sub_tasks" not in tables:
                connection.execute(
                    text(
                        """
                        CREATE TABLE action_sub_tasks (
                            id INTEGER PRIMARY KEY,
                            parent_action_id INTEGER NOT NULL,
                            title VARCHAR(160) NOT NULL,
                            description TEXT,
                            responsible_id INTEGER,
                            related_user_1_id INTEGER,
                            related_user_2_id INTEGER,
                            due_date DATE,
                            priority VARCHAR(40) NOT NULL DEFAULT 'Orta',
                            status VARCHAR(40) NOT NULL DEFAULT 'Beklemede',
                            evidence_required BOOLEAN NOT NULL DEFAULT 0,
                            evidence_original_name VARCHAR(255),
                            evidence_stored_name VARCHAR(255),
                            evidence_mime_type VARCHAR(120),
                            closing_note TEXT,
                            completed_at DATETIME,
                            completed_by_user_id INTEGER,
                            created_by_user_id INTEGER,
                            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                        )
                        """
                    )
                )
            else:
                columns = {
                    column["name"]
                    for column in inspector.get_columns("action_sub_tasks")
                }
                if "related_user_1_id" not in columns:
                    connection.execute(
                        text(
                            "ALTER TABLE action_sub_tasks "
                            "ADD COLUMN related_user_1_id INTEGER"
                        )
                    )
                if "related_user_2_id" not in columns:
                    connection.execute(
                        text(
                            "ALTER TABLE action_sub_tasks "
                            "ADD COLUMN related_user_2_id INTEGER"
                        )
                    )
        current_app.extensions["action_sub_task_schema_checked"] = True
    except OperationalError:
        db.session.rollback()
        current_app.logger.exception("Alt aksiyon şeması kontrol edilemedi.")


def ensure_document_schema():
    if current_app.extensions.get("document_schema_checked"):
        return

    try:
        inspector = inspect(db.engine)
        tables = set(inspector.get_table_names())
        with db.engine.begin() as connection:
            if "document_categories" not in tables:
                connection.execute(
                    text(
                        """
                        CREATE TABLE document_categories (
                            id INTEGER PRIMARY KEY,
                            company_id INTEGER,
                            code VARCHAR(10) NOT NULL,
                            name VARCHAR(120) NOT NULL,
                            slug VARCHAR(160) NOT NULL,
                            sort_order INTEGER NOT NULL DEFAULT 0,
                            color VARCHAR(40),
                            icon VARCHAR(80),
                            is_active BOOLEAN NOT NULL DEFAULT 1,
                            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            UNIQUE(company_id, slug)
                        )
                        """
                    )
                )
                tables.add("document_categories")
            else:
                columns = {
                    column["name"]
                    for column in inspector.get_columns("document_categories")
                }
                category_columns = {
                    "code": "ALTER TABLE document_categories ADD COLUMN code VARCHAR(10) NOT NULL DEFAULT ''",
                    "name": "ALTER TABLE document_categories ADD COLUMN name VARCHAR(120) NOT NULL DEFAULT ''",
                    "slug": "ALTER TABLE document_categories ADD COLUMN slug VARCHAR(160)",
                    "sort_order": "ALTER TABLE document_categories ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0",
                    "color": "ALTER TABLE document_categories ADD COLUMN color VARCHAR(40)",
                    "icon": "ALTER TABLE document_categories ADD COLUMN icon VARCHAR(80)",
                    "is_active": "ALTER TABLE document_categories ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT 1",
                    "created_at": "ALTER TABLE document_categories ADD COLUMN created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
                    "updated_at": "ALTER TABLE document_categories ADD COLUMN updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
                }
                for column_name, statement in category_columns.items():
                    if column_name not in columns:
                        connection.execute(text(statement))

            if "documents" not in tables:
                connection.execute(
                    text(
                        """
                        CREATE TABLE documents (
                            id INTEGER PRIMARY KEY,
                            category_id INTEGER NOT NULL,
                            document_code VARCHAR(80) NOT NULL,
                            title VARCHAR(200) NOT NULL,
                            revision_no VARCHAR(40),
                            publish_date DATE,
                            revision_date DATE,
                            department VARCHAR(80),
                            description TEXT,
                            status VARCHAR(40) NOT NULL DEFAULT 'Yayında',
                            file_name VARCHAR(255) NOT NULL,
                            original_file_name VARCHAR(255) NOT NULL,
                            file_path VARCHAR(500) NOT NULL,
                            file_type VARCHAR(20),
                            file_size INTEGER,
                            preview_file_name VARCHAR(255),
                            preview_file_path VARCHAR(500),
                            preview_status VARCHAR(40),
                            preview_error TEXT,
                            preview_generated_at DATETIME,
                            uploaded_by INTEGER,
                            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            archived_at DATETIME
                        )
                        """
                    )
                )
            else:
                columns = {column["name"] for column in inspector.get_columns("documents")}
                document_columns = {
                    "category_id": "ALTER TABLE documents ADD COLUMN category_id INTEGER",
                    "document_code": "ALTER TABLE documents ADD COLUMN document_code VARCHAR(80) NOT NULL DEFAULT ''",
                    "title": "ALTER TABLE documents ADD COLUMN title VARCHAR(200) NOT NULL DEFAULT ''",
                    "revision_no": "ALTER TABLE documents ADD COLUMN revision_no VARCHAR(40)",
                    "publish_date": "ALTER TABLE documents ADD COLUMN publish_date DATE",
                    "revision_date": "ALTER TABLE documents ADD COLUMN revision_date DATE",
                    "department": "ALTER TABLE documents ADD COLUMN department VARCHAR(80)",
                    "description": "ALTER TABLE documents ADD COLUMN description TEXT",
                    "status": "ALTER TABLE documents ADD COLUMN status VARCHAR(40) NOT NULL DEFAULT 'Yayında'",
                    "file_name": "ALTER TABLE documents ADD COLUMN file_name VARCHAR(255) NOT NULL DEFAULT ''",
                    "original_file_name": "ALTER TABLE documents ADD COLUMN original_file_name VARCHAR(255) NOT NULL DEFAULT ''",
                    "file_path": "ALTER TABLE documents ADD COLUMN file_path VARCHAR(500) NOT NULL DEFAULT ''",
                    "file_type": "ALTER TABLE documents ADD COLUMN file_type VARCHAR(20)",
                    "file_size": "ALTER TABLE documents ADD COLUMN file_size INTEGER",
                    "preview_file_name": "ALTER TABLE documents ADD COLUMN preview_file_name VARCHAR(255)",
                    "preview_file_path": "ALTER TABLE documents ADD COLUMN preview_file_path VARCHAR(500)",
                    "preview_status": "ALTER TABLE documents ADD COLUMN preview_status VARCHAR(40)",
                    "preview_error": "ALTER TABLE documents ADD COLUMN preview_error TEXT",
                    "preview_generated_at": "ALTER TABLE documents ADD COLUMN preview_generated_at DATETIME",
                    "uploaded_by": "ALTER TABLE documents ADD COLUMN uploaded_by INTEGER",
                    "created_at": "ALTER TABLE documents ADD COLUMN created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
                    "updated_at": "ALTER TABLE documents ADD COLUMN updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
                    "archived_at": "ALTER TABLE documents ADD COLUMN archived_at DATETIME",
                }
                for column_name, statement in document_columns.items():
                    if column_name not in columns:
                        connection.execute(text(statement))
        current_app.extensions["document_schema_checked"] = True
        ensure_document_categories()
    except OperationalError:
        db.session.rollback()
        current_app.logger.exception("Doküman yönetimi şeması kontrol edilemedi.")


def ensure_document_categories():
    changed = False
    company_id = current_company_id()
    for category_data in DOCUMENT_CATEGORY_DEFAULTS:
        category_query = DocumentCategory.query.filter_by(slug=category_data["slug"])
        if company_id:
            category_query = category_query.filter_by(company_id=company_id)
        else:
            category_query = category_query.filter(DocumentCategory.company_id.is_(None))
        category = category_query.first()
        if category is None:
            category_values = dict(category_data)
            category_values["company_id"] = company_id
            category = DocumentCategory(**category_values)
            db.session.add(category)
            changed = True
            continue

        for key, value in category_data.items():
            if getattr(category, key) != value:
                setattr(category, key, value)
                changed = True
        if category.is_active is False:
            category.is_active = True
            changed = True

    if changed:
        db.session.commit()


def ensure_maintenance_schema():
    if current_app.extensions.get("maintenance_schema_checked"):
        return

    try:
        inspector = inspect(db.engine)
        tables = set(inspector.get_table_names())
        with db.engine.begin() as connection:
            if "maintenance_machines" not in tables:
                connection.execute(
                    text(
                        """
                        CREATE TABLE maintenance_machines (
                            id INTEGER NOT NULL PRIMARY KEY,
                            company_id INTEGER,
                            code VARCHAR(80) NOT NULL,
                            machine_name VARCHAR(180) NOT NULL,
                            brand_model VARCHAR(180),
                            serial_no VARCHAR(120),
                            status VARCHAR(40) NOT NULL DEFAULT 'ÇALIŞIYOR',
                            location VARCHAR(160),
                            notes TEXT,
                            is_active BOOLEAN NOT NULL DEFAULT 1,
                            created_by_user_id INTEGER,
                            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            FOREIGN KEY(created_by_user_id) REFERENCES users (id),
                            UNIQUE(company_id, code)
                        )
                        """
                    )
                )
            else:
                columns = {
                    column["name"]
                    for column in inspector.get_columns("maintenance_machines")
                }
                machine_columns = {
                    "code": "ALTER TABLE maintenance_machines ADD COLUMN code VARCHAR(80) NOT NULL DEFAULT ''",
                    "machine_name": "ALTER TABLE maintenance_machines ADD COLUMN machine_name VARCHAR(180) NOT NULL DEFAULT ''",
                    "brand_model": "ALTER TABLE maintenance_machines ADD COLUMN brand_model VARCHAR(180)",
                    "serial_no": "ALTER TABLE maintenance_machines ADD COLUMN serial_no VARCHAR(120)",
                    "status": "ALTER TABLE maintenance_machines ADD COLUMN status VARCHAR(40) NOT NULL DEFAULT 'ÇALIŞIYOR'",
                    "location": "ALTER TABLE maintenance_machines ADD COLUMN location VARCHAR(160)",
                    "notes": "ALTER TABLE maintenance_machines ADD COLUMN notes TEXT",
                    "is_active": "ALTER TABLE maintenance_machines ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT 1",
                    "created_by_user_id": "ALTER TABLE maintenance_machines ADD COLUMN created_by_user_id INTEGER",
                    "created_at": "ALTER TABLE maintenance_machines ADD COLUMN created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
                    "updated_at": "ALTER TABLE maintenance_machines ADD COLUMN updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
                }
                for column_name, statement in machine_columns.items():
                    if column_name not in columns:
                        connection.execute(text(statement))

            if "maintenance_faults" not in tables:
                connection.execute(
                    text(
                        """
                        CREATE TABLE maintenance_faults (
                            id INTEGER NOT NULL PRIMARY KEY,
                            company_id INTEGER,
                            fault_number INTEGER,
                            machine_id INTEGER NOT NULL,
                            title VARCHAR(180) NOT NULL,
                            description TEXT,
                            status VARCHAR(40) NOT NULL DEFAULT 'Açık',
                            priority VARCHAR(40) NOT NULL DEFAULT 'Orta',
                            reported_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            due_date DATE,
                            completed_at DATETIME,
                            closing_note TEXT,
                            reporting_department VARCHAR(80),
                            reported_by_user_id INTEGER,
                            responsible_user_id INTEGER,
                            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            FOREIGN KEY(machine_id) REFERENCES maintenance_machines (id),
                            FOREIGN KEY(reported_by_user_id) REFERENCES users (id),
                            FOREIGN KEY(responsible_user_id) REFERENCES users (id),
                            UNIQUE(company_id, fault_number)
                        )
                        """
                    )
                )
            else:
                columns = {
                    column["name"]
                    for column in inspector.get_columns("maintenance_faults")
                }
                fault_columns = {
                    "fault_number": "ALTER TABLE maintenance_faults ADD COLUMN fault_number INTEGER",
                    "machine_id": "ALTER TABLE maintenance_faults ADD COLUMN machine_id INTEGER NOT NULL DEFAULT 0",
                    "title": "ALTER TABLE maintenance_faults ADD COLUMN title VARCHAR(180) NOT NULL DEFAULT ''",
                    "description": "ALTER TABLE maintenance_faults ADD COLUMN description TEXT",
                    "status": "ALTER TABLE maintenance_faults ADD COLUMN status VARCHAR(40) NOT NULL DEFAULT 'Açık'",
                    "priority": "ALTER TABLE maintenance_faults ADD COLUMN priority VARCHAR(40) NOT NULL DEFAULT 'Orta'",
                    "reported_at": "ALTER TABLE maintenance_faults ADD COLUMN reported_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
                    "due_date": "ALTER TABLE maintenance_faults ADD COLUMN due_date DATE",
                    "completed_at": "ALTER TABLE maintenance_faults ADD COLUMN completed_at DATETIME",
                    "closing_note": "ALTER TABLE maintenance_faults ADD COLUMN closing_note TEXT",
                    "reporting_department": "ALTER TABLE maintenance_faults ADD COLUMN reporting_department VARCHAR(80)",
                    "reported_by_user_id": "ALTER TABLE maintenance_faults ADD COLUMN reported_by_user_id INTEGER",
                    "responsible_user_id": "ALTER TABLE maintenance_faults ADD COLUMN responsible_user_id INTEGER",
                    "created_at": "ALTER TABLE maintenance_faults ADD COLUMN created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
                    "updated_at": "ALTER TABLE maintenance_faults ADD COLUMN updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
                }
                for column_name, statement in fault_columns.items():
                    if column_name not in columns:
                        connection.execute(text(statement))

            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_maintenance_faults_machine_id "
                    "ON maintenance_faults (machine_id)"
                )
            )
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_maintenance_faults_status "
                    "ON maintenance_faults (status)"
                )
            )

        current_app.extensions["maintenance_schema_checked"] = True
    except OperationalError:
        db.session.rollback()
        current_app.logger.exception("Bakım yönetimi şeması kontrol edilemedi.")


def ensure_quality_test_schema():
    if current_app.extensions.get("quality_test_schema_checked"):
        return

    try:
        inspector = inspect(db.engine)
        tables = set(inspector.get_table_names())
        with db.engine.begin() as connection:
            if "quality_test_records" not in tables:
                connection.execute(
                    text(
                        """
                        CREATE TABLE quality_test_records (
                            id INTEGER NOT NULL PRIMARY KEY,
                            test_type VARCHAR(80) NOT NULL,
                            record_number INTEGER,
                            title VARCHAR(180) NOT NULL,
                            record_date DATE,
                            customer VARCHAR(180),
                            sample_name VARCHAR(180),
                            concrete_class VARCHAR(40),
                            air_temperature FLOAT,
                            strength_2_day FLOAT,
                            strength_2_recorded_at DATETIME,
                            strength_7_day FLOAT,
                            strength_7_recorded_at DATETIME,
                            strength_28_day FLOAT,
                            strength_28_recorded_at DATETIME,
                            status VARCHAR(40) NOT NULL DEFAULT 'Kayıtlı',
                            description TEXT,
                            created_by_user_id INTEGER,
                            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            FOREIGN KEY(created_by_user_id) REFERENCES users (id)
                        )
                        """
                    )
                )
            else:
                columns = {
                    column["name"]
                    for column in inspector.get_columns("quality_test_records")
                }
                record_columns = {
                    "test_type": "ALTER TABLE quality_test_records ADD COLUMN test_type VARCHAR(80) NOT NULL DEFAULT ''",
                    "record_number": "ALTER TABLE quality_test_records ADD COLUMN record_number INTEGER",
                    "title": "ALTER TABLE quality_test_records ADD COLUMN title VARCHAR(180) NOT NULL DEFAULT ''",
                    "record_date": "ALTER TABLE quality_test_records ADD COLUMN record_date DATE",
                    "customer": "ALTER TABLE quality_test_records ADD COLUMN customer VARCHAR(180)",
                    "sample_name": "ALTER TABLE quality_test_records ADD COLUMN sample_name VARCHAR(180)",
                    "concrete_class": "ALTER TABLE quality_test_records ADD COLUMN concrete_class VARCHAR(40)",
                    "air_temperature": "ALTER TABLE quality_test_records ADD COLUMN air_temperature FLOAT",
                    "strength_2_day": "ALTER TABLE quality_test_records ADD COLUMN strength_2_day FLOAT",
                    "strength_2_recorded_at": "ALTER TABLE quality_test_records ADD COLUMN strength_2_recorded_at DATETIME",
                    "strength_7_day": "ALTER TABLE quality_test_records ADD COLUMN strength_7_day FLOAT",
                    "strength_7_recorded_at": "ALTER TABLE quality_test_records ADD COLUMN strength_7_recorded_at DATETIME",
                    "strength_28_day": "ALTER TABLE quality_test_records ADD COLUMN strength_28_day FLOAT",
                    "strength_28_recorded_at": "ALTER TABLE quality_test_records ADD COLUMN strength_28_recorded_at DATETIME",
                    "status": "ALTER TABLE quality_test_records ADD COLUMN status VARCHAR(40) NOT NULL DEFAULT 'Kayıtlı'",
                    "description": "ALTER TABLE quality_test_records ADD COLUMN description TEXT",
                    "created_by_user_id": "ALTER TABLE quality_test_records ADD COLUMN created_by_user_id INTEGER",
                    "created_at": "ALTER TABLE quality_test_records ADD COLUMN created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
                    "updated_at": "ALTER TABLE quality_test_records ADD COLUMN updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
                }
                for column_name, statement in record_columns.items():
                    if column_name not in columns:
                        connection.execute(text(statement))

            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_quality_test_records_test_type "
                    "ON quality_test_records (test_type)"
                )
            )
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_quality_test_records_status "
                    "ON quality_test_records (status)"
                )
            )

        current_app.extensions["quality_test_schema_checked"] = True
    except OperationalError:
        db.session.rollback()
        current_app.logger.exception("Kalite deneyleri şeması kontrol edilemedi.")


def ensure_suggestion_schema():
    if current_app.extensions.get("suggestion_schema_checked"):
        return

    try:
        inspector = inspect(db.engine)
        tables = set(inspector.get_table_names())
        with db.engine.begin() as connection:
            if "suggestion_score_parameters" not in tables:
                connection.execute(
                    text(
                        """
                        CREATE TABLE suggestion_score_parameters (
                            id INTEGER NOT NULL PRIMARY KEY,
                            company_id INTEGER,
                            name VARCHAR(160) NOT NULL,
                            score INTEGER NOT NULL DEFAULT 0,
                            sort_order INTEGER NOT NULL DEFAULT 0,
                            is_active BOOLEAN NOT NULL DEFAULT 1,
                            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            UNIQUE(company_id, name),
                            FOREIGN KEY(company_id) REFERENCES companies (id)
                        )
                        """
                    )
                )
                tables.add("suggestion_score_parameters")
            else:
                columns = {
                    column["name"]
                    for column in inspector.get_columns("suggestion_score_parameters")
                }
                parameter_columns = {
                    "company_id": "ALTER TABLE suggestion_score_parameters ADD COLUMN company_id INTEGER",
                    "name": "ALTER TABLE suggestion_score_parameters ADD COLUMN name VARCHAR(160) NOT NULL DEFAULT ''",
                    "score": "ALTER TABLE suggestion_score_parameters ADD COLUMN score INTEGER NOT NULL DEFAULT 0",
                    "sort_order": "ALTER TABLE suggestion_score_parameters ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0",
                    "is_active": "ALTER TABLE suggestion_score_parameters ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT 1",
                    "created_at": "ALTER TABLE suggestion_score_parameters ADD COLUMN created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
                    "updated_at": "ALTER TABLE suggestion_score_parameters ADD COLUMN updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
                }
                for column_name, statement in parameter_columns.items():
                    if column_name not in columns:
                        connection.execute(text(statement))

            if "suggestions" not in tables:
                connection.execute(
                    text(
                        """
                        CREATE TABLE suggestions (
                            id INTEGER NOT NULL PRIMARY KEY,
                            company_id INTEGER,
                            suggestion_number INTEGER,
                            suggestion_date DATE,
                            evaluation_month VARCHAR(20),
                            department VARCHAR(80),
                            owner_name VARCHAR(160) NOT NULL,
                            definition TEXT NOT NULL,
                            status VARCHAR(40) NOT NULL DEFAULT 'Değerlendirmede',
                            unit_comment TEXT,
                            qdms_no VARCHAR(80),
                            action_responsible VARCHAR(160),
                            action_status VARCHAR(80),
                            detail TEXT,
                            attachment_original_name VARCHAR(255),
                            attachment_stored_name VARCHAR(255),
                            attachment_mime_type VARCHAR(120),
                            created_by_user_id INTEGER,
                            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            UNIQUE(company_id, suggestion_number),
                            FOREIGN KEY(company_id) REFERENCES companies (id),
                            FOREIGN KEY(created_by_user_id) REFERENCES users (id)
                        )
                        """
                    )
                )
                tables.add("suggestions")
            else:
                columns = {column["name"] for column in inspector.get_columns("suggestions")}
                suggestion_columns = {
                    "company_id": "ALTER TABLE suggestions ADD COLUMN company_id INTEGER",
                    "suggestion_number": "ALTER TABLE suggestions ADD COLUMN suggestion_number INTEGER",
                    "suggestion_date": "ALTER TABLE suggestions ADD COLUMN suggestion_date DATE",
                    "evaluation_month": "ALTER TABLE suggestions ADD COLUMN evaluation_month VARCHAR(20)",
                    "department": "ALTER TABLE suggestions ADD COLUMN department VARCHAR(80)",
                    "owner_name": "ALTER TABLE suggestions ADD COLUMN owner_name VARCHAR(160) NOT NULL DEFAULT ''",
                    "definition": "ALTER TABLE suggestions ADD COLUMN definition TEXT NOT NULL DEFAULT ''",
                    "status": "ALTER TABLE suggestions ADD COLUMN status VARCHAR(40) NOT NULL DEFAULT 'Değerlendirmede'",
                    "unit_comment": "ALTER TABLE suggestions ADD COLUMN unit_comment TEXT",
                    "qdms_no": "ALTER TABLE suggestions ADD COLUMN qdms_no VARCHAR(80)",
                    "action_responsible": "ALTER TABLE suggestions ADD COLUMN action_responsible VARCHAR(160)",
                    "action_status": "ALTER TABLE suggestions ADD COLUMN action_status VARCHAR(80)",
                    "detail": "ALTER TABLE suggestions ADD COLUMN detail TEXT",
                    "attachment_original_name": "ALTER TABLE suggestions ADD COLUMN attachment_original_name VARCHAR(255)",
                    "attachment_stored_name": "ALTER TABLE suggestions ADD COLUMN attachment_stored_name VARCHAR(255)",
                    "attachment_mime_type": "ALTER TABLE suggestions ADD COLUMN attachment_mime_type VARCHAR(120)",
                    "created_by_user_id": "ALTER TABLE suggestions ADD COLUMN created_by_user_id INTEGER",
                    "created_at": "ALTER TABLE suggestions ADD COLUMN created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
                    "updated_at": "ALTER TABLE suggestions ADD COLUMN updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
                }
                for column_name, statement in suggestion_columns.items():
                    if column_name not in columns:
                        connection.execute(text(statement))

            if "suggestion_scores" not in tables:
                connection.execute(
                    text(
                        """
                        CREATE TABLE suggestion_scores (
                            id INTEGER NOT NULL PRIMARY KEY,
                            company_id INTEGER,
                            suggestion_id INTEGER NOT NULL,
                            parameter_id INTEGER,
                            parameter_name VARCHAR(160) NOT NULL,
                            score_value INTEGER NOT NULL DEFAULT 0,
                            is_selected BOOLEAN NOT NULL DEFAULT 0,
                            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            UNIQUE(suggestion_id, parameter_id),
                            FOREIGN KEY(company_id) REFERENCES companies (id),
                            FOREIGN KEY(suggestion_id) REFERENCES suggestions (id),
                            FOREIGN KEY(parameter_id) REFERENCES suggestion_score_parameters (id)
                        )
                        """
                    )
                )
                tables.add("suggestion_scores")
            else:
                columns = {
                    column["name"]
                    for column in inspector.get_columns("suggestion_scores")
                }
                score_columns = {
                    "company_id": "ALTER TABLE suggestion_scores ADD COLUMN company_id INTEGER",
                    "suggestion_id": "ALTER TABLE suggestion_scores ADD COLUMN suggestion_id INTEGER NOT NULL DEFAULT 0",
                    "parameter_id": "ALTER TABLE suggestion_scores ADD COLUMN parameter_id INTEGER",
                    "parameter_name": "ALTER TABLE suggestion_scores ADD COLUMN parameter_name VARCHAR(160) NOT NULL DEFAULT ''",
                    "score_value": "ALTER TABLE suggestion_scores ADD COLUMN score_value INTEGER NOT NULL DEFAULT 0",
                    "is_selected": "ALTER TABLE suggestion_scores ADD COLUMN is_selected BOOLEAN NOT NULL DEFAULT 0",
                    "created_at": "ALTER TABLE suggestion_scores ADD COLUMN created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
                    "updated_at": "ALTER TABLE suggestion_scores ADD COLUMN updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
                }
                for column_name, statement in score_columns.items():
                    if column_name not in columns:
                        connection.execute(text(statement))

            if "suggestion_evaluations" not in tables:
                connection.execute(
                    text(
                        """
                        CREATE TABLE suggestion_evaluations (
                            id INTEGER NOT NULL PRIMARY KEY,
                            company_id INTEGER,
                            suggestion_id INTEGER NOT NULL,
                            parameter_id INTEGER NOT NULL,
                            parameter_name VARCHAR(160) NOT NULL,
                            parameter_multiplier INTEGER NOT NULL DEFAULT 0,
                            evaluator_department VARCHAR(80) NOT NULL,
                            evaluator_user_id INTEGER,
                            rating INTEGER NOT NULL DEFAULT 0,
                            comment TEXT,
                            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            UNIQUE(suggestion_id, parameter_id, evaluator_department),
                            FOREIGN KEY(company_id) REFERENCES companies (id),
                            FOREIGN KEY(suggestion_id) REFERENCES suggestions (id),
                            FOREIGN KEY(parameter_id) REFERENCES suggestion_score_parameters (id),
                            FOREIGN KEY(evaluator_user_id) REFERENCES users (id)
                        )
                        """
                    )
                )
                tables.add("suggestion_evaluations")
            else:
                columns = {
                    column["name"]
                    for column in inspector.get_columns("suggestion_evaluations")
                }
                evaluation_columns = {
                    "company_id": "ALTER TABLE suggestion_evaluations ADD COLUMN company_id INTEGER",
                    "suggestion_id": "ALTER TABLE suggestion_evaluations ADD COLUMN suggestion_id INTEGER NOT NULL DEFAULT 0",
                    "parameter_id": "ALTER TABLE suggestion_evaluations ADD COLUMN parameter_id INTEGER NOT NULL DEFAULT 0",
                    "parameter_name": "ALTER TABLE suggestion_evaluations ADD COLUMN parameter_name VARCHAR(160) NOT NULL DEFAULT ''",
                    "parameter_multiplier": "ALTER TABLE suggestion_evaluations ADD COLUMN parameter_multiplier INTEGER NOT NULL DEFAULT 0",
                    "evaluator_department": "ALTER TABLE suggestion_evaluations ADD COLUMN evaluator_department VARCHAR(80) NOT NULL DEFAULT ''",
                    "evaluator_user_id": "ALTER TABLE suggestion_evaluations ADD COLUMN evaluator_user_id INTEGER",
                    "rating": "ALTER TABLE suggestion_evaluations ADD COLUMN rating INTEGER NOT NULL DEFAULT 0",
                    "comment": "ALTER TABLE suggestion_evaluations ADD COLUMN comment TEXT",
                    "created_at": "ALTER TABLE suggestion_evaluations ADD COLUMN created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
                    "updated_at": "ALTER TABLE suggestion_evaluations ADD COLUMN updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
                }
                for column_name, statement in evaluation_columns.items():
                    if column_name not in columns:
                        connection.execute(text(statement))

            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_suggestion_score_parameters_company_id "
                    "ON suggestion_score_parameters (company_id)"
                )
            )
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_suggestions_company_id "
                    "ON suggestions (company_id)"
                )
            )
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_suggestion_scores_company_id "
                    "ON suggestion_scores (company_id)"
                )
            )
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_suggestion_scores_suggestion_id "
                    "ON suggestion_scores (suggestion_id)"
                )
            )
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_suggestion_scores_parameter_id "
                    "ON suggestion_scores (parameter_id)"
                )
            )
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_suggestion_evaluations_company_id "
                    "ON suggestion_evaluations (company_id)"
                )
            )
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_suggestion_evaluations_suggestion_id "
                    "ON suggestion_evaluations (suggestion_id)"
                )
            )
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_suggestion_evaluations_parameter_id "
                    "ON suggestion_evaluations (parameter_id)"
                )
            )

        current_app.extensions["suggestion_schema_checked"] = True
    except OperationalError:
        db.session.rollback()
        current_app.logger.exception("Öneri ve şikayet şeması kontrol edilemedi.")


def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if g.current_user is None:
            return redirect(url_for("main.login", next=request.full_path))
        return view(*args, **kwargs)

    return wrapped_view


def permission_required(permission):
    def decorator(view):
        @wraps(view)
        def wrapped_view(*args, **kwargs):
            if g.current_user is None:
                return redirect(url_for("main.login", next=request.full_path))
            if not has_permission(g.current_user, permission):
                abort(403)
            return view(*args, **kwargs)

        return wrapped_view

    return decorator


def super_admin_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if g.current_user is None:
            return redirect(url_for("main.login", next=request.full_path))
        if not is_super_admin():
            abort(403)
        return view(*args, **kwargs)

    return wrapped_view


QUALITY_TEST_ENDPOINTS = {
    "main.quality_test_page",
    "main.quality_test_parameters",
    "main.create_quality_test_record",
    "main.quality_test_measurement",
}
MODULE_ENDPOINTS = {
    "main.organization": "organization",
    "main.organization_legacy": "organization",
    "main.orientation": "organization",
    "main.create_orientation_node": "organization",
    "main.update_orientation_node": "organization",
    "main.move_orientation_node": "organization",
    "main.delete_orientation_node": "organization",
    "main.maintenance_dashboard": "maintenance",
    "main.create_maintenance_machine": "maintenance",
    "main.edit_maintenance_machine": "maintenance",
    "main.delete_maintenance_machine": "maintenance",
    "main.create_maintenance_fault": "maintenance",
    "main.maintenance_fault_detail": "maintenance",
    "main.edit_maintenance_fault": "maintenance",
    "main.delete_maintenance_fault": "maintenance",
    "main.vehicle_dashboard": "vehicles",
    "main.create_vehicle": "vehicles",
    "main.edit_vehicle": "vehicles",
    "main.delete_vehicle": "vehicles",
    "main.create_vehicle_operation": "vehicles",
    "main.delete_vehicle_operation": "vehicles",
    "main.save_vehicle_fuel": "vehicles",
    "main.suggestions_dashboard": "suggestions",
    "main.create_suggestion": "suggestions",
    "main.edit_suggestion": "suggestions",
    "main.suggestion_detail": "suggestions",
    "main.evaluate_suggestion": "suggestions",
    "main.delete_suggestion": "suggestions",
    "main.download_suggestion_attachment": "suggestions",
    "main.suggestion_parameters": "suggestions",
    "main.delete_suggestion_parameter": "suggestions",
    "main.complaints_dashboard": "suggestions",
    "main.dof_management": "if_management",
    "main.create_dof": "if_management",
    "main.edit_dof_draft": "if_management",
    "main.dof_detail": "if_management",
    "main.approve_dof_management": "if_management",
    "main.approve_dof_deputy": "if_management",
    "main.reject_dof": "if_management",
    "main.revise_dof": "if_management",
    "main.download_dof_evidence_file": "if_management",
    "main.download_dof_file": "if_management",
    "main.delete_dof": "if_management",
    "main.internal_audit": "internal_audit",
    "main.create_internal_audit": "internal_audit",
    "main.edit_internal_audit": "internal_audit",
    "main.copy_internal_audit": "internal_audit",
    "main.internal_audit_report": "internal_audit",
    "main.internal_audit_personnel_report": "internal_audit",
    "main.delete_internal_audit": "internal_audit",
    "main.internal_audit_question": "internal_audit",
    "main.previous_internal_audit_question": "internal_audit",
    "main.save_internal_audit_answer": "internal_audit",
    "main.open_internal_audit_nonconformity": "internal_audit",
    "main.complete_internal_audit": "internal_audit",
    "main.documents_dashboard": "documents",
    "main.documents_list": "documents",
    "main.documents_category": "documents",
    "main.upload_document": "documents",
    "main.document_detail": "documents",
    "main.edit_document": "documents",
    "main.download_document": "documents",
    "main.preview_document": "documents",
    "main.generate_document_preview_route": "documents",
    "main.archive_document": "documents",
    "main.delete_document": "documents",
}


def company_module_catalog():
    return sorted(COMPANY_MODULE_CATALOG, key=lambda item: item["sort_order"])


def default_company_module_state(enabled=True):
    return {key: enabled for key in COMPANY_MODULE_KEYS}


def company_module_state(company):
    state = default_company_module_state(True)
    if company is None:
        return state

    try:
        settings = CompanyModule.query.filter_by(company_id=company.id).all()
    except OperationalError:
        db.session.rollback()
        return state

    for setting in settings:
        if setting.module_key in state:
            state[setting.module_key] = bool(setting.is_enabled)
    return state


def company_module_parent_key(module_key):
    module = next(
        (item for item in COMPANY_MODULE_CATALOG if item["key"] == module_key),
        None,
    )
    return module.get("parent_key") if module else None


def company_module_enabled(module_key):
    state = getattr(g, "enabled_company_modules", None)
    if state is None:
        state = company_module_state(getattr(g, "current_company", None))
        g.enabled_company_modules = state

    if module_key not in COMPANY_MODULE_KEYS:
        return True

    parent_key = company_module_parent_key(module_key)
    if parent_key and not state.get(parent_key, True):
        return False
    return state.get(module_key, True)


def endpoint_required_company_module(endpoint=None):
    endpoint = endpoint or request.endpoint
    if endpoint in QUALITY_TEST_ENDPOINTS:
        slug = (request.view_args or {}).get("slug")
        if slug:
            return QUALITY_TEST_MODULE_BY_SLUG.get(slug, "quality_tests")
        return "quality_tests"
    return MODULE_ENDPOINTS.get(endpoint)


def enforce_company_module_access():
    if g.current_user is None:
        return
    module_key = endpoint_required_company_module()
    if module_key and not company_module_enabled(module_key):
        abort(403)


def selected_company_module_keys_from_form():
    selected = set(request.form.getlist("enabled_modules"))
    selected = {key for key in selected if key in COMPANY_MODULE_KEYS}
    child_keys = {
        item["key"]
        for item in COMPANY_MODULE_CATALOG
        if item.get("parent_key") == "quality_tests"
    }
    if "quality_tests" not in selected:
        selected -= child_keys
    elif selected & child_keys:
        selected.add("quality_tests")
    return selected


def sync_company_modules(company, selected_keys=None):
    selected_keys = set(COMPANY_MODULE_KEYS if selected_keys is None else selected_keys)
    existing = {
        item.module_key: item
        for item in CompanyModule.query.filter_by(company_id=company.id).all()
    }
    for module_key in COMPANY_MODULE_KEYS:
        setting = existing.get(module_key)
        if setting is None:
            setting = CompanyModule(company_id=company.id, module_key=module_key)
            db.session.add(setting)
        setting.is_enabled = module_key in selected_keys


def company_module_form_state(company):
    if request.method == "POST":
        return {key: key in selected_company_module_keys_from_form() for key in COMPANY_MODULE_KEYS}
    return company_module_state(company)


LEGACY_PERMISSION_ALIASES = {
    "can_create_actions": "actions.create",
    "can_edit_actions": "actions.edit",
    "can_delete_actions": "actions.delete",
    "can_comment_assigned_actions": "actions.comment_assigned",
    "can_close_assigned_actions": "actions.request_close_assigned",
    "can_manage_users": "users.manage",
}


def has_role(user, role_key):
    return bool(user and hasattr(user, "has_role") and user.has_role(role_key))


def has_permission(user, permission):
    if user is None:
        return False
    if has_role(user, "super_admin"):
        return True
    role_permission = LEGACY_PERMISSION_ALIASES.get(permission, permission)
    if hasattr(user, "has_permission") and user.has_permission(role_permission):
        return True
    return bool(getattr(user, permission, False))


def current_user_can(permission):
    return has_permission(g.current_user, permission)


def is_assigned_to_current_user(action):
    return (
        g.current_user is not None
        and action.responsible_user_id is not None
        and action.responsible_user_id == g.current_user.id
    )


def is_related_to_current_user(action):
    return (
        g.current_user is not None
        and g.current_user.id
        in {action.related_user_1_id, action.related_user_2_id}
    )


def is_oguzhan_admin():
    return current_user_can("roles.manage") or has_role(
        g.current_user, "management_representative"
    )


def is_super_admin(user=None):
    user = user or g.current_user
    return has_role(user, "super_admin")


def normalize_for_role(value):
    replacements = str.maketrans(
        {
            "ç": "c",
            "Ç": "c",
            "ğ": "g",
            "Ğ": "g",
            "ı": "i",
            "I": "i",
            "İ": "i",
            "ö": "o",
            "Ö": "o",
            "ş": "s",
            "Ş": "s",
            "ü": "u",
            "Ü": "u",
        }
    )
    return (value or "").translate(replacements).lower()


def user_title_has(user, expected_title):
    return normalize_for_role(expected_title) in normalize_for_role(
        getattr(user, "title", "")
    )


def is_management_representative(user=None):
    user = user or g.current_user
    return user is not None and (
        has_role(user, "super_admin")
        or has_role(user, "management_representative")
        or user_title_has(user, "Yönetim Temsilcisi")
    )


def is_deputy_general_manager(user=None):
    user = user or g.current_user
    return user is not None and (
        has_role(user, "super_admin")
        or has_role(user, "executive_approver")
        or user_title_has(user, "Genel Müdür Yardımcısı")
    )


def is_general_manager(user=None):
    user = user or g.current_user
    if user is None:
        return False
    if has_role(user, "super_admin") or has_role(user, "executive_approver"):
        return True
    normalized_title = normalize_for_role(getattr(user, "title", ""))
    return "genel mudur" in normalized_title and "yardimci" not in normalized_title


def can_view_all_dofs():
    return (
        is_management_representative()
        or is_deputy_general_manager()
        or is_general_manager()
    )


def can_view_dof(dof):
    return (
        g.current_user is not None
        and (
            can_view_all_dofs()
            or dof.responsible_id == g.current_user.id
            or dof.created_by_user_id == g.current_user.id
        )
    )


def can_delete_dof(dof=None):
    return can_view_all_dofs()


def can_edit_dof_draft(dof):
    return (
        g.current_user is not None
        and dof is not None
        and (dof.status == "Taslak" or dof.approval_step == "draft")
        and can_view_dof(dof)
    )


def can_edit_dof(dof):
    if (
        g.current_user is None
        or dof is None
        or dof.status == "Tamamlandı"
        or dof.approval_step == "completed"
    ):
        return False
    return (
        can_edit_dof_draft(dof)
        or can_view_all_dofs()
        or dof.responsible_id == g.current_user.id
        or dof.created_by_user_id == g.current_user.id
    )


def can_approve_dof_management(dof):
    return (
        is_management_representative()
        and dof.approval_step == "management_representative"
        and dof.status != "Tamamlandı"
    )


def can_approve_dof_deputy(dof):
    return (
        is_deputy_general_manager()
        and dof.approval_step == "general_manager_deputy"
        and dof.status != "Tamamlandı"
    )


def can_reject_dof(dof):
    if (
        g.current_user is None
        or dof.status in {"Taslak", "Tamamlandı"}
        or dof.approval_step not in {"management_representative", "general_manager_deputy"}
    ):
        return False
    return (
        is_general_manager()
        or (
            is_management_representative()
            and dof.approval_step == "management_representative"
        )
        or (
            is_deputy_general_manager()
            and dof.approval_step == "general_manager_deputy"
        )
    )


def can_revise_rejected_dof(dof):
    if (
        g.current_user is None
        or dof.status != "Revizyon Bekleniyor"
        or dof.approval_step != "revision_requested"
    ):
        return False
    if dof.responsible_id == g.current_user.id:
        return True
    return (
        dof.rejected_step == "general_manager_deputy"
        and is_management_representative()
    )


def can_request_dof_approval(dof):
    return can_edit_dof_draft(dof) or can_revise_rejected_dof(dof)


def can_manage_orientation():
    return g.current_user is not None and (
        current_user_can("organization.manage") or current_user_can("users.manage")
    )


def can_complete_action(action):
    if g.current_user is None:
        return False
    return can_approve_closure_action(action)


def can_request_closure_action(action):
    if (
        g.current_user is None
        or is_oguzhan_admin()
        or action.is_completed
        or action.closure_approval_requested
    ):
        return False
    return (
        (
            current_user_can("actions.request_close_assigned")
            and is_assigned_to_current_user(action)
        )
        or (
            current_user_can("actions.comment_assigned")
            and is_related_to_current_user(action)
        )
    )


def can_approve_closure_action(action):
    return (
        is_oguzhan_admin()
        and not action.is_completed
        and action.closure_approval_requested
    )


def can_comment_action(action):
    if g.current_user is None:
        return False
    return is_oguzhan_admin() or (
        current_user_can("actions.comment_assigned")
        and (is_assigned_to_current_user(action) or is_related_to_current_user(action))
    )


def can_reassign_action(action):
    if g.current_user is None:
        return False
    return is_oguzhan_admin() or (
        current_user_can("actions.request_close_assigned")
        and is_assigned_to_current_user(action)
    )


def can_view_action(action):
    if g.current_user is None:
        return False
    return (
        is_oguzhan_admin()
        or is_assigned_to_current_user(action)
        or is_related_to_current_user(action)
        or any(
            g.current_user.id in item.participant_user_ids()
            for item in action.sub_actions
        )
    )


def can_revise_termin(action):
    if g.current_user is None or action.is_completed:
        return False
    return (
        is_oguzhan_admin()
        or is_assigned_to_current_user(action)
        or is_related_to_current_user(action)
    )


def can_create_sub_action(action):
    if g.current_user is None or action.is_completed:
        return False
    return (
        is_oguzhan_admin()
        or current_user_can("actions.edit")
        or is_assigned_to_current_user(action)
        or is_related_to_current_user(action)
    )


def is_sub_action_responsible(sub_action):
    return g.current_user is not None and sub_action.responsible_id == g.current_user.id


def is_sub_action_related(sub_action):
    return g.current_user is not None and g.current_user.id in {
        sub_action.related_user_1_id,
        sub_action.related_user_2_id,
    }


def can_full_edit_sub_action(sub_action):
    action = sub_action.parent_action
    if g.current_user is None or action.is_completed:
        return False
    return (
        is_oguzhan_admin()
        or current_user_can("actions.edit")
        or sub_action.created_by_user_id == g.current_user.id
        or is_assigned_to_current_user(action)
        or is_related_to_current_user(action)
    )


def can_reassign_sub_action(sub_action):
    action = sub_action.parent_action
    if g.current_user is None or action.is_completed:
        return False
    return can_full_edit_sub_action(sub_action) or (
        current_user_can("actions.request_close_assigned")
        and is_sub_action_responsible(sub_action)
    )


def can_revise_sub_action_termin(sub_action):
    action = sub_action.parent_action
    if g.current_user is None or action.is_completed:
        return False
    return (
        can_full_edit_sub_action(sub_action)
        or is_sub_action_responsible(sub_action)
        or is_sub_action_related(sub_action)
    )


def can_edit_sub_action(sub_action):
    return can_full_edit_sub_action(sub_action) or can_reassign_sub_action(
        sub_action
    ) or can_revise_sub_action_termin(sub_action)


def can_delete_sub_action(sub_action):
    return can_full_edit_sub_action(sub_action)


def can_complete_sub_action(sub_action):
    if sub_action.status in {"Tamamlandı", "İptal Edildi"}:
        return False
    return can_full_edit_sub_action(sub_action) or is_sub_action_responsible(sub_action)


def visible_actions_query():
    query = scoped_query(Action.query, Action)
    if is_oguzhan_admin():
        return query
    return query.filter(
        or_(
            Action.responsible_user_id == g.current_user.id,
            Action.related_user_1_id == g.current_user.id,
            Action.related_user_2_id == g.current_user.id,
            Action.sub_actions.any(
                or_(
                    ActionSubTask.responsible_id == g.current_user.id,
                    ActionSubTask.related_user_1_id == g.current_user.id,
                    ActionSubTask.related_user_2_id == g.current_user.id,
                )
            ),
        )
    )


def active_users():
    query = User.query.filter_by(is_active=True)
    company_id = current_company_id()
    if company_id:
        query = query.filter(or_(User.company_id == company_id, User.company_id.is_(None)))
    elif not getattr(g, "current_user_is_super_admin", False):
        query = query.filter(User.company_id == g.current_user.company_id)
    return query.order_by(User.full_name.asc()).all()


def active_user_by_id(user_id):
    query = User.query.filter_by(id=user_id, is_active=True)
    company_id = current_company_id()
    if company_id:
        query = query.filter(or_(User.company_id == company_id, User.company_id.is_(None)))
    elif not getattr(g, "current_user_is_super_admin", False):
        query = query.filter(User.company_id == g.current_user.company_id)
    return query.first()


def user_initials(user):
    parts = (user.full_name or user.username or "").split()
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return f"{parts[0][0]}{parts[-1][0]}".upper()


def oguzhan_user():
    query = User.query.filter_by(username="oguzhan", is_active=True)
    company_id = current_company_id()
    if company_id:
        query = query.filter(User.company_id == company_id)
    elif not getattr(g, "current_user_is_super_admin", False) and g.current_user:
        query = query.filter(User.company_id == g.current_user.company_id)
    return query.first()


def company_counter_key(key):
    company_id = current_company_id()
    return f"company:{company_id}:{key}" if company_id else key


def company_scoped_counter_query(query, model):
    company_id = current_company_id()
    if company_id and hasattr(model, "company_id"):
        return query.filter(model.company_id == company_id)
    return query


def reserve_action_number():
    max_number = (
        company_scoped_counter_query(
            db.session.query(db.func.max(db.func.coalesce(Action.action_number, Action.id))),
            Action,
        )
        .scalar()
        or 0
    )
    setting_key = company_counter_key("next_action_number")
    setting = db.session.get(AppSetting, setting_key)
    if setting is None:
        setting = AppSetting(key=setting_key, value=str(max_number + 1))
        db.session.add(setting)

    next_number = int(setting.value)
    if next_number <= max_number:
        next_number = max_number + 1

    setting.value = str(next_number + 1)
    return next_number


def reserve_dof_number(today=None):
    today = today or date.today()
    year = today.year
    prefix = f"IF-{year}-"
    existing_numbers = (
        company_scoped_counter_query(
            db.session.query(Dof.dof_no),
            Dof,
        )
        .filter(Dof.dof_no.like(f"{prefix}%"))
        .all()
    )
    max_number = 0
    for (dof_no,) in existing_numbers:
        try:
            max_number = max(max_number, int((dof_no or "").replace(prefix, "")))
        except ValueError:
            continue

    setting_key = company_counter_key(f"next_dof_number_{year}")
    setting = db.session.get(AppSetting, setting_key)
    if setting is None:
        setting = AppSetting(key=setting_key, value=str(max_number + 1))
        db.session.add(setting)

    next_number = int(setting.value)
    if next_number <= max_number:
        next_number = max_number + 1

    setting.value = str(next_number + 1)
    return f"{prefix}{next_number:04d}"


def reserve_internal_audit_number(today=None):
    today = today or date.today()
    year = today.year
    prefix = f"ICD-{year}-"
    existing_numbers = (
        company_scoped_counter_query(
            db.session.query(InternalAudit.audit_no),
            InternalAudit,
        )
        .filter(InternalAudit.audit_no.like(f"{prefix}%"))
        .all()
    )
    max_number = 0
    for (audit_no,) in existing_numbers:
        try:
            max_number = max(max_number, int((audit_no or "").replace(prefix, "")))
        except ValueError:
            continue

    setting_key = company_counter_key(f"next_internal_audit_number_{year}")
    setting = db.session.get(AppSetting, setting_key)
    if setting is None:
        setting = AppSetting(key=setting_key, value=str(max_number + 1))
        db.session.add(setting)

    next_number = int(setting.value)
    if next_number <= max_number:
        next_number = max_number + 1

    setting.value = str(next_number + 1)
    return f"{prefix}{next_number:04d}"


def reserve_maintenance_fault_number():
    max_number = (
        company_scoped_counter_query(
            db.session.query(
                db.func.max(db.func.coalesce(MaintenanceFault.fault_number, MaintenanceFault.id))
            ),
            MaintenanceFault,
        )
        .scalar()
        or 0
    )
    setting_key = company_counter_key("next_maintenance_fault_number")
    setting = db.session.get(AppSetting, setting_key)
    if setting is None:
        setting = AppSetting(
            key=setting_key,
            value=str(max_number + 1),
        )
        db.session.add(setting)

    next_number = int(setting.value)
    if next_number <= max_number:
        next_number = max_number + 1

    setting.value = str(next_number + 1)
    return next_number


def quality_test_by_slug(slug):
    return next((test for test in QUALITY_TESTS if test["slug"] == slug), None)


def reserve_quality_test_record_number(slug):
    max_number = (
        company_scoped_counter_query(
            db.session.query(db.func.max(QualityTestRecord.record_number)),
            QualityTestRecord,
        )
        .filter(QualityTestRecord.test_type == slug)
        .scalar()
        or 0
    )
    return max_number + 1


def is_concrete_quality_test(slug):
    return slug == "beton-deneyi"


def can_create_quality_test_record():
    return current_user_can("quality.create") or current_user_can(
        "quality.parameters_manage"
    )


def format_quality_decimal(value, digits=1):
    if value is None:
        return "-"
    rounded = round(float(value), digits)
    if rounded == int(rounded):
        return str(int(rounded))
    return f"{rounded:.{digits}f}".replace(".", ",")


def parse_quality_decimal(field_name):
    value = request.form.get(field_name, "").strip()
    if not value:
        raise ValueError("required_strength")
    try:
        return float(value.replace(",", "."))
    except ValueError:
        raise ValueError("invalid_strength") from None


def parse_required_quality_decimal(field_name):
    value = request.form.get(field_name, "").strip()
    if not value:
        raise ValueError("required_parameter")
    try:
        return float(value.replace(",", "."))
    except ValueError:
        raise ValueError("invalid_parameter") from None


def parse_optional_quality_decimal(field_name):
    value = request.form.get(field_name, "").strip()
    if not value:
        return None
    try:
        return float(value.replace(",", "."))
    except ValueError:
        raise ValueError("invalid_parameter") from None


def concrete_strength_setting_key(concrete_class, field_name):
    return f"concrete_strength_{concrete_class}_{field_name}"


def concrete_strength_rule_setting_key(concrete_class, tone, field_name):
    return f"concrete_strength_{concrete_class}_{tone}_{field_name}"


def format_setting_decimal(value):
    if value is None:
        return ""
    formatted = f"{float(value):.2f}".rstrip("0").rstrip(".")
    return formatted or "0"


def concrete_strength_default_parameters(concrete_class):
    return {
        tone: rule.copy()
        for tone, rule in DEFAULT_CONCRETE_STRENGTH_PARAMETERS[concrete_class].items()
    }


def read_concrete_strength_legacy_value(concrete_class, field_name):
    setting = db.session.get(AppSetting, concrete_strength_setting_key(concrete_class, field_name))
    default_lookup = {
        "green_min": DEFAULT_CONCRETE_STRENGTH_PARAMETERS[concrete_class]["success"]["value"],
        "orange_min": DEFAULT_CONCRETE_STRENGTH_PARAMETERS[concrete_class]["warning"]["value"],
        "red_max": DEFAULT_CONCRETE_STRENGTH_PARAMETERS[concrete_class]["danger"]["value"],
    }
    if setting is None:
        return default_lookup[field_name]
    try:
        return float(setting.value)
    except (TypeError, ValueError):
        return default_lookup[field_name]


def concrete_strength_legacy_parameters(concrete_class):
    green_min = read_concrete_strength_legacy_value(concrete_class, "green_min")
    orange_min = read_concrete_strength_legacy_value(concrete_class, "orange_min")
    red_max = read_concrete_strength_legacy_value(concrete_class, "red_max")
    warning_max = max(orange_min, green_min - 0.01)
    return {
        "success": {"operator": "gte", "value": green_min, "value_to": None},
        "warning": {"operator": "between", "value": orange_min, "value_to": warning_max},
        "danger": {"operator": "lte", "value": red_max, "value_to": None},
    }


def has_concrete_strength_rule_settings(concrete_class):
    for tone, _label, _icon in CONCRETE_STRENGTH_TONES:
        for field_name in CONCRETE_STRENGTH_RULE_FIELDS:
            if db.session.get(
                AppSetting,
                concrete_strength_rule_setting_key(concrete_class, tone, field_name),
            ):
                return True
    return False


def concrete_strength_parameters():
    parameters = {}
    for concrete_class in QUALITY_TEST_CONCRETE_CLASS_OPTIONS:
        defaults = (
            concrete_strength_default_parameters(concrete_class)
            if has_concrete_strength_rule_settings(concrete_class)
            else concrete_strength_legacy_parameters(concrete_class)
        )
        class_parameters = {}
        for tone, _label, _icon in CONCRETE_STRENGTH_TONES:
            class_parameters[tone] = defaults[tone].copy()
            for field_name in CONCRETE_STRENGTH_RULE_FIELDS:
                setting = db.session.get(
                    AppSetting,
                    concrete_strength_rule_setting_key(concrete_class, tone, field_name),
                )
                if setting is None:
                    continue
                if field_name == "operator":
                    if setting.value in CONCRETE_STRENGTH_OPERATOR_VALUES:
                        class_parameters[tone][field_name] = setting.value
                    continue
                try:
                    class_parameters[tone][field_name] = (
                        float(setting.value) if setting.value else None
                    )
                except (TypeError, ValueError):
                    continue
        parameters[concrete_class] = class_parameters
    return parameters


def save_concrete_strength_parameters(parameters):
    for concrete_class, class_parameters in parameters.items():
        for tone, rule in class_parameters.items():
            for field_name in CONCRETE_STRENGTH_RULE_FIELDS:
                value = rule.get(field_name)
                key = concrete_strength_rule_setting_key(concrete_class, tone, field_name)
                setting = db.session.get(AppSetting, key)
                if field_name == "operator":
                    setting_value = value
                else:
                    setting_value = format_setting_decimal(value)
                if setting is None:
                    setting = AppSetting(key=key, value=setting_value)
                    db.session.add(setting)
                else:
                    setting.value = setting_value


def parse_concrete_strength_parameters_form():
    parameters = {}
    for concrete_class in QUALITY_TEST_CONCRETE_CLASS_OPTIONS:
        class_parameters = {}
        for tone, _label, _icon in CONCRETE_STRENGTH_TONES:
            operator = request.form.get(f"{concrete_class}_{tone}_operator", "").strip()
            if operator not in CONCRETE_STRENGTH_OPERATOR_VALUES:
                raise ValueError("invalid_operator")

            rule = {
                "operator": operator,
                "value": parse_required_quality_decimal(f"{concrete_class}_{tone}_value"),
                "value_to": None,
            }
            if operator in {"between", "plus_minus"}:
                rule["value_to"] = parse_required_quality_decimal(
                    f"{concrete_class}_{tone}_value_to"
                )
            if operator == "between" and rule["value"] > rule["value_to"]:
                raise ValueError("invalid_between_range")
            if operator == "plus_minus" and rule["value_to"] < 0:
                raise ValueError("invalid_tolerance")
            class_parameters[tone] = rule
        parameters[concrete_class] = class_parameters
    return parameters


def concrete_strength_rule_matches(value, rule):
    operator = rule.get("operator")
    target = rule.get("value")
    second_value = rule.get("value_to")
    if target is None:
        return False
    if operator == "gt":
        return value > target
    if operator == "gte":
        return value >= target
    if operator == "lt":
        return value < target
    if operator == "lte":
        return value <= target
    if operator == "between":
        if second_value is None:
            return False
        return target <= value <= second_value
    if operator == "plus_minus":
        if second_value is None:
            return False
        tolerance = abs(second_value)
        return (target - tolerance) <= value <= (target + tolerance)
    return False


def concrete_strength_tone(value, concrete_class, parameters):
    if value is None:
        return "muted"
    class_parameters = parameters.get(concrete_class)
    if not class_parameters:
        return "muted"

    value = float(value)
    for tone, _label, _icon in CONCRETE_STRENGTH_TONES:
        if concrete_strength_rule_matches(value, class_parameters.get(tone, {})):
            return tone
    return "muted"


def quality_test_records_context(quality_test):
    filters = {
        "search": request.args.get("search", "").strip(),
        "sample_name": request.args.get("sample_name", "").strip(),
        "concrete_class": request.args.get("concrete_class", "").strip(),
    }
    query = scoped_query(QualityTestRecord.query, QualityTestRecord).filter_by(
        test_type=quality_test["slug"]
    )
    if filters["search"]:
        search_value = f"%{filters['search']}%"
        query = query.filter(
            or_(
                QualityTestRecord.title.ilike(search_value),
                QualityTestRecord.customer.ilike(search_value),
                QualityTestRecord.sample_name.ilike(search_value),
                QualityTestRecord.concrete_class.ilike(search_value),
                QualityTestRecord.description.ilike(search_value),
            )
        )
    if filters["sample_name"]:
        query = query.filter(QualityTestRecord.sample_name == filters["sample_name"])
    if filters["concrete_class"]:
        query = query.filter(QualityTestRecord.concrete_class == filters["concrete_class"])

    records = query.order_by(
        QualityTestRecord.record_number.asc(),
        QualityTestRecord.id.asc(),
    ).all()
    total_count = scoped_query(QualityTestRecord.query, QualityTestRecord).filter_by(
        test_type=quality_test["slug"]
    ).count()
    today = date.today()
    is_concrete = is_concrete_quality_test(quality_test["slug"])
    strength_parameters = concrete_strength_parameters() if is_concrete else {}

    return {
        "quality_test": quality_test,
        "is_concrete_test": is_concrete,
        "records": records,
        "total_count": total_count,
        "filtered_count": len(records),
        "element_count": len({record.sample_name for record in records if record.sample_name}),
        "class_count": len({record.concrete_class for record in records if record.concrete_class}),
        "measurement_waiting_count": (
            sum(1 for record in records if record.current_measurement_day is not None)
            if is_concrete
            else 0
        ),
        "measurement_completed_count": (
            sum(1 for record in records if record.current_measurement_day is None)
            if is_concrete
            else 0
        ),
        "measurement_delayed_count": (
            sum(1 for record in records if record.measurement_tone(today) == "danger")
            if is_concrete
            else 0
        ),
        "today": today,
        "filters": filters,
        "element_options": QUALITY_TEST_ELEMENT_OPTIONS,
        "concrete_class_options": QUALITY_TEST_CONCRETE_CLASS_OPTIONS,
        "format_decimal": format_quality_decimal,
        "strength_parameters": strength_parameters,
        "strength_tone": concrete_strength_tone,
        "can_create_quality_test": can_create_quality_test_record(),
        "can_manage_quality_parameters": is_concrete
        and current_user_can("quality.parameters_manage"),
    }


def parse_quality_test_record_form():
    title = request.form.get("title", "").strip()
    record_date = parse_optional_date("record_date")
    sample_name = request.form.get("sample_name", "").strip()
    concrete_class = request.form.get("concrete_class", "").strip()
    air_temperature = request.form.get("air_temperature", "").strip()
    status = "Kayıtlı"
    description = request.form.get("description", "").strip()

    if not title:
        raise ValueError("required_fields")
    if sample_name and sample_name not in QUALITY_TEST_ELEMENT_OPTIONS:
        raise ValueError("invalid_element")
    if concrete_class and concrete_class not in QUALITY_TEST_CONCRETE_CLASS_OPTIONS:
        raise ValueError("invalid_concrete_class")
    if air_temperature:
        try:
            air_temperature = float(air_temperature.replace(",", "."))
        except ValueError:
            raise ValueError("invalid_temperature") from None
    else:
        air_temperature = None
    if any(
        len(value) > limit
        for value, limit in (
            (title, 180),
            (sample_name, 180),
            (concrete_class, 40),
            (description, 2000),
        )
    ):
        raise ValueError("text_too_long")

    return {
        "title": title,
        "record_date": record_date,
        "customer": None,
        "sample_name": sample_name or None,
        "concrete_class": concrete_class or None,
        "air_temperature": air_temperature,
        "status": status,
        "description": description or None,
    }


def can_view_internal_audit(audit):
    return (
        current_user_can("internal_audit.manage")
        or (
            g.current_user is not None
            and audit is not None
            and g.current_user.id in {audit.auditor_id, audit.audited_user_id}
        )
    )


def can_create_internal_audit():
    return current_user_can("internal_audit.manage")


def can_delete_internal_audit(audit=None):
    return current_user_can("internal_audit.manage")


def can_edit_internal_audit(audit=None):
    return current_user_can("internal_audit.manage")


def can_answer_internal_audit(audit=None):
    return current_user_can("internal_audit.manage")


def visible_internal_audits():
    query = scoped_query(InternalAudit.query, InternalAudit)
    if not current_user_can("internal_audit.manage"):
        query = query.filter(InternalAudit.id == 0)
    return query.order_by(InternalAudit.created_at.desc(), InternalAudit.id.desc()).all()


def internal_audit_option_meta(value):
    if value in INTERNAL_AUDIT_RESULT_MAP:
        return INTERNAL_AUDIT_RESULT_MAP[value]
    normalized = normalize_for_role(value)
    if (
        "hayir" in normalized
        or "uygunsuz" in normalized
        or "uygun degil" in normalized
        or "uygun olmayan" in normalized
    ):
        return {"label": "Uygun Değil", "tone": "danger"}
    if "kismen" in normalized:
        return {"label": "Kısmen Uygun", "tone": "warning"}
    if "evet" in normalized or "uygun" in normalized:
        return {"label": "Uygun", "tone": "success"}
    return {"label": value, "tone": "secondary"}


def internal_audit_canonical_result(value):
    normalized = normalize_for_role(value)
    if not normalized:
        return ""
    if "kismen" in normalized:
        return "Kısmen Uygun"
    if (
        "hayir" in normalized
        or "uygunsuz" in normalized
        or "uygun degil" in normalized
        or "uygun olmayan" in normalized
    ):
        return "Uygun Değil"
    if "evet" in normalized or normalized == "uygun" or "uygun" in normalized:
        return "Uygun"
    return value.strip()


def internal_audit_options_from_text(value):
    raw_options = re.split(r"[\n,;]+", value or "")
    options = []
    seen = set()
    for raw_option in raw_options:
        option = raw_option.strip()
        if not option:
            continue
        key = normalize_for_role(option)
        if key in seen:
            continue
        seen.add(key)
        options.append(option[:80])
    return options


def internal_audit_question_result_choices(question):
    return INTERNAL_AUDIT_RESULTS


def internal_audit_question_result_map(question):
    return {
        value: {"label": label, "tone": tone}
        for value, label, tone in internal_audit_question_result_choices(question)
    }


def internal_audit_result_requires_finding(result):
    return internal_audit_canonical_result(result) in INTERNAL_AUDIT_FINDING_REQUIRED_RESULTS


def parse_internal_audit_builder_form():
    title = request.form.get("title", "").strip() or f"{date.today().year} İç Denetim"
    planned_date = parse_optional_date("planned_date") or date.today()
    evaluated_department = request.form.get("evaluated_department", "").strip()
    audited_user = parse_optional_active_user("audited_user_id")
    raw_indexes = request.form.get("question_indexes", "")
    indexes = [index.strip() for index in raw_indexes.split(",") if index.strip()]
    questions = []

    if not evaluated_department or audited_user is None:
        raise ValueError("audit_scope_required")
    if evaluated_department not in DEPARTMENTS:
        raise ValueError("invalid_department")

    for index in indexes:
        standard = request.form.get(f"standard_{index}", "").strip()
        audit_topic = request.form.get(f"audit_topic_{index}", "").strip()
        audit_subject = request.form.get(f"audit_subject_{index}", "").strip()
        question_text = request.form.get(f"question_text_{index}", "").strip()
        expected_answer = request.form.get(f"expected_answer_{index}", "").strip()
        evaluator_department = INTERNAL_AUDIT_LOCKED_DEPARTMENT
        is_required = request.form.get(f"is_required_{index}") == "on"

        has_any_value = any(
            [
                standard,
                audit_topic,
                audit_subject,
                question_text,
                expected_answer,
            ]
        )
        if not has_any_value:
            continue
        if not standard or not audit_topic or not question_text:
            raise ValueError("question_required_fields")
        if standard not in INTERNAL_AUDIT_STANDARD_CHOICES:
            raise ValueError("invalid_standard")
        if len(question_text) > 2000:
            raise ValueError("question_too_long")
        if len(audit_subject) > 2000:
            raise ValueError("audit_subject_too_long")
        if len(expected_answer) > 2000:
            raise ValueError("expected_answer_too_long")

        questions.append(
            {
                "standard": standard[:160],
                "audit_topic": audit_topic[:200],
                "audit_subject": audit_subject or None,
                "question_text": question_text,
                "evaluated_department": evaluated_department,
                "evaluator_department": evaluator_department,
                "answer_options": [value for value, _label, _tone in INTERNAL_AUDIT_RESULTS],
                "expected_answer": expected_answer or None,
                "is_required": is_required,
            }
        )

    if not questions:
        raise ValueError("no_questions")

    return title[:160], planned_date, evaluated_department, audited_user, questions


def internal_audit_builder_blank_questions():
    return [
        {
            "standard": "ISO 9001:2015 - Kalite Yönetim Sistemi",
            "audit_topic": "",
            "audit_subject": "",
            "question_text": "",
            "evaluator_department": INTERNAL_AUDIT_LOCKED_DEPARTMENT,
            "answer_options": DEFAULT_INTERNAL_AUDIT_OPTION_TEXT,
            "expected_answer": "",
            "is_required": True,
        }
    ]


def internal_audit_builder_questions_from_audit(audit):
    questions = []
    for question in audit.questions:
        questions.append(
            {
                "standard": question.standard,
                "audit_topic": question.audit_topic,
                "audit_subject": question.audit_subject or "",
                "question_text": question.question_text,
                "evaluated_department": audit.evaluated_department
                or question.evaluated_department
                or "",
                "evaluator_department": question.evaluator_department
                or INTERNAL_AUDIT_LOCKED_DEPARTMENT,
                "answer_options": DEFAULT_INTERNAL_AUDIT_OPTION_TEXT,
                "expected_answer": question.expected_answer or "",
                "is_required": question.is_required,
            }
        )
    return questions or internal_audit_builder_blank_questions()


def apply_internal_audit_questions(audit, parsed_questions):
    existing_questions = list(audit.questions)
    for order_no, question_data in enumerate(parsed_questions, start=1):
        if order_no <= len(existing_questions):
            question = existing_questions[order_no - 1]
        else:
            question = InternalAuditQuestion(audit=audit)
            db.session.add(question)

        question.company_id = audit.company_id
        question.order_no = order_no
        question.standard = question_data["standard"]
        question.audit_topic = question_data["audit_topic"]
        question.audit_subject = question_data["audit_subject"]
        question.question_text = question_data["question_text"]
        question.evaluated_department = question_data["evaluated_department"]
        question.evaluator_department = question_data["evaluator_department"]
        question.answer_options = json.dumps(
            question_data["answer_options"],
            ensure_ascii=False,
        )
        question.expected_answer = question_data["expected_answer"]
        question.is_required = question_data["is_required"]

        for answer in question.answers:
            answer.company_id = audit.company_id
            answer.standard = question.standard
            answer.audit_topic = question.audit_topic
            answer.audit_subject = question.audit_subject
            answer.question_text = question.question_text
            answer.evaluated_department = question.evaluated_department
            answer.evaluator_department = question.evaluator_department

    for question in existing_questions[len(parsed_questions):]:
        db.session.delete(question)


def internal_audit_open_question(audit):
    if not audit.questions:
        return None
    return (
        internal_audit_question_by_order(audit, audit.active_question_order or 1)
        or internal_audit_question_by_order(audit, 1)
        or audit.questions[0]
    )


def internal_audit_dashboard_context():
    if not current_user_can("internal_audit.manage"):
        return {
            "can_access_internal_audit": False,
            "audits": [],
            "total_count": 0,
            "active_count": 0,
            "completed_count": 0,
            "empty_question_count": 0,
            "open_question_for_audit": internal_audit_open_question,
            "progress_for_audit": internal_audit_progress,
            "can_delete_internal_audit": False,
            "can_edit_internal_audit": False,
        }

    audits = visible_internal_audits()
    return {
        "can_access_internal_audit": True,
        "audits": audits,
        "total_count": len(audits),
        "active_count": sum(1 for audit in audits if audit.status != "Tamamlandı"),
        "completed_count": sum(1 for audit in audits if audit.status == "Tamamlandı"),
        "empty_question_count": sum(1 for audit in audits if not audit.questions),
        "open_question_for_audit": internal_audit_open_question,
        "progress_for_audit": internal_audit_progress,
        "can_delete_internal_audit": can_delete_internal_audit(),
        "can_edit_internal_audit": can_edit_internal_audit(),
    }


def internal_audit_report_context(audit):
    answers_by_question = internal_audit_answer_map(audit)
    question_rows = []
    result_counts = {}

    for question in audit.questions:
        answer = answers_by_question.get(question.id)
        result = (
            internal_audit_canonical_result(answer.result)
            if answer and not answer.is_draft
            else ""
        )
        result_meta = internal_audit_result_meta(result, question)
        evaluated_department = audit.evaluated_department or (
            answer.evaluated_department
            if answer and answer.evaluated_department
            else question.evaluated_department
        )
        if result:
            result_counts[result] = result_counts.get(result, 0) + 1
        question_rows.append(
            {
                "question": question,
                "answer": answer,
                "result": result,
                "result_label": result_meta["label"],
                "tone": result_meta["tone"],
                "technical_findings": answer.technical_findings if answer else "",
                "evaluated_department": evaluated_department,
                "evaluator_department": (
                    answer.evaluator_department
                    if answer and answer.evaluator_department
                    else question.evaluator_department
                    or INTERNAL_AUDIT_LOCKED_DEPARTMENT
                ),
                "answered_by": audit.audited_user or (answer.answered_by if answer else None),
                "answered_at": answer.answered_at if answer else None,
                "previous_nonconformity": answer.previous_nonconformity if answer else None,
                "dof": answer.dof if answer else None,
            }
        )

    progress = internal_audit_progress(audit)
    return {
        "audit": audit,
        "question_rows": question_rows,
        "progress": progress,
        "result_counts": result_counts,
        "report_generated_at": datetime.utcnow(),
        "prepared_by": g.current_user,
        "locked_department": INTERNAL_AUDIT_LOCKED_DEPARTMENT,
        "evaluated_department": audit.evaluated_department
        or (audit.questions[0].evaluated_department if audit.questions else ""),
        "audited_user": audit.audited_user,
    }


def internal_audit_answer_for_question(audit, question):
    return InternalAuditAnswer.query.filter_by(
        audit_id=audit.id,
        question_id=question.id,
    ).first()


def internal_audit_answer_map(audit):
    return {
        answer.question_id: answer
        for answer in InternalAuditAnswer.query.filter_by(audit_id=audit.id).all()
    }


def completed_internal_audit_answers(audit):
    return [
        answer
        for answer in audit.answers
        if answer.result and not answer.is_draft
    ]


def internal_audit_progress(audit):
    total = len(audit.questions)
    completed = len(completed_internal_audit_answers(audit))
    remaining = max(total - completed, 0)
    percent = int((completed / total) * 100) if total else 0
    return {
        "total": total,
        "completed": completed,
        "remaining": remaining,
        "percent": percent,
    }


def internal_audit_is_complete(audit):
    required_question_ids = {question.id for question in audit.questions if question.is_required}
    completed_question_ids = {
        answer.question_id
        for answer in completed_internal_audit_answers(audit)
    }
    return required_question_ids.issubset(completed_question_ids)


def internal_audit_question_by_order(audit, order_no):
    return InternalAuditQuestion.query.filter_by(
        audit_id=audit.id,
        order_no=order_no,
    ).first()


def internal_audit_next_order(audit, question):
    total = len(audit.questions)
    return min(question.order_no + 1, total) if total else question.order_no


def internal_audit_previous_order(audit, question):
    return max(question.order_no - 1, 1)


def internal_audit_result_meta(result, question=None):
    result_map = (
        internal_audit_question_result_map(question)
        if question is not None
        else INTERNAL_AUDIT_RESULT_MAP
    )
    canonical_result = internal_audit_canonical_result(result)
    return result_map.get(
        canonical_result or result,
        {"label": result or "Bekliyor", "tone": "secondary"},
    )


def internal_audit_history_items(audit, active_question):
    answers_by_question = internal_audit_answer_map(audit)
    questions = list(audit.questions)
    if not questions:
        return []

    active_index = max(active_question.order_no - 1, 0)
    start = max(active_index - 4, 0)
    end = min(start + 8, len(questions))
    start = max(end - 8, 0)
    items = []
    for question in questions[start:end]:
        answer = answers_by_question.get(question.id)
        result = (
            internal_audit_canonical_result(answer.result)
            if answer and not answer.is_draft
            else None
        )
        result_meta = internal_audit_result_meta(result, question)
        items.append(
            {
                "question": question,
                "answer": answer,
                "is_active": question.id == active_question.id,
                "is_complete": bool(answer and answer.result and not answer.is_draft),
                "result": result,
                "result_label": result_meta["label"],
                "tone": result_meta["tone"],
                "date": answer.answered_at or answer.updated_at if answer else None,
            }
        )
    return items


def internal_audit_previous_nonconformities(question, selected_dof_id=None):
    candidates = [
        dof
        for dof in scoped_query(Dof.query, Dof)
        .order_by(Dof.created_at.desc(), Dof.id.desc())
        .limit(200)
        .all()
        if can_view_dof(dof)
    ]
    if selected_dof_id and all(dof.id != selected_dof_id for dof in candidates):
        selected_dof = scoped_query(Dof.query, Dof).filter_by(id=selected_dof_id).first()
        if selected_dof and can_view_dof(selected_dof):
            candidates.insert(0, selected_dof)
    return attach_dof_view_state(candidates)


def parse_internal_audit_answer_form(audit, question, is_draft=False):
    evaluated_department = audit.evaluated_department or question.evaluated_department or ""
    evaluator_department = INTERNAL_AUDIT_LOCKED_DEPARTMENT
    result = internal_audit_canonical_result(request.form.get("result", "").strip())
    technical_findings = request.form.get("technical_findings", "").strip()
    previous_nonconformity_id = request.form.get("previous_nonconformity_id", "").strip()

    if len(technical_findings) > 1000:
        raise ValueError("technical_findings_too_long")
    if evaluated_department and evaluated_department not in DEPARTMENTS:
        raise ValueError("invalid_department")
    result_map = internal_audit_question_result_map(question)
    if result and result not in result_map:
        raise ValueError("invalid_result")
    if not is_draft and (
        not question.standard
        or not question.audit_topic
        or not question.question_text
        or not evaluated_department
        or not result
    ):
        raise ValueError("required_fields")
    if (
        not is_draft
        and internal_audit_result_requires_finding(result)
        and not technical_findings
    ):
        raise ValueError("technical_findings_required")

    previous_dof = None
    if previous_nonconformity_id:
        try:
            previous_dof_id = int(previous_nonconformity_id)
        except ValueError:
            raise ValueError("invalid_previous_nonconformity") from None
        previous_dof = scoped_query(Dof.query, Dof).filter_by(id=previous_dof_id).first()
        if previous_dof is None or not can_view_dof(previous_dof):
            raise ValueError("invalid_previous_nonconformity")

    answer = internal_audit_answer_for_question(audit, question)
    if answer is None:
        answer = InternalAuditAnswer(
            audit=audit,
            question=question,
            company_id=audit.company_id,
        )
        db.session.add(answer)

    answer.standard = question.standard
    answer.audit_topic = question.audit_topic
    answer.audit_subject = question.audit_subject
    answer.question_text = question.question_text
    answer.evaluated_department = evaluated_department
    answer.evaluator_department = evaluator_department
    answer.technical_findings = technical_findings or None
    answer.result = result or None
    answer.previous_nonconformity_id = previous_dof.id if previous_dof else None
    answer.answered_by_user_id = g.current_user.id
    answer.answered_at = datetime.utcnow()
    answer.is_draft = is_draft
    return answer


def internal_audit_dof_prefill(answer):
    finding_text = answer.technical_findings or "Teknik bulgu girilmemiş."
    return {
        "internal_audit_answer_id": str(answer.id),
        "title": short_text(answer.audit_subject or answer.audit_topic or answer.question_text, 150),
        "department": answer.evaluated_department or "",
        "responsible_id": str(answer.audit.audited_user_id or g.current_user.id),
        "opening_date": date.today().isoformat(),
        "priority": "Orta",
        "source": "İç Denetim",
        "nonconformity_description": (
            f"Soru: {answer.question_text}\n\n"
            f"İlgili Standart: {answer.standard}\n"
            f"Tetkik Başlık No: {answer.audit_topic}\n"
            f"Tetkik Konusu: {answer.audit_subject or '-'}\n"
            f"Sonuç: {answer.result or '-'}\n\n"
            f"Teknik Bulgular: {finding_text}"
        ),
        "root_cause_analysis": "",
        "corrective_action": "",
        "preventive_action": "",
    }


def parse_optional_date(field_name):
    value = request.form.get(field_name, "").strip()
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise ValueError("invalid_date") from None


def parse_optional_active_user(field_name):
    value = request.form.get(field_name, "").strip()
    if not value:
        return None
    try:
        user_id = int(value)
    except ValueError:
        raise ValueError("invalid_user") from None
    user = active_user_by_id(user_id)
    if user is None:
        raise ValueError("invalid_user")
    return user


def validate_dof_evidence_file(uploaded_file):
    if "." not in uploaded_file.filename:
        raise ValueError("invalid_dof_file_type")
    extension = uploaded_file.filename.rsplit(".", 1)[1].lower()
    if extension not in DOF_EVIDENCE_EXTENSIONS:
        raise ValueError("invalid_dof_file_type")


def validate_dof_opening_file(uploaded_file):
    if "." not in uploaded_file.filename:
        raise ValueError("invalid_dof_opening_file_type")
    extension = uploaded_file.filename.rsplit(".", 1)[1].lower()
    if extension not in DOF_OPENING_FILE_EXTENSIONS:
        raise ValueError("invalid_dof_opening_file_type")


def upload_storage_relative_path(filename, folder=None, company_id=None):
    parts = []
    effective_company_id = company_id if company_id is not None else current_company_id()
    if effective_company_id:
        parts.append(f"company-{effective_company_id:03d}")
    if folder:
        parts.append(folder)
    parts.append(filename)
    return Path(*parts)


def upload_storage_path(filename, folder=None, company_id=None):
    relative_path = upload_storage_relative_path(filename, folder, company_id)
    absolute_path = Path(current_app.config["UPLOAD_FOLDER"]) / relative_path
    absolute_path.parent.mkdir(parents=True, exist_ok=True)
    return relative_path, absolute_path


def uploaded_file_path(stored_name):
    if not stored_name:
        return None
    return Path(current_app.config["UPLOAD_FOLDER"]) / stored_name


def legacy_uploaded_file_path(stored_name):
    if not stored_name:
        return None
    return Path(current_app.config["UPLOAD_FOLDER"]) / Path(stored_name).name


def existing_uploaded_file_path(stored_name):
    file_path = uploaded_file_path(stored_name)
    if file_path and file_path.exists():
        return file_path

    legacy_path = legacy_uploaded_file_path(stored_name)
    if legacy_path and legacy_path.exists():
        return legacy_path
    return file_path


def delete_stored_upload(stored_name):
    file_path = existing_uploaded_file_path(stored_name)
    if file_path and file_path.exists():
        file_path.unlink()


def send_stored_upload(stored_name, download_name=None, mimetype=None, as_attachment=True):
    file_path = existing_uploaded_file_path(stored_name)
    if not file_path or not file_path.exists():
        abort(404)

    return send_from_directory(
        str(file_path.parent),
        file_path.name,
        as_attachment=as_attachment,
        download_name=download_name,
        mimetype=mimetype,
    )


def dof_opening_file_uploads():
    uploaded_files = request.files.getlist("opening_files")
    return [uploaded_file for uploaded_file in uploaded_files if uploaded_file.filename]


def save_dof_opening_files(dof):
    uploaded_files = dof_opening_file_uploads()
    if not uploaded_files:
        return

    for uploaded_file in uploaded_files:
        validate_dof_opening_file(uploaded_file)

    saved_paths = []
    try:
        for uploaded_file in uploaded_files:
            safe_name = secure_filename(uploaded_file.filename) or "dof-gorsel"
            extension = uploaded_file.filename.rsplit(".", 1)[1].lower()
            stored_name = f"dof-opening-{uuid4().hex}.{extension}"
            relative_path, upload_path = upload_storage_path(
                stored_name,
                "dof/opening",
                dof.company_id,
            )
            uploaded_file.save(upload_path)
            saved_paths.append(upload_path)
            if upload_path.stat().st_size > DOF_EVIDENCE_MAX_BYTES:
                raise ValueError("dof_opening_file_too_large")
            db.session.add(
                DofFile(
                    dof=dof,
                    company_id=dof.company_id,
                    original_name=safe_name,
                    stored_name=str(relative_path).replace("\\", "/"),
                    mime_type=uploaded_file.mimetype,
                    file_type="opening",
                )
            )
    except ValueError:
        for saved_path in saved_paths:
            if saved_path.exists():
                saved_path.unlink()
        raise


def save_dof_evidence_file(dof):
    uploaded_file = request.files.get("evidence_file")
    if not uploaded_file or not uploaded_file.filename:
        return

    validate_dof_evidence_file(uploaded_file)
    safe_name = secure_filename(uploaded_file.filename) or "dof-kanit"
    extension = safe_name.rsplit(".", 1)[1].lower()
    stored_name = f"dof-{uuid4().hex}.{extension}"
    relative_path, upload_path = upload_storage_path(stored_name, "dof/evidence", dof.company_id)
    uploaded_file.save(upload_path)
    if upload_path.stat().st_size > DOF_EVIDENCE_MAX_BYTES:
        upload_path.unlink(missing_ok=True)
        raise ValueError("dof_file_too_large")

    dof.evidence_original_name = safe_name
    dof.evidence_stored_name = str(relative_path).replace("\\", "/")
    dof.evidence_mime_type = uploaded_file.mimetype


def delete_dof_evidence_file(dof):
    for dof_file in list(dof.files):
        delete_stored_upload(dof_file.stored_name)
        db.session.delete(dof_file)

    if dof.evidence_stored_name:
        delete_stored_upload(dof.evidence_stored_name)

    dof.evidence_original_name = None
    dof.evidence_stored_name = None
    dof.evidence_mime_type = None


def parse_optional_user(field_name):
    value = request.form.get(field_name, "").strip()
    if not value:
        return None

    try:
        user_id = int(value)
    except ValueError:
        raise ValueError("invalid_user") from None

    user = active_user_by_id(user_id)
    if user is None:
        raise ValueError("invalid_user")
    return user


def user_name(user_id):
    if not user_id:
        return "-"
    user = User.query.get(user_id)
    return user.full_name if user else "-"


def format_date(value):
    return value.strftime("%d.%m.%Y") if value else "-"


def format_money(value):
    if value is None:
        return "-"
    return f"{float(value):,.2f} TL".replace(",", "X").replace(".", ",").replace("X", ".")


def format_quantity(value, suffix="L"):
    if value is None:
        return "-"
    return f"{float(value):,.2f} {suffix}".replace(",", "X").replace(".", ",").replace("X", ".")


def format_file_size(size):
    if not size:
        return "-"
    units = ["B", "KB", "MB", "GB"]
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


def can_manage_documents():
    return current_user_can("documents.manage")


def can_view_documents():
    return current_user_can("documents.view") or can_manage_documents()


def can_delete_document(document=None):
    return current_user_can("documents.delete")


def document_status_tone(status):
    return {
        "Yayında": "success",
        "Revizyon Bekleyen": "warning",
        "Onay Bekleyen": "purple",
        "Arşiv": "muted",
        "İptal": "danger",
    }.get(status, "muted")


def document_file_meta(document):
    extension = (document.file_type or "").lower()
    if extension == "pdf":
        return {"label": "PDF", "tone": "pdf", "icon": "file-earmark-pdf"}
    if extension in {"doc", "docx"}:
        return {"label": "Word", "tone": "word", "icon": "file-earmark-word"}
    if extension in {"xls", "xlsx"}:
        return {"label": "Excel", "tone": "excel", "icon": "file-earmark-excel"}
    if extension in {"ppt", "pptx"}:
        return {"label": "PowerPoint", "tone": "ppt", "icon": "file-earmark-slides"}
    if extension in {"png", "jpg", "jpeg"}:
        return {"label": "Görsel", "tone": "image", "icon": "file-earmark-image"}
    return {"label": "Dosya", "tone": "file", "icon": "file-earmark"}


def document_can_preview(document):
    return (
        document.preview_status == "ready"
        and bool(document.preview_file_path)
        and existing_uploaded_file_path(document.preview_file_path).exists()
    )


def document_preview_status(document):
    status = (document.preview_status or "").strip()
    return status if status in DOCUMENT_PREVIEW_STATUSES else "pending"


def document_preview_message(document):
    status = document_preview_status(document)
    if status == "ready":
        if not document_can_preview(document):
            return "PDF önizleme dosyası bulunamadı. Orijinal dosyayı indirebilirsiniz."
        return "PDF önizleme hazır."
    if status == "pending":
        return "PDF önizleme hazırlanıyor."
    if status == "not_supported":
        return "Bu dosya türü için PDF önizleme desteklenmiyor."
    return "PDF önizleme oluşturulamadı. Orijinal dosyayı indirerek görüntüleyebilirsiniz."


def libreoffice_binary():
    return (
        shutil.which("libreoffice")
        or shutil.which("soffice")
        or shutil.which("soffice.exe")
    )


def document_source_path(document):
    return existing_uploaded_file_path(document.file_path)


def document_preview_storage(document):
    category_slug = document.category.slug if document.category else "genel"
    source_stem = Path(document.file_name or "document").stem
    preview_key = f"{source_stem}-{document.id or uuid4().hex}"
    preview_name = f"{preview_key}_preview.pdf"
    preview_relative, preview_path = upload_storage_path(
        preview_name,
        Path("documents") / "previews" / category_slug,
        document.company_id,
    )
    return preview_name, preview_path, str(preview_relative).replace("\\", "/")


def delete_document_preview(document):
    if not document.preview_file_path:
        return
    delete_stored_upload(document.preview_file_path)


def fail_document_preview(document, status, message):
    document.preview_file_name = None
    document.preview_file_path = None
    document.preview_status = status
    document.preview_error = message[:1000] if message else None
    document.preview_generated_at = datetime.utcnow()
    return False


def image_to_pdf_preview(source_path, preview_path):
    try:
        from PIL import Image, ImageOps
    except ImportError:
        raise RuntimeError("Pillow yüklü olmadığı için görsel PDF'e dönüştürülemedi.") from None

    with Image.open(source_path) as image:
        image = ImageOps.exif_transpose(image)
        if image.mode in {"RGBA", "LA"}:
            background = Image.new("RGB", image.size, (255, 255, 255))
            background.paste(image, mask=image.split()[-1])
            image = background
        else:
            image = image.convert("RGB")
        image.save(preview_path, "PDF", resolution=100.0)


def office_to_pdf_preview(source_path, preview_dir, preview_path):
    binary = libreoffice_binary()
    if binary is None:
        raise RuntimeError("LibreOffice bulunamadı. Office dosyası PDF'e dönüştürülemedi.")

    result = subprocess.run(
        [
            binary,
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            str(preview_dir),
            str(source_path),
        ],
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    converted_path = preview_dir / f"{source_path.stem}.pdf"
    if result.returncode != 0 or not converted_path.exists():
        error_text = (result.stderr or result.stdout or "LibreOffice PDF üretmedi.").strip()
        raise RuntimeError(error_text)
    if converted_path != preview_path:
        if preview_path.exists():
            preview_path.unlink()
        converted_path.replace(preview_path)


def generate_document_preview(document):
    extension = (document.file_type or "").lower()
    source_path = document_source_path(document)
    delete_document_preview(document)
    document.preview_file_name = None
    document.preview_file_path = None
    document.preview_status = "pending"
    document.preview_error = None
    document.preview_generated_at = None

    if not source_path.exists():
        return fail_document_preview(document, "failed", "Orijinal dosya bulunamadı.")

    preview_name, preview_path, preview_relative = document_preview_storage(document)
    try:
        if extension == "pdf":
            shutil.copyfile(source_path, preview_path)
        elif extension in DOCUMENT_IMAGE_EXTENSIONS:
            image_to_pdf_preview(source_path, preview_path)
        elif extension in DOCUMENT_OFFICE_EXTENSIONS:
            office_to_pdf_preview(source_path, preview_path.parent, preview_path)
        else:
            return fail_document_preview(
                document,
                "not_supported",
                "Bu dosya türü için PDF önizleme desteklenmiyor.",
            )
    except Exception as error:
        if preview_path.exists():
            preview_path.unlink()
        return fail_document_preview(document, "failed", str(error))

    document.preview_file_name = preview_name
    document.preview_file_path = preview_relative
    document.preview_status = "ready"
    document.preview_error = None
    document.preview_generated_at = datetime.utcnow()
    return True


def document_allowed_file(uploaded_file):
    return (
        uploaded_file
        and uploaded_file.filename
        and "." in uploaded_file.filename
        and uploaded_file.filename.rsplit(".", 1)[1].lower()
        in DOCUMENT_ALLOWED_EXTENSIONS
    )


def document_uploads():
    uploaded_files = request.files.getlist("document_files")
    if not uploaded_files:
        uploaded_file = request.files.get("document_file")
        uploaded_files = [uploaded_file] if uploaded_file else []
    return [uploaded_file for uploaded_file in uploaded_files if uploaded_file and uploaded_file.filename]


def parse_document_form():
    title = request.form.get("title", "").strip()
    document_code = request.form.get("document_code", "").strip()
    revision_no = request.form.get("revision_no", "").strip()
    department = request.form.get("department", "").strip()
    description = request.form.get("description", "").strip()
    status = request.form.get("status", "Yayında").strip()

    try:
        category_id = int(request.form.get("category_id", ""))
    except ValueError:
        raise ValueError("invalid_category") from None

    category = DocumentCategory.query.filter_by(
        id=category_id,
        is_active=True,
    ).first()
    if category is None:
        raise ValueError("invalid_category")
    if not title or not document_code:
        raise ValueError("required_fields")
    if department and department not in DOCUMENT_DEPARTMENTS:
        raise ValueError("invalid_department")
    if status not in DOCUMENT_STATUSES:
        raise ValueError("invalid_status")
    if len(description) > 2000:
        raise ValueError("text_too_long")

    return {
        "category": category,
        "document_code": document_code[:80],
        "title": title[:200],
        "revision_no": revision_no[:40] or None,
        "publish_date": parse_optional_date("publish_date"),
        "revision_date": parse_optional_date("revision_date"),
        "department": department or None,
        "description": description or None,
        "status": status,
    }


def save_document_upload(uploaded_file, category):
    if not document_allowed_file(uploaded_file):
        raise ValueError("invalid_document_file_type")

    original_name = secure_filename(uploaded_file.filename)
    extension = uploaded_file.filename.rsplit(".", 1)[1].lower()
    if not original_name:
        original_name = f"dokuman.{extension}"
    stored_name = f"document-{uuid4().hex}.{extension}"
    relative_path, upload_path = upload_storage_path(
        stored_name,
        Path("documents") / "originals" / category.slug,
    )
    uploaded_file.save(upload_path)

    if upload_path.stat().st_size > DOCUMENT_MAX_BYTES:
        upload_path.unlink(missing_ok=True)
        raise ValueError("document_file_too_large")

    return {
        "file_name": stored_name,
        "original_file_name": original_name,
        "file_path": str(relative_path).replace("\\", "/"),
        "file_type": extension,
        "file_size": upload_path.stat().st_size,
    }


def delete_document_file(document):
    if not document.file_path:
        return
    delete_stored_upload(document.file_path)


def delete_document_files(document):
    delete_document_file(document)
    delete_document_preview(document)


def document_query():
    return scoped_query(Document.query, Document).join(DocumentCategory)


def document_filters():
    return {
        "search": request.args.get("search", "").strip(),
        "status": request.args.get("status", "").strip(),
        "department": request.args.get("department", "").strip(),
    }


def filtered_document_query(category=None, filters=None):
    filters = filters or document_filters()
    query = document_query()
    if category is not None:
        query = query.filter(Document.category_id == category.id)
    if filters["status"]:
        query = query.filter(Document.status == filters["status"])
    if filters["department"]:
        query = query.filter(Document.department == filters["department"])
    if filters["search"]:
        search_value = f"%{filters['search']}%"
        query = query.filter(
            or_(
                Document.document_code.ilike(search_value),
                Document.title.ilike(search_value),
                Document.description.ilike(search_value),
                DocumentCategory.name.ilike(search_value),
            )
        )
    return query.order_by(Document.created_at.desc(), Document.id.desc())


def ordered_document_categories():
    ensure_document_categories()
    return (
        scoped_query(DocumentCategory.query, DocumentCategory)
        .filter_by(is_active=True)
        .order_by(DocumentCategory.sort_order.asc(), DocumentCategory.id.asc())
        .all()
    )


def document_category_cards(categories, documents):
    documents_by_category = {category.id: [] for category in categories}
    for document in documents:
        documents_by_category.setdefault(document.category_id, []).append(document)

    cards = []
    for category in categories:
        category_documents = documents_by_category.get(category.id, [])
        latest_document = max(
            category_documents,
            key=lambda item: item.updated_at or item.created_at,
            default=None,
        )
        cards.append(
            {
                "category": category,
                "count": len(category_documents),
                "last_update": latest_document.updated_at or latest_document.created_at
                if latest_document
                else None,
            }
        )
    return cards


def documents_dashboard_context():
    categories = ordered_document_categories()
    documents = document_query().order_by(Document.created_at.desc(), Document.id.desc()).all()
    status_counts = {
        status: sum(1 for document in documents if document.status == status)
        for status in DOCUMENT_STATUSES
    }
    return {
        "categories": categories,
        "category_cards": document_category_cards(categories, documents),
        "recent_documents": documents[:5],
        "total_count": len(documents),
        "published_count": status_counts.get("Yayında", 0),
        "revision_count": status_counts.get("Revizyon Bekleyen", 0),
        "approval_count": status_counts.get("Onay Bekleyen", 0),
        "archive_count": status_counts.get("Arşiv", 0),
        "document_file_meta": document_file_meta,
        "document_can_preview": document_can_preview,
        "document_status_tone": document_status_tone,
        "format_date": format_date,
        "format_file_size": format_file_size,
        "can_manage_documents": can_manage_documents(),
        "can_delete_document": can_delete_document,
    }


def documents_category_context(category):
    filters = document_filters()
    documents = filtered_document_query(category, filters).all()
    return {
        "category": category,
        "page_title": category.display_name if category else "Tüm Dokümanlar",
        "page_description": (
            "Bu kategoriye ait kalite dokümanlarını görüntüleyin."
            if category
            else "Sistemde kayıtlı tüm kalite dokümanlarını görüntüleyin."
        ),
        "documents": documents,
        "filters": filters,
        "statuses": DOCUMENT_STATUSES,
        "departments": DOCUMENT_DEPARTMENTS,
        "document_file_meta": document_file_meta,
        "document_can_preview": document_can_preview,
        "document_status_tone": document_status_tone,
        "format_date": format_date,
        "format_file_size": format_file_size,
        "can_manage_documents": can_manage_documents(),
        "can_delete_document": can_delete_document,
    }


def document_form_context(document=None, category_slug=None):
    selected_category = None
    if document is not None:
        selected_category = document.category
    elif category_slug:
        selected_category = (
            scoped_query(DocumentCategory.query, DocumentCategory)
            .filter_by(slug=category_slug, is_active=True)
            .first()
        )

    form_data = request.form if request.method == "POST" else {}
    return {
        "document": document,
        "categories": ordered_document_categories(),
        "selected_category": selected_category,
        "statuses": DOCUMENT_STATUSES,
        "departments": DOCUMENT_DEPARTMENTS,
        "form_data": form_data,
    }


VEHICLE_MONTHS = (
    (1, "Ocak"),
    (2, "Şubat"),
    (3, "Mart"),
    (4, "Nisan"),
    (5, "Mayıs"),
    (6, "Haziran"),
    (7, "Temmuz"),
    (8, "Ağustos"),
    (9, "Eylül"),
    (10, "Ekim"),
    (11, "Kasım"),
    (12, "Aralık"),
)


def can_view_vehicles():
    return (
        current_user_can("vehicles.view")
        or current_user_can("maintenance.fault_manage")
        or can_manage_vehicles()
    )


def can_manage_vehicles():
    return current_user_can("vehicles.manage") or current_user_can(
        "maintenance.inventory_manage"
    )


def vehicle_day_status(target_date, days_before=7):
    if not target_date:
        return {"days": None, "label": "-", "tone": "muted", "is_due_window": False}
    try:
        days_before = int(days_before)
    except (TypeError, ValueError):
        days_before = 7
    days_before = min(max(days_before, 1), 30)
    days = (target_date - date.today()).days
    if days > 0:
        label = f"{days} gün kaldı"
        tone = "warning" if days <= days_before else "success"
    elif days == 0:
        label = "Bugün bitiyor"
        tone = "danger"
    else:
        label = f"{abs(days)} gün geçti"
        tone = "danger"
    return {
        "days": days,
        "label": label,
        "tone": tone,
        "is_due_window": 0 <= days <= days_before,
    }


def parse_decimal_field(field_name):
    raw_value = request.form.get(field_name, "").strip()
    if not raw_value:
        return None
    if "," in raw_value:
        raw_value = raw_value.replace(".", "").replace(",", ".")
    try:
        value = Decimal(raw_value)
    except (InvalidOperation, ValueError):
        raise ValueError("invalid_decimal") from None
    if value < 0:
        raise ValueError("invalid_decimal")
    return value


def parse_vehicle_form():
    plate = request.form.get("plate", "").strip().upper()
    brand = request.form.get("brand", "").strip()
    model = request.form.get("model", "").strip()
    owner = request.form.get("owner", "").strip()

    if not plate or not brand or not model or not owner:
        raise ValueError("required_fields")

    return {
        "plate": plate[:40],
        "brand": brand[:120],
        "model": model[:120],
        "owner": owner[:160],
    }


def parse_vehicle_detail_form():
    values = parse_vehicle_form()
    try:
        reminder_days_before = int(request.form.get("reminder_days_before", "7"))
    except ValueError:
        raise ValueError("invalid_reminder_days") from None
    if reminder_days_before < 1 or reminder_days_before > 30:
        raise ValueError("invalid_reminder_days")

    active_user_ids = {user.id for user in active_users()}
    reminder_user_ids = []
    for raw_user_id in request.form.getlist("reminder_user_ids"):
        try:
            user_id = int(raw_user_id)
        except ValueError:
            continue
        if user_id in active_user_ids and user_id not in reminder_user_ids:
            reminder_user_ids.append(user_id)

    values.update(
        {
        "traffic_insurance_due_date": parse_optional_date("traffic_insurance_due_date"),
        "casco_insurance_due_date": parse_optional_date("casco_insurance_due_date"),
        "last_inspection_date": parse_optional_date("last_inspection_date"),
        "next_inspection_due_date": parse_optional_date("next_inspection_due_date"),
        "reminder_days_before": reminder_days_before,
        "reminder_user_ids": reminder_user_ids,
        }
    )
    return values


def parse_vehicle_operation_form():
    operation_date = parse_optional_date("operation_date")
    description = request.form.get("description", "").strip()
    amount_tl = parse_decimal_field("amount_tl")
    if not operation_date or not description:
        raise ValueError("required_fields")
    return {
        "operation_date": operation_date,
        "description": description[:255],
        "amount_tl": amount_tl,
    }


def vehicle_query():
    return scoped_query(Vehicle.query, Vehicle).order_by(Vehicle.plate.asc())


def vehicle_maintenance_users():
    users = []
    for user in active_users():
        search_text = " ".join(
            [
                user.full_name or "",
                user.title or "",
                " ".join(user.role_names),
            ]
        ).lower()
        if "bakım" in search_text or "bakim" in search_text:
            users.append(user)
    return users


def send_vehicle_due_reminders(vehicle):
    reminder_users = list(vehicle.reminder_recipients) or vehicle_maintenance_users()
    if not reminder_users:
        return False

    sent_any = False
    days_before = vehicle.reminder_days_before or 7
    reminder_fields = (
        (
            "traffic_insurance_due_date",
            "traffic_insurance_reminder_sent_at",
            "Trafik Sigortası",
        ),
        (
            "casco_insurance_due_date",
            "casco_insurance_reminder_sent_at",
            "Kasko Sigorta",
        ),
        (
            "next_inspection_due_date",
            "next_inspection_reminder_sent_at",
            "Sonraki Muayene",
        ),
    )
    for date_field, sent_field, title in reminder_fields:
        due_date = getattr(vehicle, date_field)
        status = vehicle_day_status(due_date, days_before)
        if status["is_due_window"] and getattr(vehicle, sent_field) is None:
            if send_vehicle_reminder_email(
                reminder_users,
                vehicle,
                title,
                due_date,
                status["label"],
                days_before,
            ):
                setattr(vehicle, sent_field, datetime.utcnow())
                sent_any = True
    return sent_any


def reset_vehicle_reminder_flags(vehicle, previous_dates):
    fields = (
        ("traffic_insurance_due_date", "traffic_insurance_reminder_sent_at"),
        ("casco_insurance_due_date", "casco_insurance_reminder_sent_at"),
        ("next_inspection_due_date", "next_inspection_reminder_sent_at"),
    )
    if previous_dates.get("reminder_days_before") != vehicle.reminder_days_before:
        for _date_field, sent_field in fields:
            setattr(vehicle, sent_field, None)
        return
    for date_field, sent_field in fields:
        if previous_dates.get(date_field) != getattr(vehicle, date_field):
            setattr(vehicle, sent_field, None)


def vehicle_dashboard_context():
    vehicles = vehicle_query().all()
    for vehicle in vehicles:
        send_vehicle_due_reminders(vehicle)
    db.session.commit()
    due_soon_count = 0
    for vehicle in vehicles:
        if any(
            vehicle_day_status(target_date, vehicle.reminder_days_before or 7)["is_due_window"]
            for target_date in (
                vehicle.traffic_insurance_due_date,
                vehicle.casco_insurance_due_date,
                vehicle.next_inspection_due_date,
            )
        ):
            due_soon_count += 1
    return {
        "vehicles": vehicles,
        "due_soon_count": due_soon_count,
        "can_manage_vehicles": can_manage_vehicles(),
        "vehicle_day_status": vehicle_day_status,
        "format_date": format_date,
    }


def vehicle_detail_context(vehicle):
    operations = list(vehicle.operations)
    fuel_entries = {
        (entry.year, entry.month): entry
        for entry in scoped_query(VehicleFuelEntry.query, VehicleFuelEntry)
        .filter_by(vehicle_id=vehicle.id)
        .all()
    }
    current_year = date.today().year
    fuel_rows = []
    total_fuel_tl = Decimal("0")
    total_fuel_liter = Decimal("0")
    for month, label in VEHICLE_MONTHS:
        entry = fuel_entries.get((current_year, month))
        amount_tl = entry.amount_tl if entry and entry.amount_tl is not None else None
        fuel_liter = entry.fuel_liter if entry and entry.fuel_liter is not None else None
        if amount_tl is not None:
            total_fuel_tl += amount_tl
        if fuel_liter is not None:
            total_fuel_liter += fuel_liter
        fuel_rows.append(
            {
                "month": month,
                "label": label,
                "amount_tl": amount_tl,
                "fuel_liter": fuel_liter,
            }
        )

    operation_total = sum(
        (operation.amount_tl for operation in operations if operation.amount_tl is not None),
        Decimal("0"),
    )
    return {
        "vehicle": vehicle,
        "operations": operations,
        "operation_total": operation_total,
        "fuel_rows": fuel_rows,
        "fuel_year": current_year,
        "total_fuel_tl": total_fuel_tl,
        "total_fuel_liter": total_fuel_liter,
        "vehicle_day_status": vehicle_day_status,
        "format_date": format_date,
        "format_money": format_money,
        "format_quantity": format_quantity,
        "can_manage_vehicles": can_manage_vehicles(),
        "users": active_users(),
        "reminder_day_options": range(1, 31),
    }


def can_manage_maintenance_inventory():
    return current_user_can("maintenance.inventory_manage")


def can_open_maintenance_fault():
    return g.current_user is not None


def can_edit_maintenance_fault(fault):
    return (
        g.current_user is not None
        and fault.status != "Tamamlandı"
        and current_user_can("maintenance.fault_manage")
    )


def can_complete_maintenance_fault(fault):
    return can_edit_maintenance_fault(fault)


def can_delete_maintenance_fault(fault=None):
    return can_manage_maintenance_inventory()


def maintenance_filters():
    return {
        "search": request.args.get("search", "").strip(),
        "machine_status": request.args.get("machine_status", "").strip(),
        "reporting_department": request.args.get("reporting_department", "").strip(),
    }


def maintenance_status_tone(status):
    normalized = normalize_for_role(status)
    if "calisiyor" in normalized or status == "Tamamlandı":
        return "success"
    if "arizali" in normalized or "gecikti" in normalized:
        return "danger"
    if "islemde" in normalized:
        return "info"
    if "hurda" in normalized or "pasif" in normalized or "iptal" in normalized:
        return "muted"
    return "warning"


def maintenance_fault_count(machine):
    return len(machine.faults)


def is_unplanned_maintenance_machine(machine):
    return machine is not None and machine.code == UNPLANNED_MAINTENANCE_CODE


def ensure_unplanned_maintenance_machine():
    machine = scoped_query(MaintenanceMachine.query, MaintenanceMachine).filter_by(
        code=UNPLANNED_MAINTENANCE_CODE
    ).first()
    if machine is None:
        machine = MaintenanceMachine(
            code=UNPLANNED_MAINTENANCE_CODE,
            machine_name=UNPLANNED_MAINTENANCE_LABEL,
            status="ÇALIŞIYOR",
            is_active=True,
        )
        assign_current_company(machine)
        db.session.add(machine)
        db.session.flush()
    else:
        changed = False
        if machine.machine_name != UNPLANNED_MAINTENANCE_LABEL:
            machine.machine_name = UNPLANNED_MAINTENANCE_LABEL
            changed = True
        if not machine.is_active:
            machine.is_active = True
            changed = True
        if changed:
            db.session.add(machine)
    return machine


def refresh_machine_status_from_faults(machine):
    if machine is None or is_unplanned_maintenance_machine(machine):
        return
    has_open_fault = (
        scoped_query(MaintenanceFault.query, MaintenanceFault).filter(
            MaintenanceFault.machine_id == machine.id,
            MaintenanceFault.status != "Tamamlandı",
        ).first()
        is not None
    )
    if has_open_fault:
        machine.status = "ARIZALI"
    elif machine.status == "ARIZALI":
        machine.status = "ÇALIŞIYOR"


def maintenance_machine_query():
    return scoped_query(MaintenanceMachine.query, MaintenanceMachine).filter(
        MaintenanceMachine.code != UNPLANNED_MAINTENANCE_CODE
    ).order_by(
        MaintenanceMachine.code.asc(),
        MaintenanceMachine.machine_name.asc(),
    )


def maintenance_fault_query():
    return scoped_query(MaintenanceFault.query, MaintenanceFault).join(MaintenanceMachine).order_by(
        MaintenanceFault.created_at.desc(),
        MaintenanceFault.id.desc(),
    )


def filtered_maintenance_machines(filters):
    query = maintenance_machine_query()
    if filters["machine_status"]:
        query = query.filter(MaintenanceMachine.status == filters["machine_status"])
    if filters["search"]:
        search_value = f"%{filters['search']}%"
        query = query.filter(
            or_(
                MaintenanceMachine.code.ilike(search_value),
                MaintenanceMachine.machine_name.ilike(search_value),
                MaintenanceMachine.brand_model.ilike(search_value),
                MaintenanceMachine.serial_no.ilike(search_value),
                MaintenanceMachine.location.ilike(search_value),
            )
        )
    return query.all()


def filtered_maintenance_faults(filters):
    query = maintenance_fault_query()
    if filters["reporting_department"]:
        query = query.filter(
            MaintenanceFault.reporting_department == filters["reporting_department"]
        )
    if filters["search"]:
        search_value = f"%{filters['search']}%"
        query = query.filter(
            or_(
                MaintenanceFault.title.ilike(search_value),
                MaintenanceFault.description.ilike(search_value),
                MaintenanceFault.reporting_department.ilike(search_value),
                MaintenanceMachine.code.ilike(search_value),
                MaintenanceMachine.machine_name.ilike(search_value),
                MaintenanceMachine.brand_model.ilike(search_value),
                MaintenanceMachine.serial_no.ilike(search_value),
            )
        )
    return query.all()


def parse_maintenance_machine_form():
    code = request.form.get("code", "").strip()
    machine_name = request.form.get("machine_name", "").strip()
    brand_model = request.form.get("brand_model", "").strip()
    serial_no = request.form.get("serial_no", "").strip()
    status = request.form.get("status", "").strip() or "ÇALIŞIYOR"
    location = request.form.get("location", "").strip()
    notes = request.form.get("notes", "").strip()

    if not code or not machine_name:
        raise ValueError("required_fields")
    if status not in MAINTENANCE_MACHINE_STATUSES:
        raise ValueError("invalid_status")

    return {
        "code": code[:80],
        "machine_name": machine_name[:180],
        "brand_model": brand_model[:180] or None,
        "serial_no": serial_no[:120] or None,
        "status": status,
        "location": location[:160] or None,
        "notes": notes or None,
    }


def parse_maintenance_fault_form(fault=None):
    machine_id = request.form.get("machine_id", "").strip()
    title = request.form.get("title", "").strip()
    description = request.form.get("description", "").strip()
    responsible_user = parse_optional_active_user("responsible_user_id")
    reporting_department = request.form.get("reporting_department", "").strip()
    reported_date = parse_optional_date("reported_date")

    if machine_id == UNPLANNED_MAINTENANCE_VALUE:
        machine = ensure_unplanned_maintenance_machine()
    else:
        try:
            machine_id = int(machine_id)
        except ValueError:
            raise ValueError("invalid_machine") from None

        machine = scoped_query(MaintenanceMachine.query, MaintenanceMachine).filter_by(
            id=machine_id,
            is_active=True,
        ).first()
        if machine is None or is_unplanned_maintenance_machine(machine):
            raise ValueError("invalid_machine")
    if not title:
        raise ValueError("required_fields")
    if not reporting_department or reporting_department not in DEPARTMENTS:
        raise ValueError("invalid_department")
    if reported_date is None:
        reported_date = fault.reported_at.date() if fault and fault.reported_at else date.today()

    return {
        "machine": machine,
        "title": title[:180],
        "description": description or None,
        "responsible_user": responsible_user,
        "reported_at": datetime.combine(reported_date, datetime.min.time()),
        "reporting_department": reporting_department,
    }


def maintenance_dashboard_context():
    filters = maintenance_filters()
    machines = filtered_maintenance_machines(filters)
    faults = filtered_maintenance_faults(filters)
    all_machines = scoped_query(MaintenanceMachine.query, MaintenanceMachine).filter(
        MaintenanceMachine.code != UNPLANNED_MAINTENANCE_CODE
    ).all()
    all_faults = scoped_query(MaintenanceFault.query, MaintenanceFault).all()
    open_faults = [fault for fault in all_faults if fault.status != "Tamamlandı"]

    return {
        "machines": machines,
        "faults": faults,
        "filters": filters,
        "machine_statuses": MAINTENANCE_MACHINE_STATUSES,
        "departments": DEPARTMENTS,
        "users": active_users(),
        "total_machine_count": len(all_machines),
        "active_machine_count": sum(1 for machine in all_machines if machine.is_active),
        "total_fault_count": len(all_faults),
        "open_fault_count": len(open_faults),
        "completed_fault_count": sum(
            1 for fault in all_faults if fault.status == "Tamamlandı"
        ),
        "can_manage_inventory": can_manage_maintenance_inventory(),
        "can_open_fault": can_open_maintenance_fault(),
        "can_edit_fault": can_edit_maintenance_fault,
        "can_complete_fault": can_complete_maintenance_fault,
        "can_delete_fault": can_delete_maintenance_fault,
        "fault_count_for_machine": maintenance_fault_count,
        "status_tone": maintenance_status_tone,
        "unplanned_maintenance_code": UNPLANNED_MAINTENANCE_CODE,
        "unplanned_maintenance_label": UNPLANNED_MAINTENANCE_LABEL,
        "format_date": format_date,
    }


def maintenance_machine_form_context(machine=None):
    return {
        "machine": machine,
        "statuses": MAINTENANCE_MACHINE_STATUSES,
        "form_data": request.form if request.method == "POST" else {},
    }


def maintenance_fault_form_context(fault=None, machine=None):
    selected_machine = machine or (fault.machine if fault else None)
    return {
        "fault": fault,
        "selected_machine": selected_machine,
        "machines": scoped_query(MaintenanceMachine.query, MaintenanceMachine)
        .filter_by(is_active=True)
        .filter(MaintenanceMachine.code != UNPLANNED_MAINTENANCE_CODE)
        .order_by(MaintenanceMachine.code.asc(), MaintenanceMachine.machine_name.asc())
        .all(),
        "users": active_users(),
        "departments": DEPARTMENTS,
        "is_unplanned_selected": is_unplanned_maintenance_machine(selected_machine),
        "unplanned_maintenance_value": UNPLANNED_MAINTENANCE_VALUE,
        "unplanned_maintenance_label": UNPLANNED_MAINTENANCE_LABEL,
        "today": date.today().isoformat(),
        "form_data": request.form if request.method == "POST" else {},
    }


def action_snapshot(action):
    return {
        "title": action.title,
        "responsible_user_id": action.responsible_user_id,
        "related_user_1_id": action.related_user_1_id,
        "related_user_2_id": action.related_user_2_id,
        "department": action.department,
        "description": action.description or "",
        "termin_date": action.termin_date,
        "file_original_name": action.file_original_name,
    }


def describe_action_changes(before, action):
    changes = []
    if before["title"] != action.title:
        changes.append(f"başlığı \"{before['title']}\" -> \"{action.title}\"")
    if before["responsible_user_id"] != action.responsible_user_id:
        changes.append(
            "sorumlusu "
            f"{user_name(before['responsible_user_id'])} -> {user_name(action.responsible_user_id)}"
        )
    if before["related_user_1_id"] != action.related_user_1_id:
        changes.append(
            "İlgili 1 "
            f"{user_name(before['related_user_1_id'])} -> {user_name(action.related_user_1_id)}"
        )
    if before["related_user_2_id"] != action.related_user_2_id:
        changes.append(
            "İlgili 2 "
            f"{user_name(before['related_user_2_id'])} -> {user_name(action.related_user_2_id)}"
        )
    if before["department"] != action.department:
        changes.append(f"departmanı {before['department']} -> {action.department}")
    if before["termin_date"] != action.termin_date:
        changes.append(
            f"termini {format_date(before['termin_date'])} -> {format_date(action.termin_date)}"
        )
    if before["description"] != (action.description or ""):
        changes.append("açıklaması güncellendi")
    if before["file_original_name"] != action.file_original_name:
        changes.append("dosyası güncellendi")
    return changes


def sub_action_snapshot(sub_action):
    return {
        "title": sub_action.title,
        "responsible_id": sub_action.responsible_id,
        "related_user_1_id": sub_action.related_user_1_id,
        "related_user_2_id": sub_action.related_user_2_id,
        "due_date": sub_action.due_date,
        "priority": sub_action.priority,
        "status": sub_action.status,
        "description": sub_action.description or "",
        "evidence_required": sub_action.evidence_required,
        "evidence_original_name": sub_action.evidence_original_name,
        "closing_note": sub_action.closing_note or "",
    }


def describe_sub_action_changes(before, sub_action):
    changes = []
    if before["title"] != sub_action.title:
        changes.append(f"başlığı \"{before['title']}\" -> \"{sub_action.title}\"")
    if before["responsible_id"] != sub_action.responsible_id:
        changes.append(
            "sorumlusu "
            f"{user_name(before['responsible_id'])} -> {user_name(sub_action.responsible_id)}"
        )
    if before["related_user_1_id"] != sub_action.related_user_1_id:
        changes.append(
            "İlgili 1 "
            f"{user_name(before['related_user_1_id'])} -> {user_name(sub_action.related_user_1_id)}"
        )
    if before["related_user_2_id"] != sub_action.related_user_2_id:
        changes.append(
            "İlgili 2 "
            f"{user_name(before['related_user_2_id'])} -> {user_name(sub_action.related_user_2_id)}"
        )
    if before["due_date"] != sub_action.due_date:
        changes.append(
            f"termini {format_date(before['due_date'])} -> {format_date(sub_action.due_date)}"
        )
    if before["priority"] != sub_action.priority:
        changes.append(f"önceliği {before['priority']} -> {sub_action.priority}")
    if before["status"] != sub_action.status:
        changes.append(f"durumu {before['status']} -> {sub_action.status}")
    if before["description"] != (sub_action.description or ""):
        changes.append("açıklaması güncellendi")
    if before["evidence_required"] != sub_action.evidence_required:
        changes.append(
            "kanıt zorunluluğu "
            f"{'Evet' if before['evidence_required'] else 'Hayır'} -> "
            f"{'Evet' if sub_action.evidence_required else 'Hayır'}"
        )
    if before["evidence_original_name"] != sub_action.evidence_original_name:
        changes.append("kanıt dosyası güncellendi")
    if before["closing_note"] != (sub_action.closing_note or ""):
        changes.append("kapanış açıklaması güncellendi")
    return changes


def add_action_history(action, event_type, message, actor=None):
    history = ActionHistory(
        action=action,
        company_id=action.company_id,
        actor_user_id=actor.id if actor else None,
        event_type=event_type,
        message=message,
    )
    db.session.add(history)
    return history


def notify_users(user_ids, action, message, exclude_user_id=None):
    target_user_ids = {user_id for user_id in user_ids if user_id}
    if exclude_user_id:
        target_user_ids.discard(exclude_user_id)

    users = (
        User.query.filter(User.id.in_(target_user_ids), User.is_active.is_(True)).all()
        if target_user_ids
        else []
    )

    for user in users:
        user_id = user.id
        if exclude_user_id and user_id == exclude_user_id:
            continue
        db.session.add(
            Notification(
                user_id=user_id,
                company_id=action.company_id,
                action=action,
                message=message,
            )
        )
    send_action_notification_email(users, action, message)


def notify_action_participants(action, message, exclude_user_id=None, extra_user_ids=None):
    user_ids = set(action.participant_user_ids())
    if extra_user_ids:
        user_ids.update(extra_user_ids)
    notify_users(user_ids, action, message, exclude_user_id=exclude_user_id)


def notify_sub_action_participants(
    sub_action,
    message,
    exclude_user_id=None,
    extra_user_ids=None,
):
    user_ids = set(sub_action.participant_user_ids())
    user_ids.add(sub_action.parent_action.responsible_user_id)
    if extra_user_ids:
        user_ids.update(extra_user_ids)
    notify_users(
        user_ids,
        sub_action.parent_action,
        message,
        exclude_user_id=exclude_user_id,
    )


def unique_users(users):
    unique_by_id = {}
    for user in users:
        if user is not None and user.id:
            unique_by_id[user.id] = user
    return list(unique_by_id.values())


def dof_management_approver_users():
    return unique_users(
        user for user in active_users() if is_management_representative(user)
    )


def dof_deputy_approver_users():
    users = [
        user for user in active_users() if user_title_has(user, "Genel Müdür Yardımcısı")
    ]
    if not users:
        users = [oguzhan_user()]
    return unique_users(users)


def dof_primary_users(dof):
    return unique_users([dof.responsible, dof.created_by])


def add_dof_comment(dof, message, comment_type="note", actor=None):
    comment = DofComment(
        dof=dof,
        company_id=dof.company_id,
        user_id=actor.id if actor else None,
        comment=message,
        comment_type=comment_type,
    )
    db.session.add(comment)
    return comment


def dof_approver_label(step):
    if step == "general_manager_deputy":
        return "Genel Müdür Yardımcısı"
    if step == "management_representative":
        return "Yönetim Temsilcisi"
    return "Onay"


def dof_rejection_recipients(dof, rejected_step):
    recipients = dof_primary_users(dof)
    if rejected_step == "general_manager_deputy":
        recipients.extend(dof_management_approver_users())
    return unique_users(recipients)


def dof_label(dof):
    return dof.dof_no or "İF kaydı"


def notify_dof_users(users, dof, message, exclude_user_id=None):
    users = [
        user
        for user in unique_users(users)
        if getattr(user, "is_active", True)
        and not (exclude_user_id and user.id == exclude_user_id)
    ]

    for user in users:
        db.session.add(
            Notification(
                user_id=user.id,
                company_id=dof.company_id,
                dof=dof,
                message=message,
            )
        )
    send_dof_notification_email(users, dof, message)


def notify_dof_waiting_approvers(dof):
    if dof.approval_step == "management_representative":
        notify_dof_users(
            dof_management_approver_users(),
            dof,
            f"{dof_label(dof)} için Yönetim Temsilcisi onayınız bekleniyor.",
        )
    elif dof.approval_step == "general_manager_deputy":
        notify_dof_users(
            dof_deputy_approver_users(),
            dof,
            f"{dof_label(dof)} için Genel Müdür Yardımcısı onayınız bekleniyor.",
        )


def dof_change_notification_users(dof):
    users = dof_primary_users(dof)
    if dof.approval_step == "management_representative":
        users.extend(dof_management_approver_users())
    elif dof.approval_step == "general_manager_deputy":
        users.extend(dof_deputy_approver_users())
    return unique_users(users)


def orientation_nodes_payload():
    nodes = (
        scoped_query(OrientationNode.query, OrientationNode)
        .order_by(
            OrientationNode.y.asc(),
            OrientationNode.x.asc(),
            OrientationNode.id.asc(),
        )
        .all()
    )
    payloads = [node.to_dict() for node in nodes]
    payload_by_id = {payload["id"]: payload for payload in payloads}
    child_map = {}
    for payload in payloads:
        child_map.setdefault(payload["parent_id"], []).append(payload["id"])

    def descendant_person_count(node_id):
        total = 0
        for child_id in child_map.get(node_id, []):
            child = payload_by_id[child_id]
            if child["node_type"] == "person":
                total += 1
            total += descendant_person_count(child_id)
        return total

    for payload in payloads:
        payload["descendant_count"] = descendant_person_count(payload["id"])
    return payloads


def parse_node_parent(parent_id, current_node=None):
    if parent_id in (None, "", "null"):
        return None

    try:
        parent_id = int(parent_id)
    except (TypeError, ValueError):
        raise ValueError("invalid_parent") from None

    parent = scoped_query(OrientationNode.query, OrientationNode).filter_by(
        id=parent_id
    ).first()
    if parent is None:
        raise ValueError("invalid_parent")

    if current_node is not None:
        check_parent = parent
        while check_parent is not None:
            if check_parent.id == current_node.id:
                raise ValueError("invalid_parent")
            check_parent = check_parent.parent

    return parent


def parse_coordinate(data, key, default):
    try:
        value = int(float(data.get(key, default)))
    except (TypeError, ValueError):
        value = default
    return max(20, min(value, 4000))


def parse_node_color(value):
    value = (value or "").strip()
    if HEX_COLOR_PATTERN.match(value):
        return value.lower()
    return "#198754"


def short_text(value, length=90):
    value = " ".join((value or "").split())
    if len(value) <= length:
        return value
    return f"{value[: length - 3]}..."


def dashboard_filters():
    return {
        "search": request.args.get("search", "").strip(),
        "department": request.args.get("department", "").strip(),
        "responsible_user_id": request.args.get("responsible_user_id", "").strip(),
        "status": request.args.get("status", "").strip(),
    }


def filtered_actions(actions, filters):
    search = filters["search"].lower()
    department = filters["department"]
    responsible_user_id = filters["responsible_user_id"]
    status = filters["status"]

    if responsible_user_id:
        try:
            responsible_user_id = int(responsible_user_id)
        except ValueError:
            responsible_user_id = None

    result = []
    for action in actions:
        if search and search not in " ".join(
            [
                action.title or "",
                action.description or "",
                action.responsible_owner or "",
                action.related_user_1.full_name if action.related_user_1 else "",
                action.related_user_2.full_name if action.related_user_2 else "",
                action.department or "",
            ]
        ).lower():
            continue
        if department and action.department != department:
            continue
        if responsible_user_id and action.responsible_user_id != responsible_user_id:
            continue
        if status == "open" and (
            action.is_completed
            or action.closure_approval_requested
            or action.closure_rejection_reason
            or action.delay_days > 0
        ):
            continue
        if status == "pending" and (
            action.is_completed or not action.closure_approval_requested
        ):
            continue
        if status == "rejected" and (
            action.is_completed
            or action.closure_approval_requested
            or not action.closure_rejection_reason
        ):
            continue
        if status == "delayed" and (action.is_completed or action.delay_days == 0):
            continue
        if status == "completed" and not action.is_completed:
            continue
        result.append(action)

    return result


def dof_display_status(dof, today=None):
    if dof.status == "Taslak" or dof.approval_step == "draft":
        return "Taslak"
    if dof.status == "Revizyon Bekleniyor" or dof.approval_step == "revision_requested":
        return "Revizyon Bekleniyor"
    if dof.status == "Tamamlandı" or dof.approval_step == "completed":
        return "Tamamlandı"
    if dof.approval_step in {
        "management_representative",
        "general_manager_deputy",
    }:
        return "Onay Akışı Bekleniyor"
    return dof.status or "Onay Akışı Bekleniyor"


def dof_delay_days(dof, today=None):
    today = today or date.today()
    if dof.status in {"Taslak", "Tamamlandı"} or not dof.due_date:
        return 0
    return max((today - dof.due_date).days, 0)


def dof_due_status(dof, today=None):
    today = today or date.today()
    if not dof.due_date:
        return {"text": "Termin yok", "tone": "muted"}
    if dof.status == "Tamamlandı" or dof.approval_step == "completed":
        return {"text": "Tamamlandı", "tone": "success"}

    remaining_days = (dof.due_date - today).days
    if remaining_days > 0:
        return {
            "text": f"{remaining_days} gün kaldı",
            "tone": "warning" if remaining_days <= 7 else "muted",
        }
    if remaining_days == 0:
        return {"text": "Bugün", "tone": "warning"}
    return {"text": f"{abs(remaining_days)} gün gecikti", "tone": "danger"}


def attach_dof_view_state(dofs):
    today = date.today()
    for dof in dofs:
        if dof.approval_step not in DOF_APPROVAL_STEPS:
            dof.approval_step = "draft" if dof.status == "Taslak" else "management_representative"
        dof.display_status = dof_display_status(dof, today=today)
        dof.delay_days = dof_delay_days(dof, today=today)
        due_status = dof_due_status(dof, today=today)
        dof.due_status_text = due_status["text"]
        dof.due_status_tone = due_status["tone"]
    return dofs


def dof_approval_steps(dof):
    step = dof.approval_step or "draft"
    is_rejected = step == "revision_requested" or dof.status == "Revizyon Bekleniyor"
    rejected_step = dof.rejected_step if is_rejected else None
    return [
        {
            "key": "opened",
            "title": "İF Açılması",
            "status": "Tamamlandı" if step != "draft" else "Beklemede",
            "is_active": step == "draft",
            "is_complete": step != "draft",
            "actor": dof.created_by.full_name if dof.created_by else "",
            "date": dof.created_at,
        },
        {
            "key": "management_representative",
            "title": "Yönetim Temsilcisi",
            "status": "Reddedildi"
            if rejected_step == "management_representative"
            else (
                "Tamamlandı"
                if dof.management_approved_at
                else ("Onay Bekliyor" if step == "management_representative" else "Beklemede")
            ),
            "is_active": step == "management_representative"
            or rejected_step == "management_representative",
            "is_complete": bool(dof.management_approved_at)
            or step in {"general_manager_deputy", "completed"},
            "is_rejected": rejected_step == "management_representative",
            "actor": (
                dof.rejected_by.full_name
                if rejected_step == "management_representative" and dof.rejected_by
                else (
                    dof.management_approved_by.full_name
                    if dof.management_approved_by
                    else ""
                )
            ),
            "date": (
                dof.rejected_at
                if rejected_step == "management_representative"
                else dof.management_approved_at
            ),
        },
        {
            "key": "general_manager_deputy",
            "title": "Genel Müdür Yardımcısı",
            "status": "Reddedildi"
            if rejected_step == "general_manager_deputy"
            else (
                "Tamamlandı"
                if dof.deputy_approved_at
                else ("Onay Bekliyor" if step == "general_manager_deputy" else "Beklemede")
            ),
            "is_active": step == "general_manager_deputy"
            or rejected_step == "general_manager_deputy",
            "is_complete": bool(dof.deputy_approved_at) or step == "completed",
            "is_rejected": rejected_step == "general_manager_deputy",
            "actor": (
                dof.rejected_by.full_name
                if rejected_step == "general_manager_deputy" and dof.rejected_by
                else (
                    dof.deputy_approved_by.full_name
                    if dof.deputy_approved_by
                    else ""
                )
            ),
            "date": (
                dof.rejected_at
                if rejected_step == "general_manager_deputy"
                else dof.deputy_approved_at
            ),
        },
    ]


def visible_dofs_query():
    query = scoped_query(Dof.query, Dof)
    if can_view_all_dofs():
        return query
    return query.filter(
        or_(
            Dof.responsible_id == g.current_user.id,
            Dof.created_by_user_id == g.current_user.id,
        )
    )


def dof_filters():
    return {
        "search": request.args.get("search", "").strip(),
        "department": request.args.get("department", "").strip(),
        "responsible_id": request.args.get("responsible_id", "").strip(),
        "status": request.args.get("status", "").strip(),
    }


def filtered_dofs(dofs, filters):
    search = filters["search"].lower()
    department = filters["department"]
    responsible_id = filters["responsible_id"]
    status = filters["status"]

    if responsible_id:
        try:
            responsible_id = int(responsible_id)
        except ValueError:
            responsible_id = None

    result = []
    for dof in dofs:
        if search and search not in " ".join(
            [
                dof.dof_no or "",
                dof.title or "",
                dof.nonconformity_description or "",
                dof.department or "",
                dof.priority or "",
                dof.source or "",
                dof.responsible.full_name if dof.responsible else "",
            ]
        ).lower():
            continue
        if department and dof.department != department:
            continue
        if responsible_id and dof.responsible_id != responsible_id:
            continue
        if status == "draft" and dof.display_status != "Taslak":
            continue
        if status == "approval" and dof.display_status != "Onay Akışı Bekleniyor":
            continue
        if status == "revision" and dof.display_status != "Revizyon Bekleniyor":
            continue
        if status == "completed" and dof.display_status != "Tamamlandı":
            continue
        if status == "delayed" and (
            dof.display_status == "Tamamlandı" or dof.delay_days == 0
        ):
            continue
        result.append(dof)

    return result


def delete_uploaded_file(action):
    if not action.file_stored_name:
        return

    delete_stored_upload(action.file_stored_name)

    action.file_original_name = None
    action.file_stored_name = None
    action.file_mime_type = None


def store_uploaded_file(uploaded_file, allowed_extensions=None, folder="actions", company_id=None):
    extension_allowed = (
        "." in uploaded_file.filename
        and uploaded_file.filename.rsplit(".", 1)[1].lower()
        in (allowed_extensions or ALLOWED_EXTENSIONS)
    )
    if not extension_allowed:
        raise ValueError("invalid_file_type")

    safe_name = secure_filename(uploaded_file.filename)
    extension = safe_name.rsplit(".", 1)[1].lower()
    stored_name = f"{uuid4().hex}.{extension}"
    relative_path, upload_path = upload_storage_path(stored_name, folder, company_id)
    uploaded_file.save(upload_path)
    return safe_name, str(relative_path).replace("\\", "/"), uploaded_file.mimetype


def save_uploaded_file(action):
    uploaded_file = request.files.get("action_file")
    if not uploaded_file or not uploaded_file.filename:
        return

    delete_uploaded_file(action)
    safe_name, stored_name, mime_type = store_uploaded_file(
        uploaded_file,
        folder="actions/files",
        company_id=action.company_id,
    )

    action.file_original_name = safe_name
    action.file_stored_name = stored_name
    action.file_mime_type = mime_type


def delete_closure_evidence_file(action):
    for closure_file in list(action.closure_files):
        delete_stored_upload(closure_file.stored_name)
        db.session.delete(closure_file)

    if action.closure_file_stored_name:
        delete_stored_upload(action.closure_file_stored_name)

    action.closure_file_original_name = None
    action.closure_file_stored_name = None
    action.closure_file_mime_type = None


def closure_evidence_uploads():
    uploaded_files = request.files.getlist("closure_files")
    if not uploaded_files:
        uploaded_file = request.files.get("closure_file")
        uploaded_files = [uploaded_file] if uploaded_file else []
    return [uploaded_file for uploaded_file in uploaded_files if uploaded_file.filename]


def save_closure_evidence_files(action):
    uploaded_files = closure_evidence_uploads()
    for uploaded_file in uploaded_files:
        if not allowed_file(uploaded_file.filename):
            raise ValueError("invalid_file_type")

    delete_closure_evidence_file(action)
    for uploaded_file in uploaded_files:
        safe_name, stored_name, mime_type = store_uploaded_file(
            uploaded_file,
            folder="actions/closure",
            company_id=action.company_id,
        )
        db.session.add(
            ActionClosureFile(
                action=action,
                company_id=action.company_id,
                original_name=safe_name,
                stored_name=stored_name,
                mime_type=mime_type,
            )
        )


def delete_sub_action_evidence_file(sub_action):
    if not sub_action.evidence_stored_name:
        return

    delete_stored_upload(sub_action.evidence_stored_name)

    sub_action.evidence_original_name = None
    sub_action.evidence_stored_name = None
    sub_action.evidence_mime_type = None


def save_sub_action_evidence_file(sub_action):
    uploaded_file = request.files.get("evidence_file")
    if not uploaded_file or not uploaded_file.filename:
        return

    delete_sub_action_evidence_file(sub_action)
    safe_name, stored_name, mime_type = store_uploaded_file(
        uploaded_file,
        SUB_ACTION_EVIDENCE_EXTENSIONS,
        folder="actions/sub-actions",
        company_id=sub_action.company_id,
    )
    sub_action.evidence_original_name = safe_name
    sub_action.evidence_stored_name = stored_name
    sub_action.evidence_mime_type = mime_type


def parse_sub_action_form(sub_action=None):
    sub_action = sub_action or ActionSubTask()
    title = request.form.get("title", "").strip()
    responsible = parse_optional_user("responsible_id")
    related_user_1 = parse_optional_user("related_user_1_id")
    related_user_2 = parse_optional_user("related_user_2_id")
    due_date = parse_optional_date("due_date")
    priority = request.form.get("priority", "Orta").strip() or "Orta"
    status = request.form.get("status", "Beklemede").strip() or "Beklemede"
    description = request.form.get("description", "").strip()
    closing_note = request.form.get("closing_note", "").strip()
    evidence_required = request.form.get("evidence_required") == "on"

    if not title:
        raise ValueError("required_fields")
    if len(title) > 160 or len(description) > 2000 or len(closing_note) > 2000:
        raise ValueError("text_too_long")
    if priority not in ACTION_SUB_TASK_PRIORITIES:
        raise ValueError("invalid_priority")
    if status not in ACTION_SUB_TASK_STATUSES:
        raise ValueError("invalid_status")

    sub_action.title = title
    sub_action.responsible_id = responsible.id if responsible else None
    sub_action.related_user_1_id = related_user_1.id if related_user_1 else None
    sub_action.related_user_2_id = related_user_2.id if related_user_2 else None
    sub_action.due_date = due_date
    sub_action.priority = priority
    sub_action.status = status
    sub_action.description = description or None
    sub_action.evidence_required = evidence_required
    sub_action.closing_note = closing_note or None
    save_sub_action_evidence_file(sub_action)

    if status == "Tamamlandı":
        if evidence_required and not sub_action.evidence_stored_name:
            raise ValueError("evidence_required")
        if evidence_required and not closing_note:
            raise ValueError("closing_note_required")
        sub_action.completed_at = sub_action.completed_at or datetime.utcnow()
        sub_action.completed_by_user_id = sub_action.completed_by_user_id or g.current_user.id
    else:
        sub_action.completed_at = None
        sub_action.completed_by_user_id = None
    return sub_action


def parse_sub_action_limited_revision(sub_action):
    responsible_value = request.form.get("responsible_id", "").strip()
    responsible = None
    if responsible_value:
        try:
            responsible_id = int(responsible_value)
        except ValueError:
            raise ValueError("invalid_user") from None

        responsible = active_user_by_id(responsible_id)
        if responsible is None:
            raise ValueError("invalid_user")

    related_user_1 = parse_optional_user("related_user_1_id")
    related_user_2 = parse_optional_user("related_user_2_id")
    due_date = parse_optional_date("due_date")
    if due_date is None:
        raise ValueError("invalid_date")

    sub_action.responsible_id = responsible.id if responsible else None
    sub_action.related_user_1_id = related_user_1.id if related_user_1 else None
    sub_action.related_user_2_id = related_user_2.id if related_user_2 else None
    sub_action.due_date = due_date
    return sub_action


def parse_sub_action_inline(index):
    title = request.form.get(f"sub_action_title_{index}", "").strip()
    description = request.form.get(f"sub_action_description_{index}", "").strip()
    responsible = parse_optional_user(f"sub_action_responsible_id_{index}")
    related_user_1 = parse_optional_user(f"sub_action_related_user_1_id_{index}")
    related_user_2 = parse_optional_user(f"sub_action_related_user_2_id_{index}")
    due_date = parse_optional_date(f"sub_action_due_date_{index}")
    priority = request.form.get(f"sub_action_priority_{index}", "Orta").strip() or "Orta"
    status = request.form.get(f"sub_action_status_{index}", "Beklemede").strip() or "Beklemede"
    evidence_required = request.form.get(f"sub_action_evidence_required_{index}") == "on"

    has_any_value = any(
        [title, description, responsible, related_user_1, related_user_2, due_date]
    )
    if not has_any_value:
        return None
    if not title:
        raise ValueError("sub_action_required_fields")
    if len(title) > 160 or len(description) > 2000:
        raise ValueError("text_too_long")
    if priority not in ACTION_SUB_TASK_PRIORITIES:
        raise ValueError("invalid_sub_action_priority")
    if status not in ACTION_SUB_TASK_STATUSES:
        raise ValueError("invalid_sub_action_status")
    if status == "Tamamlandı" and evidence_required:
        raise ValueError("sub_action_completion_requires_evidence")

    return {
        "title": title,
        "description": description or None,
        "responsible_id": responsible.id if responsible else None,
        "related_user_1_id": related_user_1.id if related_user_1 else None,
        "related_user_2_id": related_user_2.id if related_user_2 else None,
        "due_date": due_date,
        "priority": priority,
        "status": status,
        "evidence_required": evidence_required,
    }


def create_inline_sub_actions(action):
    indexes = [
        index.strip()
        for index in request.form.get("sub_action_indexes", "").split(",")
        if index.strip()
    ]
    created_items = []
    for index in indexes:
        data = parse_sub_action_inline(index)
        if not data:
            continue
        sub_action = ActionSubTask(
            parent_action=action,
            company_id=action.company_id,
            created_by_user_id=g.current_user.id,
            **data,
        )
        if sub_action.status == "Tamamlandı":
            sub_action.completed_at = datetime.utcnow()
            sub_action.completed_by_user_id = g.current_user.id
        db.session.add(sub_action)
        created_items.append(sub_action)
    return created_items


def refresh_all_actions():
    actions = visible_actions_query().order_by(Action.termin_date.asc(), Action.id.asc()).all()
    changed = False
    for action in actions:
        old_delay_days = action.delay_days
        action.refresh_delay()
        changed = changed or old_delay_days != action.delay_days

    if changed:
        db.session.commit()

    return actions


def parse_action_form(action=None):
    action = action or Action()
    title = request.form.get("title", "").strip()
    responsible_user_id = request.form.get("responsible_user_id", "").strip()
    department = request.form.get("department", "").strip()

    if not title or not responsible_user_id or not department:
        raise ValueError("required_fields")
    if department not in DEPARTMENTS:
        raise ValueError("invalid_department")

    try:
        responsible_user_id = int(responsible_user_id)
    except ValueError:
        raise ValueError("invalid_user") from None

    responsible_user = active_user_by_id(responsible_user_id)
    if responsible_user is None:
        raise ValueError("invalid_user")
    related_user_1 = parse_optional_user("related_user_1_id")
    related_user_2 = parse_optional_user("related_user_2_id")

    action.title = title
    action.responsible_user_id = responsible_user.id
    action.responsible_owner = responsible_user.full_name
    action.related_user_1_id = related_user_1.id if related_user_1 else None
    action.related_user_2_id = related_user_2.id if related_user_2 else None
    action.department = department
    action.description = request.form.get("description", "").strip()

    termin_value = request.form.get("termin_date", "")
    action.termin_date = datetime.strptime(termin_value, "%Y-%m-%d").date()
    action.refresh_delay()
    save_uploaded_file(action)
    return action


def parse_dof_form(dof=None, save_mode="open", update_workflow=True):
    dof = dof or Dof()
    is_draft = save_mode == "draft"
    is_approval_request = save_mode == "open"
    require_closing_actions = (
        request.form.get("require_closing_actions") == "1" and is_approval_request
    )
    title = request.form.get("title", "").strip()
    department = request.form.get("department", "").strip()
    priority = request.form.get("priority", "").strip()
    source = request.form.get("source", "").strip()
    responsible = parse_optional_active_user("responsible_id")
    opening_date = parse_optional_date("opening_date")
    due_date = parse_optional_date("due_date")
    nonconformity_description = request.form.get(
        "nonconformity_description", ""
    ).strip()
    root_cause_analysis = request.form.get("root_cause_analysis", "").strip()
    corrective_action = request.form.get("corrective_action", "").strip()
    preventive_action = request.form.get("preventive_action", "").strip()
    closing_evidence = request.form.get("closing_evidence", "").strip()

    for text_value in (
        nonconformity_description,
        root_cause_analysis,
        corrective_action,
        preventive_action,
        closing_evidence,
    ):
        if len(text_value) > 2000:
            raise ValueError("text_too_long")

    if department and department not in DEPARTMENTS:
        raise ValueError("invalid_department")
    if priority and priority not in DOF_PRIORITIES:
        raise ValueError("invalid_priority")
    if source and source not in DOF_SOURCES:
        raise ValueError("invalid_source")

    if not is_draft and (
        not title
        or not department
        or not responsible
        or not opening_date
        or not priority
        or not source
        or not nonconformity_description
    ):
        raise ValueError("required_fields")
    if not is_draft and require_closing_actions and not closing_evidence:
        raise ValueError("closing_actions_required")

    dof.title = title or None
    dof.department = department or None
    dof.responsible_id = responsible.id if responsible else None
    dof.opening_date = opening_date
    dof.due_date = due_date
    dof.priority = priority or None
    dof.source = source or None
    dof.nonconformity_description = nonconformity_description or None
    dof.root_cause_analysis = root_cause_analysis or None
    dof.corrective_action = corrective_action or None
    dof.preventive_action = preventive_action or None
    if require_closing_actions or "closing_evidence" in request.form:
        dof.closing_evidence = closing_evidence or None
    if not update_workflow:
        return dof

    if is_draft:
        dof.status = "Taslak"
        dof.approval_step = "draft"
        dof.management_approved_by_user_id = None
        dof.management_approved_at = None
        dof.deputy_approved_by_user_id = None
        dof.deputy_approved_at = None
        dof.completed_at = None
    else:
        dof.status = "Onay Akışı Bekleniyor"
        dof.rejection_reason = None
        dof.rejected_by_user_id = None
        dof.rejected_at = None
        dof.rejected_step = None
        dof.deputy_approved_by_user_id = None
        dof.deputy_approved_at = None
        dof.completed_at = None
        dof.approval_step = "management_representative"
        dof.management_approved_by_user_id = None
        dof.management_approved_at = None
    return dof


def dof_form_data_from_record(dof):
    return {
        "title": dof.title or "",
        "department": dof.department or "",
        "responsible_id": str(dof.responsible_id or ""),
        "opening_date": dof.opening_date.isoformat() if dof.opening_date else "",
        "due_date": dof.due_date.isoformat() if dof.due_date else "",
        "priority": dof.priority or "",
        "source": dof.source or "",
        "nonconformity_description": dof.nonconformity_description or "",
        "root_cause_analysis": dof.root_cause_analysis or "",
        "corrective_action": dof.corrective_action or "",
        "preventive_action": dof.preventive_action or "",
        "closing_evidence": dof.closing_evidence or "",
    }


def dof_revision_snapshot(dof):
    return {
        "title": dof.title or "",
        "department": dof.department or "",
        "responsible_id": dof.responsible_id,
        "opening_date": dof.opening_date,
        "due_date": dof.due_date,
        "priority": dof.priority or "",
        "source": dof.source or "",
        "nonconformity_description": dof.nonconformity_description or "",
        "root_cause_analysis": dof.root_cause_analysis or "",
        "corrective_action": dof.corrective_action or "",
        "preventive_action": dof.preventive_action or "",
        "closing_evidence": dof.closing_evidence or "",
        "evidence_original_name": dof.evidence_original_name or "",
    }


def parse_dof_revision_form(dof):
    title = request.form.get("title", "").strip()
    department = request.form.get("department", "").strip()
    priority = request.form.get("priority", "").strip()
    source = request.form.get("source", "").strip()
    responsible = parse_optional_active_user("responsible_id")
    opening_date = parse_optional_date("opening_date")
    due_date = parse_optional_date("due_date")
    nonconformity_description = request.form.get(
        "nonconformity_description", ""
    ).strip()
    root_cause_analysis = request.form.get("root_cause_analysis", "").strip()
    corrective_action = request.form.get("corrective_action", "").strip()
    preventive_action = request.form.get("preventive_action", "").strip()
    closing_evidence = request.form.get("closing_evidence", "").strip()

    for text_value in (
        nonconformity_description,
        root_cause_analysis,
        corrective_action,
        preventive_action,
        closing_evidence,
    ):
        if len(text_value) > 2000:
            raise ValueError("text_too_long")

    if (
        not title
        or not department
        or not responsible
        or not opening_date
        or not priority
        or not source
        or not nonconformity_description
    ):
        raise ValueError("required_fields")
    if department not in DEPARTMENTS:
        raise ValueError("invalid_department")
    if priority not in DOF_PRIORITIES:
        raise ValueError("invalid_priority")
    if source not in DOF_SOURCES:
        raise ValueError("invalid_source")

    dof.title = title
    dof.department = department
    dof.responsible_id = responsible.id
    dof.opening_date = opening_date
    dof.due_date = due_date
    dof.priority = priority
    dof.source = source
    dof.nonconformity_description = nonconformity_description
    dof.root_cause_analysis = root_cause_analysis or None
    dof.corrective_action = corrective_action or None
    dof.preventive_action = preventive_action or None
    dof.closing_evidence = closing_evidence or None
    save_dof_evidence_file(dof)


def describe_dof_revision_changes(before, dof):
    labels = {
        "title": "başlık",
        "department": "departman",
        "opening_date": "açılış tarihi",
        "due_date": "termin",
        "priority": "öncelik",
        "source": "kaynak",
        "nonconformity_description": "uygunsuzluk açıklaması",
        "root_cause_analysis": "kök neden analizi",
        "corrective_action": "düzeltici faaliyet",
        "preventive_action": "önleyici faaliyet",
        "closing_evidence": "kapanış kanıtı açıklaması",
    }
    after = dof_revision_snapshot(dof)
    changes = []

    if before["responsible_id"] != after["responsible_id"]:
        old_user = User.query.get(before["responsible_id"]) if before["responsible_id"] else None
        new_user = User.query.get(after["responsible_id"]) if after["responsible_id"] else None
        changes.append(
            "sorumlu "
            f"{old_user.full_name if old_user else '-'} -> "
            f"{new_user.full_name if new_user else '-'}"
        )

    for field, label in labels.items():
        old_value = before[field]
        new_value = after[field]
        if field in {"opening_date", "due_date"}:
            old_value = format_date(old_value)
            new_value = format_date(new_value)
        if old_value != new_value:
            changes.append(f"{label} güncellendi")

    if before["evidence_original_name"] != after["evidence_original_name"]:
        changes.append("kanıt dosyası güncellendi")

    return changes


def parse_user_form(user=None):
    user = user or User()
    username = request.form.get("username", "").strip().lower()
    full_name = request.form.get("full_name", "").strip()
    password = request.form.get("password", "")
    company_id = None if username == "superadmin" else current_company_id()

    if not username or not full_name:
        raise ValueError("required_fields")
    if user.id is None and not password:
        raise ValueError("password_required")
    if password:
        validate_password_policy(password)

    existing_query = User.query.filter(User.username == username, User.id != user.id)
    if username == "superadmin":
        existing_query = existing_query.filter(User.company_id.is_(None))
    elif company_id:
        existing_query = existing_query.filter(User.company_id == company_id)
    else:
        existing_query = existing_query.filter(User.company_id.is_(None))

    existing_user = existing_query.first()
    if existing_user:
        raise ValueError("username_exists")

    user.username = username
    user.full_name = full_name
    user.title = request.form.get("title", "").strip()
    user.email = request.form.get("email", "").strip() or None
    user.is_active = request.form.get("is_active") == "on"
    user.can_create_actions = request.form.get("can_create_actions") == "on"
    user.can_edit_actions = request.form.get("can_edit_actions") == "on"
    user.can_delete_actions = request.form.get("can_delete_actions") == "on"
    user.can_comment_assigned_actions = (
        request.form.get("can_comment_assigned_actions") == "on"
    )
    user.can_close_assigned_actions = request.form.get("can_close_assigned_actions") == "on"
    user.can_manage_users = request.form.get("can_manage_users") == "on"
    if user.username == "superadmin":
        user.company_id = None
    elif company_id:
        user.company_id = company_id

    if password:
        user.set_password(password)

    return user


def sync_user_legacy_permissions(user):
    legacy_map = {
        "can_create_actions": "actions.create",
        "can_edit_actions": "actions.edit",
        "can_delete_actions": "actions.delete",
        "can_comment_assigned_actions": "actions.comment_assigned",
        "can_close_assigned_actions": "actions.request_close_assigned",
        "can_manage_users": "users.manage",
    }
    for field, permission_key in legacy_map.items():
        setattr(user, field, has_permission(user, permission_key))


def user_extra_permission_keys(user):
    return {permission.permission_key for permission in user.extra_permissions}


def permission_catalog_grouped():
    from .seed import PERMISSION_CATALOG

    groups = {}
    for item in PERMISSION_CATALOG:
        groups.setdefault(item["group"], []).append(item)
    return groups


def role_hierarchy():
    return (
        Role.query.filter_by(is_system=True)
        .order_by(Role.hierarchy_level.asc(), Role.name.asc())
        .all()
    )


RESERVED_COMPANY_SLUGS = {
    "admin",
    "api",
    "app",
    "assets",
    "mail",
    "smtp",
    "static",
    "superadmin",
    "www",
}


def normalize_company_slug(value):
    value = (value or "").strip().lower()
    replacements = {
        "ç": "c",
        "ğ": "g",
        "ı": "i",
        "ö": "o",
        "ş": "s",
        "ü": "u",
    }
    for source, target in replacements.items():
        value = value.replace(source, target)

    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")
    return value[:80]


def normalize_company_domain(value):
    value = (value or "").strip().lower()
    for prefix in ("https://", "http://"):
        if value.startswith(prefix):
            value = value[len(prefix):]
    value = value.split("/")[0].strip(".")
    return value[:255]


def tenant_base_domain():
    return normalize_company_domain(current_app.config.get("TENANT_BASE_DOMAIN"))


def company_primary_domain_for_slug(slug):
    base_domain = tenant_base_domain()
    if not base_domain:
        return slug
    return f"{slug}.{base_domain}"


def company_field_exists(field_name, value, company_id=None):
    if not value:
        return False

    return (
        Company.query.filter(
            getattr(Company, field_name) == value,
            Company.id != company_id,
        ).first()
        is not None
    )


def parse_company_form(company=None):
    company = company or Company()
    code = request.form.get("code", "").strip()
    name = request.form.get("name", "").strip()
    slug = normalize_company_slug(request.form.get("slug") or name)
    primary_domain = normalize_company_domain(request.form.get("primary_domain"))
    custom_domain = normalize_company_domain(request.form.get("custom_domain"))

    if not code or not name:
        raise ValueError("required_fields")
    if not code.isdigit() or len(code) != 3:
        raise ValueError("invalid_code")
    if not slug or slug in RESERVED_COMPANY_SLUGS:
        raise ValueError("invalid_slug")
    if not primary_domain:
        primary_domain = company_primary_domain_for_slug(slug)
    if custom_domain and custom_domain == primary_domain:
        raise ValueError("duplicate_domain")

    existing_company = Company.query.filter(
        Company.code == code,
        Company.id != company.id,
    ).first()
    if existing_company:
        raise ValueError("code_exists")
    if company_field_exists("slug", slug, company.id):
        raise ValueError("slug_exists")
    if company_field_exists("primary_domain", primary_domain, company.id):
        raise ValueError("domain_exists")
    if company_field_exists("custom_domain", custom_domain, company.id):
        raise ValueError("domain_exists")

    company.code = code
    company.name = name[:160]
    company.slug = slug
    company.primary_domain = primary_domain
    company.custom_domain = custom_domain or None
    company.is_active = request.form.get("is_active") == "on"
    return company


def flash_company_form_error(error):
    error_key = str(error)
    if error_key == "required_fields":
        flash("Åirket kodu ve ÅŸirket adÄ± zorunludur.", "danger")
    elif error_key == "invalid_code":
        flash("Åirket kodu 000 gibi tam 3 haneli sayÄ± olmalÄ±dÄ±r.", "danger")
    elif error_key == "code_exists":
        flash("Bu ÅŸirket kodu zaten kullanÄ±lÄ±yor.", "danger")
    else:
        flash("Åirket formunu kontrol edin.", "danger")


def normalize_login_identity(value):
    return (value or "").strip().lower()[:160]


def login_client_ip():
    return (request.remote_addr or "unknown")[:45]


def login_user_agent():
    return (request.headers.get("User-Agent") or "")[:255]


def login_lockout_window_start():
    return datetime.utcnow() - timedelta(
        minutes=current_app.config["LOGIN_LOCKOUT_MINUTES"]
    )


def login_counter_start(username=None, ip_address=None):
    window_start = login_lockout_window_start()
    query = LoginAttempt.query.filter(LoginAttempt.success.is_(True))
    if username is not None:
        query = query.filter(LoginAttempt.username == username)
    if ip_address is not None:
        query = query.filter(LoginAttempt.ip_address == ip_address)
    last_success_at = query.with_entities(db.func.max(LoginAttempt.created_at)).scalar()
    if last_success_at and last_success_at > window_start:
        return last_success_at
    return window_start


def recent_failed_login_count(username=None, ip_address=None):
    counter_start = login_counter_start(username=username, ip_address=ip_address)
    query = LoginAttempt.query.filter(
        LoginAttempt.success.is_(False),
        LoginAttempt.reason == "wrong_credentials",
        LoginAttempt.created_at >= counter_start,
    )
    if username is not None:
        query = query.filter(LoginAttempt.username == username)
    if ip_address is not None:
        query = query.filter(LoginAttempt.ip_address == ip_address)
    return query.count()


def login_rate_limit_reason(username, ip_address):
    max_user_attempts = current_app.config["LOGIN_MAX_FAILED_ATTEMPTS"]
    max_ip_attempts = current_app.config["LOGIN_IP_MAX_FAILED_ATTEMPTS"]
    username_blocked = bool(username) and (
        recent_failed_login_count(username=username) >= max_user_attempts
    )
    ip_blocked = recent_failed_login_count(ip_address=ip_address) >= max_ip_attempts
    if username_blocked:
        return "locked"
    if ip_blocked:
        return "rate_limited"
    return None


def log_login_attempt(username, ip_address, success, reason):
    db.session.add(
        LoginAttempt(
            username=username or None,
            ip_address=ip_address,
            user_agent=login_user_agent(),
            success=success,
            reason=reason,
        )
    )


def find_login_user(identity, company=None):
    identity = normalize_login_identity(identity)
    if not identity:
        return None

    query = User.query.filter(
        or_(
            db.func.lower(User.username) == identity,
            db.func.lower(User.full_name) == identity,
        )
    )

    if company is not None:
        query = query.filter(
            or_(
                User.company_id == company.id,
                User.company_id.is_(None),
            )
        ).order_by(User.company_id.is_(None).asc(), User.id.asc())
    else:
        query = query.filter(User.company_id.is_(None)).order_by(User.id.asc())

    return query.first()


def validate_password_policy(password):
    if not password or len(password) < current_app.config["PASSWORD_MIN_LENGTH"]:
        raise ValueError("password_too_short")


def flash_user_form_error(error):
    error_key = str(error)
    if error_key == "username_exists":
        flash("Bu kullanıcı adı zaten kullanılıyor.", "danger")
    elif error_key == "password_too_short":
        flash("Parola en az 4 karakter olmalıdır.", "danger")
    else:
        flash("Lütfen kullanıcı bilgilerini eksiksiz doldurun.", "danger")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if g.current_user is not None:
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        identity = normalize_login_identity(request.form.get("identity"))
        password = request.form.get("password", "")
        remember_me = request.form.get("remember_me") == "1"
        ip_address = login_client_ip()
        tenant_company = getattr(g, "tenant_company", None)

        lock_reason = login_rate_limit_reason(identity, ip_address)
        if lock_reason:
            log_login_attempt(identity, ip_address, False, lock_reason)
            db.session.commit()
            flash(
                "Çok fazla hatalı giriş denemesi yapıldı. Lütfen birkaç dakika sonra tekrar deneyin.",
                "danger",
            )
            return render_template("login.html")

        company = tenant_company
        user = find_login_user(identity, company)

        if user and user.is_active and user.check_password(password):
            is_super_admin = has_role(user, "super_admin")
            if not is_super_admin:
                if company is None:
                    log_login_attempt(identity, ip_address, False, "missing_company")
                    db.session.commit()
                    flash("Lutfen sirketinize ait VolkaPortal adresinden giris yapin.", "danger")
                    return render_template("login.html")
                if user.company_id != company.id:
                    log_login_attempt(identity, ip_address, False, "wrong_company")
                    db.session.commit()
                    flash("Bu kullanıcı seçilen şirkete bağlı değil.", "danger")
                    return render_template("login.html")

            log_login_attempt(identity, ip_address, True, "success")
            db.session.commit()
            session.clear()
            session.permanent = remember_me
            session["user_id"] = user.id
            if company is not None:
                session["company_id"] = company.id
            elif user.company_id:
                user_company = db.session.get(Company, user.company_id)
                if user_company is not None:
                    session["company_id"] = user_company.id
            flash("Giriş başarılı.", "success")
            next_url = request.args.get("next") or url_for("main.dashboard")
            return redirect(next_url)

        log_login_attempt(identity, ip_address, False, "wrong_credentials")
        db.session.commit()
        flash("Kullanıcı adı veya şifre hatalı.", "danger")

    return render_template("login.html")


@bp.route("/logout", methods=["GET", "POST"])
def logout():
    if request.method != "POST":
        flash(
            "Bu işlem güvenlik nedeniyle sadece çıkış butonu üzerinden yapılabilir.",
            "warning",
        )
        if g.current_user is not None:
            return redirect(url_for("main.dashboard"))
        return redirect(url_for("main.login"))
    session.clear()
    flash("Çıkış yapıldı.", "success")
    return redirect(url_for("main.login"))


@bp.get("/notifications")
@login_required
def notifications():
    notification_list = (
        scoped_query(Notification.query, Notification)
        .filter_by(user_id=g.current_user.id)
        .order_by(Notification.created_at.desc())
        .limit(100)
        .all()
    )
    unread_count = scoped_query(Notification.query, Notification).filter_by(
        user_id=g.current_user.id, is_read=False
    ).count()
    return render_template(
        "notifications.html",
        notifications=notification_list,
        unread_count=unread_count,
    )


@bp.get("/notifications/count")
@login_required
def notification_count():
    unread_count = scoped_query(Notification.query, Notification).filter_by(
        user_id=g.current_user.id, is_read=False
    ).count()
    return jsonify({"count": unread_count})


@bp.post("/notifications/<int:notification_id>/read")
@login_required
def mark_notification_read(notification_id):
    notification = scoped_query(Notification.query, Notification).filter_by(
        id=notification_id, user_id=g.current_user.id
    ).first_or_404()
    if not notification.is_read:
        notification.is_read = True
        db.session.commit()
    unread_count = scoped_query(Notification.query, Notification).filter_by(
        user_id=g.current_user.id, is_read=False
    ).count()
    return jsonify({"ok": True, "count": unread_count})


@bp.post("/notifications/read-all")
@login_required
def mark_all_notifications_read():
    unread_notifications = scoped_query(Notification.query, Notification).filter_by(
        user_id=g.current_user.id, is_read=False
    ).all()
    for notification in unread_notifications:
        notification.is_read = True
    if unread_notifications:
        db.session.commit()
    flash("Tüm bildirimler okundu olarak işaretlendi.", "success")
    return redirect(url_for("main.notifications"))


@bp.get("/notifications/<int:notification_id>/open")
@login_required
def open_notification(notification_id):
    notification = scoped_query(Notification.query, Notification).filter_by(
        id=notification_id, user_id=g.current_user.id
    ).first_or_404()
    if notification.action and can_view_action(notification.action):
        return redirect(url_for("main.action_detail", action_id=notification.action.id))
    if notification.dof and can_view_dof(notification.dof):
        return redirect(url_for("main.dof_detail", dof_id=notification.dof.id))
    return redirect(url_for("main.notifications"))


@bp.get("/organization")
@login_required
def organization():
    return render_template(
        "organization.html",
        nodes=orientation_nodes_payload(),
        can_edit=can_manage_orientation(),
    )


@bp.get("/organization1")
@login_required
def organization_legacy():
    return redirect(url_for("main.organization"))


@bp.get("/orientation")
@login_required
def orientation():
    return redirect(url_for("main.organization"))


@bp.post("/orientation/nodes")
@login_required
def create_orientation_node():
    if not can_manage_orientation():
        abort(403)

    data = request.get_json(silent=True) or {}
    node_type = (data.get("node_type") or "person").strip()
    if node_type not in ORGANIZATION_NODE_TYPES:
        node_type = "person"

    default_name = "Yeni departman" if node_type == "department" else "Yeni kişi"
    name = (data.get("name") or default_name).strip()
    title = (data.get("title") or "").strip()
    color = parse_node_color(data.get("color"))

    try:
        parent = parse_node_parent(data.get("parent_id"))
    except ValueError:
        return jsonify({"ok": False, "message": "Geçerli bir üst kişi seçin."}), 400

    if parent is not None:
        child_count = scoped_query(OrientationNode.query, OrientationNode).filter_by(
            parent_id=parent.id
        ).count()
        default_x = parent.x + (child_count * 24)
        default_y = parent.y + 170
    else:
        root_count = scoped_query(OrientationNode.query, OrientationNode).filter_by(
            parent_id=None
        ).count()
        default_x = 120 + (root_count * 32)
        default_y = 80

    node = OrientationNode(
        company_id=current_company_id(),
        parent_id=parent.id if parent else None,
        name=name[:160],
        title=title[:160],
        node_type=node_type,
        color=color,
        x=parse_coordinate(data, "x", default_x),
        y=parse_coordinate(data, "y", default_y),
    )
    db.session.add(node)
    db.session.commit()
    return jsonify({"ok": True, "node": node.to_dict(), "nodes": orientation_nodes_payload()})


@bp.post("/orientation/nodes/<int:node_id>/update")
@login_required
def update_orientation_node(node_id):
    if not can_manage_orientation():
        abort(403)

    node = OrientationNode.query.get_or_404(node_id)
    ensure_same_company(node)
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    title = (data.get("title") or "").strip()
    node_type = (data.get("node_type") or node.node_type or "person").strip()
    if node_type not in ORGANIZATION_NODE_TYPES:
        node_type = "person"
    color = parse_node_color(data.get("color") or node.color)

    if not name:
        return jsonify({"ok": False, "message": "İsim alanı boş bırakılamaz."}), 400

    try:
        parent = parse_node_parent(data.get("parent_id"), current_node=node)
    except ValueError:
        return jsonify({"ok": False, "message": "Geçerli bir üst kişi seçin."}), 400

    node.name = name[:160]
    node.title = title[:160]
    node.node_type = node_type
    node.color = color
    node.parent_id = parent.id if parent else None
    db.session.commit()
    return jsonify({"ok": True, "node": node.to_dict(), "nodes": orientation_nodes_payload()})


@bp.post("/orientation/nodes/<int:node_id>/move")
@login_required
def move_orientation_node(node_id):
    if not can_manage_orientation():
        abort(403)

    node = OrientationNode.query.get_or_404(node_id)
    ensure_same_company(node)
    data = request.get_json(silent=True) or {}
    node.x = parse_coordinate(data, "x", node.x)
    node.y = parse_coordinate(data, "y", node.y)
    db.session.commit()
    return jsonify({"ok": True, "node": node.to_dict()})


@bp.post("/orientation/nodes/<int:node_id>/delete")
@login_required
def delete_orientation_node(node_id):
    if not can_manage_orientation():
        abort(403)

    node = OrientationNode.query.get_or_404(node_id)
    ensure_same_company(node)
    db.session.delete(node)
    db.session.commit()
    return jsonify({"ok": True, "nodes": orientation_nodes_payload()})


def dashboard_context():
    all_actions = refresh_all_actions()
    filters = dashboard_filters()
    actions = filtered_actions(all_actions, filters)
    delayed_count = sum(
        1 for action in all_actions if not action.is_completed and action.delay_days > 0
    )
    completed_count = sum(1 for action in all_actions if action.is_completed)
    pending_approval_count = sum(
        1
        for action in all_actions
        if not action.is_completed and action.closure_approval_requested
    )
    total_count = len(all_actions)

    return {
        "actions": actions,
        "available_companies": Company.query.filter_by(is_active=True)
        .order_by(Company.code.asc())
        .all()
        if g.current_user_is_super_admin
        else [],
        "delayed_count": delayed_count,
        "completed_count": completed_count,
        "pending_approval_count": pending_approval_count,
        "total_count": total_count,
        "can_complete_action": can_complete_action,
        "can_request_closure_action": can_request_closure_action,
        "can_approve_closure_action": can_approve_closure_action,
        "departments": DEPARTMENTS,
        "filters": filters,
        "users": active_users(),
        "current_user_initials": user_initials(g.current_user),
    }


def dof_dashboard_context():
    all_dofs = attach_dof_view_state(
        visible_dofs_query().order_by(Dof.dof_no.asc(), Dof.id.asc()).all()
    )
    filters = dof_filters()
    dofs = filtered_dofs(all_dofs, filters)
    total_count = len(all_dofs)
    draft_count = sum(1 for dof in all_dofs if dof.display_status == "Taslak")
    approval_count = sum(
        1 for dof in all_dofs if dof.display_status == "Onay Akışı Bekleniyor"
    )
    revision_count = sum(
        1 for dof in all_dofs if dof.display_status == "Revizyon Bekleniyor"
    )
    completed_count = sum(1 for dof in all_dofs if dof.display_status == "Tamamlandı")
    delayed_count = sum(
        1
        for dof in all_dofs
        if dof.display_status != "Tamamlandı" and dof.delay_days > 0
    )

    return {
        "dofs": dofs,
        "total_count": total_count,
        "draft_count": draft_count,
        "approval_count": approval_count,
        "revision_count": revision_count,
        "completed_count": completed_count,
        "delayed_count": delayed_count,
        "departments": DEPARTMENTS,
        "filters": filters,
        "users": active_users() if can_view_all_dofs() else [g.current_user],
        "can_delete_dof": can_delete_dof,
        "can_edit_dof_draft": can_edit_dof_draft,
        "can_edit_dof": can_edit_dof,
        "can_revise_rejected_dof": can_revise_rejected_dof,
        "can_request_dof_approval": can_request_dof_approval,
    }


def assigned_filters():
    return {
        "scope": request.args.get("scope", "assigned").strip() or "assigned",
        "tab": request.args.get("tab", "all").strip() or "all",
        "search": request.args.get("search", "").strip(),
        "department": request.args.get("department", "").strip(),
        "module": request.args.get("module", "").strip(),
        "status": request.args.get("status", "").strip(),
        "due_start": request.args.get("due_start", "").strip(),
        "due_end": request.args.get("due_end", "").strip(),
    }


def parse_query_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def action_reference(action):
    year_source = action.termin_date or action.created_at or datetime.utcnow()
    year = year_source.year
    number = action.action_number or action.id
    return f"AKS-{year}-{number:04d}"


def compact_dof_status(status):
    if status == "Onay Akışı Bekleniyor":
        return "Onay Bekliyor"
    return status


def status_tone(status, status_key=None):
    if status_key in {"completed", "success"} or status == "Tamamlandı":
        return "success"
    if status_key in {"delayed", "rejected", "revision", "cancelled"}:
        return "danger" if status_key != "cancelled" else "muted"
    if status_key in {"pending", "draft"}:
        return "warning"
    if status in {"Devam Ediyor", "Planlandı"}:
        return "info"
    return "muted"


def priority_tone(priority):
    normalized = normalize_for_role(priority)
    if "kritik" in normalized or "yuksek" in normalized:
        return "danger"
    if "orta" in normalized:
        return "warning"
    if "dusuk" in normalized:
        return "info"
    return "muted"


def due_meta(due_date, is_completed=False):
    if not due_date:
        return {"text": "-", "tone": "muted"}
    if is_completed:
        return {"text": "Tamamlandı", "tone": "success"}

    remaining = (due_date - date.today()).days
    if remaining > 0:
        return {
            "text": f"{remaining} gün kaldı",
            "tone": "warning" if remaining <= 7 else "muted",
        }
    if remaining == 0:
        return {"text": "Bugün", "tone": "warning"}
    return {"text": f"{abs(remaining)} gün gecikti", "tone": "danger"}


def action_task_status(action):
    if action.is_completed:
        return "Tamamlandı", "completed"
    if action.closure_approval_requested:
        return "Kapanma Onayı Beklemede", "pending"
    if action.closure_rejection_reason:
        return "Kapanma Onayı Reddedildi", "rejected"
    if action.delay_days > 0:
        return "Gecikti", "delayed"
    return "Açık", "open"


def action_task_priority(action):
    if action.is_completed:
        return "Düşük"
    if action.delay_days > 0:
        return "Yüksek"
    if action.termin_date and (action.termin_date - date.today()).days <= 7:
        return "Yüksek"
    return "Orta"


def sub_action_task_status(sub_action):
    if sub_action.status == "Tamamlandı":
        return sub_action.status, "completed"
    if sub_action.status == "İptal Edildi":
        return sub_action.status, "cancelled"
    return sub_action.status, "open"


def dof_task_status(dof):
    display_status = compact_dof_status(dof_display_status(dof))
    if display_status == "Tamamlandı":
        return display_status, "completed"
    if display_status == "Taslak":
        return display_status, "draft"
    if display_status == "Revizyon Bekleniyor":
        return display_status, "revision"
    if dof_delay_days(dof) > 0 and display_status != "Tamamlandı":
        return "Gecikti", "delayed"
    if display_status == "Onay Bekliyor":
        return display_status, "pending"
    return display_status, "open"


def audit_task_status(audit):
    if not audit.questions:
        return "Soru Listesi Yok", "rejected"
    if audit.status == "Tamamlandı":
        return audit.status, "completed"
    return audit.status or "Devam Ediyor", "open"


def internal_audit_detail_url(audit):
    question = internal_audit_open_question(audit)
    if question:
        return url_for(
            "main.internal_audit_question",
            audit_id=audit.id,
            question_id=question.id,
        )
    return url_for("main.internal_audit")


def assigned_task_row(
    *,
    module_key,
    module_label,
    module_icon,
    module_tone,
    title,
    description,
    reference_no,
    department,
    due_date,
    status,
    status_key,
    priority,
    detail_url,
    created_at=None,
    sort_id=0,
):
    due_state = due_meta(due_date, status_key == "completed")
    return {
        "module_key": module_key,
        "module_label": module_label,
        "module_icon": module_icon,
        "module_tone": module_tone,
        "title": title,
        "description": short_text(description or "", 130),
        "reference_no": reference_no,
        "department": department or "-",
        "due_date": due_date,
        "due_label": format_date(due_date),
        "due_text": due_state["text"],
        "due_tone": due_state["tone"],
        "status": status,
        "status_key": status_key,
        "status_tone": status_tone(status, status_key),
        "priority": priority or "Orta",
        "priority_tone": priority_tone(priority or "Orta"),
        "detail_url": detail_url,
        "created_at": created_at,
        "sort_date": due_date or date.max,
        "sort_id": sort_id,
    }


def assigned_action_tasks(scope):
    user_id = g.current_user.id
    if scope == "created":
        created_action_ids = [
            row.action_id
            for row in scoped_query(ActionHistory.query, ActionHistory)
            .with_entities(ActionHistory.action_id)
            .filter(
                ActionHistory.actor_user_id == user_id,
                ActionHistory.event_type == "created",
            )
            .distinct()
            .all()
        ]
        actions = (
            scoped_query(Action.query, Action).filter(Action.id.in_(created_action_ids)).all()
            if created_action_ids
            else []
        )
        sub_actions = scoped_query(ActionSubTask.query, ActionSubTask).filter_by(
            created_by_user_id=user_id
        ).all()
    else:
        actions = scoped_query(Action.query, Action).filter_by(
            responsible_user_id=user_id
        ).all()
        sub_actions = scoped_query(ActionSubTask.query, ActionSubTask).filter_by(
            responsible_id=user_id
        ).all()

    rows = []
    for action in actions:
        action.refresh_delay()
        status, status_key = action_task_status(action)
        rows.append(
            assigned_task_row(
                module_key="action",
                module_label="Aksiyon",
                module_icon="check-circle",
                module_tone="success",
                title=f"{action.number_label} {action.title}",
                description=action.description,
                reference_no=action_reference(action),
                department=action.department,
                due_date=action.termin_date,
                status=status,
                status_key=status_key,
                priority=action_task_priority(action),
                detail_url=url_for("main.action_detail", action_id=action.id),
                created_at=action.created_at,
                sort_id=action.id,
            )
        )

    for sub_action in sub_actions:
        action = sub_action.parent_action
        if action is None:
            continue
        status, status_key = sub_action_task_status(sub_action)
        rows.append(
            assigned_task_row(
                module_key="action",
                module_label="Aksiyon",
                module_icon="check-circle",
                module_tone="success",
                title=sub_action.title,
                description=sub_action.description
                or f"{action.number_label} {action.title} aksiyonuna bağlı alt aksiyon.",
                reference_no=f"{action_reference(action)} / ALT-{sub_action.id:04d}",
                department=action.department,
                due_date=sub_action.due_date,
                status=status,
                status_key=status_key,
                priority=sub_action.priority,
                detail_url=url_for("main.sub_action_detail", sub_action_id=sub_action.id),
                created_at=sub_action.created_at,
                sort_id=sub_action.id,
            )
        )

    return rows


def assigned_dof_tasks(scope):
    user_id = g.current_user.id
    if scope == "created":
        dofs = scoped_query(Dof.query, Dof).filter_by(created_by_user_id=user_id).all()
    else:
        dofs = scoped_query(Dof.query, Dof).filter_by(responsible_id=user_id).all()

    rows = []
    for dof in attach_dof_view_state(dofs):
        status, status_key = dof_task_status(dof)
        rows.append(
            assigned_task_row(
                module_key="dof",
                module_label="IF Kaydı",
                module_icon="bookmark-check",
                module_tone="purple",
                title=dof.dof_no,
                description=dof.nonconformity_description or dof.title,
                reference_no=dof.dof_no,
                department=dof.department,
                due_date=dof.due_date,
                status=status,
                status_key=status_key,
                priority=dof.priority or "Orta",
                detail_url=url_for("main.dof_detail", dof_id=dof.id),
                created_at=dof.created_at,
                sort_id=dof.id,
            )
        )
    return rows


def assigned_internal_audit_tasks(scope):
    user_id = g.current_user.id
    if scope == "created":
        audits = scoped_query(InternalAudit.query, InternalAudit).filter_by(
            auditor_id=user_id
        ).all()
    else:
        audits = scoped_query(InternalAudit.query, InternalAudit).filter(
            or_(
                InternalAudit.auditor_id == user_id,
                InternalAudit.audited_user_id == user_id,
            )
        ).all()

    rows = []
    for audit in audits:
        status, status_key = audit_task_status(audit)
        description_parts = [
            audit.title,
            audit.evaluated_department,
            audit.audited_user.full_name if audit.audited_user else "",
        ]
        rows.append(
            assigned_task_row(
                module_key="internal_audit",
                module_label="İç Denetim",
                module_icon="clipboard-check",
                module_tone="warning",
                title=audit.title,
                description=" | ".join(part for part in description_parts if part),
                reference_no=audit.audit_no,
                department=audit.evaluated_department,
                due_date=audit.planned_date,
                status=status,
                status_key=status_key,
                priority="Orta",
                detail_url=internal_audit_detail_url(audit),
                created_at=audit.created_at,
                sort_id=audit.id,
            )
        )
    return rows


def maintenance_task_status(fault):
    if fault.status == "Tamamlandı":
        return "Tamamlandı", "completed"
    if fault.status == "İptal Edildi":
        return "İptal Edildi", "cancelled"
    return "Açık", "open"


def assigned_maintenance_tasks(scope):
    user_id = g.current_user.id
    if scope == "created":
        faults = scoped_query(MaintenanceFault.query, MaintenanceFault).filter_by(
            reported_by_user_id=user_id
        ).all()
    else:
        faults = scoped_query(MaintenanceFault.query, MaintenanceFault).filter_by(
            responsible_user_id=user_id
        ).all()

    rows = []
    for fault in faults:
        status, status_key = maintenance_task_status(fault)
        machine = fault.machine
        description_parts = [
            machine.code if machine else "",
            machine.machine_name if machine else "",
            fault.reporting_department or "",
            fault.description or "",
        ]
        rows.append(
            assigned_task_row(
                module_key="maintenance",
                module_label="Bakım",
                module_icon="wrench-adjustable",
                module_tone="info",
                title=fault.title,
                description=" | ".join(part for part in description_parts if part),
                reference_no=fault.number_label,
                department="Bakım",
                due_date=fault.reported_at.date() if fault.reported_at else None,
                status=status,
                status_key=status_key,
                priority="-",
                detail_url=url_for("main.maintenance_fault_detail", fault_id=fault.id),
                created_at=fault.created_at,
                sort_id=fault.id,
            )
        )
    return rows


def assigned_all_tasks(scope):
    return (
        assigned_action_tasks(scope)
        + assigned_internal_audit_tasks(scope)
        + assigned_dof_tasks(scope)
        + assigned_maintenance_tasks(scope)
    )


def assigned_module_filter_matches(task, module):
    if not module:
        return True
    return task["module_key"] == module


def assigned_tab_filter_matches(task, tab):
    if tab == "actions":
        return task["module_key"] == "action"
    if tab == "audits":
        return task["module_key"] == "internal_audit"
    if tab == "dofs":
        return task["module_key"] == "dof"
    if tab == "maintenance":
        return task["module_key"] == "maintenance"
    return True


def assigned_status_filter_matches(task, status):
    if not status:
        return True
    return task["status_key"] == status


def filtered_assigned_tasks(tasks, filters):
    search = filters["search"].lower()
    due_start = parse_query_date(filters["due_start"])
    due_end = parse_query_date(filters["due_end"])
    filtered = []

    for task in tasks:
        if not assigned_tab_filter_matches(task, filters["tab"]):
            continue
        if not assigned_module_filter_matches(task, filters["module"]):
            continue
        if not assigned_status_filter_matches(task, filters["status"]):
            continue
        if filters["department"] and task["department"] != filters["department"]:
            continue
        if due_start and (not task["due_date"] or task["due_date"] < due_start):
            continue
        if due_end and (not task["due_date"] or task["due_date"] > due_end):
            continue
        if search and search not in " ".join(
            [
                task["module_label"],
                task["title"],
                task["description"],
                task["reference_no"],
                task["department"],
                task["status"],
                task["priority"],
            ]
        ).lower():
            continue
        filtered.append(task)

    return filtered


def assigned_url(filters, **overrides):
    args = {
        "scope": filters["scope"],
        "tab": filters["tab"],
        "search": filters["search"],
        "department": filters["department"],
        "module": filters["module"],
        "status": filters["status"],
        "due_start": filters["due_start"],
        "due_end": filters["due_end"],
    }
    args.update(overrides)
    args = {key: value for key, value in args.items() if value not in ("", None)}
    return url_for("main.assigned_tasks", **args)


def assigned_tasks_context():
    filters = assigned_filters()
    if filters["scope"] not in {"assigned", "created"}:
        filters["scope"] = "assigned"
    if filters["tab"] not in {"all", "actions", "audits", "dofs", "maintenance"}:
        filters["tab"] = "all"

    all_tasks = sorted(
        assigned_all_tasks(filters["scope"]),
        key=lambda task: (task["sort_date"], task["sort_id"]),
    )
    tasks = filtered_assigned_tasks(all_tasks, filters)
    total_count = len(tasks)
    page = request.args.get("page", 1, type=int) or 1
    per_page = request.args.get("per_page", 10, type=int) or 10
    per_page = max(5, min(per_page, 50))
    total_pages = max((total_count + per_page - 1) // per_page, 1)
    page = max(1, min(page, total_pages))
    start = (page - 1) * per_page
    paged_tasks = tasks[start : start + per_page]

    encountered_departments = sorted(
        {task["department"] for task in all_tasks if task["department"] not in {"", "-"}}
    )
    departments = list(dict.fromkeys([*DEPARTMENTS, *encountered_departments]))

    return {
        "tasks": paged_tasks,
        "total_count": total_count,
        "all_count": len(all_tasks),
        "filters": filters,
        "departments": departments,
        "module_options": [
            ("", "Tümü"),
            ("action", "Aksiyon"),
            ("internal_audit", "İç Denetim"),
            ("dof", "IF Kaydı"),
            ("maintenance", "Bakım"),
        ],
        "status_options": [
            ("", "Tümü"),
            ("open", "Açık / Devam ediyor"),
            ("pending", "Onay bekleyen"),
            ("draft", "Taslak"),
            ("revision", "Revizyon bekleyen"),
            ("delayed", "Geciken"),
            ("completed", "Tamamlanan"),
            ("cancelled", "İptal edilen"),
            ("rejected", "Reddedilen"),
        ],
        "tabs": [
            ("all", "Tümü"),
            ("actions", "Aksiyonlar"),
            ("audits", "İç Denetimler"),
            ("dofs", "IF Kayıtları"),
            ("maintenance", "Bakım"),
        ],
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
        "assigned_url": assigned_url,
    }


def internal_audit_question_context(audit, question):
    answer = internal_audit_answer_for_question(audit, question)
    selected_previous_dof_id = answer.previous_nonconformity_id if answer else None
    current_result = internal_audit_canonical_result(answer.result if answer else "")
    current_department = audit.evaluated_department or question.evaluated_department or ""
    return {
        "audit": audit,
        "question": question,
        "answer": answer,
        "progress": internal_audit_progress(audit),
        "result_choices": internal_audit_question_result_choices(question),
        "result_map": internal_audit_question_result_map(question),
        "departments": DEPARTMENTS,
        "locked_department": INTERNAL_AUDIT_LOCKED_DEPARTMENT,
        "evaluated_department": current_department,
        "evaluator_department": INTERNAL_AUDIT_LOCKED_DEPARTMENT,
        "audited_user": audit.audited_user,
        "history_items": internal_audit_history_items(audit, question),
        "available_audits": visible_internal_audits(),
        "can_delete_internal_audit": can_delete_internal_audit(),
        "can_edit_internal_audit": can_edit_internal_audit(audit),
        "can_answer_internal_audit": can_answer_internal_audit(audit),
        "previous_nonconformities": internal_audit_previous_nonconformities(
            question,
            selected_previous_dof_id,
        ),
        "previous_question": internal_audit_question_by_order(
            audit,
            internal_audit_previous_order(audit, question),
        ),
        "next_question": internal_audit_question_by_order(
            audit,
            internal_audit_next_order(audit, question),
        ),
        "is_complete": internal_audit_is_complete(audit),
        "can_create_internal_audit": can_create_internal_audit(),
        "current_result": current_result,
        "current_result_requires_finding": internal_audit_result_requires_finding(current_result),
    }


@bp.route("/landing-preview")
def landing():
    return render_template("public/landing.html")


@bp.route("/landing-dynamic-preview")
def landing_dynamic_preview():
    return render_template("public/landing_dynamic.html")


@bp.route("/")
@login_required
def dashboard():
    return render_template("dashboard.html", **dashboard_context())


@bp.post("/companies/switch")
@login_required
def switch_company():
    if not g.current_user_is_super_admin:
        abort(403)

    is_local_host = host_looks_local(request.host.split(":", 1)[0].lower())
    company_id = request.form.get("company_id", type=int)
    if not company_id:
        session.pop("company_id", None)
        if not is_local_host:
            flash("Ortak superadmin gorunumune gecildi.", "success")
            return redirect(tenant_base_url(url_for("main.dashboard")))
        flash("Ortak superadmin görünümüne geçildi.", "success")
        return redirect(request.referrer or url_for("main.dashboard"))

    company = Company.query.filter_by(id=company_id, is_active=True).first()
    if company is None:
        flash("Seçilen şirket bulunamadı veya pasif.", "danger")
        return redirect(request.referrer or url_for("main.dashboard"))

    session["company_id"] = company.id
    if not is_local_host:
        flash(f"{company.label} sirketine gecildi.", "success")
        return redirect(tenant_url_for_company(company, url_for("main.dashboard")))
    flash(f"{company.label} şirketine geçildi.", "success")
    return redirect(request.referrer or url_for("main.dashboard"))


@bp.route("/uzerime-atananlar")
@login_required
def assigned_tasks():
    return render_template("assigned_tasks.html", **assigned_tasks_context())


@bp.route("/kalite-deneyleri/<slug>")
@login_required
def quality_test_page(slug):
    quality_test = quality_test_by_slug(slug)
    if quality_test is None:
        abort(404)

    return render_template(
        "quality_tests/index.html",
        **quality_test_records_context(quality_test),
    )


@bp.route("/kalite-deneyleri/<slug>/parametreler", methods=["GET", "POST"])
@login_required
def quality_test_parameters(slug):
    quality_test = quality_test_by_slug(slug)
    if quality_test is None or not is_concrete_quality_test(slug):
        abort(404)
    if not current_user_can("quality.parameters_manage"):
        abort(403)

    if request.method == "POST":
        try:
            parameters = parse_concrete_strength_parameters_form()
            save_concrete_strength_parameters(parameters)
            db.session.commit()
            flash("Beton dayanım renk parametreleri güncellendi.", "success")
            return redirect(url_for("main.quality_test_page", slug=slug))
        except ValueError as error:
            db.session.rollback()
            error_key = str(error)
            if error_key == "required_parameter":
                flash("Tüm parametre değerlerini doldurun.", "danger")
            elif error_key == "invalid_parameter":
                flash("Parametre değerleri sayısal olmalıdır.", "danger")
            elif error_key == "invalid_operator":
                flash("Geçerli bir karşılaştırma tipi seçin.", "danger")
            elif error_key == "invalid_between_range":
                flash("Arasında koşulunda ilk değer ikinci değerden büyük olamaz.", "danger")
            elif error_key == "invalid_tolerance":
                flash("+/- tolerans değeri negatif olamaz.", "danger")
            else:
                flash("Parametreler kaydedilemedi.", "danger")

    return render_template(
        "quality_tests/parameters.html",
        quality_test=quality_test,
        concrete_class_options=QUALITY_TEST_CONCRETE_CLASS_OPTIONS,
        tone_options=CONCRETE_STRENGTH_TONES,
        operator_options=CONCRETE_STRENGTH_OPERATOR_OPTIONS,
        parameters=concrete_strength_parameters(),
        format_decimal=format_quality_decimal,
    )


@bp.route("/kalite-deneyleri/<slug>/yeni", methods=["GET", "POST"])
@login_required
def create_quality_test_record(slug):
    quality_test = quality_test_by_slug(slug)
    if quality_test is None:
        abort(404)
    if not can_create_quality_test_record():
        abort(403)

    if request.method == "POST":
        try:
            values = parse_quality_test_record_form()
            if is_concrete_quality_test(slug):
                values["status"] = "Devam Ediyor"
            record = QualityTestRecord(
                test_type=slug,
                record_number=reserve_quality_test_record_number(slug),
                created_by_user_id=g.current_user.id,
                **values,
            )
            assign_current_company(record)
            db.session.add(record)
            db.session.commit()
            if is_concrete_quality_test(slug):
                flash("Deney kaydı oluşturuldu. 2 günlük basınç dayanımı ölçüm takibi başlatıldı.", "success")
            else:
                flash("Deney kaydı oluşturuldu.", "success")
            return redirect(url_for("main.quality_test_page", slug=slug))
        except ValueError as error:
            db.session.rollback()
            error_key = str(error)
            if error_key == "required_fields":
                flash("Müşteri adı zorunludur.", "danger")
            elif error_key == "invalid_date":
                flash("Geçerli bir tarih girin.", "danger")
            elif error_key == "invalid_element":
                flash("Geçerli bir dökülen yapı elemanı seçin.", "danger")
            elif error_key == "invalid_concrete_class":
                flash("Geçerli bir beton sınıfı seçin.", "danger")
            elif error_key == "invalid_temperature":
                flash("Hava sıcaklığı için sayısal bir değer girin.", "danger")
            elif error_key == "text_too_long":
                flash("Formdaki metinlerden biri çok uzun.", "danger")
            else:
                flash("Deney kaydı oluşturulamadı.", "danger")

    return render_template(
        "quality_tests/form.html",
        quality_test=quality_test,
        element_options=QUALITY_TEST_ELEMENT_OPTIONS,
        concrete_class_options=QUALITY_TEST_CONCRETE_CLASS_OPTIONS,
        form_data=request.form,
        form_action=url_for("main.create_quality_test_record", slug=slug),
    )


@bp.route("/kalite-deneyleri/<slug>/<int:record_id>/olcum", methods=["GET", "POST"])
@login_required
def quality_test_measurement(slug, record_id):
    quality_test = quality_test_by_slug(slug)
    if quality_test is None or not is_concrete_quality_test(slug):
        abort(404)
    if not can_create_quality_test_record():
        abort(403)

    record = scoped_query(QualityTestRecord.query, QualityTestRecord).filter_by(
        id=record_id,
        test_type=slug,
    ).first_or_404()
    current_day = record.current_measurement_day

    if request.method == "POST":
        try:
            if current_day is None:
                raise ValueError("measurements_complete")
            strength_value = parse_quality_decimal("strength_value")
            setattr(record, f"strength_{current_day}_day", strength_value)
            setattr(record, f"strength_{current_day}_recorded_at", datetime.utcnow())
            record.status = "Tamamlandı" if record.current_measurement_day is None else "Devam Ediyor"
            db.session.commit()
            if record.current_measurement_day is None:
                flash("28 günlük ölçüm girildi. Beton deneyi ölçüm takibi tamamlandı.", "success")
            else:
                flash(
                    f"{current_day} günlük ölçüm kaydedildi. Sıradaki takip: {record.current_measurement_label}.",
                    "success",
                )
            return redirect(url_for("main.quality_test_page", slug=slug))
        except ValueError as error:
            db.session.rollback()
            error_key = str(error)
            if error_key == "required_strength":
                flash("Basınç dayanımı değeri zorunludur.", "danger")
            elif error_key == "invalid_strength":
                flash("Basınç dayanımı için sayısal bir değer girin.", "danger")
            elif error_key == "measurements_complete":
                flash("Bu kaydın tüm ölçümleri tamamlanmış.", "info")
                return redirect(url_for("main.quality_test_page", slug=slug))
            else:
                flash("Ölçüm kaydedilemedi.", "danger")

    return render_template(
        "quality_tests/measurement_form.html",
        quality_test=quality_test,
        record=record,
        current_day=current_day,
        today=date.today(),
        format_decimal=format_quality_decimal,
        form_action=url_for("main.quality_test_measurement", slug=slug, record_id=record.id),
    )


@bp.route("/kalite-deneyleri/<slug>/<int:record_id>/olcum-duzenle", methods=["GET", "POST"])
@login_required
def edit_quality_test_measurements(slug, record_id):
    quality_test = quality_test_by_slug(slug)
    if quality_test is None or not is_concrete_quality_test(slug):
        abort(404)
    if not can_create_quality_test_record():
        abort(403)

    record = scoped_query(QualityTestRecord.query, QualityTestRecord).filter_by(
        id=record_id,
        test_type=slug,
    ).first_or_404()

    if request.method == "POST":
        try:
            changed = False
            for day in (2, 7, 28):
                field_name = f"strength_{day}_day"
                timestamp_name = f"strength_{day}_recorded_at"
                previous_value = getattr(record, field_name)
                next_value = parse_optional_quality_decimal(field_name)
                if previous_value != next_value:
                    setattr(record, field_name, next_value)
                    setattr(record, timestamp_name, datetime.utcnow() if next_value is not None else None)
                    changed = True
            record.status = "Tamamlandı" if record.current_measurement_day is None else "Devam Ediyor"
            if changed:
                db.session.commit()
                flash("Ölçüm sonuçları güncellendi.", "success")
            else:
                flash("Ölçüm sonuçlarında değişiklik yapılmadı.", "info")
            return redirect(url_for("main.quality_test_page", slug=slug))
        except ValueError as error:
            db.session.rollback()
            if str(error) == "invalid_parameter":
                flash("Ölçüm sonuçları için sayısal değer girin veya silmek için alanı boş bırakın.", "danger")
            else:
                flash("Ölçüm sonuçları güncellenemedi.", "danger")

    return render_template(
        "quality_tests/measurement_edit.html",
        quality_test=quality_test,
        record=record,
        today=date.today(),
        format_decimal=format_quality_decimal,
        form_action=url_for("main.edit_quality_test_measurements", slug=slug, record_id=record.id),
    )


@bp.route("/documents")
@login_required
def documents_dashboard():
    if not can_view_documents():
        abort(403)
    return render_template("documents/index.html", **documents_dashboard_context())


@bp.route("/documents/list")
@login_required
def documents_list():
    if not can_view_documents():
        abort(403)
    return render_template(
        "documents/category.html",
        **documents_category_context(None),
    )


@bp.route("/documents/category/<slug>")
@login_required
def documents_category(slug):
    if not can_view_documents():
        abort(403)
    category = (
        scoped_query(DocumentCategory.query, DocumentCategory)
        .filter_by(slug=slug, is_active=True)
        .first_or_404()
    )
    return render_template(
        "documents/category.html",
        **documents_category_context(category),
    )


@bp.route("/documents/upload", methods=["GET", "POST"])
@login_required
def upload_document():
    if not can_manage_documents():
        abort(403)

    if request.method == "POST":
        saved_documents = []
        try:
            form_values = parse_document_form()
            uploaded_files = document_uploads()
            if not uploaded_files:
                raise ValueError("document_file_required")

            for uploaded_file in uploaded_files:
                file_values = save_document_upload(uploaded_file, form_values["category"])
                document = Document(
                    category_id=form_values["category"].id,
                    category=form_values["category"],
                    document_code=form_values["document_code"],
                    title=form_values["title"],
                    revision_no=form_values["revision_no"],
                    publish_date=form_values["publish_date"],
                    revision_date=form_values["revision_date"],
                    department=form_values["department"],
                    description=form_values["description"],
                    status=form_values["status"],
                    uploaded_by=g.current_user.id,
                    **file_values,
                )
                assign_current_company(document)
                db.session.add(document)
                saved_documents.append(document)

            db.session.flush()
            for document in saved_documents:
                generate_document_preview(document)
            db.session.commit()
            flash(
                f"{len(saved_documents)} doküman başarıyla yüklendi.",
                "success",
            )
            if len(saved_documents) == 1:
                return redirect(
                    url_for("main.document_detail", document_id=saved_documents[0].id)
                )
            return redirect(
                url_for("main.documents_category", slug=form_values["category"].slug)
            )
        except ValueError as error:
            db.session.rollback()
            for document in saved_documents:
                delete_document_files(document)
            error_key = str(error)
            if error_key == "document_file_required":
                flash("Doküman yüklemek için en az bir dosya seçin.", "danger")
            elif error_key == "invalid_document_file_type":
                flash("Sadece PDF, DOC, DOCX, XLS, XLSX, PPT, PPTX, PNG, JPG veya JPEG yükleyebilirsiniz.", "danger")
            elif error_key == "document_file_too_large":
                flash("Doküman dosyası en fazla 25 MB olabilir.", "danger")
            elif error_key == "required_fields":
                flash("Doküman adı ve doküman kodu zorunludur.", "danger")
            elif error_key == "invalid_category":
                flash("Geçerli bir doküman kategorisi seçin.", "danger")
            elif error_key == "invalid_department":
                flash("Geçerli bir departman seçin.", "danger")
            elif error_key == "invalid_status":
                flash("Geçerli bir doküman durumu seçin.", "danger")
            elif error_key == "invalid_date":
                flash("Yayın tarihini geçerli biçimde girin.", "danger")
            elif error_key == "text_too_long":
                flash("Açıklama alanı en fazla 2000 karakter olabilir.", "danger")
            else:
                flash("Doküman formunu kontrol edin.", "danger")

    return render_template(
        "documents/upload.html",
        **document_form_context(category_slug=request.args.get("category")),
    )


@bp.get("/documents/<int:document_id>")
@login_required
def document_detail(document_id):
    if not can_view_documents():
        abort(403)
    document = Document.query.get_or_404(document_id)
    ensure_same_company(document)
    if not document.preview_status:
        generate_document_preview(document)
        db.session.commit()
    return render_template(
        "documents/detail.html",
        document=document,
        file_meta=document_file_meta(document),
        can_preview=document_can_preview(document),
        preview_status=document_preview_status(document),
        preview_message=document_preview_message(document),
        status_tone=document_status_tone(document.status),
        format_date=format_date,
        format_file_size=format_file_size,
        can_manage_documents=can_manage_documents(),
        can_delete_document=can_delete_document(document),
    )


@bp.route("/documents/<int:document_id>/edit", methods=["GET", "POST"])
@login_required
def edit_document(document_id):
    document = Document.query.get_or_404(document_id)
    ensure_same_company(document)
    if not can_manage_documents():
        abort(403)

    if request.method == "POST":
        saved_file_values = None
        try:
            form_values = parse_document_form()
            uploaded_files = document_uploads()
            if uploaded_files:
                saved_file_values = save_document_upload(
                    uploaded_files[0],
                    form_values["category"],
                )

            old_file_path = document.file_path
            document.category_id = form_values["category"].id
            document.category = form_values["category"]
            document.document_code = form_values["document_code"]
            document.title = form_values["title"]
            document.revision_no = form_values["revision_no"]
            document.publish_date = form_values["publish_date"]
            document.revision_date = form_values["revision_date"]
            document.department = form_values["department"]
            document.description = form_values["description"]
            document.status = form_values["status"]
            document.archived_at = datetime.utcnow() if document.status == "Arşiv" else None
            if saved_file_values is not None:
                if old_file_path:
                    delete_stored_upload(old_file_path)
                delete_document_preview(document)
                for key, value in saved_file_values.items():
                    setattr(document, key, value)
                generate_document_preview(document)

            db.session.commit()
            flash("Doküman bilgileri güncellendi.", "success")
            return redirect(url_for("main.document_detail", document_id=document.id))
        except ValueError as error:
            db.session.rollback()
            if saved_file_values is not None:
                temp_document = Document(file_path=saved_file_values["file_path"])
                delete_document_files(temp_document)
            error_key = str(error)
            if error_key == "invalid_document_file_type":
                flash("Sadece PDF, DOC, DOCX, XLS, XLSX, PPT, PPTX, PNG, JPG veya JPEG yükleyebilirsiniz.", "danger")
            elif error_key == "document_file_too_large":
                flash("Doküman dosyası en fazla 25 MB olabilir.", "danger")
            elif error_key == "required_fields":
                flash("Doküman adı ve doküman kodu zorunludur.", "danger")
            elif error_key == "invalid_category":
                flash("Geçerli bir doküman kategorisi seçin.", "danger")
            elif error_key == "invalid_department":
                flash("Geçerli bir departman seçin.", "danger")
            elif error_key == "invalid_status":
                flash("Geçerli bir doküman durumu seçin.", "danger")
            elif error_key == "invalid_date":
                flash("Yayın tarihini geçerli biçimde girin.", "danger")
            else:
                flash("Doküman düzenleme formunu kontrol edin.", "danger")

    return render_template(
        "documents/edit.html",
        **document_form_context(document=document),
    )


@bp.get("/documents/<int:document_id>/download")
@login_required
def download_document(document_id):
    if not can_view_documents():
        abort(403)
    document = Document.query.get_or_404(document_id)
    ensure_same_company(document)
    return send_stored_upload(
        document.file_path,
        as_attachment=True,
        download_name=document.original_file_name,
    )


@bp.get("/documents/<int:document_id>/preview")
@login_required
def preview_document(document_id):
    if not can_view_documents():
        abort(403)
    document = Document.query.get_or_404(document_id)
    ensure_same_company(document)
    if not document_can_preview(document):
        flash(document_preview_message(document), "warning")
        return redirect(url_for("main.document_detail", document_id=document.id))

    response = send_stored_upload(
        document.preview_file_path,
        mimetype="application/pdf",
        as_attachment=False,
        download_name=document.preview_file_name or f"{document.document_code}_preview.pdf",
    )
    preview_name = document.preview_file_name or f"{document.document_code}_preview.pdf"
    response.headers["Content-Disposition"] = f'inline; filename="{preview_name}"'
    return response


@bp.post("/documents/<int:document_id>/generate-preview")
@login_required
def generate_document_preview_route(document_id):
    document = Document.query.get_or_404(document_id)
    ensure_same_company(document)
    if not can_manage_documents():
        abort(403)
    if generate_document_preview(document):
        flash("PDF önizleme yeniden oluşturuldu.", "success")
    else:
        flash(document_preview_message(document), "warning")
    db.session.commit()
    return redirect(url_for("main.document_detail", document_id=document.id))


@bp.post("/documents/<int:document_id>/archive")
@login_required
def archive_document(document_id):
    document = Document.query.get_or_404(document_id)
    ensure_same_company(document)
    if not can_delete_document(document):
        abort(403)
    document.status = "Arşiv"
    document.archived_at = datetime.utcnow()
    db.session.commit()
    flash("Doküman arşive alındı.", "success")
    return redirect(url_for("main.document_detail", document_id=document.id))


@bp.post("/documents/<int:document_id>/delete")
@login_required
def delete_document(document_id):
    document = Document.query.get_or_404(document_id)
    ensure_same_company(document)
    if not can_delete_document(document):
        abort(403)
    category_slug = document.category.slug if document.category else None
    delete_document_files(document)
    db.session.delete(document)
    db.session.commit()
    flash("Doküman silindi.", "success")
    if category_slug:
        return redirect(url_for("main.documents_category", slug=category_slug))
    return redirect(url_for("main.documents_dashboard"))


@bp.route("/arac-yonetimi")
@login_required
def vehicle_dashboard():
    if not can_view_vehicles():
        abort(403)
    return render_template("vehicles/dashboard.html", **vehicle_dashboard_context())


@bp.route("/arac-yonetimi/arac/yeni", methods=["GET", "POST"])
@login_required
def create_vehicle():
    if not can_manage_vehicles():
        abort(403)

    if request.method == "POST":
        try:
            values = parse_vehicle_form()
            if vehicle_query().filter_by(plate=values["plate"]).first():
                raise ValueError("duplicate_plate")
            vehicle = Vehicle(**values, created_by_user_id=g.current_user.id)
            assign_current_company(vehicle)
            db.session.add(vehicle)
            db.session.commit()
            flash("Araç eklendi.", "success")
            return redirect(url_for("main.edit_vehicle", vehicle_id=vehicle.id))
        except ValueError as error:
            db.session.rollback()
            if str(error) == "duplicate_plate":
                flash("Bu plaka zaten kayıtlı.", "danger")
            else:
                flash("Plaka, marka, model ve araç sahibi zorunludur.", "danger")

    return render_template(
        "vehicles/form.html",
        page_title="Araç Ekle",
        page_description="Araç bilgilerini girerek yeni kayıt oluşturun.",
        form_action=url_for("main.create_vehicle"),
        submit_label="Aracı Kaydet",
        vehicle=None,
    )


@bp.route("/arac-yonetimi/arac/<int:vehicle_id>/duzenle", methods=["GET", "POST"])
@login_required
def edit_vehicle(vehicle_id):
    if not can_manage_vehicles():
        abort(403)
    vehicle = Vehicle.query.get_or_404(vehicle_id)
    ensure_same_company(vehicle)

    if request.method == "POST":
        try:
            previous_dates = {
                "traffic_insurance_due_date": vehicle.traffic_insurance_due_date,
                "casco_insurance_due_date": vehicle.casco_insurance_due_date,
                "next_inspection_due_date": vehicle.next_inspection_due_date,
                "reminder_days_before": vehicle.reminder_days_before,
            }
            previous_reminder_user_ids = {user.id for user in vehicle.reminder_recipients}
            values = parse_vehicle_detail_form()
            reminder_user_ids = values.pop("reminder_user_ids")
            existing = vehicle_query().filter_by(plate=values["plate"]).first()
            if existing is not None and existing.id != vehicle.id:
                raise ValueError("duplicate_plate")
            for key, value in values.items():
                setattr(vehicle, key, value)
            reset_vehicle_reminder_flags(vehicle, previous_dates)
            if previous_reminder_user_ids != set(reminder_user_ids):
                vehicle.traffic_insurance_reminder_sent_at = None
                vehicle.casco_insurance_reminder_sent_at = None
                vehicle.next_inspection_reminder_sent_at = None
            vehicle.reminder_recipients = (
                User.query.filter(User.id.in_(reminder_user_ids)).all()
                if reminder_user_ids
                else []
            )
            send_vehicle_due_reminders(vehicle)
            db.session.commit()
            flash("Araç takip tarihleri güncellendi.", "success")
            return redirect(url_for("main.edit_vehicle", vehicle_id=vehicle.id))
        except ValueError as error:
            db.session.rollback()
            if str(error) == "duplicate_plate":
                flash("Bu plaka başka bir araçta kullanılıyor.", "danger")
            elif str(error) == "required_fields":
                flash("Plaka, marka, model ve araç sahibi zorunludur.", "danger")
            else:
                flash("Tarih alanlarını kontrol edin.", "danger")

    return render_template("vehicles/detail.html", **vehicle_detail_context(vehicle))


@bp.post("/arac-yonetimi/arac/<int:vehicle_id>/sil")
@login_required
def delete_vehicle(vehicle_id):
    if not can_manage_vehicles():
        abort(403)
    vehicle = Vehicle.query.get_or_404(vehicle_id)
    ensure_same_company(vehicle)
    db.session.delete(vehicle)
    db.session.commit()
    flash("Araç silindi.", "success")
    return redirect(url_for("main.vehicle_dashboard"))


@bp.post("/arac-yonetimi/arac/<int:vehicle_id>/islem-ekle")
@login_required
def create_vehicle_operation(vehicle_id):
    if not can_manage_vehicles():
        abort(403)
    vehicle = Vehicle.query.get_or_404(vehicle_id)
    ensure_same_company(vehicle)
    try:
        values = parse_vehicle_operation_form()
        operation = VehicleOperation(
            **values,
            vehicle=vehicle,
            created_by_user_id=g.current_user.id,
        )
        assign_current_company(operation)
        db.session.add(operation)
        db.session.commit()
        flash("Araç işlemi eklendi.", "success")
    except ValueError as error:
        db.session.rollback()
        if str(error) == "invalid_decimal":
            flash("Tutar alanını geçerli bir sayı olarak girin.", "danger")
        else:
            flash("İşlem tarihi ve işlem açıklaması zorunludur.", "danger")
    return redirect(url_for("main.edit_vehicle", vehicle_id=vehicle.id))


@bp.post("/arac-yonetimi/islem/<int:operation_id>/sil")
@login_required
def delete_vehicle_operation(operation_id):
    if not can_manage_vehicles():
        abort(403)
    operation = VehicleOperation.query.get_or_404(operation_id)
    ensure_same_company(operation)
    vehicle_id = operation.vehicle_id
    db.session.delete(operation)
    db.session.commit()
    flash("Araç işlemi silindi.", "success")
    return redirect(url_for("main.edit_vehicle", vehicle_id=vehicle_id))


@bp.post("/arac-yonetimi/arac/<int:vehicle_id>/akaryakit")
@login_required
def save_vehicle_fuel(vehicle_id):
    if not can_manage_vehicles():
        abort(403)
    vehicle = Vehicle.query.get_or_404(vehicle_id)
    ensure_same_company(vehicle)
    year = date.today().year
    try:
        existing_entries = {
            entry.month: entry
            for entry in scoped_query(VehicleFuelEntry.query, VehicleFuelEntry)
            .filter_by(vehicle_id=vehicle.id, year=year)
            .all()
        }
        for month, _label in VEHICLE_MONTHS:
            amount_tl = parse_decimal_field(f"fuel_amount_{month}")
            fuel_liter = parse_decimal_field(f"fuel_liter_{month}")
            entry = existing_entries.get(month)
            if amount_tl is None and fuel_liter is None:
                if entry is not None:
                    db.session.delete(entry)
                continue
            if entry is None:
                entry = VehicleFuelEntry(
                    vehicle=vehicle,
                    year=year,
                    month=month,
                )
                assign_current_company(entry)
                db.session.add(entry)
            entry.amount_tl = amount_tl
            entry.fuel_liter = fuel_liter
        db.session.commit()
        flash("Aylık akaryakıt tablosu güncellendi.", "success")
    except ValueError:
        db.session.rollback()
        flash("Akaryakıt miktar alanlarını geçerli sayı olarak girin.", "danger")
    return redirect(url_for("main.edit_vehicle", vehicle_id=vehicle.id))


def can_manage_suggestion_parameters():
    return (
        getattr(g, "current_user_is_super_admin", False)
        or is_management_representative()
        or current_user_can("quality.parameters_manage")
    )


def suggestion_query():
    return scoped_query(Suggestion.query, Suggestion).order_by(
        Suggestion.created_at.desc(),
    )


def suggestion_parameter_query(include_inactive=False):
    query = scoped_query(SuggestionScoreParameter.query, SuggestionScoreParameter)
    if not include_inactive:
        query = query.filter_by(is_active=True)
    return query.order_by(
        SuggestionScoreParameter.sort_order.asc(),
        SuggestionScoreParameter.id.asc(),
    )


def ensure_default_suggestion_parameters():
    company_id = current_company_id()
    existing_count = suggestion_parameter_query(include_inactive=True).count()
    if existing_count:
        normalize_suggestion_parameter_order()
        return
    for name, score, sort_order in DEFAULT_SUGGESTION_SCORE_PARAMETERS:
        parameter = SuggestionScoreParameter(
            company_id=company_id,
            name=name,
            score=score,
            sort_order=sort_order,
            is_active=True,
        )
        db.session.add(parameter)
    db.session.flush()


def normalize_suggestion_parameter_order():
    parameters = suggestion_parameter_query(include_inactive=True).all()
    changed = False
    for index, parameter in enumerate(parameters, start=1):
        if parameter.sort_order != index:
            parameter.sort_order = index
            changed = True
    if changed:
        db.session.flush()


def reserve_suggestion_number():
    max_number = (
        company_scoped_counter_query(
            db.session.query(db.func.max(db.func.coalesce(Suggestion.suggestion_number, Suggestion.id))),
            Suggestion,
        )
        .scalar()
        or 0
    )
    setting_key = company_counter_key("next_suggestion_number")
    setting = db.session.get(AppSetting, setting_key)
    if setting is None:
        setting = AppSetting(key=setting_key, value=str(max_number + 1))
        db.session.add(setting)

    next_number = int(setting.value)
    if next_number <= max_number:
        next_number = max_number + 1
    setting.value = str(next_number + 1)
    return next_number


def build_suggestion_qdms_no(suggestion_number, suggestion_date=None):
    source_date = suggestion_date or date.today()
    return f"QDMS-{source_date.year}-{suggestion_number:04d}"


def parse_suggestion_form(include_defaults=True):
    suggestion_date = parse_optional_date("suggestion_date") or date.today()
    department = request.form.get("department", "").strip()
    owner_name = request.form.get("owner_name", "").strip()
    definition = request.form.get("definition", "").strip()

    if not owner_name or not definition:
        raise ValueError("required_fields")
    if department and department not in DEPARTMENTS:
        raise ValueError("invalid_department")

    data = {
        "suggestion_date": suggestion_date,
        "department": department or None,
        "owner_name": owner_name,
        "definition": definition,
    }
    if include_defaults:
        data.update(
            {
                "evaluation_month": None,
                "status": "Değerlendirmede",
                "unit_comment": None,
                "action_responsible": None,
                "action_status": None,
                "detail": None,
            }
        )
    return data


def save_suggestion_attachment(suggestion):
    uploaded_file = request.files.get("attachment")
    if not uploaded_file or not uploaded_file.filename:
        return
    if suggestion.attachment_stored_name:
        delete_stored_upload(suggestion.attachment_stored_name)
    safe_name, stored_name, mime_type = store_uploaded_file(
        uploaded_file,
        folder="suggestions",
        company_id=suggestion.company_id or current_company_id(),
    )
    suggestion.attachment_original_name = safe_name
    suggestion.attachment_stored_name = stored_name
    suggestion.attachment_mime_type = mime_type


def apply_suggestion_scores(suggestion):
    selected_parameter_ids = {
        int(parameter_id)
        for parameter_id in request.form.getlist("score_parameter_ids")
        if parameter_id.isdigit()
    }
    parameters = suggestion_parameter_query().all()
    existing_scores = {score.parameter_id: score for score in suggestion.scores}
    for parameter in parameters:
        score = existing_scores.get(parameter.id)
        if score is None:
            score = SuggestionScore(
                suggestion=suggestion,
                parameter_id=parameter.id,
                parameter_name=parameter.name,
            )
            assign_current_company(score)
            db.session.add(score)
        score.parameter_name = parameter.name
        score.score_value = parameter.score
        score.is_selected = parameter.id in selected_parameter_ids


def save_suggestion_evaluation(suggestion):
    evaluator_department = request.form.get("evaluator_department", "").strip()
    comment = request.form.get("evaluation_comment", "").strip()
    if not evaluator_department or evaluator_department not in DEPARTMENTS:
        raise ValueError("invalid_department")

    parameters = suggestion_parameter_query().all()
    parameter_by_id = {parameter.id: parameter for parameter in parameters}
    if not parameter_by_id:
        raise ValueError("missing_parameters")

    changed = False
    for parameter_id, parameter in parameter_by_id.items():
        raw_rating = request.form.get(f"rating_{parameter_id}", "").strip()
        if not raw_rating:
            continue
        try:
            rating = int(raw_rating)
        except ValueError as exc:
            raise ValueError("invalid_rating") from exc
        if rating < 1 or rating > 10:
            raise ValueError("invalid_rating")

        evaluation = (
            SuggestionEvaluation.query.filter_by(
                suggestion_id=suggestion.id,
                parameter_id=parameter.id,
                evaluator_department=evaluator_department,
            ).first()
        )
        if evaluation is None:
            evaluation = SuggestionEvaluation(
                suggestion=suggestion,
                parameter_id=parameter.id,
                evaluator_department=evaluator_department,
            )
            assign_current_company(evaluation)
            db.session.add(evaluation)
        evaluation.parameter_name = parameter.name
        evaluation.parameter_multiplier = parameter.score
        evaluation.evaluator_user_id = g.current_user.id
        evaluation.rating = rating
        evaluation.comment = comment or None
        changed = True

    if not changed:
        raise ValueError("missing_rating")


def suggestion_evaluation_summary(suggestion):
    grouped = {}
    for evaluation in suggestion.evaluations:
        grouped.setdefault(evaluation.evaluator_department, []).append(evaluation)
    return [
        {
            "department": department,
            "evaluations": evaluations,
            "total": sum(evaluation.weighted_score for evaluation in evaluations),
        }
        for department, evaluations in sorted(grouped.items())
    ]


def suggestion_form_context(suggestion=None):
    ensure_default_suggestion_parameters()
    return {
        "suggestion": suggestion,
        "departments": DEPARTMENTS,
        "statuses": SUGGESTION_STATUSES,
        "parameters": suggestion_parameter_query().all(),
        "selected_parameter_ids": {
            score.parameter_id
            for score in (suggestion.scores if suggestion else [])
            if score.is_selected
        },
    }


@bp.route("/oneri-sikayet/oneri")
@login_required
def suggestions_dashboard():
    ensure_default_suggestion_parameters()
    db.session.commit()
    suggestions = suggestion_query().all()
    total_score = sum(item.total_score for item in suggestions)
    return render_template(
        "suggestions/dashboard.html",
        suggestions=suggestions,
        total_score=total_score,
        can_manage_parameters=can_manage_suggestion_parameters(),
        format_date=format_date,
    )


@bp.route("/oneri-sikayet/oneri/yeni", methods=["GET", "POST"])
@login_required
def create_suggestion():
    ensure_default_suggestion_parameters()
    if request.method == "POST":
        try:
            suggestion_number = reserve_suggestion_number()
            suggestion = Suggestion(
                **parse_suggestion_form(),
                suggestion_number=suggestion_number,
                qdms_no=build_suggestion_qdms_no(
                    suggestion_number,
                    parse_optional_date("suggestion_date") or date.today(),
                ),
                created_by_user_id=g.current_user.id,
            )
            assign_current_company(suggestion)
            db.session.add(suggestion)
            db.session.flush()
            save_suggestion_attachment(suggestion)
            db.session.commit()
            flash("Öneri kaydı oluşturuldu.", "success")
            return redirect(url_for("main.suggestion_detail", suggestion_id=suggestion.id))
        except ValueError as error:
            db.session.rollback()
            error_key = str(error)
            if error_key == "invalid_file_type":
                flash("Ek dosya türü desteklenmiyor.", "danger")
            elif error_key == "invalid_department":
                flash("Geçerli bir bölüm seçin.", "danger")
            elif error_key == "invalid_status":
                flash("Geçerli bir öneri durumu seçin.", "danger")
            else:
                flash("Öneri sahibi ve öneri tanımı zorunludur.", "danger")

    return render_template(
        "suggestions/form.html",
        page_title="Yeni Öneri Kaydı",
        form_action=url_for("main.create_suggestion"),
        submit_label="Öneriyi Kaydet",
        **suggestion_form_context(),
    )


@bp.route("/oneri-sikayet/oneri/<int:suggestion_id>")
@login_required
def suggestion_detail(suggestion_id):
    suggestion = Suggestion.query.get_or_404(suggestion_id)
    ensure_same_company(suggestion)
    ensure_default_suggestion_parameters()
    return render_template(
        "suggestions/detail.html",
        suggestion=suggestion,
        departments=DEPARTMENTS,
        parameters=suggestion_parameter_query().all(),
        evaluation_summary=suggestion_evaluation_summary(suggestion),
        format_date=format_date,
    )


@bp.post("/oneri-sikayet/oneri/<int:suggestion_id>/degerlendir")
@login_required
def evaluate_suggestion(suggestion_id):
    ensure_default_suggestion_parameters()
    suggestion = Suggestion.query.get_or_404(suggestion_id)
    ensure_same_company(suggestion)
    try:
        save_suggestion_evaluation(suggestion)
        db.session.commit()
        flash("Öneri değerlendirmesi kaydedildi.", "success")
    except ValueError as error:
        db.session.rollback()
        error_key = str(error)
        if error_key == "invalid_department":
            flash("Değerlendirme için geçerli bir departman seçin.", "danger")
        elif error_key == "missing_parameters":
            flash("Aktif puanlama parametresi bulunamadı.", "danger")
        elif error_key == "missing_rating":
            flash("En az bir parametre için 1-10 arası puan seçin.", "danger")
        else:
            flash("Puanlar 1 ile 10 arasında olmalıdır.", "danger")
    return redirect(url_for("main.suggestion_detail", suggestion_id=suggestion.id))


@bp.route("/oneri-sikayet/oneri/<int:suggestion_id>/duzenle", methods=["GET", "POST"])
@login_required
def edit_suggestion(suggestion_id):
    ensure_default_suggestion_parameters()
    suggestion = Suggestion.query.get_or_404(suggestion_id)
    ensure_same_company(suggestion)
    if request.method == "POST":
        try:
            for key, value in parse_suggestion_form(include_defaults=False).items():
                setattr(suggestion, key, value)
            if not suggestion.qdms_no:
                suggestion.qdms_no = build_suggestion_qdms_no(
                    suggestion.suggestion_number or suggestion.id,
                    suggestion.suggestion_date,
                )
            save_suggestion_attachment(suggestion)
            db.session.commit()
            flash("Öneri kaydı güncellendi.", "success")
            return redirect(url_for("main.suggestion_detail", suggestion_id=suggestion.id))
        except ValueError as error:
            db.session.rollback()
            error_key = str(error)
            if error_key == "invalid_file_type":
                flash("Ek dosya türü desteklenmiyor.", "danger")
            elif error_key == "invalid_department":
                flash("Geçerli bir bölüm seçin.", "danger")
            elif error_key == "invalid_status":
                flash("Geçerli bir öneri durumu seçin.", "danger")
            else:
                flash("Öneri sahibi ve öneri tanımı zorunludur.", "danger")

    return render_template(
        "suggestions/form.html",
        page_title=f"{suggestion.number_label} Düzenle",
        form_action=url_for("main.edit_suggestion", suggestion_id=suggestion.id),
        submit_label="Değişiklikleri Kaydet",
        **suggestion_form_context(suggestion),
    )


@bp.post("/oneri-sikayet/oneri/<int:suggestion_id>/sil")
@login_required
def delete_suggestion(suggestion_id):
    suggestion = Suggestion.query.get_or_404(suggestion_id)
    ensure_same_company(suggestion)
    if suggestion.attachment_stored_name:
        delete_stored_upload(suggestion.attachment_stored_name)
    db.session.delete(suggestion)
    db.session.commit()
    flash("Öneri kaydı silindi.", "success")
    return redirect(url_for("main.suggestions_dashboard"))


@bp.get("/oneri-sikayet/oneri/<int:suggestion_id>/ek/indir")
@login_required
def download_suggestion_attachment(suggestion_id):
    suggestion = Suggestion.query.get_or_404(suggestion_id)
    ensure_same_company(suggestion)
    if not suggestion.attachment_stored_name:
        flash("Bu öneriye ait ek dosya bulunamadı.", "warning")
        return redirect(url_for("main.suggestion_detail", suggestion_id=suggestion.id))
    return send_stored_upload(
        suggestion.attachment_stored_name,
        as_attachment=True,
        download_name=suggestion.attachment_original_name,
    )


@bp.route("/oneri-sikayet/oneri/parametreler", methods=["GET", "POST"])
@login_required
def suggestion_parameters():
    if not can_manage_suggestion_parameters():
        abort(403)
    ensure_default_suggestion_parameters()
    db.session.commit()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        score = request.form.get("score", "").strip()
        sort_order = request.form.get("sort_order", "").strip()
        if not name:
            flash("Parametre adı zorunludur.", "danger")
            return redirect(url_for("main.suggestion_parameters"))
        try:
            next_sort_order = (
                suggestion_parameter_query(include_inactive=True)
                .with_entities(db.func.max(SuggestionScoreParameter.sort_order))
                .scalar()
                or 0
            ) + 1
            parameter = SuggestionScoreParameter(
                name=name,
                score=int(score),
                sort_order=int(sort_order or next_sort_order),
                is_active=True,
            )
        except ValueError:
            flash("Puan ve sıralama alanları sayı olmalıdır.", "danger")
            return redirect(url_for("main.suggestion_parameters"))
        assign_current_company(parameter)
        db.session.add(parameter)
        try:
            db.session.commit()
            flash("Puan parametresi eklendi.", "success")
        except Exception:
            db.session.rollback()
            flash("Bu parametre adı zaten kullanılıyor olabilir.", "danger")
        return redirect(url_for("main.suggestion_parameters"))

    return render_template(
        "suggestions/parameters.html",
        parameters=suggestion_parameter_query(include_inactive=True).all(),
    )


@bp.post("/oneri-sikayet/oneri/parametre/<int:parameter_id>/sil")
@login_required
def delete_suggestion_parameter(parameter_id):
    if not can_manage_suggestion_parameters():
        abort(403)
    parameter = SuggestionScoreParameter.query.get_or_404(parameter_id)
    ensure_same_company(parameter)
    if SuggestionScore.query.filter_by(parameter_id=parameter.id).first():
        parameter.is_active = False
    else:
        db.session.delete(parameter)
    db.session.commit()
    flash("Puan parametresi kaldırıldı.", "success")
    return redirect(url_for("main.suggestion_parameters"))


@bp.route("/oneri-sikayet/sikayet")
@login_required
def complaints_dashboard():
    return render_template("suggestions/complaints.html")


@bp.route("/bakim")
@login_required
def maintenance_dashboard():
    return render_template(
        "maintenance/dashboard.html",
        **maintenance_dashboard_context(),
    )


@bp.route("/bakim/makine/yeni", methods=["GET", "POST"])
@login_required
def create_maintenance_machine():
    if not can_manage_maintenance_inventory():
        abort(403)

    if request.method == "POST":
        try:
            values = parse_maintenance_machine_form()
            if scoped_query(MaintenanceMachine.query, MaintenanceMachine).filter_by(
                code=values["code"]
            ).first():
                raise ValueError("duplicate_code")
            machine = MaintenanceMachine(
                **values,
                created_by_user_id=g.current_user.id,
                is_active=True,
            )
            assign_current_company(machine)
            db.session.add(machine)
            db.session.commit()
            flash("Makine envantere eklendi.", "success")
            return redirect(url_for("main.maintenance_dashboard"))
        except ValueError as error:
            db.session.rollback()
            error_key = str(error)
            if error_key == "required_fields":
                flash("Kod ve makine adı zorunludur.", "danger")
            elif error_key == "duplicate_code":
                flash("Bu makine kodu zaten kayıtlı.", "danger")
            elif error_key == "invalid_status":
                flash("Geçerli bir makine durumu seçin.", "danger")
            else:
                flash("Makine formunu kontrol edin.", "danger")

    return render_template(
        "maintenance/machine_form.html",
        page_title="Makine Ekle",
        page_description="Bakım envanterine yeni makine ekleyin.",
        form_action=url_for("main.create_maintenance_machine"),
        submit_label="Makineyi Kaydet",
        **maintenance_machine_form_context(),
    )


@bp.route("/bakim/makine/<int:machine_id>/duzenle", methods=["GET", "POST"])
@login_required
def edit_maintenance_machine(machine_id):
    if not can_manage_maintenance_inventory():
        abort(403)

    machine = MaintenanceMachine.query.get_or_404(machine_id)
    ensure_same_company(machine)
    if request.method == "POST":
        try:
            values = parse_maintenance_machine_form()
            existing = scoped_query(MaintenanceMachine.query, MaintenanceMachine).filter_by(
                code=values["code"]
            ).first()
            if existing is not None and existing.id != machine.id:
                raise ValueError("duplicate_code")
            for key, value in values.items():
                setattr(machine, key, value)
            machine.is_active = request.form.get("is_active") == "on"
            db.session.commit()
            flash("Makine bilgileri güncellendi.", "success")
            return redirect(url_for("main.maintenance_dashboard"))
        except ValueError as error:
            db.session.rollback()
            error_key = str(error)
            if error_key == "required_fields":
                flash("Kod ve makine adı zorunludur.", "danger")
            elif error_key == "duplicate_code":
                flash("Bu makine kodu başka bir kayıtta kullanılıyor.", "danger")
            elif error_key == "invalid_status":
                flash("Geçerli bir makine durumu seçin.", "danger")
            else:
                flash("Makine formunu kontrol edin.", "danger")

    return render_template(
        "maintenance/machine_form.html",
        page_title="Makine Düzenle",
        page_description="Makine envanter bilgisini güncelleyin.",
        form_action=url_for("main.edit_maintenance_machine", machine_id=machine.id),
        submit_label="Değişiklikleri Kaydet",
        **maintenance_machine_form_context(machine),
    )


@bp.post("/bakim/makine/<int:machine_id>/sil")
@login_required
def delete_maintenance_machine(machine_id):
    if not can_manage_maintenance_inventory():
        abort(403)

    machine = MaintenanceMachine.query.get_or_404(machine_id)
    ensure_same_company(machine)
    if machine.faults:
        machine.is_active = False
        machine.status = "PASİF"
        db.session.commit()
        flash(
            "Bu makineye bağlı arıza kayıtları olduğu için silinmedi, pasife alındı.",
            "warning",
        )
    else:
        db.session.delete(machine)
        db.session.commit()
        flash("Makine envanterden silindi.", "success")
    return redirect(url_for("main.maintenance_dashboard"))


@bp.route("/bakim/ariza/yeni", methods=["GET", "POST"])
@login_required
def create_maintenance_fault():
    if not can_open_maintenance_fault():
        abort(403)

    selected_machine = None
    machine_id = request.args.get("machine_id", type=int)
    if machine_id:
        selected_machine = scoped_query(MaintenanceMachine.query, MaintenanceMachine).filter_by(
            id=machine_id,
            is_active=True,
        ).first()

    if request.method == "POST":
        try:
            values = parse_maintenance_fault_form()
            fault = MaintenanceFault(
                machine=values["machine"],
                fault_number=reserve_maintenance_fault_number(),
                title=values["title"],
                description=values["description"],
                reported_at=values["reported_at"],
                reporting_department=values["reporting_department"],
                responsible_user_id=(
                    values["responsible_user"].id
                    if values["responsible_user"] is not None
                    else None
                ),
                due_date=None,
                priority="Orta",
                status="Açık",
                reported_by_user_id=g.current_user.id,
            )
            assign_current_company(fault)
            db.session.add(fault)
            db.session.flush()
            refresh_machine_status_from_faults(values["machine"])
            db.session.commit()
            flash("Arıza kaydı açıldı.", "success")
            return redirect(url_for("main.maintenance_fault_detail", fault_id=fault.id))
        except ValueError as error:
            db.session.rollback()
            error_key = str(error)
            if error_key == "required_fields":
                flash("Makine ve arıza başlığı zorunludur.", "danger")
            elif error_key == "invalid_machine":
                flash("Geçerli bir makine seçin.", "danger")
            elif error_key == "invalid_user":
                flash("Geçerli bir sorumlu kullanıcı seçin.", "danger")
            elif error_key == "invalid_date":
                flash("Arıza açılma tarihini geçerli biçimde girin.", "danger")
            elif error_key == "invalid_department":
                flash("Arızayı bildiren departmanı seçin.", "danger")
            else:
                flash("Arıza formunu kontrol edin.", "danger")

    return render_template(
        "maintenance/fault_form.html",
        page_title="Arıza Aç",
        page_description="Makine arızası için takip kaydı oluşturun.",
        form_action=url_for("main.create_maintenance_fault"),
        submit_label="Arızayı Kaydet",
        **maintenance_fault_form_context(machine=selected_machine),
    )


@bp.get("/bakim/ariza/<int:fault_id>")
@login_required
def maintenance_fault_detail(fault_id):
    fault = MaintenanceFault.query.get_or_404(fault_id)
    ensure_same_company(fault)
    return render_template(
        "maintenance/fault_detail.html",
        fault=fault,
        status_tone=maintenance_status_tone,
        unplanned_maintenance_code=UNPLANNED_MAINTENANCE_CODE,
        unplanned_maintenance_label=UNPLANNED_MAINTENANCE_LABEL,
        format_date=format_date,
        can_edit_fault=can_edit_maintenance_fault(fault),
        can_complete_fault=can_complete_maintenance_fault(fault),
        can_delete_fault=can_delete_maintenance_fault(fault),
    )


@bp.route("/bakim/ariza/<int:fault_id>/duzenle", methods=["GET", "POST"])
@login_required
def edit_maintenance_fault(fault_id):
    fault = MaintenanceFault.query.get_or_404(fault_id)
    ensure_same_company(fault)
    if not can_edit_maintenance_fault(fault):
        abort(403)

    if request.method == "POST":
        try:
            values = parse_maintenance_fault_form(fault)
            previous_machine = fault.machine
            fault.machine = values["machine"]
            fault.title = values["title"]
            fault.description = values["description"]
            fault.reported_at = values["reported_at"]
            fault.reporting_department = values["reporting_department"]
            fault.responsible_user_id = (
                values["responsible_user"].id
                if values["responsible_user"] is not None
                else None
            )
            fault.due_date = None
            if previous_machine is not None and previous_machine.id != fault.machine.id:
                refresh_machine_status_from_faults(previous_machine)
            refresh_machine_status_from_faults(fault.machine)
            db.session.commit()
            flash("Arıza kaydı güncellendi.", "success")
            return redirect(url_for("main.maintenance_fault_detail", fault_id=fault.id))
        except ValueError as error:
            db.session.rollback()
            error_key = str(error)
            if error_key == "required_fields":
                flash("Makine ve arıza başlığı zorunludur.", "danger")
            elif error_key == "invalid_machine":
                flash("Geçerli bir makine seçin.", "danger")
            elif error_key == "invalid_user":
                flash("Geçerli bir sorumlu kullanıcı seçin.", "danger")
            elif error_key == "invalid_date":
                flash("Arıza açılma tarihini geçerli biçimde girin.", "danger")
            elif error_key == "invalid_department":
                flash("Arızayı bildiren departmanı seçin.", "danger")
            else:
                flash("Arıza formunu kontrol edin.", "danger")

    return render_template(
        "maintenance/fault_form.html",
        page_title="Arıza Düzenle",
        page_description="Makine arıza kaydını güncelleyin.",
        form_action=url_for("main.edit_maintenance_fault", fault_id=fault.id),
        submit_label="Değişiklikleri Kaydet",
        **maintenance_fault_form_context(fault=fault),
    )


@bp.post("/bakim/ariza/<int:fault_id>/kapat")
@login_required
def complete_maintenance_fault(fault_id):
    fault = MaintenanceFault.query.get_or_404(fault_id)
    ensure_same_company(fault)
    if not can_complete_maintenance_fault(fault):
        abort(403)

    closing_note = request.form.get("closing_note", "").strip()
    if not closing_note:
        flash("Arızayı kapatmak için yapılan işlemi yazın.", "danger")
        return redirect(url_for("main.maintenance_fault_detail", fault_id=fault.id))

    fault.status = "Tamamlandı"
    fault.closing_note = closing_note
    fault.completed_at = datetime.utcnow()
    refresh_machine_status_from_faults(fault.machine)
    db.session.commit()
    flash("Arıza kaydı kapatıldı.", "success")
    return redirect(url_for("main.maintenance_fault_detail", fault_id=fault.id))


@bp.post("/bakim/ariza/<int:fault_id>/sil")
@login_required
def delete_maintenance_fault(fault_id):
    fault = MaintenanceFault.query.get_or_404(fault_id)
    ensure_same_company(fault)
    if not can_delete_maintenance_fault(fault):
        abort(403)

    machine = fault.machine
    db.session.delete(fault)
    db.session.flush()
    refresh_machine_status_from_faults(machine)
    db.session.commit()
    flash("Arıza kaydı silindi.", "success")
    return redirect(url_for("main.maintenance_dashboard"))


@bp.route("/dashboard-liste")
@login_required
def dashboard_list():
    return redirect(url_for("main.dashboard"))


@bp.route("/dashboard-eski")
@login_required
def dashboard_legacy():
    return redirect(url_for("main.dashboard"))


@bp.route("/dofs")
@login_required
def dof_management():
    return render_template("dof_dashboard.html", **dof_dashboard_context())


@bp.route("/ic-denetim")
@login_required
def internal_audit():
    return render_template(
        "internal_audit_dashboard.html",
        **internal_audit_dashboard_context(),
    )


@bp.route("/ic-denetim/olustur", methods=["GET", "POST"])
@login_required
def create_internal_audit():
    if not can_create_internal_audit():
        abort(403)

    form_data = request.form if request.method == "POST" else {}
    questions = internal_audit_builder_blank_questions()

    if request.method == "POST":
        raw_indexes = request.form.get("question_indexes", "")
        posted_questions = []
        for index in [item.strip() for item in raw_indexes.split(",") if item.strip()]:
            posted_questions.append(
                {
                    "standard": request.form.get(f"standard_{index}", "").strip(),
                    "audit_topic": request.form.get(f"audit_topic_{index}", "").strip(),
                    "audit_subject": request.form.get(f"audit_subject_{index}", "").strip(),
                    "question_text": request.form.get(f"question_text_{index}", "").strip(),
                    "evaluator_department": INTERNAL_AUDIT_LOCKED_DEPARTMENT,
                    "answer_options": DEFAULT_INTERNAL_AUDIT_OPTION_TEXT,
                    "expected_answer": request.form.get(
                        f"expected_answer_{index}",
                        "",
                    ).strip(),
                    "is_required": request.form.get(f"is_required_{index}") == "on",
                }
            )
        questions = posted_questions or questions

        try:
            (
                title,
                planned_date,
                evaluated_department,
                audited_user,
                parsed_questions,
            ) = parse_internal_audit_builder_form()
        except ValueError as error:
            error_key = str(error)
            if error_key == "audit_scope_required":
                flash("İç denetim için değerlendirilen departman ve denetlenen personel seçin.", "danger")
            elif error_key == "question_required_fields":
                flash("Her soru için standart, tetkik başlık no ve soru alanlarını doldurun.", "danger")
            elif error_key == "invalid_standard":
                flash("Sorulardaki ilgili standart alanlarından biri geçerli değil.", "danger")
            elif error_key == "invalid_department":
                flash("Değerlendirilen departman geçerli değil.", "danger")
            elif error_key == "invalid_user":
                flash("Denetlenen personel geçerli değil.", "danger")
            elif error_key == "question_too_long":
                flash("Soru metni en fazla 2000 karakter olabilir.", "danger")
            elif error_key == "audit_subject_too_long":
                flash("Tetkik konusu en fazla 2000 karakter olabilir.", "danger")
            elif error_key == "expected_answer_too_long":
                flash("Beklenen cevap en fazla 2000 karakter olabilir.", "danger")
            elif error_key == "not_enough_answer_options":
                flash("Her soru için en az iki cevap seçeneği girin.", "danger")
            elif error_key == "no_questions":
                flash("İç denetim oluşturmak için en az bir soru ekleyin.", "danger")
            else:
                flash("İç denetim oluşturma formunu kontrol edin.", "danger")
        else:
            audit = InternalAudit(
                audit_no=reserve_internal_audit_number(planned_date),
                title=title,
                auditor_id=g.current_user.id,
                evaluated_department=evaluated_department,
                audited_user_id=audited_user.id,
                planned_date=planned_date,
                status="Devam Ediyor",
                active_question_order=1,
            )
            assign_current_company(audit)
            db.session.add(audit)
            db.session.flush()
            apply_internal_audit_questions(audit, parsed_questions)

            db.session.commit()
            flash(f"{audit.audit_no} numaralı iç denetim oluşturuldu.", "success")
            first_question = internal_audit_question_by_order(audit, 1)
            return redirect(
                url_for(
                    "main.internal_audit_question",
                    audit_id=audit.id,
                    question_id=first_question.id,
                )
            )

    return render_template(
        "internal_audit_builder.html",
        form_data=form_data,
        questions=questions,
        departments=DEPARTMENTS,
        users=active_users(),
        standard_choices=INTERNAL_AUDIT_STANDARD_CHOICES,
        locked_department=INTERNAL_AUDIT_LOCKED_DEPARTMENT,
        default_answer_options=DEFAULT_INTERNAL_AUDIT_OPTION_TEXT,
        today=date.today().isoformat(),
        page_title="İç Denetim Oluştur",
        page_description="Soru listesini ve tetkik konularını hazırlayın.",
        submit_label="Denetimi Oluştur",
        is_edit=False,
    )


@bp.route("/ic-denetim/<int:audit_id>/duzenle", methods=["GET", "POST"])
@login_required
def edit_internal_audit(audit_id):
    audit = InternalAudit.query.get_or_404(audit_id)
    ensure_same_company(audit)
    if not can_edit_internal_audit(audit):
        abort(403)

    fallback_department = audit.evaluated_department or (
        audit.questions[0].evaluated_department if audit.questions else ""
    )
    form_data = request.form if request.method == "POST" else {
        "title": audit.title,
        "planned_date": audit.planned_date.isoformat() if audit.planned_date else "",
        "evaluated_department": fallback_department or "",
        "audited_user_id": str(audit.audited_user_id or ""),
    }
    questions = internal_audit_builder_questions_from_audit(audit)

    if request.method == "POST":
        raw_indexes = request.form.get("question_indexes", "")
        posted_questions = []
        for index in [item.strip() for item in raw_indexes.split(",") if item.strip()]:
            posted_questions.append(
                {
                    "standard": request.form.get(f"standard_{index}", "").strip(),
                    "audit_topic": request.form.get(f"audit_topic_{index}", "").strip(),
                    "audit_subject": request.form.get(f"audit_subject_{index}", "").strip(),
                    "question_text": request.form.get(f"question_text_{index}", "").strip(),
                    "evaluator_department": INTERNAL_AUDIT_LOCKED_DEPARTMENT,
                    "answer_options": DEFAULT_INTERNAL_AUDIT_OPTION_TEXT,
                    "expected_answer": request.form.get(
                        f"expected_answer_{index}",
                        "",
                    ).strip(),
                    "is_required": request.form.get(f"is_required_{index}") == "on",
                }
            )
        questions = posted_questions or questions

        try:
            (
                title,
                planned_date,
                evaluated_department,
                audited_user,
                parsed_questions,
            ) = parse_internal_audit_builder_form()
        except ValueError as error:
            error_key = str(error)
            if error_key == "audit_scope_required":
                flash("İç denetim için değerlendirilen departman ve denetlenen personel seçin.", "danger")
            elif error_key == "question_required_fields":
                flash("Her soru için standart, tetkik başlık no ve soru alanlarını doldurun.", "danger")
            elif error_key == "invalid_standard":
                flash("Sorulardaki ilgili standart alanlarından biri geçerli değil.", "danger")
            elif error_key == "invalid_department":
                flash("Değerlendirilen departman geçerli değil.", "danger")
            elif error_key == "invalid_user":
                flash("Denetlenen personel geçerli değil.", "danger")
            elif error_key == "question_too_long":
                flash("Soru metni en fazla 2000 karakter olabilir.", "danger")
            elif error_key == "audit_subject_too_long":
                flash("Tetkik konusu en fazla 2000 karakter olabilir.", "danger")
            elif error_key == "expected_answer_too_long":
                flash("Beklenen cevap en fazla 2000 karakter olabilir.", "danger")
            elif error_key == "not_enough_answer_options":
                flash("Her soru için en az iki cevap seçeneği girin.", "danger")
            elif error_key == "no_questions":
                flash("İç denetim için en az bir soru ekleyin.", "danger")
            else:
                flash("İç denetim düzenleme formunu kontrol edin.", "danger")
        else:
            audit.title = title
            audit.planned_date = planned_date
            audit.evaluated_department = evaluated_department
            audit.audited_user_id = audited_user.id
            if audit.active_question_order > len(parsed_questions):
                audit.active_question_order = len(parsed_questions)
            apply_internal_audit_questions(audit, parsed_questions)
            db.session.commit()
            flash(f"{audit.audit_no} numaralı iç denetim güncellendi.", "success")
            return redirect(url_for("main.internal_audit"))

    return render_template(
        "internal_audit_builder.html",
        form_data=form_data,
        questions=questions,
        departments=DEPARTMENTS,
        users=active_users(),
        standard_choices=INTERNAL_AUDIT_STANDARD_CHOICES,
        locked_department=INTERNAL_AUDIT_LOCKED_DEPARTMENT,
        default_answer_options=DEFAULT_INTERNAL_AUDIT_OPTION_TEXT,
        today=date.today().isoformat(),
        audit=audit,
        page_title="İç Denetim Düzenle",
        page_description=f"{audit.audit_no} numaralı iç denetimin sorularını ve bilgilerini güncelleyin.",
        submit_label="Değişiklikleri Kaydet",
        is_edit=True,
    )


@bp.get("/ic-denetim/<int:audit_id>/rapor")
@login_required
def internal_audit_report(audit_id):
    audit = InternalAudit.query.get_or_404(audit_id)
    ensure_same_company(audit)
    if not can_view_internal_audit(audit):
        abort(403)
    return render_template(
        "internal_audit_report.html",
        **internal_audit_report_context(audit),
        report_variant="full",
    )


@bp.get("/ic-denetim/<int:audit_id>/rapor/personel")
@login_required
def internal_audit_personnel_report(audit_id):
    audit = InternalAudit.query.get_or_404(audit_id)
    ensure_same_company(audit)
    if not can_view_internal_audit(audit):
        abort(403)
    return render_template(
        "internal_audit_report.html",
        **internal_audit_report_context(audit),
        report_variant="personnel",
    )


@bp.post("/ic-denetim/<int:audit_id>/kopyala")
@login_required
def copy_internal_audit(audit_id):
    audit = InternalAudit.query.get_or_404(audit_id)
    ensure_same_company(audit)
    if not can_create_internal_audit():
        abort(403)

    copied_title = f"{audit.title} - Kopya"
    copied_audit = InternalAudit(
        audit_no=reserve_internal_audit_number(date.today()),
        company_id=audit.company_id,
        title=copied_title[:160],
        auditor_id=g.current_user.id,
        evaluated_department=audit.evaluated_department,
        audited_user_id=audit.audited_user_id,
        planned_date=audit.planned_date,
        status="Devam Ediyor",
        active_question_order=1,
    )
    db.session.add(copied_audit)
    db.session.flush()

    for question in audit.questions:
        copied_question = InternalAuditQuestion(
            audit=copied_audit,
            company_id=copied_audit.company_id,
            order_no=question.order_no,
            standard=question.standard,
            audit_topic=question.audit_topic,
            audit_subject=question.audit_subject,
            question_text=question.question_text,
            evaluated_department=audit.evaluated_department or question.evaluated_department,
            evaluator_department=question.evaluator_department,
            answer_options=question.answer_options,
            expected_answer=question.expected_answer,
            is_required=question.is_required,
        )
        db.session.add(copied_question)

    db.session.commit()
    flash(f"{audit.audit_no} kopyalandı. Yeni kayıt: {copied_audit.audit_no}", "success")
    return redirect(url_for("main.edit_internal_audit", audit_id=copied_audit.id))


@bp.post("/ic-denetim/<int:audit_id>/sil")
@login_required
def delete_internal_audit(audit_id):
    audit = InternalAudit.query.get_or_404(audit_id)
    ensure_same_company(audit)
    if not can_delete_internal_audit(audit):
        abort(403)

    deleted_audit_no = audit.audit_no
    db.session.delete(audit)
    db.session.commit()
    flash(f"{deleted_audit_no} numaralı iç denetim silindi.", "success")
    return redirect(url_for("main.internal_audit"))


@bp.get("/ic-denetim/<int:audit_id>/soru/<int:question_id>")
@login_required
def internal_audit_question(audit_id, question_id):
    audit = InternalAudit.query.get_or_404(audit_id)
    ensure_same_company(audit)
    if not can_view_internal_audit(audit):
        abort(403)

    question = InternalAuditQuestion.query.filter_by(
        id=question_id,
        audit_id=audit.id,
    ).first_or_404()
    if audit.active_question_order != question.order_no:
        audit.active_question_order = question.order_no
        db.session.commit()

    return render_template(
        "internal_audit_flow.html",
        **internal_audit_question_context(audit, question),
    )


@bp.get("/ic-denetim/<int:audit_id>/onceki-soru")
@login_required
def previous_internal_audit_question(audit_id):
    audit = InternalAudit.query.get_or_404(audit_id)
    ensure_same_company(audit)
    if not can_view_internal_audit(audit):
        abort(403)
    current_question_id = request.args.get("question_id", type=int)
    question = InternalAuditQuestion.query.filter_by(
        id=current_question_id,
        audit_id=audit.id,
    ).first()
    if question is None:
        question = internal_audit_question_by_order(audit, audit.active_question_order or 1)
    previous_question = internal_audit_question_by_order(
        audit,
        internal_audit_previous_order(audit, question),
    )
    return redirect(
        url_for(
            "main.internal_audit_question",
            audit_id=audit.id,
            question_id=previous_question.id,
        )
    )


@bp.post("/ic-denetim/<int:audit_id>/cevap-kaydet")
@login_required
def save_internal_audit_answer(audit_id):
    audit = InternalAudit.query.get_or_404(audit_id)
    ensure_same_company(audit)
    if not can_view_internal_audit(audit):
        abort(403)
    if not can_answer_internal_audit(audit):
        abort(403)

    question_id = request.form.get("question_id", type=int)
    question = InternalAuditQuestion.query.filter_by(
        id=question_id,
        audit_id=audit.id,
    ).first_or_404()
    submit_action = request.form.get("submit_action", "next")
    is_draft = submit_action == "draft"

    try:
        answer = parse_internal_audit_answer_form(audit, question, is_draft=is_draft)
    except ValueError as error:
        error_key = str(error)
        if error_key == "required_fields":
            flash("Kaydetmek için değerlendirilecek departman ve sonucu seçin.", "danger")
        elif error_key == "technical_findings_required":
            flash("Kısmen Uygun veya Uygun Değil sonucunda teknik bulgular alanı zorunludur.", "danger")
        elif error_key == "technical_findings_too_long":
            flash("Teknik bulgular en fazla 1000 karakter olabilir.", "danger")
        else:
            flash("Lütfen iç denetim cevap alanlarını geçerli biçimde doldurun.", "danger")
        return redirect(
            url_for(
                "main.internal_audit_question",
                audit_id=audit.id,
                question_id=question.id,
            )
        )

    if is_draft:
        audit.active_question_order = question.order_no
        db.session.commit()
        flash("Soru taslak olarak kaydedildi.", "success")
        return redirect(
            url_for(
                "main.internal_audit_question",
                audit_id=audit.id,
                question_id=question.id,
            )
        )

    next_question = internal_audit_question_by_order(
        audit,
        internal_audit_next_order(audit, question),
    )
    if internal_audit_is_complete(audit):
        audit.status = "Tamamlandı"
        audit.active_question_order = question.order_no
        db.session.commit()
        flash("İç denetimdeki tüm zorunlu sorular tamamlandı.", "success")
        return redirect(
            url_for(
                "main.internal_audit_question",
                audit_id=audit.id,
                question_id=question.id,
            )
        )

    audit.status = "Devam Ediyor"
    audit.active_question_order = next_question.order_no if next_question else question.order_no
    db.session.commit()
    if internal_audit_result_requires_finding(answer.result):
        flash("Soru kaydedildi. Bu cevap için Uygunsuzluk Aç butonu ile İF oluşturabilirsiniz.", "warning")
    else:
        flash("Soru kaydedildi ve bir sonraki soruya geçildi.", "success")

    return redirect(
        url_for(
            "main.internal_audit_question",
            audit_id=audit.id,
            question_id=(next_question.id if next_question else question.id),
        )
    )


@bp.post("/ic-denetim/<int:audit_id>/uygunsuzluk-ac")
@login_required
def open_internal_audit_nonconformity(audit_id):
    audit = InternalAudit.query.get_or_404(audit_id)
    ensure_same_company(audit)
    if not can_view_internal_audit(audit):
        abort(403)
    if not can_answer_internal_audit(audit):
        abort(403)

    question_id = request.form.get("question_id", type=int)
    question = InternalAuditQuestion.query.filter_by(
        id=question_id,
        audit_id=audit.id,
    ).first_or_404()

    try:
        answer = parse_internal_audit_answer_form(audit, question, is_draft=False)
    except ValueError as error:
        error_key = str(error)
        if error_key == "technical_findings_required":
            flash("İF açmak için teknik bulgular alanını doldurun.", "danger")
        elif error_key == "required_fields":
            flash("İF açmak için departman, sonuç ve zorunlu alanları tamamlayın.", "danger")
        else:
            flash("İF açmadan önce iç denetim cevabını geçerli biçimde doldurun.", "danger")
        return redirect(
            url_for(
                "main.internal_audit_question",
                audit_id=audit.id,
                question_id=question.id,
            )
        )

    if not internal_audit_result_requires_finding(answer.result):
        db.session.rollback()
        flash("İF açmak için sonuç Kısmen Uygun veya Uygun Değil olmalıdır.", "warning")
        return redirect(
            url_for(
                "main.internal_audit_question",
                audit_id=audit.id,
                question_id=question.id,
            )
        )

    db.session.flush()
    if answer.dof_id:
        db.session.commit()
        flash("Bu soru için daha önce İF açılmış. Mevcut İF detayına yönlendirildiniz.", "info")
        return redirect(url_for("main.dof_detail", dof_id=answer.dof_id))

    audit.active_question_order = question.order_no
    db.session.commit()
    return redirect(url_for("main.create_dof", internal_audit_answer_id=answer.id))


@bp.post("/ic-denetim/<int:audit_id>/bitir")
@login_required
def complete_internal_audit(audit_id):
    audit = InternalAudit.query.get_or_404(audit_id)
    ensure_same_company(audit)
    if not can_view_internal_audit(audit):
        abort(403)
    if not can_answer_internal_audit(audit):
        abort(403)
    if not internal_audit_is_complete(audit):
        flash("Tüm zorunlu sorular tamamlanmadan denetim bitirilemez.", "danger")
        return redirect(url_for("main.internal_audit"))

    audit.status = "Tamamlandı"
    db.session.commit()
    flash("İç denetim tamamlandı. Rapor ekranı için özet kayıt hazır.", "success")
    question = internal_audit_question_by_order(audit, audit.active_question_order or 1)
    return redirect(
        url_for(
            "main.internal_audit_question",
            audit_id=audit.id,
            question_id=question.id,
        )
    )


@bp.route("/dofs/new", methods=["GET", "POST"])
@login_required
def create_dof():
    if request.method == "POST":
        save_mode = request.form.get("save_mode", "open")
        if save_mode not in {"draft", "open"}:
            save_mode = "open"
        audit_answer = None
        audit_answer_id = request.form.get("internal_audit_answer_id", type=int)
        if audit_answer_id:
            audit_answer = scoped_query(
                InternalAuditAnswer.query,
                InternalAuditAnswer,
            ).filter_by(id=audit_answer_id).first()
            if audit_answer is None or not can_view_internal_audit(audit_answer.audit):
                flash("İç denetim cevabı bulunamadı veya erişim yetkiniz yok.", "danger")
                return redirect(url_for("main.dof_management"))
            if audit_answer.dof_id:
                flash("Bu iç denetim cevabı için daha önce İF açılmış.", "info")
                return redirect(url_for("main.dof_detail", dof_id=audit_answer.dof_id))
        try:
            dof = parse_dof_form(save_mode=save_mode)
            assign_current_company(dof)
            dof.dof_no = reserve_dof_number()
            dof.created_by_user_id = g.current_user.id
            db.session.add(dof)
            db.session.flush()
            save_dof_opening_files(dof)
            if audit_answer is not None:
                audit_answer.dof_id = dof.id
                add_dof_comment(
                    dof,
                    (
                        "İF iç denetim soru akışından açıldı. "
                        f"Soru: {short_text(audit_answer.question_text, 140)}"
                    ),
                    comment_type="internal_audit",
                    actor=g.current_user,
                )
            if save_mode != "draft":
                notify_dof_users(
                    [dof.responsible],
                    dof,
                    f"{dof_label(dof)} size atandı.",
                )
                notify_dof_waiting_approvers(dof)
            db.session.commit()
            flash(
                f"{dof.dof_no} numaralı İF kaydı "
                f"{'taslak olarak ' if save_mode == 'draft' else ''}kaydedildi.",
                "success",
            )
            return redirect(url_for("main.dof_management"))
        except ValueError as error:
            db.session.rollback()
            error_key = str(error)
            if error_key == "invalid_dof_file_type":
                flash("Kapanış kanıtı için sadece PDF, JPG veya PNG yükleyebilirsiniz.", "danger")
            elif error_key == "dof_file_too_large":
                flash("Kapanış kanıtı dosyası en fazla 10 MB olabilir.", "danger")
            elif error_key == "invalid_dof_opening_file_type":
                flash("Uygunsuzluk görselleri için sadece JPG, PNG veya WEBP yükleyebilirsiniz.", "danger")
            elif error_key == "dof_opening_file_too_large":
                flash("Uygunsuzluk görsellerinin her biri en fazla 10 MB olabilir.", "danger")
            elif error_key == "required_fields":
                flash("Kaydetmek için yıldızlı zorunlu alanları doldurun.", "danger")
            elif error_key == "text_too_long":
                flash("Açıklama alanları en fazla 2000 karakter olabilir.", "danger")
            else:
                flash("Lütfen İF form alanlarını geçerli biçimde doldurun.", "danger")

    form_data = request.form if request.method == "POST" else {}
    if request.method == "GET":
        audit_answer_id = request.args.get("internal_audit_answer_id", type=int)
        if audit_answer_id:
            audit_answer = scoped_query(
                InternalAuditAnswer.query,
                InternalAuditAnswer,
            ).filter_by(id=audit_answer_id).first()
            if audit_answer is None or not can_view_internal_audit(audit_answer.audit):
                flash("İç denetim cevabı bulunamadı veya erişim yetkiniz yok.", "danger")
                return redirect(url_for("main.dof_management"))
            if audit_answer.dof_id:
                flash("Bu iç denetim cevabı için daha önce İF açılmış.", "info")
                return redirect(url_for("main.dof_detail", dof_id=audit_answer.dof_id))
            form_data = internal_audit_dof_prefill(audit_answer)

    return render_template(
        "dof_form.html",
        users=active_users(),
        departments=DEPARTMENTS,
        priorities=DOF_PRIORITIES,
        sources=DOF_SOURCES,
        today=date.today().isoformat(),
        form_data=form_data,
        form_action=url_for("main.create_dof"),
        page_title="Yeni İF Kaydı",
        page_description="Düzeltici ve önleyici faaliyet kaydı oluşturun",
    )


@bp.route("/dofs/<int:dof_id>/edit", methods=["GET", "POST"])
@login_required
def edit_dof_draft(dof_id):
    dof = Dof.query.get_or_404(dof_id)
    ensure_same_company(dof)
    if not can_view_dof(dof):
        abort(403)
    if not can_edit_dof(dof):
        flash("Bu İF kaydını düzenleme yetkiniz yok veya kayıt tamamlanmış durumda.", "warning")
        return redirect(url_for("main.dof_detail", dof_id=dof.id))

    is_draft_record = can_edit_dof_draft(dof)
    if request.method == "POST":
        save_mode = request.form.get("save_mode", "open")
        if save_mode not in {"draft", "open", "save_changes"}:
            save_mode = "open"
        if is_draft_record and save_mode == "save_changes":
            save_mode = "draft"
        if not is_draft_record:
            save_mode = "save_changes" if save_mode == "save_changes" else "open"
        before = dof_revision_snapshot(dof)
        old_responsible_id = dof.responsible_id
        uploaded_opening_file_count = len(dof_opening_file_uploads())
        try:
            parse_dof_form(
                dof,
                save_mode=save_mode,
                update_workflow=(save_mode == "open"),
            )
            save_dof_opening_files(dof)
            if is_draft_record and save_mode == "draft":
                flash(f"{dof.dof_no} numaralı İF taslağı güncellendi.", "success")
            elif save_mode == "save_changes":
                changes = describe_dof_revision_changes(before, dof)
                if uploaded_opening_file_count:
                    changes.append(
                        f"{uploaded_opening_file_count} uygunsuzluk görseli eklendi"
                    )
                if changes:
                    add_dof_comment(
                        dof,
                        (
                            f"{g.current_user.full_name} İF kaydında düzenleme yaptı: "
                            + ", ".join(changes)
                        ),
                        comment_type="revision",
                        actor=g.current_user,
                    )
                    notification_users = dof_change_notification_users(dof)
                    old_responsible = (
                        User.query.get(old_responsible_id)
                        if old_responsible_id and old_responsible_id != dof.responsible_id
                        else None
                    )
                    if old_responsible:
                        notification_users.append(old_responsible)
                    notify_dof_users(
                        notification_users,
                        dof,
                        (
                            f"{dof_label(dof)} kaydında düzenleme yapıldı: "
                            f"{short_text(', '.join(changes), 180)}"
                        ),
                        exclude_user_id=g.current_user.id,
                    )
                    flash("İF düzenlemeleri kaydedildi ve ilgililere bildirim gönderildi.", "success")
                else:
                    flash("Kaydedilecek yeni bir düzenleme bulunamadı.", "info")
            elif is_draft_record:
                add_dof_comment(
                    dof,
                    f"{g.current_user.full_name} İF taslağını onay akışına gönderdi.",
                    comment_type="approval",
                    actor=g.current_user,
                )
                notify_dof_users(
                    [dof.responsible],
                    dof,
                    f"{dof_label(dof)} size atandı.",
                )
                notify_dof_waiting_approvers(dof)
                flash(f"{dof.dof_no} numaralı İF kaydı onay akışına alındı.", "success")
            elif not is_draft_record:
                changes = describe_dof_revision_changes(before, dof)
                add_dof_comment(
                    dof,
                    (
                        f"{g.current_user.full_name} İF kaydını düzenledi ve onaya gönderdi: "
                        + ", ".join(changes)
                    )
                    if changes
                    else f"{g.current_user.full_name} İF kaydını onaya gönderdi.",
                    comment_type="approval",
                    actor=g.current_user,
                )
                if old_responsible_id != dof.responsible_id:
                    notify_dof_users(
                        [dof.responsible],
                        dof,
                        f"{dof_label(dof)} sorumluluğu size atandı.",
                    )
                notify_dof_waiting_approvers(dof)
                flash(f"{dof.dof_no} numaralı İF kaydı onaya gönderildi.", "success")
            db.session.commit()
            return redirect(url_for("main.dof_detail", dof_id=dof.id))
        except ValueError as error:
            db.session.rollback()
            error_key = str(error)
            if error_key == "invalid_dof_opening_file_type":
                flash("Uygunsuzluk görselleri için sadece JPG, PNG veya WEBP yükleyebilirsiniz.", "danger")
            elif error_key == "dof_opening_file_too_large":
                flash("Uygunsuzluk görsellerinin her biri en fazla 10 MB olabilir.", "danger")
            elif error_key == "required_fields":
                flash("Kaydetmek için yıldızlı zorunlu alanları doldurun.", "danger")
            elif error_key == "closing_actions_required":
                flash("Onaya göndermek için Uygunsuzluğu Kapatmak İçin Alınan Aksiyonlar alanını doldurun.", "danger")
            elif error_key == "text_too_long":
                flash("Açıklama alanları en fazla 2000 karakter olabilir.", "danger")
            else:
                flash("Lütfen İF form alanlarını geçerli biçimde doldurun.", "danger")

    form_data = request.form if request.method == "POST" else dof_form_data_from_record(dof)
    return render_template(
        "dof_form.html",
        users=active_users(),
        departments=DEPARTMENTS,
        priorities=DOF_PRIORITIES,
        sources=DOF_SOURCES,
        today=date.today().isoformat(),
        form_data=form_data,
        form_action=url_for("main.edit_dof_draft", dof_id=dof.id),
        page_title="İF Taslağını Düzenle" if is_draft_record else "İF Kaydını Düzenle",
        page_description=(
            f"{dof.dof_no} numaralı taslağı güncelleyin veya onay akışına gönderin."
            if is_draft_record
            else f"{dof.dof_no} numaralı İF kaydındaki kapanış aksiyonlarını yazıp onaya gönderin."
        ),
        can_save_draft=is_draft_record,
        can_save_changes=not is_draft_record,
        submit_label="Onaya Gönder",
        submit_icon="bi-send-check",
        submit_button_class="btn-success",
        show_closing_actions=True,
        dof=dof,
    )


@bp.get("/dofs/<int:dof_id>")
@login_required
def dof_detail(dof_id):
    dof = Dof.query.get_or_404(dof_id)
    ensure_same_company(dof)
    if not can_view_dof(dof):
        abort(403)
    attach_dof_view_state([dof])
    return render_template(
        "dof_detail.html",
        dof=dof,
        approval_steps=dof_approval_steps(dof),
        can_approve_management=can_approve_dof_management(dof),
        can_approve_deputy=can_approve_dof_deputy(dof),
        can_reject=can_reject_dof(dof),
        can_revise=can_revise_rejected_dof(dof),
        can_edit_draft=can_edit_dof_draft(dof),
        can_edit=can_edit_dof(dof),
        can_delete=can_delete_dof(dof),
        users=active_users(),
        departments=DEPARTMENTS,
        priorities=DOF_PRIORITIES,
        sources=DOF_SOURCES,
    )


@bp.post("/dofs/<int:dof_id>/approve-management")
@login_required
def approve_dof_management(dof_id):
    dof = Dof.query.get_or_404(dof_id)
    ensure_same_company(dof)
    if not can_view_dof(dof):
        abort(403)
    attach_dof_view_state([dof])
    if not can_approve_dof_management(dof):
        abort(403)

    dof.management_approved_by_user_id = g.current_user.id
    dof.management_approved_at = datetime.utcnow()
    dof.approval_step = "general_manager_deputy"
    dof.status = "Onay Akışı Bekleniyor"
    add_dof_comment(
        dof,
        f"{g.current_user.full_name} Yönetim Temsilcisi onayını verdi.",
        comment_type="approval",
        actor=g.current_user,
    )
    notify_dof_waiting_approvers(dof)
    db.session.commit()
    flash("İF kaydı Yönetim Temsilcisi tarafından onaylandı.", "success")
    return redirect(url_for("main.dof_detail", dof_id=dof.id))


@bp.post("/dofs/<int:dof_id>/approve-deputy")
@login_required
def approve_dof_deputy(dof_id):
    dof = Dof.query.get_or_404(dof_id)
    ensure_same_company(dof)
    if not can_view_dof(dof):
        abort(403)
    attach_dof_view_state([dof])
    if not can_approve_dof_deputy(dof):
        abort(403)

    now = datetime.utcnow()
    dof.deputy_approved_by_user_id = g.current_user.id
    dof.deputy_approved_at = now
    dof.completed_at = now
    dof.approval_step = "completed"
    dof.status = "Tamamlandı"
    add_dof_comment(
        dof,
        f"{g.current_user.full_name} Genel Müdür Yardımcısı onayını verdi ve İF kapandı.",
        comment_type="approval",
        actor=g.current_user,
    )
    notify_dof_users(
        dof_primary_users(dof),
        dof,
        f"{dof_label(dof)} kapatıldı.",
    )
    db.session.commit()
    flash("İF kaydı Genel Müdür Yardımcısı onayıyla tamamlandı.", "success")
    return redirect(url_for("main.dof_detail", dof_id=dof.id))


@bp.post("/dofs/<int:dof_id>/reject")
@login_required
def reject_dof(dof_id):
    dof = Dof.query.get_or_404(dof_id)
    ensure_same_company(dof)
    if not can_view_dof(dof):
        abort(403)
    attach_dof_view_state([dof])
    if not can_reject_dof(dof):
        abort(403)

    rejection_reason = request.form.get("rejection_reason", "").strip()
    if not rejection_reason:
        flash("Red sebebi alanını doldurun.", "danger")
        return redirect(url_for("main.dof_detail", dof_id=dof.id))

    rejected_step = dof.approval_step
    dof.status = "Revizyon Bekleniyor"
    dof.approval_step = "revision_requested"
    dof.rejected_step = rejected_step
    dof.rejection_reason = rejection_reason
    dof.rejected_by_user_id = g.current_user.id
    dof.rejected_at = datetime.utcnow()
    if rejected_step == "management_representative":
        dof.management_approved_by_user_id = None
        dof.management_approved_at = None
        dof.deputy_approved_by_user_id = None
        dof.deputy_approved_at = None
    elif rejected_step == "general_manager_deputy":
        dof.deputy_approved_by_user_id = None
        dof.deputy_approved_at = None

    add_dof_comment(
        dof,
        (
            f"{g.current_user.full_name} {dof_approver_label(rejected_step)} "
            f"onayını reddetti: \"{short_text(rejection_reason)}\""
        ),
        comment_type="rejection",
        actor=g.current_user,
    )
    notify_dof_users(
        dof_rejection_recipients(dof, rejected_step),
        dof,
        (
            f"{dof_label(dof)} {dof_approver_label(rejected_step)} tarafından "
            f"reddedildi. Sebep: {short_text(rejection_reason)}"
        ),
        exclude_user_id=g.current_user.id,
    )
    db.session.commit()
    flash("İF kaydı reddedildi ve revizyon beklemeye alındı.", "success")
    return redirect(url_for("main.dof_detail", dof_id=dof.id))


@bp.post("/dofs/<int:dof_id>/revision")
@login_required
def revise_dof(dof_id):
    dof = Dof.query.get_or_404(dof_id)
    ensure_same_company(dof)
    if not can_view_dof(dof):
        abort(403)
    attach_dof_view_state([dof])
    if not can_revise_rejected_dof(dof):
        abort(403)

    target_step = (
        dof.rejected_step
        if dof.rejected_step in {"management_representative", "general_manager_deputy"}
        else "management_representative"
    )
    before = dof_revision_snapshot(dof)
    revision_note = request.form.get("revision_note", "").strip()
    try:
        parse_dof_revision_form(dof)
    except ValueError as error:
        error_key = str(error)
        if error_key == "invalid_dof_file_type":
            flash("Kanıt dosyası için sadece PDF, JPG veya PNG yükleyebilirsiniz.", "danger")
        elif error_key == "dof_file_too_large":
            flash("Kanıt dosyası en fazla 10 MB olabilir.", "danger")
        elif error_key == "required_fields":
            flash("Tekrar onay talep etmek için zorunlu alanları doldurun.", "danger")
        elif error_key == "text_too_long":
            flash("Açıklama alanları en fazla 2000 karakter olabilir.", "danger")
        else:
            flash("Lütfen İF revizyon alanlarını geçerli biçimde doldurun.", "danger")
        return redirect(url_for("main.dof_detail", dof_id=dof.id))

    changes = describe_dof_revision_changes(before, dof)
    dof.status = "Onay Akışı Bekleniyor"
    dof.approval_step = target_step
    dof.rejection_reason = None
    dof.rejected_by_user_id = None
    dof.rejected_at = None
    dof.rejected_step = None
    if target_step == "management_representative":
        dof.management_approved_by_user_id = None
        dof.management_approved_at = None
        dof.deputy_approved_by_user_id = None
        dof.deputy_approved_at = None
    elif target_step == "general_manager_deputy":
        dof.deputy_approved_by_user_id = None
        dof.deputy_approved_at = None

    comment_parts = [
        f"{g.current_user.full_name} revizyon yaptı ve tekrar onay talep etti."
    ]
    if changes:
        comment_parts.append("Değişiklikler: " + ", ".join(changes) + ".")
    if revision_note:
        comment_parts.append(f"Not: {revision_note}")
    add_dof_comment(
        dof,
        " ".join(comment_parts),
        comment_type="revision",
        actor=g.current_user,
    )
    notify_dof_waiting_approvers(dof)
    db.session.commit()
    flash("İF revizyonu kaydedildi ve tekrar onaya gönderildi.", "success")
    return redirect(url_for("main.dof_detail", dof_id=dof.id))


@bp.get("/dofs/<int:dof_id>/evidence/download")
@login_required
def download_dof_evidence_file(dof_id):
    dof = Dof.query.get_or_404(dof_id)
    ensure_same_company(dof)
    if not can_view_dof(dof):
        abort(403)
    if not dof.evidence_stored_name:
        flash("Bu İF kaydına ait kapanış kanıt dosyası bulunamadı.", "warning")
        return redirect(url_for("main.dof_detail", dof_id=dof.id))

    return send_stored_upload(
        dof.evidence_stored_name,
        as_attachment=True,
        download_name=dof.evidence_original_name,
    )


@bp.get("/dofs/<int:dof_id>/files/<int:file_id>/download")
@login_required
def download_dof_file(dof_id, file_id):
    dof = Dof.query.get_or_404(dof_id)
    ensure_same_company(dof)
    if not can_view_dof(dof):
        abort(403)

    dof_file = DofFile.query.filter_by(id=file_id, dof_id=dof.id).first_or_404()
    return send_stored_upload(
        dof_file.stored_name,
        as_attachment=True,
        download_name=dof_file.original_name,
    )


@bp.route("/dofs/<int:dof_id>/delete", methods=["GET", "POST"])
@login_required
def delete_dof(dof_id):
    dof = Dof.query.get_or_404(dof_id)
    ensure_same_company(dof)
    if not can_delete_dof(dof):
        abort(403)

    if request.method == "POST":
        InternalAuditAnswer.query.filter_by(dof_id=dof.id).update(
            {"dof_id": None},
            synchronize_session=False,
        )
        InternalAuditAnswer.query.filter_by(previous_nonconformity_id=dof.id).update(
            {"previous_nonconformity_id": None},
            synchronize_session=False,
        )
        delete_dof_evidence_file(dof)
        db.session.delete(dof)
        db.session.commit()
        flash("İF kaydı silindi.", "success")
        return redirect(url_for("main.dof_management"))

    return render_template("dof_confirm_delete.html", dof=dof)


@bp.route("/actions/new", methods=["GET", "POST"])
@login_required
@permission_required("can_create_actions")
def create_action():
    if request.method == "POST":
        try:
            action = parse_action_form()
            assign_current_company(action)
            action.action_number = reserve_action_number()
            db.session.add(action)
            db.session.flush()
            created_sub_actions = create_inline_sub_actions(action)
            add_action_history(
                action,
                "created",
                f"{g.current_user.full_name} aksiyonu oluşturdu.",
                actor=g.current_user,
            )
            if created_sub_actions:
                add_action_history(
                    action,
                    "sub_actions_created",
                    f"{len(created_sub_actions)} alt aksiyon eklendi.",
                    actor=g.current_user,
                )
            notify_action_participants(
                action,
                f"{action.number_label} {action.title} aksiyonu size atandı.",
                exclude_user_id=g.current_user.id,
            )
            for sub_action in created_sub_actions:
                notify_sub_action_participants(
                    sub_action,
                    (
                        f"{action.number_label} {action.title} aksiyonu altında "
                        f"'{sub_action.title}' alt aksiyonunda sorumlu/ilgili olarak atandınız."
                    ),
                    exclude_user_id=g.current_user.id,
                )
            db.session.commit()
            flash("Aksiyon kaydı başarıyla eklendi.", "success")
            return redirect(url_for("main.dashboard"))
        except ValueError as error:
            error_key = str(error)
            if error_key == "invalid_file_type":
                flash(
                    "Sadece PDF, Word, Excel veya görsel dosyası yükleyebilirsiniz.",
                    "danger",
                )
            elif error_key == "sub_action_required_fields":
                flash("Alt aksiyon eklediyseniz alt aksiyon başlığını doldurun.", "danger")
            elif error_key in {"invalid_sub_action_priority", "invalid_sub_action_status"}:
                flash("Alt aksiyon öncelik veya durum alanını kontrol edin.", "danger")
            elif error_key == "sub_action_completion_requires_evidence":
                flash(
                    "Kanıt zorunlu alt aksiyonu ilk kayıtta tamamlandı olarak açamazsınız.",
                    "danger",
                )
            else:
                flash("Lütfen form alanlarını geçerli biçimde doldurun.", "danger")

    return render_template(
        "action_form.html",
        action=None,
        users=active_users(),
        departments=DEPARTMENTS,
        today=date.today().isoformat(),
        title="Yeni Aksiyon",
        sub_action_statuses=ACTION_SUB_TASK_STATUSES,
        sub_action_priorities=ACTION_SUB_TASK_PRIORITIES,
    )


@bp.route("/actions/<int:action_id>")
@login_required
def action_detail(action_id):
    action = Action.query.get_or_404(action_id)
    ensure_same_company(action)
    if not can_view_action(action):
        abort(403)

    return render_template(
        "action_detail.html",
        action=action,
        users=active_users(),
        can_complete=can_complete_action(action),
        can_request_closure=can_request_closure_action(action),
        can_approve_closure=can_approve_closure_action(action),
        can_comment=can_comment_action(action),
        can_reassign=can_reassign_action(action),
        can_revise_termin=can_revise_termin(action),
        can_create_sub_action=can_create_sub_action(action),
        can_edit_sub_action=can_edit_sub_action,
        can_full_edit_sub_action=can_full_edit_sub_action,
        can_delete_sub_action=can_delete_sub_action,
        can_complete_sub_action=can_complete_sub_action,
        sub_action_statuses=ACTION_SUB_TASK_STATUSES,
        sub_action_priorities=ACTION_SUB_TASK_PRIORITIES,
    )


@bp.post("/actions/<int:action_id>/reassign")
@login_required
def reassign_action(action_id):
    action = Action.query.get_or_404(action_id)
    ensure_same_company(action)
    if not can_reassign_action(action):
        abort(403)

    responsible_user_id = request.form.get("responsible_user_id", "").strip()
    try:
        responsible_user_id = int(responsible_user_id)
    except ValueError:
        flash("Lütfen geçerli bir aksiyon sorumlusu seçin.", "danger")
        return redirect(url_for("main.action_detail", action_id=action.id))

    responsible_user = active_user_by_id(responsible_user_id)
    if responsible_user is None:
        flash("Seçilen kullanıcı bulunamadı.", "danger")
        return redirect(url_for("main.action_detail", action_id=action.id))

    try:
        related_user_1 = parse_optional_user("related_user_1_id")
        related_user_2 = parse_optional_user("related_user_2_id")
    except ValueError:
        flash("Lütfen geçerli ilgili kullanıcı seçin.", "danger")
        return redirect(url_for("main.action_detail", action_id=action.id))

    before = action_snapshot(action)
    action.responsible_user_id = responsible_user.id
    action.responsible_owner = responsible_user.full_name
    action.related_user_1_id = related_user_1.id if related_user_1 else None
    action.related_user_2_id = related_user_2.id if related_user_2 else None

    changes = describe_action_changes(before, action)
    if not changes:
        flash("Sorumlu ve ilgili bilgilerinde değişiklik yapılmadı.", "warning")
        return redirect(url_for("main.action_detail", action_id=action.id))

    add_action_history(
        action,
        "reassigned",
        (
            f"{g.current_user.full_name} sorumlu/ilgili bilgilerini güncelledi: "
            + "; ".join(changes)
        ),
        actor=g.current_user,
    )
    notify_action_participants(
        action,
        (
            f"{action.number_label} {action.title} aksiyonunda "
            "sorumlu/ilgili bilgileri güncellendi."
        ),
        exclude_user_id=g.current_user.id,
        extra_user_ids={
            before["responsible_user_id"],
            before["related_user_1_id"],
            before["related_user_2_id"],
        },
    )
    db.session.commit()
    flash("Sorumlu ve ilgili bilgileri güncellendi.", "success")

    if can_view_action(action):
        return redirect(url_for("main.action_detail", action_id=action.id))
    return redirect(url_for("main.dashboard"))


@bp.post("/actions/<int:action_id>/revise-termin")
@login_required
def revise_action_termin(action_id):
    action = Action.query.get_or_404(action_id)
    ensure_same_company(action)
    if not can_revise_termin(action):
        abort(403)

    termin_value = request.form.get("termin_date", "")
    try:
        new_termin_date = datetime.strptime(termin_value, "%Y-%m-%d").date()
    except ValueError:
        flash("Lütfen geçerli bir termin tarihi girin.", "danger")
        return redirect(url_for("main.action_detail", action_id=action.id))

    old_termin_date = action.termin_date
    if old_termin_date == new_termin_date:
        flash("Termin tarihi zaten bu değerle kayıtlı.", "warning")
        return redirect(url_for("main.action_detail", action_id=action.id))

    action.termin_date = new_termin_date
    action.refresh_delay()
    add_action_history(
        action,
        "termin_revised",
        (
            f"{g.current_user.full_name} termini "
            f"{format_date(old_termin_date)} -> {format_date(new_termin_date)} "
            "olarak revize etti."
        ),
        actor=g.current_user,
    )
    notify_action_participants(
        action,
        f"{action.number_label} {action.title} aksiyonunda termin revize edildi.",
        exclude_user_id=g.current_user.id,
    )
    db.session.commit()
    flash("Termin tarihi revize edildi.", "success")
    return redirect(url_for("main.action_detail", action_id=action.id))


@bp.post("/actions/<int:action_id>/comments")
@login_required
def add_action_comment(action_id):
    action = Action.query.get_or_404(action_id)
    ensure_same_company(action)
    if not can_comment_action(action):
        abort(403)

    comment_text = request.form.get("comment", "").strip()
    if not comment_text:
        flash("Yorum alanı boş bırakılamaz.", "danger")
        return redirect(url_for("main.action_detail", action_id=action.id))

    comment = ActionComment(
        action_id=action.id,
        company_id=action.company_id,
        user_id=g.current_user.id,
        comment=comment_text,
    )
    db.session.add(comment)
    add_action_history(
        action,
        "commented",
        f"{g.current_user.full_name} yorum ekledi: \"{short_text(comment_text)}\"",
        actor=g.current_user,
    )
    notify_action_participants(
        action,
        f"{action.number_label} {action.title} aksiyonuna yeni yorum eklendi.",
        exclude_user_id=g.current_user.id,
    )
    db.session.commit()
    flash("Yorum eklendi.", "success")
    return redirect(url_for("main.action_detail", action_id=action.id))


@bp.route("/actions/<int:action_id>/edit", methods=["GET", "POST"])
@login_required
@permission_required("can_edit_actions")
def edit_action(action_id):
    action = Action.query.get_or_404(action_id)
    ensure_same_company(action)

    if request.method == "POST":
        try:
            before = action_snapshot(action)
            parse_action_form(action)
            changes = describe_action_changes(before, action)
            if changes:
                add_action_history(
                    action,
                    "updated",
                    (
                        f"{g.current_user.full_name} aksiyonu revize etti: "
                        + "; ".join(changes)
                    ),
                    actor=g.current_user,
                )
                notify_action_participants(
                    action,
                    f"{action.number_label} {action.title} aksiyonunda revizyon yapıldı.",
                    exclude_user_id=g.current_user.id,
                    extra_user_ids={
                        before["responsible_user_id"],
                        before["related_user_1_id"],
                        before["related_user_2_id"],
                    },
                )
            db.session.commit()
            flash("Aksiyon kaydı güncellendi.", "success")
            return redirect(url_for("main.dashboard"))
        except ValueError as error:
            if str(error) == "invalid_file_type":
                flash(
                    "Sadece PDF, Word, Excel veya görsel dosyası yükleyebilirsiniz.",
                    "danger",
                )
            else:
                flash("Lütfen form alanlarını geçerli biçimde doldurun.", "danger")

    return render_template(
        "action_form.html",
        action=action,
        users=active_users(),
        departments=DEPARTMENTS,
        today=date.today().isoformat(),
        title="Aksiyon Düzenle",
        sub_action_statuses=ACTION_SUB_TASK_STATUSES,
        sub_action_priorities=ACTION_SUB_TASK_PRIORITIES,
    )


@bp.post("/actions/<int:action_id>/sub-actions/create")
@login_required
def create_sub_action(action_id):
    action = Action.query.get_or_404(action_id)
    ensure_same_company(action)
    if not can_create_sub_action(action):
        abort(403)

    try:
        sub_action = parse_sub_action_form()
        sub_action.parent_action = action
        sub_action.company_id = action.company_id
        sub_action.created_by_user_id = g.current_user.id
        db.session.add(sub_action)
        db.session.flush()
        add_action_history(
            action,
            "sub_action_created",
            f"{g.current_user.full_name} '{sub_action.title}' alt aksiyonunu ekledi.",
            actor=g.current_user,
        )
        notify_sub_action_participants(
            sub_action,
            (
                f"{action.number_label} {action.title} aksiyonu altında "
                f"'{sub_action.title}' alt aksiyonunda sorumlu/ilgili olarak atandınız."
            ),
            exclude_user_id=g.current_user.id,
        )
        db.session.commit()
        flash("Alt aksiyon eklendi.", "success")
    except ValueError as error:
        db.session.rollback()
        error_key = str(error)
        if error_key == "invalid_file_type":
            flash("Alt aksiyon kanıtı için sadece PDF, JPG, PNG, DOCX veya XLSX yükleyebilirsiniz.", "danger")
        elif error_key == "evidence_required":
            flash("Kanıt zorunlu olan alt aksiyon tamamlanırken kanıt dosyası yüklenmelidir.", "danger")
        elif error_key == "closing_note_required":
            flash("Kanıt zorunlu olan alt aksiyon tamamlanırken kapanış açıklaması yazılmalıdır.", "danger")
        else:
            flash("Alt aksiyon bilgilerini kontrol edin.", "danger")
    return redirect(url_for("main.action_detail", action_id=action.id))


@bp.get("/sub-actions/<int:sub_action_id>")
@login_required
def sub_action_detail(sub_action_id):
    sub_action = ActionSubTask.query.get_or_404(sub_action_id)
    ensure_same_company(sub_action)
    if not can_view_action(sub_action.parent_action):
        abort(403)
    return render_template(
        "sub_action_detail.html",
        sub_action=sub_action,
        action=sub_action.parent_action,
        can_edit=can_edit_sub_action(sub_action),
        can_delete=can_delete_sub_action(sub_action),
        can_complete=can_complete_sub_action(sub_action),
    )


@bp.route("/sub-actions/<int:sub_action_id>/edit", methods=["GET", "POST"])
@login_required
def edit_sub_action(sub_action_id):
    sub_action = ActionSubTask.query.get_or_404(sub_action_id)
    ensure_same_company(sub_action)
    action = sub_action.parent_action
    if not can_edit_sub_action(sub_action):
        abort(403)

    if request.method == "POST":
        before = sub_action_snapshot(sub_action)
        can_full_edit = can_full_edit_sub_action(sub_action)
        old_status = sub_action.status
        try:
            if can_full_edit:
                parse_sub_action_form(sub_action)
            else:
                parse_sub_action_limited_revision(sub_action)

            changes = describe_sub_action_changes(before, sub_action)
            if not changes:
                flash("Alt aksiyonda değişiklik yapılmadı.", "warning")
                return redirect(url_for("main.edit_sub_action", sub_action_id=sub_action.id))

            add_action_history(
                action,
                "sub_action_updated",
                (
                    f"{g.current_user.full_name} '{sub_action.title}' alt aksiyonunu "
                    f"güncelledi: {'; '.join(changes)}"
                ),
                actor=g.current_user,
            )
            notify_sub_action_participants(
                sub_action,
                (
                    f"{action.number_label} {action.title} aksiyonu altında "
                    f"'{sub_action.title}' alt aksiyonu güncellendi."
                ),
                exclude_user_id=g.current_user.id,
                extra_user_ids={
                    before["responsible_id"],
                    before["related_user_1_id"],
                    before["related_user_2_id"],
                },
            )
            if old_status != "Tamamlandı" and sub_action.status == "Tamamlandı":
                notify_sub_action_participants(
                    sub_action,
                    f"'{sub_action.title}' alt aksiyonu tamamlandı.",
                    exclude_user_id=g.current_user.id,
                )
            db.session.commit()
            flash("Alt aksiyon güncellendi.", "success")
            if can_view_action(action):
                return redirect(url_for("main.action_detail", action_id=action.id))
            return redirect(url_for("main.dashboard"))
        except ValueError as error:
            db.session.rollback()
            error_key = str(error)
            if error_key == "invalid_file_type":
                flash("Alt aksiyon kanıtı için sadece PDF, JPG, PNG, DOCX veya XLSX yükleyebilirsiniz.", "danger")
            elif error_key == "evidence_required":
                flash("Kanıt zorunlu olan alt aksiyon tamamlanırken kanıt dosyası yüklenmelidir.", "danger")
            elif error_key == "closing_note_required":
                flash("Kanıt zorunlu olan alt aksiyon tamamlanırken kapanış açıklaması yazılmalıdır.", "danger")
            else:
                flash("Alt aksiyon bilgilerini kontrol edin.", "danger")

    return render_template(
        "sub_action_form.html",
        sub_action=sub_action,
        action=action,
        users=active_users(),
        can_full_edit=can_full_edit_sub_action(sub_action),
        can_reassign=can_reassign_sub_action(sub_action),
        can_revise_termin=can_revise_sub_action_termin(sub_action),
        sub_action_statuses=ACTION_SUB_TASK_STATUSES,
        sub_action_priorities=ACTION_SUB_TASK_PRIORITIES,
    )


@bp.post("/sub-actions/<int:sub_action_id>/complete")
@login_required
def complete_sub_action(sub_action_id):
    sub_action = ActionSubTask.query.get_or_404(sub_action_id)
    ensure_same_company(sub_action)
    action = sub_action.parent_action
    if not can_complete_sub_action(sub_action):
        abort(403)

    closing_note = request.form.get("closing_note", "").strip()
    if closing_note:
        sub_action.closing_note = closing_note
    try:
        save_sub_action_evidence_file(sub_action)
    except ValueError:
        flash("Alt aksiyon kanıtı için sadece PDF, JPG, PNG, DOCX veya XLSX yükleyebilirsiniz.", "danger")
        return redirect(url_for("main.action_detail", action_id=action.id))

    if sub_action.evidence_required and not sub_action.evidence_stored_name:
        flash("Bu alt aksiyon için kanıt dosyası yüklenmeden tamamlanamaz.", "danger")
        return redirect(url_for("main.action_detail", action_id=action.id))
    if sub_action.evidence_required and not sub_action.closing_note:
        flash("Bu alt aksiyon için kapanış açıklaması yazılmadan tamamlanamaz.", "danger")
        return redirect(url_for("main.action_detail", action_id=action.id))

    sub_action.status = "Tamamlandı"
    sub_action.completed_at = datetime.utcnow()
    sub_action.completed_by_user_id = g.current_user.id
    add_action_history(
        action,
        "sub_action_completed",
        f"{g.current_user.full_name} '{sub_action.title}' alt aksiyonunu tamamladı.",
        actor=g.current_user,
    )
    notify_sub_action_participants(
        sub_action,
        f"'{sub_action.title}' alt aksiyonu tamamlandı.",
        exclude_user_id=g.current_user.id,
    )
    db.session.commit()
    flash("Alt aksiyon tamamlandı.", "success")
    return redirect(url_for("main.action_detail", action_id=action.id))


@bp.post("/sub-actions/<int:sub_action_id>/delete")
@login_required
def delete_sub_action(sub_action_id):
    sub_action = ActionSubTask.query.get_or_404(sub_action_id)
    ensure_same_company(sub_action)
    action = sub_action.parent_action
    if not can_delete_sub_action(sub_action):
        abort(403)

    title = sub_action.title
    delete_sub_action_evidence_file(sub_action)
    db.session.delete(sub_action)
    add_action_history(
        action,
        "sub_action_deleted",
        f"{g.current_user.full_name} '{title}' alt aksiyonunu sildi.",
        actor=g.current_user,
    )
    db.session.commit()
    flash("Alt aksiyon silindi.", "success")
    return redirect(url_for("main.action_detail", action_id=action.id))


@bp.get("/sub-actions/<int:sub_action_id>/evidence/download")
@login_required
def download_sub_action_evidence(sub_action_id):
    sub_action = ActionSubTask.query.get_or_404(sub_action_id)
    ensure_same_company(sub_action)
    if not can_view_action(sub_action.parent_action):
        abort(403)
    if not sub_action.evidence_stored_name:
        flash("Bu alt aksiyon için kanıt dosyası bulunmuyor.", "warning")
        return redirect(url_for("main.sub_action_detail", sub_action_id=sub_action.id))
    return send_stored_upload(
        sub_action.evidence_stored_name,
        as_attachment=True,
        download_name=sub_action.evidence_original_name,
    )


@bp.post("/actions/<int:action_id>/request-closure")
@login_required
def request_action_closure(action_id):
    action = Action.query.get_or_404(action_id)
    ensure_same_company(action)
    if not can_request_closure_action(action):
        abort(403)

    if action.has_open_sub_actions:
        flash(
            "Bu aksiyona bağlı tamamlanmamış alt aksiyonlar bulunmaktadır. "
            "Ana aksiyonu kapatmadan önce alt aksiyonları tamamlayınız.",
            "warning",
        )
        return redirect(url_for("main.action_detail", action_id=action.id))

    evidence_note = request.form.get("closure_evidence_note", "").strip()
    if not evidence_note:
        flash("Kapatma onayı için açıklama alanını doldurun.", "danger")
        return redirect(url_for("main.action_detail", action_id=action.id))

    try:
        save_closure_evidence_files(action)
    except ValueError:
        flash("Sadece PDF, Word, Excel veya görsel dosyası yükleyebilirsiniz.", "danger")
        return redirect(url_for("main.action_detail", action_id=action.id))

    action.closure_approval_requested = True
    action.closure_requested_at = datetime.utcnow()
    action.closure_requested_by_user_id = g.current_user.id
    action.closure_evidence_note = evidence_note
    action.closure_rejected_at = None
    action.closure_rejected_by_user_id = None
    action.closure_rejection_reason = None
    add_action_history(
        action,
        "closure_requested",
        f"{g.current_user.full_name} kapatma onayı gönderdi.",
        actor=g.current_user,
    )
    admin_user = oguzhan_user()
    if admin_user:
        notify_users(
            {admin_user.id},
            action,
            f"{action.number_label} {action.title} aksiyonu için kapatma onayı bekliyor.",
            exclude_user_id=g.current_user.id,
        )
    db.session.commit()
    flash("Kapatma onayı Oğuzhan'a gönderildi.", "success")
    return redirect(url_for("main.action_detail", action_id=action.id))


@bp.post("/actions/<int:action_id>/complete")
@login_required
def complete_action(action_id):
    action = Action.query.get_or_404(action_id)
    ensure_same_company(action)
    if not can_approve_closure_action(action):
        abort(403)

    if action.has_open_sub_actions:
        flash(
            "Bu aksiyona bağlı tamamlanmamış alt aksiyonlar bulunmaktadır. "
            "Ana aksiyonu kapatmadan önce alt aksiyonları tamamlayınız.",
            "warning",
        )
        return redirect(url_for("main.action_detail", action_id=action.id))

    action.mark_completed()
    add_action_history(
        action,
        "completed",
        f"{g.current_user.full_name} kapatma onayını verdi ve aksiyonu tamamladı.",
        actor=g.current_user,
    )
    notify_action_participants(
        action,
        f"{action.number_label} {action.title} aksiyonunun kapanışı Oğuzhan tarafından onaylandı.",
        exclude_user_id=g.current_user.id,
    )
    db.session.commit()
    flash("Kapatma onayı verildi ve aksiyon tamamlandı.", "success")
    return redirect(url_for("main.action_detail", action_id=action.id))


@bp.post("/actions/<int:action_id>/reject-closure")
@login_required
def reject_action_closure(action_id):
    action = Action.query.get_or_404(action_id)
    ensure_same_company(action)
    if not can_approve_closure_action(action):
        abort(403)

    rejection_reason = request.form.get("closure_rejection_reason", "").strip()
    if not rejection_reason:
        flash("Red sebebi alanını doldurun.", "danger")
        return redirect(url_for("main.action_detail", action_id=action.id))

    action.closure_approval_requested = False
    action.closure_rejected_at = datetime.utcnow()
    action.closure_rejected_by_user_id = g.current_user.id
    action.closure_rejection_reason = rejection_reason
    add_action_history(
        action,
        "closure_rejected",
        (
            f"{g.current_user.full_name} kapatma onayını reddetti: "
            f"\"{short_text(rejection_reason)}\""
        ),
        actor=g.current_user,
    )
    notify_action_participants(
        action,
        (
            f"{action.number_label} {action.title} aksiyonunun kapatma onayı "
            f"reddedildi. Sebep: {short_text(rejection_reason)}"
        ),
        exclude_user_id=g.current_user.id,
        extra_user_ids={action.closure_requested_by_user_id},
    )
    db.session.commit()
    flash("Kapatma onayı reddedildi.", "success")
    return redirect(url_for("main.action_detail", action_id=action.id))


@bp.route("/actions/<int:action_id>/delete", methods=["GET", "POST"])
@login_required
@permission_required("can_delete_actions")
def delete_action(action_id):
    action = Action.query.get_or_404(action_id)
    ensure_same_company(action)

    if request.method == "POST":
        for sub_action in list(action.sub_actions):
            delete_sub_action_evidence_file(sub_action)
        delete_uploaded_file(action)
        delete_closure_evidence_file(action)
        db.session.delete(action)
        db.session.commit()
        flash("Aksiyon kaydı silindi.", "success")
        return redirect(url_for("main.dashboard"))

    return render_template("confirm_delete.html", action=action)


@bp.get("/actions/<int:action_id>/download")
@login_required
def download_action_file(action_id):
    action = Action.query.get_or_404(action_id)
    ensure_same_company(action)
    if not can_view_action(action):
        abort(403)

    if not action.file_stored_name:
        flash("Bu kayda ait yüklenmiş dosya bulunamadı.", "warning")
        return redirect(url_for("main.dashboard"))

    return send_stored_upload(
        action.file_stored_name,
        as_attachment=True,
        download_name=action.file_original_name,
    )


@bp.get("/actions/<int:action_id>/closure-evidence/<int:file_id>/download")
@login_required
def download_closure_evidence_file(action_id, file_id):
    action = Action.query.get_or_404(action_id)
    ensure_same_company(action)
    if not can_view_action(action):
        abort(403)

    closure_file = ActionClosureFile.query.filter_by(
        id=file_id,
        action_id=action.id,
    ).first_or_404()

    return send_stored_upload(
        closure_file.stored_name,
        as_attachment=True,
        download_name=closure_file.original_name,
    )


@bp.get("/actions/<int:action_id>/closure-evidence/download")
@login_required
def download_latest_closure_evidence_file(action_id):
    action = Action.query.get_or_404(action_id)
    ensure_same_company(action)
    if not can_view_action(action):
        abort(403)

    if action.closure_files:
        closure_file = action.closure_files[-1]
        return redirect(
            url_for(
                "main.download_closure_evidence_file",
                action_id=action.id,
                file_id=closure_file.id,
            )
        )

    if not action.closure_file_stored_name:
        flash("Bu aksiyona ait kapanış kanıt dosyası bulunamadı.", "warning")
        return redirect(url_for("main.action_detail", action_id=action.id))

    return send_stored_upload(
        action.closure_file_stored_name,
        as_attachment=True,
        download_name=action.closure_file_original_name,
    )


@bp.route("/users")
@login_required
@permission_required("can_manage_users")
def users():
    user_list = active_users()
    return render_template(
        "users.html",
        users=user_list,
        can_delete_users=current_user_can("users.delete"),
    )


def apply_role_form_to_user(user):
    if not is_super_admin() or request.form.get("role_form_present") != "1":
        return

    selected_role_ids = {
        int(role_id)
        for role_id in request.form.getlist("role_ids")
        if role_id.isdigit()
    }
    roles = Role.query.filter(Role.id.in_(selected_role_ids)).all() if selected_role_ids else []
    if user.username == "superadmin":
        super_admin_role = Role.query.filter_by(key="super_admin").first()
        if super_admin_role and super_admin_role not in roles:
            roles.append(super_admin_role)
    user.roles = roles
    selected_extra_permissions = set(request.form.getlist("extra_permissions"))
    allowed_extra_permissions = {"quality.create"}
    selected_extra_permissions &= allowed_extra_permissions
    existing_extra_permissions = {
        permission.permission_key: permission for permission in user.extra_permissions
    }
    for permission_key in selected_extra_permissions:
        if permission_key not in existing_extra_permissions:
            user.extra_permissions.append(UserPermission(permission_key=permission_key))
    for permission in list(user.extra_permissions):
        if permission.permission_key in allowed_extra_permissions and (
            permission.permission_key not in selected_extra_permissions
        ):
            user.extra_permissions.remove(permission)
    sync_user_legacy_permissions(user)


@bp.route("/users/new", methods=["GET", "POST"])
@login_required
@permission_required("can_manage_users")
def create_user():
    if request.method == "POST":
        try:
            user = parse_user_form()
            apply_role_form_to_user(user)
            db.session.add(user)
            db.session.commit()
            flash("Kullanıcı oluşturuldu.", "success")
            return redirect(url_for("main.users"))
        except ValueError as error:
            flash_user_form_error(error)

    return render_template(
        "user_form.html",
        user=None,
        title="Yeni Kullanıcı",
        roles=role_hierarchy(),
        can_manage_roles=is_super_admin(),
        user_extra_permission_keys=user_extra_permission_keys,
    )


@bp.route("/users/<int:user_id>/edit", methods=["GET", "POST"])
@login_required
@permission_required("can_manage_users")
def edit_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.username == "superadmin" and not getattr(g, "current_user_is_super_admin", False):
        abort(403)
    if user.username != "superadmin":
        company_id = current_company_id()
        if company_id and user.company_id != company_id:
            abort(404)
        if not getattr(g, "current_user_is_super_admin", False) and user.company_id != company_id:
            abort(404)

    if request.method == "POST":
        try:
            parse_user_form(user)
            apply_role_form_to_user(user)
            db.session.commit()
            flash("Kullanıcı güncellendi.", "success")
            return redirect(url_for("main.users"))
        except ValueError as error:
            flash_user_form_error(error)

    return render_template(
        "user_form.html",
        user=user,
        title="Kullanıcı Düzenle",
        roles=role_hierarchy(),
        can_manage_roles=is_super_admin(),
        user_extra_permission_keys=user_extra_permission_keys,
    )


@bp.post("/users/<int:user_id>/delete")
@login_required
@permission_required("users.delete")
def delete_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == g.current_user.id:
        flash("Kendi kullanıcı hesabınızı silemezsiniz.", "danger")
        return redirect(url_for("main.users"))
    if user.username == "superadmin":
        flash("Süper Admin kullanıcısı silinemez.", "danger")
        return redirect(url_for("main.users"))

    company_id = current_company_id()
    if company_id and user.company_id != company_id:
        abort(404)
    if not getattr(g, "current_user_is_super_admin", False) and user.company_id != company_id:
        abort(404)

    original_username = user.username
    user.is_active = False
    user.username = f"silindi_{user.id}_{user.username}"[:80]
    user.email = None
    db.session.commit()
    flash(f"{original_username} kullanıcısı sistemden kaldırıldı.", "success")
    return redirect(url_for("main.users"))


@bp.route("/roles", methods=["GET", "POST"])
@login_required
@super_admin_required
def roles():
    if request.method == "POST":
        role_id = request.form.get("role_id", type=int)
        role = Role.query.get_or_404(role_id)
        permission_keys = set(request.form.getlist("permission_keys"))
        if role.key == "super_admin":
            from .seed import PERMISSION_CATALOG

            permission_keys = {item["key"] for item in PERMISSION_CATALOG}
        existing = {item.permission_key: item for item in role.permissions}
        for permission_key in permission_keys:
            if permission_key not in existing:
                role.permissions.append(RolePermission(permission_key=permission_key))
        for permission in list(role.permissions):
            if permission.permission_key not in permission_keys:
                role.permissions.remove(permission)

        for user in role.users:
            sync_user_legacy_permissions(user)

        db.session.commit()
        flash(f"{role.name} rol yetkileri güncellendi.", "success")
        return redirect(url_for("main.roles"))

    return render_template(
        "roles.html",
        roles=role_hierarchy(),
        permission_groups=permission_catalog_grouped(),
        users=User.query.order_by(User.full_name.asc()).all(),
        user_extra_permission_keys=user_extra_permission_keys,
    )


@bp.route("/companies")
@login_required
@super_admin_required
def companies():
    from .company_onboarding import company_workspace_status

    company_list = Company.query.order_by(Company.code.asc(), Company.id.asc()).all()
    company_stats = {}
    company_workspace = {}
    for company in company_list:
        company_stats[company.id] = {
            "users": User.query.filter_by(company_id=company.id).count(),
            "actions": Action.query.filter_by(company_id=company.id).count(),
            "dofs": Dof.query.filter_by(company_id=company.id).count(),
            "audits": InternalAudit.query.filter_by(company_id=company.id).count(),
            "documents": Document.query.filter_by(company_id=company.id).count(),
        }
        company_workspace[company.id] = company_workspace_status(company)
    return render_template(
        "companies.html",
        companies=company_list,
        company_stats=company_stats,
        company_workspace=company_workspace,
    )


@bp.route("/companies/new", methods=["GET", "POST"])
@login_required
@super_admin_required
def create_company():
    if request.method == "POST":
        try:
            from .company_onboarding import initialize_company_workspace

            company = parse_company_form()
            db.session.add(company)
            db.session.flush()
            initialize_company_workspace(company)
            sync_company_modules(company, selected_company_module_keys_from_form())
            db.session.commit()
            flash(f"{company.label} ÅŸirketi oluÅŸturuldu.", "success")
            return redirect(url_for("main.companies"))
        except ValueError as error:
            flash_company_form_error(error)

    return render_template(
        "company_form.html",
        company=None,
        title="Yeni Åirket",
        description="VolkaPortal iÃ§in boÅŸ baÅŸlayacak yeni bir firma oluÅŸturun.",
        form_action=url_for("main.create_company"),
        module_catalog=company_module_catalog(),
        module_state=company_module_form_state(None),
        submit_label="Åirketi Kaydet",
    )


@bp.route("/companies/<int:company_id>/edit", methods=["GET", "POST"])
@login_required
@super_admin_required
def edit_company(company_id):
    company = Company.query.get_or_404(company_id)

    if request.method == "POST":
        try:
            parse_company_form(company)
            sync_company_modules(company, selected_company_module_keys_from_form())
            db.session.commit()
            flash(f"{company.label} ÅŸirketi gÃ¼ncellendi.", "success")
            return redirect(url_for("main.companies"))
        except ValueError as error:
            flash_company_form_error(error)

    return render_template(
        "company_form.html",
        company=company,
        title="Åirket DÃ¼zenle",
        description=f"{company.label} kaydÄ±nÄ± gÃ¼ncelleyin.",
        form_action=url_for("main.edit_company", company_id=company.id),
        module_catalog=company_module_catalog(),
        module_state=company_module_form_state(company),
        submit_label="DeÄŸiÅŸiklikleri Kaydet",
    )


@bp.post("/roles/user-assignments")
@login_required
@super_admin_required
def update_user_roles():
    managed_user_ids = {
        int(user_id)
        for user_id in request.form.getlist("managed_user_ids")
        if user_id.isdigit()
    }
    if not managed_user_ids:
        flash("Güncellenecek kullanıcı seçimi bulunamadı.", "warning")
        return redirect(url_for("main.roles"))

    users = (
        User.query.filter(User.id.in_(managed_user_ids))
        .order_by(User.full_name.asc())
        .all()
    )
    all_roles = role_hierarchy()
    role_by_id = {role.id: role for role in all_roles}
    for user in users:
        selected_role_ids = {
            int(role_id)
            for role_id in request.form.getlist(f"user_{user.id}_roles")
            if role_id.isdigit()
        }
        if user.username == "superadmin":
            super_admin_role = next(
                (role for role in all_roles if role.key == "super_admin"),
                None,
            )
            if super_admin_role:
                selected_role_ids.add(super_admin_role.id)
        user.roles = [
            role_by_id[role_id]
            for role_id in selected_role_ids
            if role_id in role_by_id
        ]
        selected_extra_permissions = set(
            request.form.getlist(f"user_{user.id}_extra_permissions")
        )
        allowed_extra_permissions = {"quality.create"}
        selected_extra_permissions &= allowed_extra_permissions
        existing_extra_permissions = {
            permission.permission_key: permission for permission in user.extra_permissions
        }
        for permission_key in selected_extra_permissions:
            if permission_key not in existing_extra_permissions:
                user.extra_permissions.append(
                    UserPermission(permission_key=permission_key)
                )
        for permission in list(user.extra_permissions):
            if permission.permission_key in allowed_extra_permissions and (
                permission.permission_key not in selected_extra_permissions
            ):
                user.extra_permissions.remove(permission)
        sync_user_legacy_permissions(user)
    db.session.commit()
    flash("Kullanıcı rol atamaları güncellendi.", "success")
    return redirect(url_for("main.roles"))
