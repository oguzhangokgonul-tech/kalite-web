from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from app import create_app
from app.extensions import db
from app.mail import build_action_email, build_generic_notification_email
from app.models import Action, AppSetting, Company, InternalAudit, Notification, Role, User
from app.notification_models import NotificationEmailBatch, NotificationEmailEvent
from app.notification_policy import reminder_timezone
from app.reminders import (
    maybe_run_due_reminders_for_request,
    reminder_delivery_window_open,
    run_due_reminders_once_for_company,
)
from app.seed import ensure_default_roles, ensure_runtime_schema


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
        ensure_default_roles()
        db.session.commit()
        yield test_app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def reminder_clock(monkeypatch):
    def set_clock(run_date=date(2026, 9, 14), hour=8, minute=30):
        now = datetime.combine(run_date, datetime.min.time()).replace(
            hour=hour, minute=minute, tzinfo=reminder_timezone(),
        )
        monkeypatch.setattr("app.notification_policy.local_now", lambda: now)
        monkeypatch.setattr("app.reminders.local_now", lambda: now)
        return run_date

    monkeypatch.setattr("app.reminders.reminder_delivery_window_open", lambda now=None: True)
    set_clock()
    return set_clock


@pytest.fixture()
def sent_mail(app, monkeypatch):
    app.config["MAIL_SUPPRESS_SEND"] = False
    sent = []

    def send(settings, recipients, subject, body):
        sent.append((recipients, subject, body))
        return True

    monkeypatch.setattr("app.mail.send_mail_now", send)
    return sent


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


def create_user(username, company=None, email=None, role_key="department_staff"):
    user = User(
        username=username,
        full_name=username.title(),
        email=email,
        password_hash="not-used",
        company_id=company.id if company else None,
        is_active=True,
    )
    user.roles.append(Role.query.filter_by(key=role_key).one())
    db.session.add(user)
    db.session.commit()
    return user


def create_action(company, user, title="Geciken aksiyon", due_date=None):
    action = Action(
        company_id=company.id,
        action_number=1,
        title=title,
        responsible_owner=user.full_name,
        responsible_user_id=user.id,
        department="Kalite",
        termin_date=due_date or date.today() - timedelta(days=2),
    )
    db.session.add(action)
    db.session.commit()
    return action


@pytest.mark.parametrize("suppressed", [False, True])
def test_due_reminders_create_deduped_action_notification_and_email_marker(
    app, reminder_clock, sent_mail, suppressed,
):
    app.config["MAIL_SUPPRESS_SEND"] = suppressed
    run_date = reminder_clock()
    company = create_company()
    user = create_user("aksiyon-sorumlusu", company=company, email="aksiyon@example.test")
    action = create_action(company, user, due_date=run_date - timedelta(days=2))

    stats = run_due_reminders_once_for_company(company.id, force=True, run_date=run_date)

    assert stats["notifications"] == 1
    assert stats["emails"] == int(not suppressed)
    assert len(sent_mail) == int(not suppressed)
    notification = Notification.query.one()
    assert notification.user_id == user.id
    assert notification.company_id == company.id
    assert notification.notification_type == "danger"
    assert notification.source_key.startswith("action:")
    assert notification.target_url.startswith("/actions/")
    assert (notification.email_sent_at is not None) is (not suppressed)
    if suppressed:
        assert NotificationEmailBatch.query.count() == 0
        assert NotificationEmailEvent.query.count() == 0
    else:
        recipients, subject, body = sent_mail[0]
        assert recipients == [user.email]
        assert subject == "[Test Firma] 1 işiniz için bildirim özeti"
        assert f"Kayıt: {action.number_label}" in body
        assert f"Konu: {action.title}" in body
        assert f"https://firma-101.volkaportal.com/actions/{action.id}" in body
        assert NotificationEmailBatch.query.one().status == "accepted"
        assert NotificationEmailEvent.query.one().status == "accepted"

    second_stats = run_due_reminders_once_for_company(company.id, force=True, run_date=run_date)

    assert second_stats["notifications"] == 0
    assert second_stats["emails"] == 0
    assert len(sent_mail) == int(not suppressed)
    assert Notification.query.count() == 1


def test_due_reminders_are_company_scoped(app, reminder_clock, sent_mail):
    run_date = reminder_clock()
    company_a = create_company("201", "A Firma")
    company_b = create_company("202", "B Firma")
    user_a = create_user("firma-a", company=company_a, email="a@example.test")
    user_b = create_user("firma-b", company=company_b, email="b@example.test")
    create_action(company_a, user_a, title="A firmasının aksiyonu", due_date=run_date - timedelta(days=2))
    create_action(company_b, user_b, title="B firmasının aksiyonu", due_date=run_date - timedelta(days=2))

    stats = run_due_reminders_once_for_company(company_a.id, force=True, run_date=run_date)

    assert stats["notifications"] == 1
    notifications = Notification.query.order_by(Notification.id.asc()).all()
    assert len(notifications) == 1
    assert notifications[0].user_id == user_a.id
    assert notifications[0].company_id == company_a.id
    assert stats["emails"] == 1
    assert len(sent_mail) == 1
    recipients, _subject, body = sent_mail[0]
    assert recipients == [user_a.email]
    assert "A firmasının aksiyonu" in body
    assert "https://firma-201.volkaportal.com/actions/" in body
    assert "B firmasının aksiyonu" not in body
    assert "firma-202.volkaportal.com" not in body


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
    assert body.startswith("Er Prefabrik | Aksiyon\n")


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


def test_company_primary_domain_wins_when_global_link_settings_are_none(app):
    app.config.update(
        PUBLIC_BASE_URL="https://none",
        TENANT_BASE_DOMAIN="None",
        SERVER_NAME="None",
        PREFERRED_URL_SCHEME="http",
    )
    company = create_company("403", "Sağıroğlu Çelik")
    company.slug = "sagiroglu-celik"
    company.primary_domain = "sagiroglucelik.volkaportal.com"
    db.session.commit()

    _subject, body = build_generic_notification_email(
        "IF/DÖF termin hatırlatması",
        title="IF/DÖF",
        target_url="/dofs/10",
        company_id=company.id,
    )

    assert "https://sagiroglucelik.volkaportal.com/dofs/10" in body
    assert "https://none" not in body


def test_notification_open_redirects_generic_target_and_marks_read(app, client):
    user = create_user("viewer", role_key="viewer")
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


def test_auto_due_reminders_run_once_on_notification_page(app, client, reminder_clock, sent_mail):
    app.config["NOTIFICATION_AUTO_REMINDERS_ENABLED"] = True
    run_date = reminder_clock()
    company = create_company("301", "Otomatik Firma")
    user = create_user("otomatik", company=company, email="otomatik@example.test")
    create_action(company, user, due_date=run_date - timedelta(days=2))
    login(client, user, company=company)

    first_response = client.get("/notifications")
    second_response = client.get("/notifications")

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert Notification.query.filter_by(user_id=user.id, company_id=company.id).count() == 1
    assert len(sent_mail) == 1
    assert sent_mail[0][0] == [user.email]


def test_request_triggered_reminders_only_run_in_0830_istanbul_window(app):
    app.config.update(
        NOTIFICATION_AUTO_REMINDERS_ENABLED=True,
        NOTIFICATION_REMINDER_TIMEZONE="Europe/Istanbul",
        NOTIFICATION_REMINDER_HOUR=8,
        NOTIFICATION_REMINDER_MINUTE=30,
        NOTIFICATION_REMINDER_WINDOW_MINUTES=10,
    )
    company = create_company("302", "Zamanlama Firma")
    user = create_user("zamanlama", company=company, email="zamanlama@example.test")
    create_action(company, user)

    assert reminder_delivery_window_open(datetime(2026, 9, 17, 5, 29, tzinfo=UTC)) is False
    assert reminder_delivery_window_open(datetime(2026, 9, 17, 5, 30, tzinfo=UTC)) is True
    assert reminder_delivery_window_open(datetime(2026, 9, 17, 5, 39, tzinfo=UTC)) is True
    assert reminder_delivery_window_open(datetime(2026, 9, 17, 5, 40, tzinfo=UTC)) is False
    assert maybe_run_due_reminders_for_request(
        company.id, user, now=datetime(2026, 9, 17, 5, 29, tzinfo=UTC)
    ) is None
    assert Notification.query.count() == 0


def test_runtime_schema_marks_sales_readiness_notification_upgrade_done(app):
    AppSetting.query.delete()
    db.session.commit()

    ensure_runtime_schema()

    setting = db.session.get(AppSetting, "sales_readiness:notification_upgrade")
    assert setting is not None
    assert setting.value == "1"


@pytest.mark.parametrize("invalid_domain", [None, "none", "None", "null", "undefined", "http://none", "bad host"])
def test_invalid_custom_domain_does_not_override_company_primary_domain(app, invalid_domain):
    company = create_company("501")
    company.primary_domain = "erprefabrik.volkaportal.com"
    company.custom_domain = invalid_domain
    db.session.commit()
    _subject, body = build_generic_notification_email(
        "Hatırlatma", target_url="/ic-denetim", company_id=company.id)
    assert "Detayları aç: https://erprefabrik.volkaportal.com/ic-denetim" in body


@pytest.mark.parametrize("target", ["http://none/ic-denetim?tab=plan#record",
                                    "https://other.volkaportal.com/ic-denetim?tab=plan#record"])
def test_absolute_notification_link_is_rebased_to_record_company(app, target):
    company = create_company("502")
    company.primary_domain = "erprefabrik.volkaportal.com"
    db.session.commit()
    with app.test_request_context(base_url="https://other.volkaportal.com"):
        _subject, body = build_generic_notification_email("Hatırlatma", target_url=target, company_id=company.id)
    assert "https://erprefabrik.volkaportal.com/ic-denetim?tab=plan#record" in body
    assert "http://none" not in body
    assert "https://other.volkaportal.com" not in body


def test_email_without_trusted_domain_omits_link_instead_of_using_request_or_none_host(app):
    app.config.update(TENANT_BASE_DOMAIN="None", PUBLIC_BASE_URL="http://none", SERVER_NAME="None")
    with app.test_request_context(base_url="https://untrusted.example.test"):
        _subject, body = build_generic_notification_email("Hatırlatma", target_url="/ic-denetim")
    assert "Detayları aç:" not in body
    assert "http://none" not in body
    assert "untrusted.example.test" not in body


def test_company_email_without_company_domain_or_missing_company_omits_link(app):
    company = create_company("503")
    company.slug = ""
    company.primary_domain = "none"
    company.custom_domain = "None"
    db.session.commit()
    for company_id in (company.id, 999999):
        _subject, body = build_generic_notification_email("Hatırlatma", target_url="/ic-denetim", company_id=company_id)
        assert "Detayları aç:" not in body
        assert "https://volkaportal.com" not in body


@pytest.mark.parametrize("target", ["//evil.example.test/path", "javascript:alert(1)",
                                    "https://user:pass@example.test/path", "/\\evil.example.test",
                                    "/ic-denetim\nInjected", "http://example.test:bad/path"])
def test_invalid_notification_targets_are_not_mailed(app, target):
    company = create_company("504")
    _subject, body = build_generic_notification_email("Hatırlatma", target_url=target, company_id=company.id)
    assert "Detayları aç:" not in body


def test_internal_audit_email_is_concise_detailed_and_company_scoped(app, reminder_clock, sent_mail):
    run_date = reminder_clock()
    company = create_company("505", "Er Prefabrik")
    other = create_company("506", "Diğer Firma")
    company.primary_domain = "erprefabrik.volkaportal.com"
    company.custom_domain = "none"
    auditor = create_user("denetci", company=company, email="auditor@example.test",
                          role_key="management_representative")
    audited = create_user("personel", company=company, email="staff@example.test",
                          role_key="management_representative")
    outsider = create_user("diger-personel", company=other, email="other@example.test",
                           role_key="management_representative")
    audit = InternalAudit(company_id=company.id, audit_no="ICD-2026-0041", title="2026 2/2 Proje",
                          planned_date=date(2026, 7, 1), evaluated_department="Proje",
                          auditor_id=auditor.id, audited_user_id=audited.id)
    other_audit = InternalAudit(company_id=other.id, audit_no="ICD-2026-0041", title="Diğer denetim",
                                planned_date=date(2026, 7, 1), auditor_id=outsider.id)
    db.session.add_all([audit, other_audit])
    db.session.commit()
    stats = run_due_reminders_once_for_company(company.id, force=True, run_date=run_date)
    assert stats["notifications"] == 2
    assert stats["emails"] == 2
    assert len(sent_mail) == 2
    assert {email for recipients, _subject, _body in sent_mail for email in recipients} == {
        auditor.email, audited.email}
    for _recipients, subject, body in sent_mail:
        assert subject == "[Er Prefabrik] 1 işiniz için bildirim özeti"
        assert body.startswith("Er Prefabrik | İşleriniz\n")
        assert "İç denetim hatırlatması ICD-2026-0041" in body
        assert "Planlanan iç denetim tarihi geçti." in body
        assert "Kayıt: ICD-2026-0041" in body
        assert "Konu: 2026 2/2 Proje" in body
        assert "Birim: Proje" in body
        assert "Denetçi: Denetci" in body
        assert "Denetlenen: Personel" in body
        assert "Termin: 01.07.2026" in body
        assert "Termin durumu: 75 gün gecikti" in body
        assert "Detayları aç: https://erprefabrik.volkaportal.com/ic-denetim" in body
        assert "internal-audit" not in body
        assert "plan tarihi durumu" not in body
        assert "Diğer denetim" not in body
        assert "firma-506.volkaportal.com" not in body
        assert "https://volkaportal.com/ic-denetim" not in body
        assert "None" not in body
    assert {notification.target_url for notification in Notification.query.all()} == {"/ic-denetim"}
    assert {notification.company_id for notification in Notification.query.all()} == {company.id}
    assert all(notification.email_sent_at is not None for notification in Notification.query.all())
    second_stats = run_due_reminders_once_for_company(company.id, force=True, run_date=run_date)
    assert second_stats["notifications"] == 0
    assert second_stats["emails"] == 0
    assert len(sent_mail) == 2
    assert Notification.query.count() == 2
    assert NotificationEmailBatch.query.count() == 2
    assert NotificationEmailEvent.query.count() == 2


def test_conflicting_company_context_does_not_link_to_either_company(app):
    company = create_company("507")
    other = create_company("508")
    _subject, body = build_generic_notification_email("Hatırlatma", target_url="/ic-denetim",
                                                     company=company, company_id=other.id)
    assert "Detayları aç:" not in body


@pytest.mark.parametrize("offset", [7, 1])
def test_internal_audit_scheduled_mail_handles_missing_people(app, reminder_clock, sent_mail, offset):
    company = create_company("509")
    user = create_user("auditor", company=company, email="auditor@example.test",
                       role_key="management_representative")
    run_date = reminder_clock(date(2026, 9, 15))
    audit = InternalAudit(company_id=company.id, audit_no="ICD-2026-0001", title="Plan",
                          auditor_id=user.id, planned_date=run_date + timedelta(days=offset))
    db.session.add(audit)
    db.session.commit()
    stats = run_due_reminders_once_for_company(company.id, force=True, run_date=run_date)
    assert stats["notifications"] == 1
    assert stats["emails"] == 1
    assert len(sent_mail) == 1
    recipients, subject, body = sent_mail[0]
    assert recipients == [user.email]
    assert subject == "[Test Firma] 1 işiniz için bildirim özeti"
    assert "İç denetim tarihi yaklaşıyor." in body
    assert "İç denetim hatırlatması ICD-2026-0001" in body
    assert "Kayıt: ICD-2026-0001" in body
    assert "Konu: Plan" in body
    assert "Denetçi: Auditor" in body
    assert f"Termin: {audit.planned_date:%d.%m.%Y}" in body
    assert "Detayları aç: https://firma-509.volkaportal.com/ic-denetim" in body
    assert "Denetlenen:" not in body
    assert "Birim:" not in body
    assert "None" not in body
    assert NotificationEmailEvent.query.one().phase == f"due:{offset}"
    assert Notification.query.one().email_sent_at is not None
    second_stats = run_due_reminders_once_for_company(company.id, force=True, run_date=run_date)
    assert second_stats["notifications"] == 0
    assert second_stats["emails"] == 0
    assert len(sent_mail) == 1


@pytest.mark.parametrize("offset", [0, 3])
def test_internal_audit_unscheduled_days_do_not_send_mail(app, reminder_clock, sent_mail, offset):
    run_date = reminder_clock(date(2026, 9, 15))
    company = create_company("510")
    user = create_user("auditor", company=company, email="auditor@example.test",
                       role_key="management_representative")
    audit = InternalAudit(company_id=company.id, audit_no="ICD-2026-0002", title="Plan",
                          auditor_id=user.id, planned_date=run_date + timedelta(days=offset))
    db.session.add(audit)
    db.session.commit()

    stats = run_due_reminders_once_for_company(company.id, force=True, run_date=run_date)

    assert stats["notifications"] == 1
    assert stats["emails"] == 0
    assert sent_mail == []
    assert Notification.query.one().email_sent_at is None
    assert NotificationEmailBatch.query.count() == 0
    assert NotificationEmailEvent.query.count() == 0


def test_legacy_global_notification_uses_only_valid_configured_base(app):
    app.config.update(PUBLIC_BASE_URL="https://volkaportal.com", TENANT_BASE_DOMAIN="None")
    _subject, body = build_generic_notification_email("Global bildirim", target_url="/ic-denetim")
    assert "Detayları aç: https://volkaportal.com/ic-denetim" in body
