from datetime import date

from app.extensions import db
from app.models import (
    DOCUMENT_STATUSES,
    AppSetting,
    AuditLog,
    Document,
    DocumentAcknowledgement,
    DocumentRevisionRequest,
    Notification,
    TrainingParticipant,
    TrainingRecord,
)
from app.routes import DOCUMENT_REVISION_APPROVED_STATUS, DOCUMENT_REVISION_PENDING_STATUS
from app.seed import ensure_runtime_schema

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


def test_document_acknowledgement_requires_view_and_is_revision_scoped(app, client):
    company = create_company("316")
    user = create_user(
        "document-reader",
        company=company,
        permissions=("documents.view",),
        full_name="Ayse Celik",
    )
    document = make_document(
        app,
        company,
        document_code="PR.20",
        title="Okuma Onayi Proseduru",
        revision_no="0",
    )

    login(client, user)
    response = client.post(f"/documents/{document.id}/acknowledge")

    assert response.status_code == 302
    assert DocumentAcknowledgement.query.count() == 0

    client.get(f"/documents/{document.id}")
    response = client.post(f"/documents/{document.id}/acknowledge", follow_redirects=True)

    assert response.status_code == 200
    acknowledgement = DocumentAcknowledgement.query.one()
    assert acknowledgement.company_id == company.id
    assert acknowledgement.document_id == document.id
    assert acknowledgement.user_id == user.id
    assert acknowledgement.document_code_snapshot == "PR.20"
    assert acknowledgement.document_title_snapshot == "Okuma Onayi Proseduru"
    assert acknowledgement.revision_no_snapshot == "0"
    assert AuditLog.query.filter_by(
        entity_type="DocumentAcknowledgement",
        entity_id=str(acknowledgement.id),
        action="created",
    ).count() == 1

    client.post(f"/documents/{document.id}/acknowledge", follow_redirects=True)
    assert DocumentAcknowledgement.query.count() == 1

    document.revision_no = "1"
    db.session.commit()
    client.get(f"/documents/{document.id}")
    client.post(f"/documents/{document.id}/acknowledge", follow_redirects=True)

    assert DocumentAcknowledgement.query.count() == 2
    assert sorted(
        item.revision_no_snapshot for item in DocumentAcknowledgement.query.all()
    ) == ["0", "1"]


def test_document_acknowledgement_tracking_shows_pending_and_completed_users(app, client):
    company = create_company("317")
    manager = create_user(
        "document-manager",
        company=company,
        permissions=("documents.manage", "training.manage", "training.view"),
    )
    participant_user = create_user(
        "training-reader",
        company=company,
        permissions=("documents.view", "training.view"),
        full_name="Turgut Ozel Pekyilmaz",
    )
    document = make_document(app, company, document_code="PR.21", revision_no="2")
    training = TrainingRecord(
        company_id=company.id,
        training_no="EGT-2026-0001",
        title="PR.21 Okuma Onayi",
        training_type="Doküman Okuma Onayı",
        document_id=document.id,
        created_by_user_id=manager.id,
    )
    participant = TrainingParticipant(
        company_id=company.id,
        training=training,
        user_id=participant_user.id,
        status="Atandı",
    )
    db.session.add_all([training, participant])
    db.session.commit()

    login(client, manager)
    response = client.get(f"/documents/{document.id}/acknowledgements")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Turgut Ozel Pekyilmaz" in body
    assert "Bekliyor" in body

    login(client, participant_user)
    client.get(f"/documents/{document.id}")
    response = client.post(f"/documents/{document.id}/acknowledge", follow_redirects=True)

    assert response.status_code == 200
    db.session.refresh(participant)
    assert participant.status == "Okundu"
    acknowledgement = DocumentAcknowledgement.query.one()
    assert acknowledgement.training_participant_id == participant.id

    login(client, manager)
    response = client.get(f"/documents/{document.id}/acknowledgements")
    body = response.get_data(as_text=True)

    assert "Okundu / Onaylandı" in body
    assert "Bekliyor" not in body


def test_training_document_read_confirmation_creates_document_acknowledgement(app, client):
    company = create_company("318")
    manager = create_user(
        "training-manager",
        company=company,
        permissions=("training.manage", "training.view", "training.delete", "documents.view"),
    )
    participant_user = create_user(
        "training-participant",
        company=company,
        permissions=("training.view", "documents.view"),
    )
    document = make_document(app, company, document_code="PR.22", revision_no="3")
    training = TrainingRecord(
        company_id=company.id,
        training_no="EGT-2026-0002",
        title="PR.22 Okuma Onayi",
        training_type="Doküman Okuma Onayı",
        document_id=document.id,
        created_by_user_id=manager.id,
    )
    participant = TrainingParticipant(
        company_id=company.id,
        training=training,
        user_id=participant_user.id,
        status="Atandı",
    )
    db.session.add_all([training, participant])
    db.session.commit()

    login(client, participant_user)
    response = client.post(
        f"/egitim-yeterlilik/{training.id}/katilimci/{participant.id}/onayla",
        follow_redirects=True,
    )

    assert response.status_code == 200
    db.session.refresh(participant)
    db.session.refresh(training)
    acknowledgement = DocumentAcknowledgement.query.one()
    assert participant.status == "Okundu"
    assert training.status == "Tamamlandı"
    assert acknowledgement.document_id == document.id
    assert acknowledgement.user_id == participant_user.id
    assert acknowledgement.training_participant_id == participant.id
    assert acknowledgement.revision_no_snapshot == "3"

    login(client, manager)
    response = client.post(f"/egitim-yeterlilik/{training.id}/sil", follow_redirects=True)

    assert response.status_code == 200
    acknowledgement = DocumentAcknowledgement.query.one()
    assert acknowledgement.training_participant_id is None


def test_runtime_schema_marks_sales_readiness_document_read_done(app):
    AppSetting.query.delete()
    db.session.commit()

    ensure_runtime_schema()

    setting = db.session.get(AppSetting, "sales_readiness:month2_document_read")
    assert setting is not None
    assert setting.value == "1"


def test_document_schema_marks_sales_readiness_document_read_done_on_request(app, client):
    company = create_company("319")
    user = create_user("document-readiness", company=company, permissions=("documents.view",))
    AppSetting.query.delete()
    db.session.commit()

    login(client, user)
    response = client.get("/documents")

    assert response.status_code == 200
    setting = db.session.get(AppSetting, "sales_readiness:month2_document_read")
    assert setting is not None
    assert setting.value == "1"
