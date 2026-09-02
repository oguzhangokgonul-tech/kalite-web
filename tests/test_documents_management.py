from datetime import date

from app.extensions import db
from app.models import DOCUMENT_STATUSES, Document, DocumentRevisionRequest, Notification
from app.routes import DOCUMENT_REVISION_APPROVED_STATUS, DOCUMENT_REVISION_PENDING_STATUS

from .helpers import (
    create_company,
    create_user,
    first_document_category,
    login,
    make_document,
    upload_tuple,
)


def document_payload(category, **overrides):
    data = {
        "category_id": str(category.id),
        "document_code": "PR.01",
        "title": "Montaj Proseduru",
        "revision_no": "0",
        "publish_date": date.today().isoformat(),
        "revision_date": "",
        "department": "",
        "description": "Smoke test dokumani",
        "status": DOCUMENT_STATUSES[0],
    }
    data.update(overrides)
    return data


def test_document_permissions_and_company_isolation(app, client):
    company_a = create_company("311")
    company_b = create_company("312")
    viewer = create_user("viewer", company=company_a)
    document_viewer = create_user(
        "document-viewer",
        company=company_a,
        permissions=("documents.view",),
    )
    foreign_document = make_document(app, company_b)

    login(client, viewer)
    assert client.get("/documents").status_code == 403
    assert client.get("/documents/upload").status_code == 403

    login(client, document_viewer)
    assert client.get(f"/documents/{foreign_document.id}").status_code == 404
    assert client.get(f"/documents/{foreign_document.id}/download").status_code == 404


def test_document_upload_download_revision_request_and_approval(app, client):
    company = create_company("313")
    manager = create_user(
        "management-representative",
        company=company,
        role_key="management_representative",
    )
    requester = create_user(
        "document-user",
        company=company,
        permissions=("documents.view",),
    )
    category = first_document_category(company)

    login(client, manager)
    response = client.post(
        "/documents/upload",
        data={
            **document_payload(category),
            "document_file": upload_tuple(b"%PDF-1.4\nold\n", "montaj.pdf"),
        },
    )

    assert response.status_code == 302
    document = Document.query.one()
    assert document.company_id == company.id
    assert document.document_code == "PR.01"
    assert document.file_type == "pdf"

    download_response = client.get(f"/documents/{document.id}/download")
    assert download_response.status_code == 200
    assert download_response.data == b"%PDF-1.4\nold\n"

    login(client, requester)
    response = client.post(
        f"/documents/{document.id}/revision-request",
        data={
            "explanation": "Revizyon gerekcesi",
            "document_file": upload_tuple(b"excel-data", "kanit.xlsx"),
        },
    )

    assert response.status_code == 302
    revision_request = DocumentRevisionRequest.query.one()
    assert revision_request.status == DOCUMENT_REVISION_PENDING_STATUS
    assert len(revision_request.files) == 1
    assert Notification.query.filter_by(
        user_id=manager.id,
        document_revision_request_id=revision_request.id,
    ).count() == 1
    db.session.refresh(document)
    assert document.status == DOCUMENT_STATUSES[1]

    login(client, manager)
    response = client.post(
        f"/documents/revision-requests/{revision_request.id}/approve",
        data={
            "revision_no": "1",
            "revision_date": date.today().isoformat(),
            "approval_note": "Uygundur",
            "document_file": upload_tuple(b"%PDF-1.4\nnew\n", "montaj-r1.pdf"),
        },
    )

    assert response.status_code == 302
    db.session.refresh(document)
    db.session.refresh(revision_request)
    assert revision_request.status == DOCUMENT_REVISION_APPROVED_STATUS
    assert document.revision_no == "1"
    assert document.original_file_name == "montaj-r1.pdf"
    assert client.get(f"/documents/{document.id}/download").data == b"%PDF-1.4\nnew\n"

    archive = Document.query.filter(
        Document.id != document.id,
        Document.document_code == "PR.01",
    ).one()
    assert archive.status == DOCUMENT_STATUSES[3]
    assert archive.original_file_name == "montaj.pdf"


def test_documents_list_search_filter_uses_current_company(app, client):
    company_a = create_company("314")
    company_b = create_company("315")
    user = create_user("document-searcher", company=company_a, permissions=("documents.view",))
    make_document(app, company_a, document_code="PRS.01", title="Gorunen Proses")
    make_document(app, company_b, document_code="PRS.02", title="Gorunmeyen Proses")

    login(client, user)
    response = client.get("/documents/list?search=Gorunen")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Gorunen Proses" in body
    assert "Gorunmeyen Proses" not in body
