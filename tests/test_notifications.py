from datetime import date, timedelta
from pathlib import Path

import pytest

from app import create_app
from app.extensions import db
from app.mail import build_action_email, build_generic_notification_email
from app.models import Action, AppSetting, Company, Notification, User
from app.reminders import run_due_reminders_once_for_company
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
        MAIL_ENABLED = True
        MAIL_SUPPRESS_SEND = True
        MAIL_SERVER = "smtp.example.test"
        MAIL_DEFAULT_SENDER = "noreply@example.test"
        MAIL_PORT = 587
        MAIL_USE_TLS = True
        MAIL_USE_SSL = False
        MAIL_USERNAME = ""
        MAIL_PASSWORD = ""
        MAIL_REPLY_TO = ""
        MAIL_TIMEOUT = 1
        MAIL_SUBJECT_PREFIX = "[VolkaPortal]"
        PREFERRED_URL_SCHEME = "https"
        NOTIFICATION_AUTO_REMINDERS_ENABLED = False
        NOTIFICATION_REMINDER_DAYS_BEFORE = 7
        NOTIFICATION_CALIBRATION_REMINDER_DAYS_BEFORE = 30

    test_app = create_app(TestConfig)
    with test_app.app_context():
        db.create_all()
        yield test_app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


def login(client, user, company=None):
    with client.session_transaction() as session:
        session["user_id"] = user.id
        if company:
            session["company_id"] = company.id


def create_company(code="101", name="Test Firma"):
    company = Company(code=code, name=name, slug=f"firma-{code}", is_active=True)
    db.session.add(company)
    db.session.commit()
    return company


def create_user(username, company=None, email=None):
    user = User(
        username=username,
        full_name=username.title(),
        email=email,
        password_hash="not-used",
        company_id=company.id if company else None,
        is_active=True,
    )
    db.session.add(user)
    db.session.commit()
    return user


def create_action(company, user, title="Geciken aksiyon"):
    action = Action(
        company_id=company.id,
        action_number=1,
        title=title,
        responsible_owner=user.full_name,
        responsible_user_id=user.id,
        department="Kalite",
        termin_date=date.today() - timedelta(days=2),
    )
    db.session.add(action)
    db.session.commit()
    return action


def test_due_reminders_create_deduped_action_notification_and_email_marker(app):
    company = create_company()
    user = create_user("aksiyon-sorumlusu", company=company, email="aksiyon@example.test")
    create_action(company, user)
    run_date = date.today()

    stats = run_due_reminders_once_for_company(company.id, force=True, run_date=run_date)

    assert stats["notifications"] == 1
    assert stats["emails"] == 1
    notification = Notification.query.one()
    assert notification.user_id == user.id
    assert notification.company_id == company.id
    assert notification.notification_type == "danger"
    assert notification.source_key.startswith("action:")
    assert notification.target_url.startswith("/actions/")
    assert notification.email_sent_at is not None

    second_stats = run_due_reminders_once_for_company(company.id, force=True, run_date=run_date)

    assert second_stats["notifications"] == 0
    assert Notification.query.count() == 1


def test_due_reminders_are_company_scoped(app):
    company_a = create_company("201", "A Firma")
    company_b = create_company("202", "B Firma")
    user_a = create_user("firma-a", company=company_a, email="a@example.test")
    user_b = create_user("firma-b", company=company_b, email="b@example.test")
    create_action(company_a, user_a, title="A firmasının aksiyonu")
    create_action(company_b, user_b, title="B firmasının aksiyonu")

    stats = run_due_reminders_once_for_company(company_a.id, force=True)

    assert stats["notifications"] == 1
    notifications = Notification.query.order_by(Notification.id.asc()).all()
    assert len(notifications) == 1
    assert notifications[0].user_id == user_a.id
    assert notifications[0].company_id == company_a.id


def test_action_email_detail_link_uses_company_subdomain(app):
    app.config["PUBLIC_BASE_URL"] = "https://volkaportal.com"
    company = create_company("401", "Er Prefabrik")
    company.slug = "erprefabrik"
    user = create_user("aksiyon-sorumlusu", company=company, email="aksiyon@example.test")
    action = create_action(company, user)
    db.session.commit()

    _subject, body = build_action_email(action, "Yeni aksiyon bildirimi")

    assert f"https://erprefabrik.volkaportal.com/actions/{action.id}" in body
    assert f"https://volkaportal.com/actions/{action.id}" not in body


def test_generic_notification_email_detail_link_uses_company_subdomain(app):
    app.config["PUBLIC_BASE_URL"] = "https://volkaportal.com"
    company = create_company("402", "Kalibrasyon Firma")
    company.slug = "kalibrasyon"
    db.session.commit()

    _subject, body = build_generic_notification_email(
        "Kalibrasyon termin hatirlatmasi",
        title="Kalibrasyon",
        target_url="/kalibrasyon",
        company_id=company.id,
    )

    assert "https://kalibrasyon.volkaportal.com/kalibrasyon" in body
    assert "https://volkaportal.com/kalibrasyon" not in body


def test_notification_open_redirects_generic_target_and_marks_read(app, client):
    user = create_user("viewer")
    notification = Notification(
        user_id=user.id,
        company_id=None,
        message="Risk termin hatırlatması",
        notification_type="warning",
        target_url="/risk-yonetimi",
        is_read=False,
    )
    db.session.add(notification)
    db.session.commit()
    login(client, user)

    response = client.get(f"/notifications/{notification.id}/open")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/risk-yonetimi")
    db.session.refresh(notification)
    assert notification.is_read is True


def test_auto_due_reminders_run_once_on_notification_page(app, client):
    app.config["NOTIFICATION_AUTO_REMINDERS_ENABLED"] = True
    company = create_company("301", "Otomatik Firma")
    user = create_user("otomatik", company=company, email="otomatik@example.test")
    create_action(company, user)
    login(client, user, company=company)

    first_response = client.get("/notifications")
    second_response = client.get("/notifications")

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert Notification.query.filter_by(user_id=user.id, company_id=company.id).count() == 1


def test_runtime_schema_marks_sales_readiness_notification_upgrade_done(app):
    AppSetting.query.delete()
    db.session.commit()

    ensure_runtime_schema()

    setting = db.session.get(AppSetting, "sales_readiness:notification_upgrade")
    assert setting is not None
    assert setting.value == "1"
