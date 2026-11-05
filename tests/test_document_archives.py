from unittest.mock import patch

from app.extensions import db
from app.models import Document, DocumentCategory, DocumentRevisionRequest
from app.routes import DOCUMENT_REVISION_PENDING_STATUS, DOCUMENT_REVISION_REJECTED_STATUS
from scripts.document_archive_release import archive_inventory, migrate_archives

from .helpers import create_company, create_user, first_document_category, login, make_document, stored_upload_path, upload_tuple


def test_archive_moves_files_and_separates_category_views(app, client):
    company = create_company("ARC01")
    manager = create_user("archive-manager", company=company, role_key="management_representative")
    category = first_document_category(company)
    document = make_document(app, company, category=category, content=b"%PDF-1.4\narchive text\n")
    old_file = stored_upload_path(app, document.file_path)
    login(client, manager)
    assert client.get(f"/documents/{document.id}").status_code == 200
    old_preview = stored_upload_path(app, document.preview_file_path)
    assert old_preview.exists()

    response = client.post(f"/documents/{document.id}/archive")
    assert response.status_code == 302
    assert response.location.endswith(f"/documents/category/{category.slug}/archive")
    db.session.refresh(document)
    assert document.status == "Arşiv"
    assert f"documents/archives/{category.slug}/originals/" in document.file_path
    assert f"documents/archives/{category.slug}/previews/" in document.preview_file_path
    assert stored_upload_path(app, document.file_path).is_file()
    assert stored_upload_path(app, document.preview_file_path).is_file()
    assert not old_file.exists()
    assert not old_preview.exists()
    assert document.search_index.source_file_path == document.file_path
    assert client.get(f"/documents/{document.id}/download").data == b"%PDF-1.4\narchive text\n"
    assert client.get(f"/documents/{document.id}/preview").status_code == 200
    assert "Test Dokuman" not in client.get(f"/documents/category/{category.slug}").get_data(as_text=True)
    assert "Test Dokuman" in client.get(f"/documents/category/{category.slug}/archive").get_data(as_text=True)
    assert "Test Dokuman" not in client.get("/documents/list").get_data(as_text=True)
    assert "Test Dokuman" in client.get("/documents/archive").get_data(as_text=True)
    assert "Arşiv <span>1</span>" in client.get("/documents").get_data(as_text=True)


def test_revision_places_old_version_in_same_category_archive(app, client):
    company = create_company("ARC02")
    manager = create_user("archive-revision-manager", company=company, role_key="management_representative")
    category = first_document_category(company)
    document = make_document(app, company, category=category, content=b"%PDF-1.4\nold revision\n")
    old_path = document.file_path
    login(client, manager)

    response = client.post(f"/documents/{document.id}/revise", data={
        "revision_no": "1", "revision_reason": "Updated procedure",
        "document_file": upload_tuple(b"%PDF-1.4\nnew revision\n", "new.pdf"),
    })
    assert response.status_code == 302
    archived = Document.query.filter_by(company_id=company.id, status="Arşiv").one()
    assert f"documents/archives/{category.slug}/originals/" in archived.file_path
    assert not stored_upload_path(app, old_path).exists()
    assert client.get(f"/documents/{archived.id}/download").data == b"%PDF-1.4\nold revision\n"
    assert client.get(f"/documents/{document.id}/download").data == b"%PDF-1.4\nnew revision\n"
    archive_html = client.get(f"/documents/category/{category.slug}/archive").get_data(as_text=True)
    assert "Test Dokuman - Arşiv" in archive_html


def test_existing_archives_migrate_once_and_missing_file_blocks_apply(app):
    company = create_company("ARC03")
    category = first_document_category(company)
    existing = make_document(app, company, category=category, status="Arşiv", document_code="AR.1")
    missing = make_document(app, company, category=category, status="Arşiv", document_code="AR.2", file_name="missing.pdf")
    stored_upload_path(app, missing.file_path).unlink()

    assert archive_inventory()["missing_original"] == 1
    try:
        migrate_archives()
    except RuntimeError:
        pass
    else:
        raise AssertionError("Migration must refuse missing archive originals")
    assert stored_upload_path(app, existing.file_path).exists()

    stored_upload_path(app, missing.file_path).write_bytes(b"%PDF-1.4\nrecovered\n")
    assert archive_inventory()["to_move"] == 2
    assert migrate_archives()["moved"] == 2
    db.session.refresh(existing)
    assert f"documents/archives/{category.slug}/originals/" in existing.file_path
    assert migrate_archives()["moved"] == 0
    stored_upload_path(app, existing.file_path).unlink()
    assert archive_inventory()["missing_original"] == 1


def test_archive_permissions_company_scope_and_missing_source(app, client):
    own = create_company("ARC04")
    foreign = create_company("ARC05")
    manager = create_user("archive-own-manager", company=own, role_key="management_representative")
    viewer = create_user("archive-own-viewer", company=own, permissions=("documents.view",))
    foreign_category = first_document_category(foreign)
    foreign_category.slug = "foreign-archive-only"
    db.session.commit()
    foreign_document = make_document(app, foreign, status="Arşiv")
    own_document = make_document(app, own)
    login(client, viewer)
    assert client.get("/documents/archive").status_code == 200
    assert client.get(f"/documents/category/{foreign_category.slug}/archive").status_code == 404
    assert client.post(f"/documents/{own_document.id}/archive").status_code == 403
    assert client.get(f"/documents/{foreign_document.id}/download").status_code == 404

    login(client, manager)
    original_path = own_document.file_path
    stored_upload_path(app, original_path).unlink()
    response = client.post(f"/documents/{own_document.id}/archive", follow_redirects=True)
    assert response.status_code == 200
    db.session.refresh(own_document)
    assert own_document.status != "Arşiv"
    assert own_document.file_path == original_path


def test_pending_revision_cannot_republish_archived_document(app, client):
    company = create_company("ARC06")
    manager = create_user("archive-pending-manager", company=company, role_key="management_representative")
    document = make_document(app, company)
    revision_request = DocumentRevisionRequest(
        company_id=company.id, document_id=document.id,
        requested_by_user_id=manager.id, status=DOCUMENT_REVISION_PENDING_STATUS,
        explanation="Old request",
    )
    db.session.add(revision_request)
    db.session.commit()
    login(client, manager)
    assert client.post(f"/documents/{document.id}/archive").status_code == 302
    response = client.post(f"/documents/revision-requests/{revision_request.id}/approve", data={
        "revision_reason": "Must not publish",
        "document_file": upload_tuple(b"%PDF-1.4\nnew\n", "new.pdf"),
    })
    assert response.status_code == 409
    db.session.refresh(document)
    assert document.status == "Arşiv"
    db.session.refresh(revision_request)
    assert revision_request.status == DOCUMENT_REVISION_REJECTED_STATUS
    assert "Onayla ve Yayınla" not in client.get(
        f"/documents/revision-requests/{revision_request.id}"
    ).get_data(as_text=True)


def test_category_removal_rehomes_archived_files(app, client):
    company = create_company("ARC07")
    manager = create_user("archive-category-manager", company=company, role_key="management_representative")
    categories = DocumentCategory.query.filter_by(company_id=company.id, is_active=True).order_by(DocumentCategory.id).all()
    source, destination = categories[:2]
    archived = make_document(app, company, category=source, status="Arşiv")
    active = make_document(app, company, category=source, file_name="active.pdf")
    login(client, manager)
    old_path = stored_upload_path(app, archived.file_path)
    response = client.post(f"/documents/categories/{source.id}/delete", data={
        "destination_id": str(destination.id), "confirmation": "EVET",
    })
    assert response.status_code == 302
    db.session.refresh(archived)
    db.session.refresh(active)
    assert archived.category_id == destination.id
    assert active.category_id == destination.id
    assert f"documents/archives/{destination.slug}/originals/" in archived.file_path
    assert stored_upload_path(app, archived.file_path).is_file()
    assert not old_path.exists()
    assert client.get(f"/documents/category/{destination.slug}/archive").status_code == 200


def test_legacy_shared_source_is_preserved_until_last_reference(app, client):
    first = create_company("ARC08")
    second = create_company("ARC09")
    manager_first = create_user("archive-legacy-first", company=first, role_key="management_representative")
    manager_second = create_user("archive-legacy-second", company=second, role_key="management_representative")
    first_document = make_document(app, first, file_path="legacy-shared.pdf")
    second_document = make_document(app, second, file_path="legacy-shared.pdf")
    legacy_path = stored_upload_path(app, "legacy-shared.pdf")
    login(client, manager_first)
    assert client.post(f"/documents/{first_document.id}/archive").status_code == 302
    assert legacy_path.exists()
    login(client, manager_second)
    assert client.post(f"/documents/{second_document.id}/archive").status_code == 302
    assert not legacy_path.exists()
    assert first_document.file_path != second_document.file_path


def test_missing_company_source_does_not_fall_back_to_root(app, client):
    company = create_company("ARC10")
    manager = create_user("archive-no-fallback", company=company, role_key="management_representative")
    document = make_document(app, company, file_name="same-name.pdf")
    stored_upload_path(app, document.file_path).unlink()
    stored_upload_path(app, "same-name.pdf").write_bytes(b"foreign data")
    login(client, manager)
    assert client.post(f"/documents/{document.id}/archive").status_code == 302
    db.session.refresh(document)
    assert document.status != "Arşiv"
    assert document.file_path.startswith(f"company-{company.id:03d}/documents/originals/")


def test_mismatched_company_storage_path_is_not_archived(app, client):
    own = create_company("ARC11")
    foreign = create_company("ARC12")
    manager = create_user("archive-mismatched-path", company=own, role_key="management_representative")
    mismatched_path = f"company-{foreign.id:03d}/documents/originals/mismatched.pdf"
    document = make_document(app, own, file_path=mismatched_path)
    archived = make_document(
        app, own, file_path=f"company-{foreign.id:03d}/documents/originals/archived-mismatch.pdf",
        status="Arşiv",
    )
    bypass_path = f"./company-{foreign.id:03d}/documents/originals/bypass.pdf"
    bypass = make_document(app, own, file_path=bypass_path)
    make_document(app, own, file_path=f"./company-{foreign.id:03d}/documents/originals/archived-bypass.pdf", status="Arşiv")
    assert archive_inventory()["unsafe_path"] == 2
    assert archived.status == "Arşiv"
    login(client, manager)
    assert client.post(f"/documents/{document.id}/archive").status_code == 302
    db.session.refresh(document)
    assert document.status != "Arşiv"
    assert document.file_path == mismatched_path
    assert stored_upload_path(app, mismatched_path).is_file()
    assert client.post(f"/documents/{document.id}/delete").status_code == 409
    assert db.session.get(Document, document.id) is not None
    assert stored_upload_path(app, mismatched_path).is_file()
    assert client.post(f"/documents/{bypass.id}/archive").status_code == 302
    assert client.post(f"/documents/{bypass.id}/delete").status_code == 409
    assert stored_upload_path(app, bypass_path).is_file()


def test_permanent_delete_keeps_file_if_commit_fails(app, client):
    company = create_company("ARC13")
    manager = create_user("archive-delete-manager", company=company, role_key="management_representative")
    document = make_document(app, company)
    original = stored_upload_path(app, document.file_path)
    login(client, manager)
    real_commit = db.session.commit

    def fail_document_commit():
        if any(isinstance(item, Document) for item in db.session.deleted):
            raise RuntimeError("database unavailable")
        return real_commit()

    with patch.object(db.session, "commit", side_effect=fail_document_commit):
        assert client.post(f"/documents/{document.id}/delete").status_code == 500
    assert original.is_file()
    db.session.rollback()
    assert db.session.get(Document, document.id) is not None
    assert client.post(f"/documents/{document.id}/delete").status_code == 302
    assert not original.exists()
