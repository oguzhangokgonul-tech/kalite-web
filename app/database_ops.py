from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import sqlite3

from flask import current_app
from sqlalchemy.engine import make_url

from .extensions import db
from .models import AuditLog


class DatabaseOperationError(RuntimeError):
    pass


@dataclass(frozen=True)
class DatabaseCheckResult:
    source_path: Path
    size_bytes: int
    quick_check: str
    integrity_check: str
    alembic_version: str
    expected_revision: str

    @property
    def is_ok(self):
        return self.quick_check.lower() == "ok" and self.integrity_check.lower() == "ok"

    @property
    def migration_warning(self):
        if not self.alembic_version or not self.expected_revision:
            return False
        return self.alembic_version != self.expected_revision


@dataclass(frozen=True)
class DatabaseBackupResult:
    source_path: Path
    backup_path: Path
    size_bytes: int
    quick_check: str
    integrity_check: str


def sqlite_database_path(database_uri=None):
    database_uri = database_uri or current_app.config.get("SQLALCHEMY_DATABASE_URI")
    if not database_uri:
        return None

    url = make_url(database_uri)
    if not url.drivername.startswith("sqlite"):
        return None
    if not url.database or url.database == ":memory:":
        return None
    return Path(url.database).expanduser().resolve()


def configured_backup_dir(output_dir=None):
    if output_dir:
        return Path(output_dir).expanduser().resolve()

    configured = current_app.config.get("DATABASE_BACKUP_DIR")
    if configured:
        return Path(configured).expanduser().resolve()

    data_dir = current_app.config.get("DATA_DIR") or current_app.instance_path
    return (Path(data_dir) / "backups").expanduser().resolve()


def configured_keep_last(keep_last=None):
    if keep_last is not None:
        return int(keep_last)
    return int(current_app.config.get("DATABASE_BACKUP_KEEP_LAST", 20))


def _timestamp(now=None):
    return (now or datetime.now()).strftime("%Y%m%d-%H%M%S")


def _sqlite_pragma_check(pragma_name, database_path=None, database_uri=None):
    path = Path(database_path).resolve() if database_path else sqlite_database_path(database_uri)
    if path is None:
        raise DatabaseOperationError("Bu komut sadece dosya tabanli SQLite icin calisir.")
    if not path.exists():
        raise DatabaseOperationError(f"Veritabani dosyasi bulunamadi: {path}")

    connection = sqlite3.connect(path)
    try:
        result = connection.execute(f"PRAGMA {pragma_name}").fetchone()
    finally:
        connection.close()
    return result[0] if result else "unknown"


def sqlite_quick_check(database_path=None, database_uri=None):
    return _sqlite_pragma_check("quick_check", database_path, database_uri)


def sqlite_integrity_check(database_path=None, database_uri=None):
    return _sqlite_pragma_check("integrity_check", database_path, database_uri)


def sqlite_alembic_version(database_path=None, database_uri=None):
    path = Path(database_path).resolve() if database_path else sqlite_database_path(database_uri)
    if path is None or not path.exists():
        return ""

    connection = sqlite3.connect(path)
    try:
        table_exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='alembic_version'"
        ).fetchone()
        if not table_exists:
            return ""
        rows = connection.execute(
            "SELECT version_num FROM alembic_version ORDER BY version_num"
        ).fetchall()
    finally:
        connection.close()
    return ", ".join(row[0] for row in rows if row and row[0])


def expected_alembic_revision():
    versions_dir = Path(current_app.root_path).parent / "migrations" / "versions"
    if not versions_dir.exists():
        return ""
    revisions = []
    for path in versions_dir.glob("*.py"):
        if path.name.startswith("__"):
            continue
        revision = path.stem.split("_", 1)[0]
        if revision:
            revisions.append(revision)
    return sorted(revisions)[-1] if revisions else ""


def sqlite_health_check(database_uri=None):
    source_path = sqlite_database_path(database_uri)
    if source_path is None:
        raise DatabaseOperationError("Bu komut sadece dosya tabanli SQLite icin calisir.")
    if not source_path.exists():
        raise DatabaseOperationError(f"Veritabani dosyasi bulunamadi: {source_path}")

    return DatabaseCheckResult(
        source_path=source_path,
        size_bytes=source_path.stat().st_size,
        quick_check=sqlite_quick_check(database_path=source_path),
        integrity_check=sqlite_integrity_check(database_path=source_path),
        alembic_version=sqlite_alembic_version(database_path=source_path),
        expected_revision=expected_alembic_revision(),
    )


def prune_sqlite_backups(output_dir=None, keep_last=None, source_stem=None):
    backup_dir = configured_backup_dir(output_dir)
    if not backup_dir.exists():
        return []

    pattern = f"{source_stem}-*.sqlite3" if source_stem else "*.sqlite3"
    backups = sorted(
        backup_dir.glob(pattern),
        key=lambda path: (path.stat().st_mtime, path.name),
        reverse=True,
    )
    keep = max(configured_keep_last(keep_last), 0)
    if keep == 0:
        stale_backups = backups
    else:
        stale_backups = backups[keep:]

    removed = []
    for path in stale_backups:
        path.unlink(missing_ok=True)
        removed.append(path)
    return removed


def create_sqlite_backup(database_uri=None, output_dir=None, now=None, keep_last=None):
    source_path = sqlite_database_path(database_uri)
    if source_path is None:
        raise DatabaseOperationError("Bu komut sadece dosya tabanli SQLite icin calisir.")
    if not source_path.exists():
        raise DatabaseOperationError(f"Veritabani dosyasi bulunamadi: {source_path}")

    backup_dir = configured_backup_dir(output_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)

    backup_path = backup_dir / f"{source_path.stem}-{_timestamp(now)}.sqlite3"
    source = sqlite3.connect(source_path)
    target = sqlite3.connect(backup_path)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()

    quick = sqlite_quick_check(database_path=backup_path)
    integrity = sqlite_integrity_check(database_path=backup_path)
    if quick.lower() != "ok" or integrity.lower() != "ok":
        backup_path.unlink(missing_ok=True)
        raise DatabaseOperationError(
            f"Yedek butunluk kontrolu basarisiz: quick={quick}, integrity={integrity}"
        )

    prune_sqlite_backups(
        output_dir=backup_dir,
        keep_last=keep_last,
        source_stem=source_path.stem,
    )

    return DatabaseBackupResult(
        source_path=source_path,
        backup_path=backup_path,
        size_bytes=backup_path.stat().st_size,
        quick_check=quick,
        integrity_check=integrity,
    )


def record_database_audit(action, summary, details=None):
    audit_log = AuditLog(
        company_id=None,
        user_id=None,
        entity_type="DatabaseSafety",
        entity_id=None,
        action=action,
        summary=summary[:255],
        new_values=json.dumps(details or {}, ensure_ascii=False, sort_keys=True),
    )
    try:
        db.session.add(audit_log)
        db.session.commit()
        return audit_log
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Veritabani guvenlik audit kaydi yazilamadi.")
        return None
