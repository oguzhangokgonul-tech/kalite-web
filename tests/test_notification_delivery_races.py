"""Independent dispatch regressions for send-time ownership and review events."""

from datetime import date, datetime, timedelta

import pytest

from app import routes
from app.extensions import db
from app.models import Action, Dof, DOF_EFFECTIVENESS_STATUS, Notification
from app.notification_models import NotificationEmailBatch, NotificationEmailEvent
from app.notification_policy import dispatch_collection, reminder_timezone
from app.reminders import generate_due_reminders

from .helpers import create_company, create_user


DAY = date(2026, 10, 6)
SEND_AT = datetime(2026, 10, 6, 8, 30, tzinfo=reminder_timezone())


@pytest.fixture()
def delivery_company(app):
    app.config.update(
        MAIL_ENABLED=True,
        MAIL_SERVER="smtp.example.test",
        MAIL_DEFAULT_SENDER="notify@example.test",
        MAIL_SUPPRESS_SEND=False,
    )
    return create_company("delivery-qa")


def delivery_user(company, name):
    user = create_user(
        name, company=company, permissions=("actions.request_close_assigned",),
    )
    user.email = f"{name}@example.test"
    db.session.commit()
    return user


def test_dispatch_does_not_email_owner_reassigned_between_recipient_sends(
    delivery_company, monkeypatch,
):
    company = delivery_company
    owners = [delivery_user(company, f"delivery-owner-{number}") for number in (1, 2)]
    replacement = delivery_user(company, "delivery-replacement")
    actions = {}
    for number, owner in enumerate(owners, start=1):
        action = Action(
            company_id=company.id, action_number=number,
            title=f"Confidential delivery task {number}",
            responsible_owner=owner.full_name, responsible_user_id=owner.id,
            termin_date=DAY,
        )
        db.session.add(action)
        actions[owner.email] = action
    db.session.commit()
    collection = generate_due_reminders(company.id, DAY)["_collection"]
    db.session.commit()
    assert {item["user_id"] for item in collection["items"].values()} == {
        owner.id for owner in owners
    }
    mails = []
    reassigned = {}

    def send_mail(settings, recipients, subject, body):
        mails.append((tuple(recipients), subject, body))
        if len(mails) == 1:
            # Commit after the initial refresh, before the other recipient is sent.
            former_email = next(email for email in actions if email not in recipients)
            action = actions[former_email]
            reassigned.update(email=former_email, user_id=action.responsible_user_id,
                              record_id=action.id)
            action.responsible_user_id = replacement.id
            action.responsible_owner = replacement.full_name
            db.session.commit()
        return True

    monkeypatch.setattr("app.mail.send_mail_now", send_mail)
    sent = dispatch_collection(collection, now=SEND_AT)

    assert reassigned, "The test must cross a real SMTP boundary before reassignment"
    assert all(reassigned["email"] not in recipients for recipients, _, _ in mails), (
        "A committed reassignment must revoke the former owner's queued digest item"
    )
    assert sent == len(mails) == 1
    event = NotificationEmailEvent.query.filter_by(
        user_id=reassigned["user_id"], kind="action", record_id=reassigned["record_id"],
    ).one()
    assert event.status != "accepted"
    assert event.accepted_at is None
    assert db.session.get(Notification, event.notification_id).email_sent_at is None


@pytest.mark.parametrize("kind", ["action", "dof"])
def test_dispatch_sends_effectiveness_approval_to_separate_assigned_reviewer(
    delivery_company, monkeypatch, kind,
):
    company = delivery_company
    owner = delivery_user(company, "effectiveness-original-owner")
    reviewer = delivery_user(company, "effectiveness-reviewer")
    # Tuesday and T-14: only the approval event can trigger this delivery.
    due = DAY + timedelta(days=14)
    fields = dict(
        company_id=company.id, title="Effectiveness delivery QA",
        effectiveness_required=True, effectiveness_owner_user_id=reviewer.id,
        effectiveness_due_date=due, effectiveness_result="Bekliyor",
        effectiveness_checked_at=None,
    )
    if kind == "action":
        record = Action(
            **fields, responsible_owner=owner.full_name, responsible_user_id=owner.id,
            termin_date=due, is_completed=True, completed_at=DAY,
        )
    else:
        record = Dof(
            **fields, dof_no="IF-DELIVERY-QA", responsible_id=owner.id,
            due_date=due, approval_step="effectiveness_review",
            status=DOF_EFFECTIVENESS_STATUS,
        )
    db.session.add(record)
    db.session.flush()
    # Use the helpers called by complete_action / approve_dof_deputy, not a mock queue.
    if kind == "action":
        routes.notify_users({reviewer.id}, record, "Review effectiveness", email_event="approval")
    else:
        routes.notify_dof_users([reviewer], record, "Review effectiveness", email_event="approval")
    db.session.commit()
    event = NotificationEmailEvent.query.one()
    assert event.user_id == reviewer.id
    assert event.phase == f"event:approval:{event.notification_id}"
    assert event.due_date == due
    collection = generate_due_reminders(company.id, DAY)["_collection"]
    db.session.commit()
    assert (reviewer.id, f"{kind}-effectiveness", record.id) in collection["items"]
    mails = []
    monkeypatch.setattr("app.mail.send_mail_now", lambda *args: mails.append(args) or True)

    assert dispatch_collection(collection, now=SEND_AT) == 1
    assert len(mails) == 1
    assert mails[0][1] == [reviewer.email]
    assert f"/{'actions' if kind == 'action' else 'dofs'}/{record.id}" in mails[0][3]
    db.session.refresh(event)
    assert event.kind == f"{kind}-effectiveness"
    assert event.status == "accepted"
    assert event.accepted_at is not None
    assert db.session.get(Notification, event.notification_id).email_sent_at is not None
    assert NotificationEmailBatch.query.one().status == "accepted"
    assert dispatch_collection(collection, now=SEND_AT) == 0
    assert len(mails) == 1
