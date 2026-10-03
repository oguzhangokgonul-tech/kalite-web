from datetime import date, datetime, timedelta
import json

import pytest

from app.extensions import db
from app.models import Company, User, Notification, AppSetting, CompanyModule
from app.notification_models import NotificationEmailBatch, NotificationEmailEvent
from app.notification_policy import (
    collect_reminder, dispatch_collection, get_company_policy, get_user_preference,
    queue_notification_event, reminder_collection, reminder_timezone,
)


@pytest.fixture()
def records(app, monkeypatch):
    company = Company(code="np1", slug="np1", name="Örnek Şirket", is_active=True)
    db.session.add(company)
    db.session.flush()
    user = User(company_id=company.id, username="np", full_name="Öğüt Şahin",
                password_hash="unused", is_active=True, email="person@example.test")
    db.session.add(user)
    db.session.commit()
    app.config.update(MAIL_ENABLED=True, MAIL_SERVER="smtp.example.test",
                      MAIL_DEFAULT_SENDER="notify@example.test", MAIL_SUPPRESS_SEND=False)
    mails = []
    monkeypatch.setattr("app.mail.send_mail_now", lambda *args: mails.append(args) or True)
    return company, user, mails


def candidates(company, user, run_date, due_date, *, kind="calibration", count=1, created_at=None):
    with reminder_collection(company.id, run_date) as collection:
        for number in range(1, count + 1):
            collect_reminder(
                [user], company_id=company.id, kind=kind, record_id=number,
                title=f"Cihaz {number}", message="Kalibrasyon planını tamamlayın.",
                target_url="/kalibrasyon", due_date=due_date, run_date=run_date,
                created_at=created_at,
            )
    db.session.commit()
    return collection


def send(collection, hour=8, minute=30):
    now = datetime.combine(collection["run_date"], datetime.min.time()).replace(
        hour=hour, minute=minute, tzinfo=reminder_timezone(),
    )
    return dispatch_collection(collection, now=now)


def test_old_overdue_only_weekly_and_no_daily_site_duplicates(records):
    company, user, mails = records
    monday = date(2026, 10, 5)
    due = monday - timedelta(days=45)
    for offset in range(8):
        collection = candidates(company, user, monday + timedelta(days=offset), due)
        assert send(collection) == int(offset in (0, 7))
    assert len(mails) == 2
    assert Notification.query.count() == 1
    assert NotificationEmailBatch.query.count() == 2


def test_deadline_and_weekly_digest_are_one_email_with_company_domain(records):
    company, user, mails = records
    day = date(2026, 10, 5)
    collection = candidates(company, user, day, day, count=3)
    assert send(collection) == 1
    assert send(collection) == 0
    assert len(mails) == 1
    assert "3 işiniz" in mails[0][2]
    assert "https://np1.volkaportal.com/kalibrasyon" in mails[0][3]
    assert NotificationEmailBatch.query.one().item_count == 3
    assert all(n.email_sent_at is not None for n in Notification.query.all())


@pytest.mark.parametrize("offset,expected", [(30, 1), (29, 0), (7, 1), (6, 0), (0, 1), (-2, 0)])
def test_calibration_milestones_not_daily(records, offset, expected):
    company, user, _ = records
    day = date(2026, 10, 6)
    assert send(candidates(company, user, day, day + timedelta(days=offset))) == expected


@pytest.mark.parametrize("hour,minute", [(8, 29), (8, 40), (9, 30), (0, 0)])
def test_no_scheduled_mail_outside_window(records, hour, minute):
    company, user, mails = records
    day = date(2026, 10, 6)
    assert send(candidates(company, user, day, day), hour, minute) == 0
    assert mails == []
    assert NotificationEmailBatch.query.count() == 0


def test_global_and_foreign_users_are_not_added(records):
    company, user, mails = records
    user.company_id = None
    db.session.commit()
    collection = candidates(company, user, date(2026, 10, 5), None)
    assert collection["items"] == {}
    assert send(collection) == 0
    assert not mails


def test_disabled_module_skipped(records):
    company, user, mails = records
    db.session.add(CompanyModule(company_id=company.id, module_key="calibration", is_enabled=False))
    db.session.commit()
    assert send(candidates(company, user, date(2026, 10, 5), None)) == 0
    assert not mails
    assert Notification.query.count() == 0


@pytest.mark.parametrize("mode,expected", [("site", 0), ("weekly", 0), ("important", 1)])
def test_personal_preferences(records, mode, expected):
    company, user, mails = records
    db.session.add(AppSetting(key=f"notification_policy:user:{company.id}:{user.id}", value=json.dumps({"mode": mode})))
    db.session.commit()
    day = date(2026, 10, 6)
    assert get_user_preference(company.id, user.id) == mode
    assert send(candidates(company, user, day, day)) == expected
    assert Notification.query.count() == 1


def test_company_opt_out_retains_site(records):
    company, user, mails = records
    db.session.add(AppSetting(key=f"notification_policy:company:{company.id}", value='{"enabled":false}'))
    db.session.commit()
    assert not get_company_policy(company.id)["enabled"]
    assert send(candidates(company, user, date(2026, 10, 5), None)) == 0
    assert Notification.query.count() == 1
    assert not mails


def test_suppression_does_not_mark_mail_delivered(app, records):
    company, user, mails = records
    app.config["MAIL_SUPPRESS_SEND"] = True
    assert send(candidates(company, user, date(2026, 10, 5), None)) == 0
    assert Notification.query.one().email_sent_at is None
    assert NotificationEmailBatch.query.count() == 0


def test_uncertain_smtp_is_not_blindly_retried(records, monkeypatch):
    company, user, mails = records
    def fail(*args):
        raise TimeoutError("simulated response timeout")
    monkeypatch.setattr("app.mail.send_mail_now", fail)
    collection = candidates(company, user, date(2026, 10, 5), None)
    assert send(collection) == 0
    assert send(collection) == 0
    assert NotificationEmailBatch.query.one().status == "uncertain"
    assert NotificationEmailEvent.query.one().status == "uncertain"
    assert Notification.query.one().email_sent_at is None


def test_closed_or_reassigned_candidate_cancels_pending(records):
    company, user, mails = records
    day = date(2026, 10, 5)
    collection = candidates(company, user, day, day)
    from app.notification_policy import _add_event
    _add_event(company.id, next(iter(collection["items"].values())), "due:0")
    db.session.commit()
    collection["items"].clear()
    assert send(collection) == 0
    assert NotificationEmailEvent.query.one().status == "cancelled"
    assert not mails


def test_notification_event_rolls_back_atomically(records):
    company, user, mails = records
    notification = Notification(company_id=company.id, user_id=user.id, message="Atama",
                                target_url="/actions/1")
    db.session.add(notification)
    queue_notification_event(notification, "action", 1, "assignment")
    assert NotificationEmailEvent.query.count() == 1
    db.session.rollback()
    assert NotificationEmailEvent.query.count() == 0
    assert Notification.query.count() == 0
    assert not mails


def test_site_dedup_and_document_approval_age(records):
    company, user, mails = records
    start = date(2026, 10, 6)
    for offset in range(5):
        collection = candidates(company, user, start + timedelta(days=offset), None,
                                kind="document-revision", created_at=start)
        assert send(collection) == int(offset in (0, 3))
    assert Notification.query.count() == 1


def test_invalid_domain_is_not_sent(records, monkeypatch):
    company, user, mails = records
    monkeypatch.setattr("app.mail._absolute_target_url", lambda *a, **k: "")
    assert send(candidates(company, user, date(2026, 10, 5), None)) == 0
    assert not mails
    assert NotificationEmailBatch.query.one().error_code == "no_current_items_or_domain"


def test_interrupted_delivery_preserves_claim_without_resending(records):
    from app.notification_policy import _add_event, reconcile_interrupted_batches
    company, user, mails = records
    day = date(2026, 10, 6)
    collection = candidates(company, user, day, day)
    event = _add_event(company.id, next(iter(collection["items"].values())), "due:0")
    batch = NotificationEmailBatch(company_id=company.id, user_id=user.id, send_date=day, status="sending")
    db.session.add(batch)
    db.session.flush()
    event.batch_id, event.status, event.attempts = batch.id, "sending", 1
    db.session.commit()
    reconcile_interrupted_batches(company.id, day + timedelta(days=1))
    assert batch.status == event.status == "uncertain"
    assert batch.error_code == "interrupted_delivery"
    assert NotificationEmailBatch.query.count() == 1
    assert send(candidates(company, user, day + timedelta(days=1), day)) == 0
    assert not mails


def test_definite_smtp_failure_retries_next_day_but_not_same_day(records, monkeypatch):
    import smtplib
    company, user, mails = records
    day = date(2026, 10, 6)
    def fail(*args):
        raise smtplib.SMTPRecipientsRefused({user.email: (450, "temporary")})
    monkeypatch.setattr("app.mail.send_mail_now", fail)
    collection = candidates(company, user, day, day)
    assert send(collection) == 0
    assert send(collection) == 0
    assert NotificationEmailEvent.query.one().attempts == 1
    monkeypatch.setattr("app.mail.send_mail_now", lambda *args: mails.append(args) or True)
    assert send(candidates(company, user, day + timedelta(days=1), day)) == 1
    assert NotificationEmailEvent.query.one().attempts == 2
    assert NotificationEmailEvent.query.one().status == "accepted"


def test_delivery_diagnostics_scoped_without_personal_content(records, app):
    company, user, _ = records
    day = date(2026, 10, 6)
    assert send(candidates(company, user, day, day)) == 1
    result = app.test_cli_runner().invoke(args=["notification-delivery-status", "--company-id", str(company.id)])
    assert result.exit_code == 0
    assert "accepted=1" in result.output
    assert user.email not in result.output
    assert user.full_name not in result.output
    result = app.test_cli_runner().invoke(args=["notification-delivery-status", "--company-id", str(company.id + 100)])
    assert "accepted=1" not in result.output


def test_policy_module_keys_exist_and_parent_disable_applies(records):
    from app.models import COMPANY_MODULE_KEYS
    from app.notification_policy import POLICY_DEFAULTS, module_is_enabled
    assert all(not rule["module"] or rule["module"] in COMPANY_MODULE_KEYS for rule in POLICY_DEFAULTS.values())
    company, user, _ = records
    db.session.add(CompanyModule(company_id=company.id, module_key="suggestions", is_enabled=False))
    db.session.commit()
    assert not module_is_enabled(company.id, "customer-portal")
