from datetime import date, timedelta
from pathlib import Path

import pytest

from app import create_app
from app.extensions import db
from app.models import (
    AppSetting,
    AuditLog,
    Document,
    DocumentCategory,
    PersonnelContact,
    TrainingParticipant,
    TrainingRecord,
    User,
    UserPermission,
)
from app.seed import ensure_runtime_schema


@pytest.fixture()
def app(tmp_path):
    class TestConfig:
        SECRET_KEY = "test"
        SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        WTF_CSRF_ENABLED = False
        UPLOAD_FOLDER = str(Path(tmp_path) / "uploads")
        TENANT_BASE_DOMAIN = "volkaportal.com"

    test_app = create_app(TestConfig)
    with test_app.app_context():
        db.create_all()
        yield test_app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


def login(client, user):
    with client.session_transaction() as session:
        session["user_id"] = user.id


def create_user(username, *permission_keys):
    user = User(
        username=username,
        full_name=username.title(),
        password_hash="not-used",
        is_active=True,
    )
    for permission_key in permission_keys:
        user.extra_permissions.append(UserPermission(permission_key=permission_key))
    db.session.add(user)
    db.session.commit()
    return user


def create_document():
    category = DocumentCategory(
        code="03",
        name="Prosedürler",
        slug="prosedurler",
        sort_order=3,
    )
    document = Document(
        category=category,
        document_code="PR.01",
        title="Eğitim Prosedürü",
        revision_no="1",
        status="Yayında",
        file_name="pr01.pdf",
        original_file_name="PR.01.pdf",
        file_path="documents/pr01.pdf",
    )
    db.session.add_all([category, document])
    db.session.commit()
    return document


def test_training_dashboard_requires_permission(app, client):
    user = create_user("viewer")
    login(client, user)

    response = client.get("/egitim-yeterlilik")

    assert response.status_code == 403


def test_training_create_confirm_update_and_delete_flow(app, client):
    manager = create_user(
        "manager",
        "training.view",
        "training.manage",
        "training.delete",
        "documents.view",
    )
    participant_user = create_user("participant", "training.view", "documents.view")
    contact = PersonnelContact(
        full_name="Personel Kartı",
        phone="555",
        title="Operatör",
        is_active=True,
    )
    db.session.add(contact)
    db.session.commit()
    document = create_document()
    login(client, manager)

    response = client.post(
        "/egitim-yeterlilik/yeni",
        data={
            "title": "Revizyon Okuma Onayı",
            "training_type": "Doküman Okuma Onayı",
            "description": "PR.01 revizyonu okunacak.",
            "document_id": str(document.id),
            "planned_date": date.today().isoformat(),
            "due_date": (date.today() + timedelta(days=7)).isoformat(),
            "instructor_user_id": str(manager.id),
            "status": "Planlandı",
            "participant_user_ids": [str(participant_user.id)],
            "participant_contact_ids": [str(contact.id)],
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Revizyon Okuma Onayı" in body
    training = TrainingRecord.query.one()
    assert training.training_no.startswith("EGT-")
    assert training.document_id == document.id
    assert len(training.participants) == 2
    assert training.status == "Planlandı"

    participant = TrainingParticipant.query.filter_by(user_id=participant_user.id).one()
    login(client, participant_user)
    response = client.post(
        f"/egitim-yeterlilik/{training.id}/katilimci/{participant.id}/onayla",
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert participant.status == "Okundu"
    assert participant.read_confirmed_at is not None
    assert training.status == "Devam Ediyor"

    contact_participant = TrainingParticipant.query.filter_by(
        personnel_contact_id=contact.id
    ).one()
    login(client, manager)
    response = client.post(
        f"/egitim-yeterlilik/{training.id}/katilimci/{contact_participant.id}/sonuc",
        data={"status": "Başarılı", "score": "92,5", "notes": "Yeterli"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert contact_participant.status == "Başarılı"
    assert str(contact_participant.score) == "92.50"
    assert contact_participant.attended_at is not None
    assert training.status == "Tamamlandı"

    response = client.post(f"/egitim-yeterlilik/{training.id}/sil", follow_redirects=True)

    assert response.status_code == 200
    assert TrainingRecord.query.count() == 0
    assert TrainingParticipant.query.count() == 0
    assert AuditLog.query.filter_by(entity_type="TrainingRecord").count() >= 2


def test_runtime_schema_marks_sales_readiness_training_module_done(app):
    AppSetting.query.delete()
    db.session.commit()

    ensure_runtime_schema()

    setting = db.session.get(AppSetting, "sales_readiness:training_module")
    assert setting is not None
    assert setting.value == "1"
