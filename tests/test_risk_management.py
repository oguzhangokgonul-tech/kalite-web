from datetime import date, timedelta
from pathlib import Path

import pytest

from app import create_app
from app.extensions import db
from app.models import Action, AppSetting, AuditLog, Dof, RiskRecord, User, UserPermission
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


def test_risk_dashboard_requires_permission(app, client):
    user = create_user("viewer")
    login(client, user)

    response = client.get("/risk-yonetimi")

    assert response.status_code == 403


def test_risk_create_edit_delete_flow(app, client):
    user = create_user("manager", "risk.view", "risk.manage", "risk.delete", "roles.manage")
    action = Action(
        action_number=1,
        title="Risk aksiyonu",
        responsible_owner=user.full_name,
        responsible_user_id=user.id,
        department="Kalite",
        termin_date=date.today() + timedelta(days=7),
    )
    dof = Dof(
        dof_no="IF-0001",
        title="Risk IF bağlantısı",
        department="Kalite",
        responsible_id=user.id,
        created_by_user_id=user.id,
        opening_date=date.today(),
        due_date=date.today() + timedelta(days=10),
        status="Onay Akışı Bekleniyor",
        approval_step="management_representative",
    )
    db.session.add_all([action, dof])
    db.session.commit()
    login(client, user)

    response = client.post(
        "/risk-yonetimi/yeni",
        data={
            "title": "Tedarik gecikmesi",
            "department": "Kalite",
            "process": "Satın alma",
            "description": "Kritik malzeme geç gelebilir.",
            "cause": "Tek tedarikçi",
            "consequence": "Termin kayması",
            "likelihood": "4",
            "severity": "5",
            "status": "Açık",
            "due_date": date.today().isoformat(),
            "owner_user_id": str(user.id),
            "action_id": str(action.id),
            "dof_id": str(dof.id),
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Tedarik gecikmesi" in body
    assert "RPN" in body
    risk = RiskRecord.query.one()
    assert risk.risk_no.startswith("RSK-")
    assert risk.rpn == 20
    assert risk.level == "Yüksek"
    assert risk.action_id == action.id
    assert risk.dof_id == dof.id

    response = client.post(
        f"/risk-yonetimi/{risk.id}/duzenle",
        data={
            "title": "Tedarik gecikmesi güncel",
            "department": "Kalite",
            "process": "Satın alma",
            "likelihood": "2",
            "severity": "3",
            "status": "İzlemede",
            "owner_user_id": str(user.id),
            "action_id": "",
            "dof_id": "",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert risk.rpn == 6
    assert risk.level == "Düşük"
    assert risk.status == "İzlemede"
    assert risk.action_id is None
    assert risk.dof_id is None

    response = client.post(f"/risk-yonetimi/{risk.id}/sil", follow_redirects=True)

    assert response.status_code == 200
    assert RiskRecord.query.count() == 0
    assert AuditLog.query.filter_by(entity_type="RiskRecord").count() >= 3


def test_runtime_schema_marks_sales_readiness_risk_module_done(app):
    AppSetting.query.delete()
    db.session.commit()

    ensure_runtime_schema()

    setting = db.session.get(AppSetting, "sales_readiness:risk_module")
    assert setting is not None
    assert setting.value == "1"
