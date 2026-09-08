from collections import Counter, deque
from datetime import datetime
from pathlib import Path
import re
import shutil

from flask import current_app
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from .company_onboarding import company_workspace_status
from .database_ops import (
    configured_full_backup_dir,
    configured_full_keep_last,
    list_full_backups,
    sqlite_database_path,
)
from .extensions import db
from .models import (
    Action,
    AuditLog,
    Company,
    CompanyModule,
    Document,
    Dof,
    InternalAudit,
    Notification,
    User,
)


LOG_ERROR_KEYWORDS = (
    "error",
    "exception",
    "traceback",
    "critical",
    "failed",
    "fatal",
    "500",
    "502",
)
SECRET_LINE_PATTERNS = (
    re.compile(
        r"(?i)(password|token|secret|api[_-]?key|authorization|cookie)"
        r"(\s*[:=]\s*)([^\s,;]+)"
    ),
    re.compile(r"(?i)(Password for '[^']+':)\s*.*"),
)
SYSTEM_ADMIN_PACKAGE_LABELS = {
    "iso_core": "ISO 9001 KYS Çekirdek",
    "production_plus": "Üretim Plus",
    "custom": "Özel Paket",
}


def safe_count(query):
    try:
        return query.count()
    except SQLAlchemyError:
        db.session.rollback()
        return 0


def format_storage_size(size_bytes):
    try:
        size_bytes = int(size_bytes or 0)
    except (TypeError, ValueError):
        size_bytes = 0
    if size_bytes >= 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"
    if size_bytes >= 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    if size_bytes >= 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes} B"


def format_admin_datetime(value):
    if not value:
        return "-"
    if isinstance(value, datetime):
        return value.strftime("%d.%m.%Y %H:%M")
    return str(value)


def upload_root_path():
    configured = current_app.config.get("UPLOAD_FOLDER") or current_app.instance_path
    return Path(configured).expanduser().resolve()


def file_size_or_zero(path):
    try:
        return path.stat().st_size if path and path.exists() and path.is_file() else 0
    except OSError:
        return 0


def folder_size_bytes(path):
    if not path:
        return 0
    try:
        if not path.exists():
            return 0
    except OSError:
        return 0

    total = 0
    try:
        for item in path.rglob("*"):
            try:
                if item.is_symlink():
                    continue
            except OSError:
                continue
            total += file_size_or_zero(item)
    except OSError:
        return total
    return total


def company_storage_folder(company_id):
    if not company_id:
        return None
    upload_root = upload_root_path()
    folder = (upload_root / f"company-{company_id:03d}").resolve()
    try:
        folder.relative_to(upload_root)
    except ValueError:
        return None
    return folder


def company_storage_quota_bytes(company):
    quota_mb = getattr(company, "storage_quota_mb", None)
    try:
        quota_mb = int(quota_mb) if quota_mb is not None else None
    except (TypeError, ValueError):
        return None
    if not quota_mb or quota_mb < 1:
        return None
    return quota_mb * 1024 * 1024


def company_storage_summary(company):
    used_bytes = folder_size_bytes(company_storage_folder(company.id))
    quota_bytes = company_storage_quota_bytes(company)
    percent = None
    if quota_bytes:
        percent = min(100, round((used_bytes / quota_bytes) * 100))
    return {
        "used_bytes": used_bytes,
        "quota_bytes": quota_bytes,
        "used_label": format_storage_size(used_bytes),
        "quota_label": format_storage_size(quota_bytes) if quota_bytes else "Limitsiz",
        "percent": percent,
        "near_limit": percent is not None and percent >= 80,
    }


def company_user_limit(company):
    limit = getattr(company, "user_limit", None)
    try:
        limit = int(limit) if limit is not None else None
    except (TypeError, ValueError):
        return None
    return limit if limit and limit > 0 else None


def company_last_activity(company):
    try:
        latest_audit = (
            AuditLog.query.filter_by(company_id=company.id)
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .first()
        )
    except SQLAlchemyError:
        db.session.rollback()
        latest_audit = None
    values = [
        getattr(company, "updated_at", None),
        getattr(company, "created_at", None),
        getattr(latest_audit, "created_at", None),
    ]
    values = [value for value in values if value]
    return max(values) if values else None


def safe_workspace_status(company):
    try:
        return company_workspace_status(company)
    except Exception:
        db.session.rollback()
        return {
            "missing_keys": [],
            "departments_ready": False,
            "document_categories_ready": False,
        }


def system_admin_package_label(package_key):
    return SYSTEM_ADMIN_PACKAGE_LABELS.get(
        str(package_key or "").strip(),
        SYSTEM_ADMIN_PACKAGE_LABELS["iso_core"],
    )


def company_admin_rows():
    rows = []
    companies = Company.query.order_by(Company.code.asc(), Company.id.asc()).all()
    for company in companies:
        active_users = safe_count(
            User.query.filter_by(company_id=company.id, is_active=True)
        )
        total_users = safe_count(User.query.filter_by(company_id=company.id))
        user_limit = company_user_limit(company)
        user_percent = min(100, round((active_users / user_limit) * 100)) if user_limit else None
        storage = company_storage_summary(company)
        workspace = safe_workspace_status(company)
        missing_keys = workspace.get("missing_keys", [])
        setup_missing = (
            missing_keys
            or not workspace.get("departments_ready")
            or not workspace.get("document_categories_ready")
        )
        module_count = safe_count(
            CompanyModule.query.filter_by(company_id=company.id, is_enabled=True)
        )
        rows.append(
            {
                "company": company,
                "status_label": "Aktif" if company.is_active else "Pasif",
                "data_label": "Demo" if company.is_demo else "Gerçek",
                "package_label": system_admin_package_label(company.package_key),
                "active_users": active_users,
                "total_users": total_users,
                "user_limit": user_limit,
                "user_limit_label": str(user_limit) if user_limit else "Limitsiz",
                "user_percent": user_percent,
                "user_near_limit": user_percent is not None and user_percent >= 80,
                "storage": storage,
                "module_count": module_count,
                "setup_ready": not setup_missing,
                "actions": safe_count(Action.query.filter_by(company_id=company.id)),
                "dofs": safe_count(Dof.query.filter_by(company_id=company.id)),
                "audits": safe_count(InternalAudit.query.filter_by(company_id=company.id)),
                "documents": safe_count(Document.query.filter_by(company_id=company.id)),
                "last_activity_label": format_admin_datetime(company_last_activity(company)),
            }
        )
    return rows


def disk_usage_summary():
    upload_root = upload_root_path()
    try:
        upload_root.mkdir(parents=True, exist_ok=True)
        disk = shutil.disk_usage(upload_root)
        return {
            "available": True,
            "path": str(upload_root),
            "used_bytes": disk.used,
            "free_bytes": disk.free,
            "total_bytes": disk.total,
            "used_label": format_storage_size(disk.used),
            "free_label": format_storage_size(disk.free),
            "total_label": format_storage_size(disk.total),
            "percent": round((disk.used / disk.total) * 100) if disk.total else 0,
        }
    except OSError as error:
        return {
            "available": False,
            "path": str(upload_root),
            "error": str(error),
            "used_label": "-",
            "free_label": "-",
            "total_label": "-",
            "percent": 0,
        }


def database_health_summary():
    try:
        db.session.execute(text("SELECT 1")).scalar()
        reachable = True
    except SQLAlchemyError as error:
        db.session.rollback()
        return {
            "label": "Erişilemiyor",
            "tone": "danger",
            "detail": str(error),
            "size_label": "-",
            "path_label": "-",
        }

    db_path = sqlite_database_path()
    size_label = "-"
    path_label = "Harici veritabanı"
    if db_path is not None:
        path_label = db_path.name
        size_label = format_storage_size(file_size_or_zero(db_path))
    return {
        "label": "Erişilebilir" if reachable else "Erişilemiyor",
        "tone": "success" if reachable else "danger",
        "detail": path_label,
        "size_label": size_label,
        "path_label": path_label,
    }


def latest_email_sent_at():
    try:
        notification = (
            Notification.query.filter(Notification.email_sent_at.isnot(None))
            .order_by(Notification.email_sent_at.desc(), Notification.id.desc())
            .first()
        )
    except SQLAlchemyError:
        db.session.rollback()
        return None
    return notification.email_sent_at if notification else None


def mail_health_summary():
    enabled = bool(current_app.config.get("MAIL_ENABLED"))
    suppressed = bool(current_app.config.get("MAIL_SUPPRESS_SEND"))
    server = current_app.config.get("MAIL_SERVER") or ""
    sender = current_app.config.get("MAIL_DEFAULT_SENDER") or ""
    password = current_app.config.get("MAIL_PASSWORD") or ""
    missing = [
        name
        for name, value in (
            ("MAIL_SERVER", server),
            ("MAIL_DEFAULT_SENDER", sender),
            ("MAIL_PASSWORD", password),
        )
        if enabled and not value
    ]
    if not enabled:
        label, tone = "Pasif", "muted"
    elif suppressed:
        label, tone = "Test Modu", "warning"
    elif missing:
        label, tone = "Eksik Ayar", "danger"
    else:
        label, tone = "Aktif", "success"
    return {
        "label": label,
        "tone": tone,
        "enabled": enabled,
        "suppressed": suppressed,
        "server": server or "-",
        "port": current_app.config.get("MAIL_PORT") or "-",
        "tls": "TLS" if current_app.config.get("MAIL_USE_TLS") else "TLS kapalı",
        "ssl": "SSL" if current_app.config.get("MAIL_USE_SSL") else "SSL kapalı",
        "sender": sender or "-",
        "reply_to": current_app.config.get("MAIL_REPLY_TO") or "-",
        "missing": missing,
        "last_sent_label": format_admin_datetime(latest_email_sent_at()),
    }


def backup_health_summary():
    try:
        backups = list_full_backups()
        backup_dir = configured_full_backup_dir()
        keep_last = configured_full_keep_last()
    except Exception as error:
        return {
            "label": "Kontrol Edilemedi",
            "tone": "danger",
            "directory": "-",
            "keep_last": "-",
            "count": 0,
            "latest_name": "-",
            "latest_label": "-",
            "latest_size_label": "-",
            "error": str(error),
        }

    latest = backups[0] if backups else None
    latest_label = "-"
    latest_size_label = "-"
    if latest is not None:
        try:
            stat = latest.stat()
            latest_label = datetime.fromtimestamp(stat.st_mtime).strftime(
                "%d.%m.%Y %H:%M"
            )
            latest_size_label = format_storage_size(stat.st_size)
        except OSError:
            latest_label = "-"
    return {
        "label": "Var" if latest is not None else "Yok",
        "tone": "success" if latest is not None else "warning",
        "directory": str(backup_dir),
        "keep_last": keep_last,
        "count": len(backups),
        "latest_name": latest.name if latest is not None else "-",
        "latest_label": latest_label,
        "latest_size_label": latest_size_label,
    }


def app_log_candidates():
    app_root = Path(current_app.root_path).resolve().parent
    data_dir = Path(current_app.config.get("DATA_DIR") or current_app.instance_path)
    data_dir = data_dir.expanduser().resolve()
    return (
        app_root / "flask-server.err.log",
        app_root / "flask-server.out.log",
        data_dir / "logs" / "app.log",
        data_dir / "logs" / "error.log",
    )


def read_tail_lines(path, max_lines=120, max_bytes=200 * 1024):
    path = Path(path)
    try:
        if not path.exists() or not path.is_file():
            return []
        size = path.stat().st_size
        with path.open("rb") as handle:
            if size > max_bytes:
                handle.seek(-max_bytes, 2)
            content = handle.read()
    except OSError:
        return []

    lines = content.decode("utf-8", errors="replace").splitlines()
    return list(deque(lines, maxlen=max_lines))


def sanitize_admin_log_line(line):
    value = str(line or "").strip()
    for pattern in SECRET_LINE_PATTERNS:
        if pattern.pattern.startswith("(?i)(Password for"):
            value = pattern.sub(r"\1 ***", value)
        else:
            value = pattern.sub(r"\1\2***", value)
    return value[:500]


def recent_error_log_lines(limit=12):
    rows = []
    for path in app_log_candidates():
        for line in read_tail_lines(path):
            lowered = line.lower()
            if any(keyword in lowered for keyword in LOG_ERROR_KEYWORDS):
                rows.append(
                    {
                        "source": path.name,
                        "message": sanitize_admin_log_line(line),
                    }
                )
    return rows[-limit:][::-1]


def latest_audit_summary(limit=5):
    try:
        audits = (
            AuditLog.query.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .limit(limit)
            .all()
        )
    except SQLAlchemyError:
        db.session.rollback()
        return []

    return [
        {
            "summary": audit.summary or audit.action,
            "entity": audit.entity_type,
            "actor": audit.user.full_name if audit.user else "Sistem",
            "created_at_label": format_admin_datetime(audit.created_at),
        }
        for audit in audits
    ]


def system_admin_context():
    company_rows = company_admin_rows()
    company_count = len(company_rows)
    active_company_count = sum(1 for row in company_rows if row["company"].is_active)
    demo_company_count = sum(1 for row in company_rows if row["company"].is_demo)
    passive_company_count = company_count - active_company_count
    active_user_total = sum(row["active_users"] for row in company_rows)
    total_user_count = sum(row["total_users"] for row in company_rows)
    total_storage_used = sum(row["storage"]["used_bytes"] for row in company_rows)
    quota_values = [
        row["storage"]["quota_bytes"]
        for row in company_rows
        if row["storage"]["quota_bytes"]
    ]
    total_storage_quota = sum(quota_values) if quota_values else None
    package_counts = Counter(row["package_label"] for row in company_rows)
    user_limit_risk_count = sum(1 for row in company_rows if row["user_near_limit"])
    storage_risk_count = sum(1 for row in company_rows if row["storage"]["near_limit"])
    backup = backup_health_summary()
    disk = disk_usage_summary()
    mail = mail_health_summary()
    database = database_health_summary()
    return {
        "company_rows": company_rows,
        "package_counts": package_counts,
        "metrics": [
            {
                "label": "Toplam Firma",
                "value": company_count,
                "subtitle": f"{active_company_count} aktif, {passive_company_count} pasif",
                "icon": "bi-buildings",
                "tone": "primary",
            },
            {
                "label": "Aktif Kullanıcı",
                "value": active_user_total,
                "subtitle": f"{total_user_count} toplam hesap",
                "icon": "bi-people",
                "tone": "success",
            },
            {
                "label": "Dosya Kullanımı",
                "value": format_storage_size(total_storage_used),
                "subtitle": (
                    f"{format_storage_size(total_storage_quota)} kota"
                    if total_storage_quota
                    else "Firma kotasi limitsiz"
                ),
                "icon": "bi-hdd",
                "tone": "info",
            },
            {
                "label": "Son Tam Yedek",
                "value": backup["latest_label"],
                "subtitle": f"{backup['count']} yedek kaydi",
                "icon": "bi-cloud-check",
                "tone": backup["tone"],
            },
        ],
        "totals": {
            "company_count": company_count,
            "active_company_count": active_company_count,
            "passive_company_count": passive_company_count,
            "demo_company_count": demo_company_count,
            "active_user_total": active_user_total,
            "user_limit_risk_count": user_limit_risk_count,
            "storage_risk_count": storage_risk_count,
            "total_storage_used_label": format_storage_size(total_storage_used),
        },
        "disk": disk,
        "mail": mail,
        "backup": backup,
        "database": database,
        "recent_error_rows": recent_error_log_lines(),
        "latest_audit_rows": latest_audit_summary(),
    }
