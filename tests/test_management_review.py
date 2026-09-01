from datetime import date, timedelta
from pathlib import Path

import pytest

from app import create_app
from app.extensions import db
from app.models import Action, AppSetting, AuditLog, ManagementReview, User, UserPermission
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


def management_review_form_payload(user, action=None, **overrides):
    payload = {
        "title": "Yıllık Yönetimin Gözden Geçirmesi",
        "review_period": "2026",
        "meeting_date": date.today().isoformat(),
        "location": "Toplantı Odası",
        "status": "Devam Ediyor",
        "chair_user_id": str(user.id),
        "recorder_user_id": str(user.id),
        "participants": "Yönetim Temsilcisi, Genel Müdür",
        "agenda": "Kalite hedefleri ve süreç performansları",
        "audit_results": "İç denetim bulguları değerlendirildi.",
        "customer_feedback": "Müşteri geri bildirimleri gözden geçirildi.",
        "process_performance": "Süreç performansları hedeflerle karşılaştırıldı.",
        "nonconformities": "Açık uygunsuzluklar izlendi.",
        "corrective_actions": "Düzeltici faaliyet durumları incelendi.",
        "monitoring_results": "Ölçüm sonuçları değerlendirildi.",
        "supplier_performance": "Tedarikçi performansı takip edildi.",
        "resource_needs": "Kaynak ihtiyacı planlandı.",
        "risk_opportunities": "Risk ve fırsatlar güncellendi.",
        "decisions": "Yeni kalite hedefleri onaylandı.",
        "outputs": "Toplantı çıktıları aksiyona bağlandı.",
        "improvement_opportunities": "Dijital raporlama iyileştirilecek.",
        "action_id": str(action.id) if action else "",
    }
    payload.update(overrides)
    return payload


def test_management_review_dashboard_requires_permission(app, client):
    user = create_user("viewer")
    login(client, user)

    response = client.get("/yonetimin-gozden-gecirmesi")

    assert response.status_code == 403


def test_management_review_create_edit_report_delete_flow(app, client):
    user = create_user(
        "manager",
        "management_review.view",
        "management_review.manage",
        "management_review.delete",
    )
    action = Action(
        action_number=1,
        title="YGG aksiyonu",
        responsible_owner=user.full_name,
        responsible_user_id=user.id,
        department="Kalite",
        termin_date=date.today() + timedelta(days=14),
    )
    db.session.add(action)
    db.session.commit()
    login(client, user)

    form_response = client.get("/yonetimin-gozden-gecirmesi/yeni")
    assert form_response.status_code == 200
    assert "Yeni YGG Kaydı" in form_response.get_data(as_text=True)

    response = client.post(
        "/yonetimin-gozden-gecirmesi/yeni",
        data=management_review_form_payload(user, action),
        follow_redirects=True,
    )

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Yıllık Yönetimin Gözden Geçirmesi" in body
    assert "#1" in body
    review = ManagementReview.query.one()
    assert review.review_no.startswith("YGG-")
    assert review.action_id == action.id
    assert review.audit_results == "İç denetim bulguları değerlendirildi."

    report_response = client.get(f"/yonetimin-gozden-gecirmesi/{review.id}/rapor")
    assert report_response.status_code == 200
    report_body = report_response.get_data(as_text=True)
    assert "Toplantı Çıktıları" in report_body
    assert "Kaynak ihtiyacı planlandı." in report_body

    response = client.post(
        f"/yonetimin-gozden-gecirmesi/{review.id}/duzenle",
        data=management_review_form_payload(
            user,
            status="Tamamlandı",
            decisions="Yıllık hedefler kapatıldı.",
            action_id="",
        ),
        follow_redirects=True,
    )

    assert response.status_code == 200
    review = db.session.get(ManagementReview, review.id)
    assert review.status == "Tamamlandı"
    assert review.decisions == "Yıllık hedefler kapatıldı."
    assert review.action_id is None

    response = client.post(
        f"/yonetimin-gozden-gecirmesi/{review.id}/sil",
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert ManagementReview.query.count() == 0
    assert AuditLog.query.filter_by(entity_type="ManagementReview").count() >= 3


def test_management_reviews_sort_overdue_open_before_completed(app, client):
    today = date.today()
    user = create_user("manager", "management_review.view")
    db.session.add_all(
        [
            ManagementReview(
                review_no="YGG-2026-0001",
                title="Tamamlanan toplantı",
                meeting_date=today - timedelta(days=20),
                status="Tamamlandı",
            ),
            ManagementReview(
                review_no="YGG-2026-0002",
                title="Az geciken toplantı",
                meeting_date=today - timedelta(days=3),
                status="Planlandı",
            ),
            ManagementReview(
                review_no="YGG-2026-0003",
                title="Çok geciken toplantı",
                meeting_date=today - timedelta(days=9),
                status="Devam Ediyor",
            ),
        ]
    )
    db.session.commit()
    login(client, user)

    response = client.get("/yonetimin-gozden-gecirmesi")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert body.find("Çok geciken toplantı") < body.find("Az geciken toplantı")
    assert body.find("Az geciken toplantı") < body.find("Tamamlanan toplantı")


def test_runtime_schema_marks_sales_readiness_management_review_done(app):
    AppSetting.query.delete()
    db.session.commit()

    ensure_runtime_schema()

    setting = db.session.get(AppSetting, "sales_readiness:management_review")
    assert setting is not None
    assert setting.value == "1"
    roadmap_setting = db.session.get(AppSetting, "sales_readiness:month3_management_review")
    assert roadmap_setting is not None
    assert roadmap_setting.value == "1"
