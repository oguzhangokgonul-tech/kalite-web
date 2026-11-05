"""Copy-on-commit storage for category-specific document archives."""

from dataclasses import dataclass, field
import hashlib
from pathlib import Path
import re
import shutil

from flask import current_app
from sqlalchemy import or_

from .extensions import db
from .models import Document


@dataclass
class ArchiveStage:
    created_paths: list[Path] = field(default_factory=list)
    old_paths: list[str] = field(default_factory=list)


def archive_relative_path(document, kind, filename):
    if not document.id or not document.company_id or not document.category:
        raise ValueError("invalid_archive_document")
    if kind not in {"originals", "previews"}:
        raise ValueError("invalid_archive_kind")
    safe_name = Path(str(filename).replace("\\", "/")).name
    relative = (
        Path(f"company-{document.company_id:03d}") / "documents" / "archives"
        / document.category.slug / kind / f"document-{document.id}-{safe_name}"
    )
    root = Path(current_app.config["UPLOAD_FOLDER"]).resolve()
    absolute = (root / relative).resolve()
    absolute.relative_to(root)
    return relative.as_posix(), absolute


def _same_file(source, destination):
    if source.stat().st_size != destination.stat().st_size:
        return False
    with source.open("rb") as first, destination.open("rb") as second:
        return hashlib.file_digest(first, "sha256").digest() == hashlib.file_digest(second, "sha256").digest()


def discard_archive_stage(stage):
    if stage is None:
        return
    for path in reversed(stage.created_paths):
        path.unlink(missing_ok=True)


def archive_source_for_document(document, stored_name, resolve_source):
    if not stored_name:
        return None
    normalized = stored_name.replace("\\", "/")
    scoped_prefix = re.match(r"^company-(\d+)(?:/|$)", normalized.lstrip("./"))
    if scoped_prefix and int(scoped_prefix.group(1)) != document.company_id:
        raise ValueError("archive_company_path_mismatch")
    source = resolve_source(stored_name)
    if source:
        upload_root = Path(current_app.config["UPLOAD_FOLDER"]).resolve()
        try:
            relative_parts = source.resolve().relative_to(upload_root).parts
        except ValueError:
            raise ValueError("archive_company_path_mismatch") from None
        if relative_parts and relative_parts[0].startswith("company-"):
            if relative_parts[0] != f"company-{document.company_id:03d}":
                raise ValueError("archive_company_path_mismatch")
    return source


def stage_document_archive(document, resolve_source):
    """Copy files first; the caller commits paths, then removes unreferenced originals."""
    stage = ArchiveStage()
    try:
        original = resolve_source(document.file_path)
        if not original or not original.is_file():
            raise FileNotFoundError("Dokümanın orijinal dosyası bulunamadı.")

        for field, kind in (("file_path", "originals"), ("preview_file_path", "previews")):
            old_relative = getattr(document, field)
            if not old_relative:
                continue
            source = archive_source_for_document(document, old_relative, resolve_source)
            if not source or not source.is_file():
                if kind == "previews":
                    document.preview_file_path = None
                    document.preview_file_name = None
                    document.preview_status = "failed"
                    document.preview_error = "Arşiv önizlemesi bulunamadı. Orijinal dosya indirilebilir."
                    continue
                raise FileNotFoundError("Dokümanın orijinal dosyası bulunamadı.")
            new_relative, destination = archive_relative_path(document, kind, source.name)
            if source.resolve() != destination:
                destination.parent.mkdir(parents=True, exist_ok=True)
                if destination.exists():
                    if not _same_file(source, destination):
                        raise FileExistsError("Arşiv hedefinde farklı içerikli bir dosya var.")
                else:
                    shutil.copy2(source, destination)
                    stage.created_paths.append(destination)
                    if not _same_file(source, destination):
                        raise OSError("Arşiv kopyası doğrulanamadı.")
                stage.old_paths.append(old_relative)
            setattr(document, field, new_relative)

        if document.search_index is not None:
            document.search_index.source_file_path = document.file_path
        return stage
    except Exception:
        discard_archive_stage(stage)
        raise


def finalize_archive_stage(stage, resolve_source):
    """Best-effort cleanup after the database commit; never remove a shared file."""
    if stage is None:
        return []
    failed_paths = []
    for old_relative in stage.old_paths:
        try:
            still_used = db.session.query(Document.id).filter(
                (Document.file_path == old_relative) | (Document.preview_file_path == old_relative)
            ).first()
            if still_used:
                continue
            old_path = resolve_source(old_relative)
            normalized = old_relative.replace("\\", "/")
            if old_path and not normalized.startswith("company-"):
                filename = old_path.name
                candidates = db.session.query(Document.file_path, Document.preview_file_path).filter(or_(
                    Document.file_path == filename,
                    Document.preview_file_path == filename,
                    Document.file_path.endswith("/" + filename, autoescape=True),
                    Document.preview_file_path.endswith("/" + filename, autoescape=True),
                ))
                if any(
                    resolve_source(value) == old_path
                    for pair in candidates
                    for value in pair if value
                ):
                    continue
            if old_path and old_path.is_file():
                old_path.unlink()
        except Exception:
            current_app.logger.warning("Archived document source cleanup failed: %s", old_relative, exc_info=True)
            failed_paths.append(old_relative)
    return failed_paths
