"""Standards index: current revisions, tenant isolation and permissions."""

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.extensions import db
from app.models import AuditLog, CompanyModule, Document
from app.standard_documentation_models import StandardDocumentationHeading, StandardDocumentationLink

from .helpers import create_company, create_user, login, make_document


BASE = "/standart-dokumantasyon"


def test_create_multiple_links_and_live_revision(app, client):
    company = create_company("standard-a")
    user = create_user("standard-editor", company=company, permissions=(
        "standard_documentation.manage", "documents.manage",
    ))
    first = make_document(app, company, document_code="PR.01", title="First")
    second = make_document(app, company, document_code="PR.02", title="Second")
    login(client, user)
    response = client.post(f"{BASE}/yeni", data={
        "title": "Uzun standart başlığı", "related_standard": "ISO 9001", "technical_heading_no": "7.5",
        "document_ids": [str(first.id), str(second.id)],
    })
    assert response.status_code == 302
    heading = StandardDocumentationHeading.query.one()
    assert heading.company_id == company.id
    assert [link.document_id for link in heading.links] == [first.id, second.id]
    assert AuditLog.query.filter_by(entity_type="StandardDocumentationHeading", entity_id=str(heading.id), action="created").count() == 1
    first.title = "Revised title"
    first.revision_no = "3"
    db.session.commit()
    page = client.get(BASE)
    assert page.status_code == 200
    assert b"Revised title" in page.data
    assert b"Revizyon 3" in page.data
    assert f"/documents/{first.id}".encode() in page.data
    assert client.get(f"/documents/{first.id}").status_code == 200
    first.archived_at = first.created_at
    db.session.commit()
    assert "Arşiv".encode() in client.get(BASE).data
    assert client.get(f"{BASE}/{heading.id}/duzenle").status_code == 200
    updated = client.post(f"{BASE}/{heading.id}/duzenle", data={
        "title": "Revised standard", "document_ids": [str(first.id), str(second.id)],
    })
    assert updated.status_code == 302
    assert len(heading.links) == 2


def test_edit_links_and_foreign_document_rejected(app, client):
    company = create_company("standard-owner")
    other = create_company("standard-other")
    editor = create_user("standard-owner-editor", company=company, permissions=(
        "standard_documentation.manage", "documents.manage",
    ))
    other_editor = create_user("standard-other-editor", company=other, permissions=(
        "standard_documentation.manage", "documents.manage",
    ))
    own_doc = make_document(app, company)
    foreign_doc = make_document(app, other)
    login(client, editor)
    invalid = client.post(f"{BASE}/yeni", data={"title": "Unsafe", "document_ids": str(foreign_doc.id)})
    assert invalid.status_code == 400
    assert StandardDocumentationHeading.query.count() == 0
    client.post(f"{BASE}/yeni", data={"title": "Safe", "document_ids": str(own_doc.id)})
    heading = StandardDocumentationHeading.query.one()
    invalid_edit = client.post(f"{BASE}/{heading.id}/duzenle", data={
        "title": "Changed", "document_ids": str(foreign_doc.id),
    })
    assert invalid_edit.status_code == 400
    assert heading.title == "Safe"
    assert StandardDocumentationLink.query.count() == 1
    login(client, other_editor)
    assert client.get(f"{BASE}/{heading.id}/duzenle").status_code == 404
    assert b"Safe" not in client.get(BASE).data


def test_permissions_module_and_document_delete_guard(app, client):
    company = create_company("standard-permissions")
    manager = create_user("standard-manager", company=company, permissions=(
        "standard_documentation.manage", "documents.manage", "documents.delete",
    ))
    viewer = create_user("standard-viewer", company=company, permissions=(
        "standard_documentation.view", "documents.view",
    ))
    no_document_right = create_user("standard-no-doc", company=company, permissions=(
        "standard_documentation.view",
    ))
    document = make_document(app, company)
    login(client, manager)
    client.post(f"{BASE}/yeni", data={"title": "Linked", "document_ids": str(document.id)})
    heading = StandardDocumentationHeading.query.one()
    assert client.post(f"/documents/{document.id}/delete").status_code == 302
    assert db.session.get(Document, document.id) is not None
    assert StandardDocumentationLink.query.filter_by(document_id=document.id).count() == 1
    login(client, viewer)
    assert client.get(BASE).status_code == 200
    assert client.get(f"{BASE}/{heading.id}/duzenle").status_code == 403
    login(client, no_document_right)
    assert client.get(BASE).status_code == 403
    login(client, manager)
    module = CompanyModule.query.filter_by(company_id=company.id, module_key="standard_documentation").one()
    module.is_enabled = False
    db.session.commit()
    assert client.get(BASE).status_code == 403


def test_unpublished_documents_cannot_be_linked(app, client):
    company = create_company("standard-status")
    editor = create_user("standard-status-editor", company=company, permissions=(
        "standard_documentation.manage", "documents.manage",
    ))
    unpublished = make_document(app, company, status="Onay Bekleyen")
    login(client, editor)
    assert f'name="document_ids" value="{unpublished.id}"'.encode() not in client.get(f"{BASE}/yeni").data
    response = client.post(f"{BASE}/yeni", data={"title": "Draft link", "document_ids": str(unpublished.id)})
    assert response.status_code == 400
    assert StandardDocumentationHeading.query.count() == 0


def test_migration_upgrade_downgrade_reupgrade(tmp_path):
    path = Path(__file__).resolve().parents[1] / "migrations/versions/202611050001_standard_documentation.py"
    spec = importlib.util.spec_from_file_location("standard_documentation_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine("sqlite:///" + (tmp_path / "standard.db").as_posix())
    try:
        with engine.begin() as connection:
            connection.execute(sa.text("CREATE TABLE companies (id INTEGER PRIMARY KEY)"))
            connection.execute(sa.text("CREATE TABLE users (id INTEGER PRIMARY KEY)"))
            connection.execute(sa.text("CREATE TABLE documents (id INTEGER PRIMARY KEY)"))
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
                migration.upgrade()
                tables = set(sa.inspect(connection).get_table_names())
                assert {"standard_documentation_headings", "standard_documentation_links"} <= tables
                connection.execute(sa.text("INSERT INTO standard_documentation_headings "
                    "(id, company_id, title, created_by_user_id) VALUES (1, 1, 'ISO', 1)"))
                with pytest.raises(RuntimeError):
                    migration.downgrade()
                connection.execute(sa.text("DELETE FROM standard_documentation_headings"))
                migration.downgrade()
                migration.upgrade()
                assert "standard_documentation_links" in sa.inspect(connection).get_table_names()
    finally:
        engine.dispose()
