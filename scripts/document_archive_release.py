"""Move existing archived document files after a verified full backup.

Dry-run is the default. Run with --apply only while the web service is stopped.
"""

import argparse
import json

from sqlalchemy import or_

from app import create_app
from app.config import Config
from app.document_archive import (
    archive_source_for_document, discard_archive_stage, finalize_archive_stage,
    stage_document_archive,
)
from app.extensions import db
from app.models import Document
from app.routes import archive_source_path


class ReleaseConfig(Config):
    MAIL_ENABLED = False
    NOTIFICATION_AUTO_REMINDERS_ENABLED = False
    AUTO_BOOTSTRAP_DATABASE = False


def archived_documents():
    return Document.query.filter(or_(Document.status == "Arşiv", Document.archived_at.isnot(None)))


def in_category_archive(document):
    if not document.category or not document.company_id:
        return False
    expected = (
        f"company-{document.company_id:03d}/documents/archives/"
        f"{document.category.slug}/originals/document-{document.id}-"
    )
    if not (document.file_path or "").replace("\\", "/").startswith(expected):
        return False
    try:
        original = archive_source_for_document(document, document.file_path, archive_source_path)
    except ValueError:
        return False
    if not original or not original.is_file():
        return False
    if document.preview_file_path:
        preview_prefix = (
            f"company-{document.company_id:03d}/documents/archives/"
            f"{document.category.slug}/previews/document-{document.id}-"
        )
        try:
            preview = archive_source_for_document(document, document.preview_file_path, archive_source_path)
        except ValueError:
            return False
        if not document.preview_file_path.replace("\\", "/").startswith(preview_prefix):
            return False
        if not preview or not preview.is_file():
            return False
    return True


def archive_inventory():
    result = {"total": 0, "already_moved": 0, "to_move": 0, "missing_original": 0, "unsafe_path": 0}
    for document in archived_documents().order_by(Document.id).all():
        result["total"] += 1
        if in_category_archive(document):
            result["already_moved"] += 1
            continue
        try:
            source = archive_source_for_document(document, document.file_path, archive_source_path)
            if document.preview_file_path:
                archive_source_for_document(document, document.preview_file_path, archive_source_path)
        except ValueError:
            result["unsafe_path"] += 1
            continue
        if not document.category or not source or not source.is_file():
            result["missing_original"] += 1
        else:
            result["to_move"] += 1
    return result


def migrate_archives():
    inventory = archive_inventory()
    if inventory["missing_original"] or inventory["unsafe_path"]:
        raise RuntimeError("Missing or unsafe archive originals; review the dry-run before applying")
    moved = 0
    document_ids = [document.id for document in archived_documents().order_by(Document.id).all()]
    for document_id in document_ids:
        document = db.session.get(Document, document_id)
        if in_category_archive(document):
            continue
        stage = None
        try:
            stage = stage_document_archive(document, archive_source_path)
            db.session.commit()
        except Exception:
            db.session.rollback()
            discard_archive_stage(stage)
            raise
        finalize_archive_stage(stage, archive_source_path)
        moved += 1
    result = archive_inventory()
    result["moved"] = moved
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Move files and update archived records")
    args = parser.parse_args()
    app = create_app(ReleaseConfig)
    with app.app_context():
        result = migrate_archives() if args.apply else archive_inventory()
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
