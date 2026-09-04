from datetime import date, timedelta
from pathlib import Path

import pytest

from app import create_app
from app.extensions import db
from app.models import (
    Action,
    ActionHistory,
    AppSetting,
    AuditLog,
    Dof,
    RiskRecord,
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


def test_risk_can_create_linked_action(app, client):
    user = create_user(
        "risk-manager",
        "risk.view",
        "risk.manage",
        "actions.create",
    )
    risk = RiskRecord(
        risk_no="RSK-2026-0001",
        title="Tedarik gecikmesi",
        department="Kalite",
        process="Satın alma",
        description="Kritik malzeme geç gelebilir.",
        cause="Tek tedarikçi",
        consequence="Üretim termin kayması",
        likelihood=4,
        severity=5,
        status="Açık",
        due_date=date.today() + timedelta(days=7),
        owner_user_id=user.id,
        created_by_user_id=user.id,
    )
    db.session.add(risk)
    db.session.commit()
    login(client, user)

    form_response = client.get(f"/actions/new?risk_id={risk.id}")
    form_body = form_response.get_data(as_text=True)

    assert form_response.status_code == 200
    assert "Bağlı Risk" in form_body
    assert "RSK-2026-0001" in form_body
    assert "Tedarik gecikmesi" in form_body

    response = client.post(
        "/actions/new",
        data={
            "title": "Risk azaltma aksiyonu",
            "responsible_user_id": str(user.id),
            "related_user_1_id": "",
            "related_user_2_id": "",
            "department": "Kalite",
            "description": "Alternatif tedarikçi değerlendirilecek.",
            "termin_date": (date.today() + timedelta(days=5)).isoformat(),
            "risk_id": str(risk.id),
            "capa_type": "Önleyici Faaliyet",
            "sub_action_indexes": "",
        },
    )

    assert response.status_code == 302
    action = Action.query.one()
    db.session.refresh(risk)
    assert risk.action_id == action.id
    assert risk.status == "Aksiyon Açıldı"
    assert ActionHistory.query.filter_by(
        action_id=action.id,
        event_type="risk_linked",
    ).count() == 1


def test_risk_action_link_requires_risk_manage_permission(app, client):
    user = create_user("action-user", "risk.view", "actions.create")
    risk = RiskRecord(
        risk_no="RSK-2026-0003",
        title="Yetkisiz bağlama riski",
        department="Kalite",
        likelihood=2,
        severity=3,
        status="Açık",
        owner_user_id=user.id,
        created_by_user_id=user.id,
    )
    db.session.add(risk)
    db.session.commit()
    login(client, user)

    response = client.post(
        "/actions/new",
        data={
            "title": "Yetkisiz risk aksiyonu",
            "responsible_user_id": str(user.id),
            "related_user_1_id": "",
            "related_user_2_id": "",
            "department": "Kalite",
            "description": "",
            "termin_date": (date.today() + timedelta(days=5)).isoformat(),
            "risk_id": str(risk.id),
            "sub_action_indexes": "",
        },
    )

    assert response.status_code == 200
    assert "Bağlanacak risk kaydı bulunamadı veya erişim yetkiniz yok." in response.get_data(
        as_text=True
    )
    assert Action.query.count() == 0
    db.session.refresh(risk)
    assert risk.action_id is None
    assert risk.status == "Açık"


def test_risk_action_link_does_not_overwrite_existing_action(app, client):
    user = create_user(
        "risk-overwrite-manager",
        "risk.view",
        "risk.manage",
        "actions.create",
    )
    existing_action = Action(
        action_number=1,
        title="Mevcut risk aksiyonu",
        responsible_owner=user.full_name,
        responsible_user_id=user.id,
        department="Kalite",
        termin_date=date.today() + timedelta(days=7),
    )
    db.session.add(existing_action)
    db.session.flush()
    risk = RiskRecord(
        risk_no="RSK-2026-0004",
        title="Bağlantısı korunacak risk",
        department="Kalite",
        likelihood=4,
        severity=4,
        status="Aksiyon Açıldı",
        owner_user_id=user.id,
        created_by_user_id=user.id,
        action_id=existing_action.id,
    )
    db.session.add(risk)
    db.session.commit()
    login(client, user)

    redirect_response = client.get(f"/actions/new?risk_id={risk.id}")
    assert redirect_response.status_code == 302
    assert redirect_response.headers["Location"].endswith(f"/actions/{existing_action.id}")

    response = client.post(
        "/actions/new",
        data={
            "title": "Yeni risk aksiyonu",
            "responsible_user_id": str(user.id),
            "related_user_1_id": "",
            "related_user_2_id": "",
            "department": "Kalite",
            "description": "",
            "termin_date": (date.today() + timedelta(days=5)).isoformat(),
            "risk_id": str(risk.id),
            "sub_action_indexes": "",
        },
    )

    assert response.status_code == 200
    assert "Risk kaydı zaten bir aksiyona bağlı." in response.get_data(as_text=True)
    assert Action.query.count() == 1
    db.session.refresh(risk)
    assert risk.action_id == existing_action.id
    assert risk.status == "Aksiyon Açıldı"


def test_linked_risks_render_on_action_and_dof_details(app, client):
    user = create_user(
        "risk-viewer",
        "risk.view",
        "risk.manage",
        "actions.create",
    )
    record_owner = create_user("record-owner")
    action = Action(
        action_number=1,
        title="Risk bağlantılı aksiyon",
        responsible_owner=record_owner.full_name,
        responsible_user_id=record_owner.id,
        department="Kalite",
        termin_date=date.today() + timedelta(days=7),
    )
    dof = Dof(
        dof_no="IF-0002",
        title="Risk bağlantılı IF",
        department="Kalite",
        responsible_id=record_owner.id,
        created_by_user_id=record_owner.id,
        opening_date=date.today(),
        due_date=date.today() + timedelta(days=10),
        status="Onay Akışı Bekleniyor",
        approval_step="management_representative",
    )
    db.session.add_all([action, dof])
    db.session.flush()
    risk = RiskRecord(
        risk_no="RSK-2026-0002",
        title="Kalibrasyon gecikmesi",
        department="Kalite",
        process="Kalibrasyon",
        likelihood=3,
        severity=4,
        status="İzlemede",
        due_date=date.today() + timedelta(days=15),
        owner_user_id=user.id,
        created_by_user_id=user.id,
        action_id=action.id,
        dof_id=dof.id,
    )
    db.session.add(risk)
    db.session.commit()
    login(client, user)

    action_response = client.get(f"/actions/{action.id}")
    dof_response = client.get(f"/dofs/{dof.id}")

    assert action_response.status_code == 200
    action_body = action_response.get_data(as_text=True)
    assert "Bağlı Riskler" in action_body
    assert "RSK-2026-0002" in action_body
    assert "Kalibrasyon gecikmesi" in action_body

    assert dof_response.status_code == 200
    dof_body = dof_response.get_data(as_text=True)
    assert "Bağlı Riskler" in dof_body
    assert "RSK-2026-0002" in dof_body
    assert "Kalibrasyon gecikmesi" in dof_body


def test_runtime_schema_marks_sales_readiness_risk_module_done(app):
    AppSetting.query.delete()
    db.session.commit()

    ensure_runtime_schema()

    setting = db.session.get(AppSetting, "sales_readiness:risk_module")
    assert setting is not None
    assert setting.value == "1"
    month3_setting = db.session.get(AppSetting, "sales_readiness:month3_risk")
    assert month3_setting is not None
    assert month3_setting.value == "1"
