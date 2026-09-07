from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import tempfile
from typing import Optional, Tuple
import zipfile

from flask import current_app
from sqlalchemy.engine import make_url

from .extensions import db
from .models import AuditLog, Company, User


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


@dataclass(frozen=True)
class FullBackupResult:
    source_path: Path
    backup_path: Path
    size_bytes: int
    database_size_bytes: int
    upload_file_count: int
    upload_total_bytes: int
    quick_check: str
    integrity_check: str


@dataclass(frozen=True)
class BackupValidationResult:
    backup_path: Path
    is_ok: bool
    issues: Tuple[str, ...]
    manifest: dict
    database_archive_path: str
    quick_check: str
    integrity_check: str
    checksum_count: int
    upload_file_count: int
    total_bytes: int


@dataclass(frozen=True)
class RestoreBackupResult:
    backup_path: Path
    dry_run: bool
    applied: bool
    pre_restore_backup_path: Optional[Path]
    restored_database_path: Optional[Path]
    restored_upload_files: int
    quick_check: str
    integrity_check: str
    issues: Tuple[str, ...]


FULL_BACKUP_FORMAT = "volkaportal-full-backup-v1"
FULL_BACKUP_CONFIRMATION_TEXT = "RESTORE_CANLI_VERIYI_EZER"
FULL_BACKUP_FILE_PREFIX = "volkaportal-backup-"


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


def configured_full_backup_dir(output_dir=None):
    if output_dir:
        return Path(output_dir).expanduser().resolve()

    configured = current_app.config.get("FULL_BACKUP_DIR")
    if configured:
        return Path(configured).expanduser().resolve()

    return configured_backup_dir() / "full"


def configured_keep_last(keep_last=None):
    if keep_last is not None:
        return int(keep_last)
    return int(current_app.config.get("DATABASE_BACKUP_KEEP_LAST", 20))


def configured_full_keep_last(keep_last=None):
    if keep_last is not None:
        return int(keep_last)
    return int(current_app.config.get("FULL_BACKUP_KEEP_LAST", 10))


def backup_include_uploads(include_uploads=None):
    if include_uploads is not None:
        return bool(include_uploads)
    return bool(current_app.config.get("BACKUP_INCLUDE_UPLOADS", True))


def restore_is_enabled():
    return bool(current_app.config.get("RESTORE_ENABLED", False))


def _timestamp(now=None):
    return (now or datetime.now()).strftime("%Y%m%d-%H%M%S")


def _unique_backup_path(path):
    path = Path(path)
    if not path.exists():
        return path
    for counter in range(1, 1000):
        candidate = path.with_name(f"{path.stem}-{counter}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise DatabaseOperationError(f"Benzersiz yedek dosya adi olusturulamadi: {path}")


def _sha256_path(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_zip_member(archive, member_name):
    digest = hashlib.sha256()
    size = 0
    with archive.open(member_name, "r") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _json_bytes(payload):
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2).encode(
        "utf-8"
    )


def _safe_zip_member_name(name):
    if not name or "\\" in name:
        return False
    posix_path = PurePosixPath(name)
    return (
        not posix_path.is_absolute()
        and all(part not in {"", ".", ".."} for part in posix_path.parts)
    )


def _add_zip_file(archive, source_path, archive_path, checksum_entries):
    archive_path = archive_path.replace("\\", "/")
    if not _safe_zip_member_name(archive_path):
        raise DatabaseOperationError(f"Gecersiz yedek dosya yolu: {archive_path}")
    source_path = Path(source_path)
    archive.write(source_path, archive_path)
    checksum_entries.append(
        {
            "path": archive_path,
            "size_bytes": source_path.stat().st_size,
            "sha256": _sha256_path(source_path),
        }
    )


def _add_zip_bytes(archive, archive_path, content, checksum_entries):
    archive_path = archive_path.replace("\\", "/")
    if not _safe_zip_member_name(archive_path):
        raise DatabaseOperationError(f"Gecersiz yedek dosya yolu: {archive_path}")
    archive.writestr(archive_path, content)
    checksum_entries.append(
        {
            "path": archive_path,
            "size_bytes": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
        }
    )


def _extract_zip_member(archive, member_name, target_path):
    if not _safe_zip_member_name(member_name):
        raise DatabaseOperationError(f"Gecersiz yedek dosya yolu: {member_name}")
    target_path = Path(target_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    with archive.open(member_name, "r") as source, target_path.open("wb") as target:
        shutil.copyfileobj(source, target)


def _backup_events_log_path():
    backup_dir = configured_backup_dir()
    backup_dir.mkdir(parents=True, exist_ok=True)
    return backup_dir / "restore-events.log"


def append_backup_event(action, details=None):
    entry = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "action": action,
        "details": details or {},
    }
    path = _backup_events_log_path()
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
    return path


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


def prune_full_backups(output_dir=None, keep_last=None):
    backup_dir = configured_full_backup_dir(output_dir)
    if not backup_dir.exists():
        return []

    backups = sorted(
        backup_dir.glob(f"{FULL_BACKUP_FILE_PREFIX}*.zip"),
        key=lambda path: (path.stat().st_mtime, path.name),
        reverse=True,
    )
    keep = max(configured_full_keep_last(keep_last), 0)
    stale_backups = backups if keep == 0 else backups[keep:]

    removed = []
    for path in stale_backups:
        path.unlink(missing_ok=True)
        removed.append(path)
    return removed


def list_full_backups(output_dir=None):
    backup_dir = configured_full_backup_dir(output_dir)
    if not backup_dir.exists():
        return []
    return sorted(
        backup_dir.glob(f"{FULL_BACKUP_FILE_PREFIX}*.zip"),
        key=lambda path: (path.stat().st_mtime, path.name),
        reverse=True,
    )


def full_backup_path_from_name(name, output_dir=None):
    backup_dir = configured_full_backup_dir(output_dir)
    backup_path = (backup_dir / str(name or "")).resolve()
    if (
        backup_path.parent != backup_dir
        or not backup_path.name.startswith(FULL_BACKUP_FILE_PREFIX)
        or backup_path.suffix.lower() != ".zip"
    ):
        return None
    return backup_path


def _company_backup_summary(checksum_entries):
    upload_entries = checksum_entries or []
    summaries = []
    try:
        companies = Company.query.order_by(Company.id.asc()).all()
    except Exception:
        db.session.rollback()
        return summaries

    for company in companies:
        prefix = f"uploads/company-{company.id:03d}/"
        company_files = [
            entry
            for entry in upload_entries
            if str(entry.get("path", "")).startswith(prefix)
        ]
        try:
            user_count = User.query.filter_by(company_id=company.id).count()
        except Exception:
            db.session.rollback()
            user_count = 0
        summaries.append(
            {
                "id": company.id,
                "code": company.code,
                "name": company.name,
                "slug": company.slug,
                "file_count": len(company_files),
                "file_total_bytes": sum(
                    int(entry.get("size_bytes") or 0) for entry in company_files
                ),
                "user_count": user_count,
            }
        )
    return summaries


def _copy_sqlite_database(source_path, target_path):
    source = sqlite3.connect(source_path)
    target = sqlite3.connect(target_path)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()


def create_full_backup(
    database_uri=None,
    output_dir=None,
    now=None,
    keep_last=None,
    include_uploads=None,
):
    source_path = sqlite_database_path(database_uri)
    if source_path is None:
        raise DatabaseOperationError("Bu komut sadece dosya tabanli SQLite icin calisir.")
    if not source_path.exists():
        raise DatabaseOperationError(f"Veritabani dosyasi bulunamadi: {source_path}")

    created_at = now or datetime.now()
    backup_dir = configured_full_backup_dir(output_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = _unique_backup_path(
        backup_dir / f"{FULL_BACKUP_FILE_PREFIX}{_timestamp(created_at)}.zip"
    )
    include_uploads = backup_include_uploads(include_uploads)
    upload_root = Path(current_app.config.get("UPLOAD_FOLDER", "")).expanduser().resolve()

    with tempfile.TemporaryDirectory(prefix="volkaportal-full-backup-") as temp_dir:
        temp_dir = Path(temp_dir)
        database_copy = temp_dir / source_path.name
        _copy_sqlite_database(source_path, database_copy)

        quick = sqlite_quick_check(database_path=database_copy)
        integrity = sqlite_integrity_check(database_path=database_copy)
        if quick.lower() != "ok" or integrity.lower() != "ok":
            raise DatabaseOperationError(
                f"Yedek veritabani kontrolu basarisiz: quick={quick}, integrity={integrity}"
            )
        database_size_bytes = database_copy.stat().st_size

        checksum_entries = []
        upload_file_count = 0
        upload_total_bytes = 0
        database_archive_path = f"database/{source_path.name}"

        with zipfile.ZipFile(backup_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            _add_zip_file(
                archive,
                database_copy,
                database_archive_path,
                checksum_entries,
            )

            if include_uploads and upload_root.exists():
                for upload_path in sorted(upload_root.rglob("*")):
                    if not upload_path.is_file():
                        continue
                    archive_name = (
                        "uploads/"
                        + upload_path.relative_to(upload_root).as_posix()
                    )
                    _add_zip_file(archive, upload_path, archive_name, checksum_entries)
                    upload_file_count += 1
                    upload_total_bytes += upload_path.stat().st_size

            manifest = {
                "format": FULL_BACKUP_FORMAT,
                "created_at": created_at.isoformat(timespec="seconds"),
                "site_name": current_app.config.get("SITE_NAME", "VolkaPortal"),
                "app_env": current_app.config.get("APP_ENV", ""),
                "database": {
                    "source_path": str(source_path),
                    "archive_path": database_archive_path,
                    "size_bytes": database_copy.stat().st_size,
                    "quick_check": quick,
                    "integrity_check": integrity,
                    "alembic_version": sqlite_alembic_version(
                        database_path=database_copy
                    ),
                    "expected_revision": expected_alembic_revision(),
                },
                "uploads": {
                    "included": include_uploads,
                    "source_path": str(upload_root),
                    "archive_prefix": "uploads/",
                    "file_count": upload_file_count,
                    "total_bytes": upload_total_bytes,
                },
                "companies": _company_backup_summary(checksum_entries),
                "checksum_file": "checksums.json",
            }
            _add_zip_bytes(archive, "manifest.json", _json_bytes(manifest), checksum_entries)
            archive.writestr(
                "checksums.json",
                _json_bytes(
                    {
                        "format": FULL_BACKUP_FORMAT,
                        "files": checksum_entries,
                    }
                ),
            )

    prune_full_backups(output_dir=backup_dir, keep_last=keep_last)
    append_backup_event(
        "full_backup_created",
        {
            "backup_path": str(backup_path),
            "source_path": str(source_path),
            "size_bytes": backup_path.stat().st_size,
            "upload_file_count": upload_file_count,
        },
    )

    return FullBackupResult(
        source_path=source_path,
        backup_path=backup_path,
        size_bytes=backup_path.stat().st_size,
        database_size_bytes=database_size_bytes,
        upload_file_count=upload_file_count,
        upload_total_bytes=upload_total_bytes,
        quick_check=quick,
        integrity_check=integrity,
    )


def _empty_validation_result(backup_path, issues):
    return BackupValidationResult(
        backup_path=Path(backup_path).expanduser().resolve(),
        is_ok=False,
        issues=tuple(issues),
        manifest={},
        database_archive_path="",
        quick_check="",
        integrity_check="",
        checksum_count=0,
        upload_file_count=0,
        total_bytes=0,
    )


def validate_backup_package(backup_path):
    backup_path = Path(backup_path).expanduser().resolve()
    issues = []
    if not backup_path.exists():
        return _empty_validation_result(backup_path, ["Yedek dosyasi bulunamadi."])

    try:
        with zipfile.ZipFile(backup_path, "r") as archive:
            names = [name for name in archive.namelist() if not name.endswith("/")]
            names_set = set(names)
            for name in names:
                if not _safe_zip_member_name(name):
                    issues.append(f"Gecersiz zip yolu: {name}")

            if "manifest.json" not in names_set:
                issues.append("manifest.json bulunamadi.")
                return _empty_validation_result(backup_path, issues)
            if "checksums.json" not in names_set:
                issues.append("checksums.json bulunamadi.")
                return _empty_validation_result(backup_path, issues)

            try:
                manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                return _empty_validation_result(backup_path, ["manifest.json okunamadi."])

            try:
                checksum_payload = json.loads(
                    archive.read("checksums.json").decode("utf-8")
                )
            except (UnicodeDecodeError, json.JSONDecodeError):
                return _empty_validation_result(backup_path, ["checksums.json okunamadi."])

            if manifest.get("format") != FULL_BACKUP_FORMAT:
                issues.append("Yedek formati desteklenmiyor.")

            checksum_entries = checksum_payload.get("files")
            if not isinstance(checksum_entries, list):
                issues.append("Checksum listesi gecersiz.")
                checksum_entries = []

            total_bytes = 0
            for entry in checksum_entries:
                member_name = str(entry.get("path", ""))
                expected_hash = str(entry.get("sha256", ""))
                expected_size = int(entry.get("size_bytes") or 0)
                if not _safe_zip_member_name(member_name):
                    issues.append(f"Gecersiz checksum yolu: {member_name}")
                    continue
                if member_name not in names_set:
                    issues.append(f"Checksum dosyasi zip icinde yok: {member_name}")
                    continue
                actual_hash, actual_size = _sha256_zip_member(archive, member_name)
                total_bytes += actual_size
                if actual_size != expected_size:
                    issues.append(f"Dosya boyutu uyusmuyor: {member_name}")
                if actual_hash != expected_hash:
                    issues.append(f"Checksum uyusmuyor: {member_name}")

            database_archive_path = str(
                (manifest.get("database") or {}).get("archive_path") or ""
            )
            if not _safe_zip_member_name(database_archive_path):
                issues.append("Veritabani yedek yolu gecersiz.")
            elif database_archive_path not in names_set:
                issues.append("Veritabani yedegi paket icinde bulunamadi.")

            quick = ""
            integrity = ""
            if database_archive_path in names_set:
                with tempfile.TemporaryDirectory(prefix="volkaportal-backup-verify-") as temp_dir:
                    database_copy = Path(temp_dir) / "backup.sqlite3"
                    _extract_zip_member(archive, database_archive_path, database_copy)
                    try:
                        quick = sqlite_quick_check(database_path=database_copy)
                        integrity = sqlite_integrity_check(database_path=database_copy)
                    except DatabaseOperationError as error:
                        issues.append(str(error))
                    if quick and quick.lower() != "ok":
                        issues.append(f"quick_check basarisiz: {quick}")
                    if integrity and integrity.lower() != "ok":
                        issues.append(f"integrity_check basarisiz: {integrity}")

            upload_info = manifest.get("uploads") or {}
            upload_file_count = int(upload_info.get("file_count") or 0)

    except zipfile.BadZipFile:
        return _empty_validation_result(backup_path, ["Zip yedek dosyasi bozuk."])
    except OSError as error:
        return _empty_validation_result(backup_path, [str(error)])

    return BackupValidationResult(
        backup_path=backup_path,
        is_ok=not issues,
        issues=tuple(issues),
        manifest=manifest,
        database_archive_path=database_archive_path,
        quick_check=quick,
        integrity_check=integrity,
        checksum_count=len(checksum_entries),
        upload_file_count=upload_file_count,
        total_bytes=total_bytes,
    )


def restore_full_backup_dry_run(backup_path):
    validation = validate_backup_package(backup_path)
    append_backup_event(
        "restore_dry_run",
        {
            "backup_path": str(validation.backup_path),
            "is_ok": validation.is_ok,
            "issues": list(validation.issues),
        },
    )
    return RestoreBackupResult(
        backup_path=validation.backup_path,
        dry_run=True,
        applied=False,
        pre_restore_backup_path=None,
        restored_database_path=None,
        restored_upload_files=validation.upload_file_count,
        quick_check=validation.quick_check,
        integrity_check=validation.integrity_check,
        issues=validation.issues,
    )


def _extract_uploads_to_temp(archive, temp_upload_root):
    restored_files = 0
    for member_name in archive.namelist():
        if member_name.endswith("/") or not member_name.startswith("uploads/"):
            continue
        if not _safe_zip_member_name(member_name):
            raise DatabaseOperationError(f"Gecersiz upload dosya yolu: {member_name}")
        relative_name = member_name[len("uploads/") :]
        if not _safe_zip_member_name(relative_name):
            raise DatabaseOperationError(f"Gecersiz upload dosya yolu: {member_name}")
        _extract_zip_member(archive, member_name, temp_upload_root / relative_name)
        restored_files += 1
    return restored_files


def restore_full_backup_apply(backup_path, confirm=None):
    if not restore_is_enabled():
        raise DatabaseOperationError(
            "Geri yukleme kapali. Calistirmak icin RESTORE_ENABLED=true ayarlayin."
        )
    if confirm != FULL_BACKUP_CONFIRMATION_TEXT:
        raise DatabaseOperationError(
            f"Geri yukleme icin --confirm {FULL_BACKUP_CONFIRMATION_TEXT} kullanin."
        )

    validation = validate_backup_package(backup_path)
    if not validation.is_ok:
        raise DatabaseOperationError(
            "Yedek dogrulamasi basarisiz: " + "; ".join(validation.issues)
        )

    source_path = sqlite_database_path()
    if source_path is None:
        raise DatabaseOperationError("Bu komut sadece dosya tabanli SQLite icin calisir.")
    upload_root = Path(current_app.config.get("UPLOAD_FOLDER", "")).expanduser().resolve()
    append_backup_event(
        "restore_started",
        {"backup_path": str(validation.backup_path), "database_path": str(source_path)},
    )

    pre_restore_backup = None
    try:
        pre_restore_backup = create_full_backup(include_uploads=True)
        with tempfile.TemporaryDirectory(prefix="volkaportal-restore-") as temp_dir:
            temp_dir = Path(temp_dir)
            restored_database = temp_dir / "restored.sqlite3"
            restored_upload_root = temp_dir / "uploads"
            with zipfile.ZipFile(validation.backup_path, "r") as archive:
                _extract_zip_member(
                    archive,
                    validation.database_archive_path,
                    restored_database,
                )
                restored_upload_files = _extract_uploads_to_temp(
                    archive,
                    restored_upload_root,
                )

            db.session.remove()
            db.engine.dispose()
            source_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(restored_database, source_path)

            if (validation.manifest.get("uploads") or {}).get("included", False):
                if upload_root.exists():
                    shutil.rmtree(upload_root)
                if restored_upload_root.exists():
                    shutil.copytree(restored_upload_root, upload_root)
                else:
                    upload_root.mkdir(parents=True, exist_ok=True)

            db.engine.dispose()
            from .seed import ensure_runtime_schema

            ensure_runtime_schema()
            final_check = sqlite_health_check()

        append_backup_event(
            "restore_completed",
            {
                "backup_path": str(validation.backup_path),
                "pre_restore_backup_path": str(pre_restore_backup.backup_path),
                "database_path": str(source_path),
                "restored_upload_files": restored_upload_files,
                "quick_check": final_check.quick_check,
                "integrity_check": final_check.integrity_check,
            },
        )
        return RestoreBackupResult(
            backup_path=validation.backup_path,
            dry_run=False,
            applied=True,
            pre_restore_backup_path=pre_restore_backup.backup_path,
            restored_database_path=source_path,
            restored_upload_files=restored_upload_files,
            quick_check=final_check.quick_check,
            integrity_check=final_check.integrity_check,
            issues=(),
        )
    except Exception as error:
        append_backup_event(
            "restore_failed",
            {
                "backup_path": str(validation.backup_path),
                "pre_restore_backup_path": (
                    str(pre_restore_backup.backup_path) if pre_restore_backup else None
                ),
                "error": str(error),
            },
        )
        raise


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
