"""Independent regressions for current workflow ownership and email policy."""

from datetime import date, datetime, timedelta
import json

import pytest

from app import routes
from app.extensions import db
from app.models import Action, AppSetting, Dof, DOF_EFFECTIVENESS_STATUS, Notification
from app.notification_models import NotificationEmailBatch, NotificationEmailEvent
from app.notification_policy import dispatch_collection, reminder_timezone
from app.reminders import generate_due_reminders

from .helpers import create_company, create_user


DAY = date(2026, 10, 6)
SEND_AT = datetime(2026, 10, 6, 8, 30, tzinfo=reminder_timezone())


@pytest.fixture()
def delivery(app, monkeypatch):
    app.config.update(
        MAIL_ENABLED=True,
        MAIL_SERVER="smtp.example.test",
        MAIL_DEFAULT_SENDER="notify@example.test",
        MAIL_SUPPRESS_SEND=False,
    )
    company = create_company("routing-regression")
    mails = []
    monkeypatch.setattr("app.mail.send_mail_now", lambda *args: mails.append(args) or True)
    return company, mails


def recipient(company, name):
    user = create_user(
        name, company=company,
        permissions=("actions.request_close_assigned", "actions.approve_closure"),
    )
    user.email = f"{name}@example.test"
    db.session.commit()
    return user


def collect(company):
    collection = generate_due_reminders(company.id, DAY)["_collection"]
    db.session.commit()
    return collection


def closure_request(company, owner):
    # Tuesday at T-14 excludes deadline and weekly triggers from these probes.
    action = Action(
        company_id=company.id, action_number=1, title="Closure approval QA",
        responsible_owner=owner.full_name, responsible_user_id=owner.id,
        termin_date=DAY + timedelta(days=14), closure_approval_requested=True,
    )
    db.session.add(action)
    db.session.flush()
    routes.notify_users(
        {owner.id}, action, "Closure approval required", email_event="approval",
    )
    db.session.commit()
    return action, NotificationEmailEvent.query.one()


@pytest.mark.parametrize("queued_assignment", [False, True])
def test_effectiveness_stage_dof_only_emails_current_reviewer(delivery, queued_assignment):
    company, mails = delivery
    owner = recipient(company, "dof-original-owner")
    reviewer = recipient(company, "dof-current-reviewer")
    dof = Dof(
        company_id=company.id, dof_no="IF-ROUTING-QA", title="Effectiveness routing QA",
        responsible_id=owner.id, due_date=DAY, approval_step="revision_requested",
        status="Revizyon Bekleniyor", effectiveness_required=True,
        effectiveness_owner_user_id=reviewer.id, effectiveness_due_date=DAY,
        effectiveness_result="Bekliyor",
    )
    db.session.add(dof)
    db.session.flush()
    if queued_assignment:
        routes.notify_dof_users([owner], dof, "Assigned to you", email_event="assignment")
    db.session.commit()
    old_event = NotificationEmailEvent.query.one_or_none()
    if queued_assignment:
        assert old_event is not None and old_event.kind == "dof"

    dof.approval_step = "effectiveness_review"
    dof.status = DOF_EFFECTIVENESS_STATUS
    db.session.commit()
    collection = collect(company)

    assert dispatch_collection(collection, now=SEND_AT) == 1
    assert len(mails) == 1 and mails[0][1] == [reviewer.email]
    assert (owner.id, "dof", dof.id) not in collection["items"]
    assert (reviewer.id, "dof-effectiveness", dof.id) in collection["items"]
    assert f"/dofs/{dof.id}" in mails[0][3]
    accepted = NotificationEmailEvent.query.filter_by(status="accepted").one()
    assert (accepted.user_id, accepted.kind) == (reviewer.id, "dof-effectiveness")
    if old_event is not None:
        db.session.refresh(old_event)
        assert old_event.status == "cancelled"
        assert old_event.accepted_at is None
        assert db.session.get(Notification, old_event.notification_id).email_sent_at is None
    assert dispatch_collection(collection, now=SEND_AT) == 0
    assert len(mails) == 1


@pytest.mark.parametrize(
    "approval_email,action_email,expected",
    [(False, True, 0), (True, False, 1), (True, True, 1)],
)
def test_closure_approval_obeys_its_own_policy(delivery, approval_email, action_email, expected):
    company, mails = delivery
    owner = recipient(company, "closure-policy-owner")
    action, event = closure_request(company, owner)
    db.session.add(AppSetting(
        key=f"notification_policy:company:{company.id}",
        value=json.dumps({"modules": {
            "action-approval": {"email": approval_email},
            "action": {"email": action_email},
        }}),
    ))
    db.session.commit()
    collection = collect(company)

    assert dispatch_collection(collection, now=SEND_AT) == expected
    assert len(mails) == expected
    db.session.refresh(event)
    assert event.kind == "action-approval"
    assert event.phase == f"event:approval:{event.notification_id}"
    notification = db.session.get(Notification, event.notification_id)
    if expected:
        assert mails[0][1] == [owner.email]
        assert f"/actions/{action.id}" in mails[0][3]
        assert event.status == "accepted" and event.accepted_at is not None
        assert notification.email_sent_at is not None
        assert NotificationEmailBatch.query.one().status == "accepted"
    else:
        assert event.status == "cancelled" and event.accepted_at is None
        assert notification.email_sent_at is None
        assert NotificationEmailBatch.query.count() == 0


@pytest.mark.parametrize("legacy_kind", [False, True])
def test_cancelled_closure_approval_is_not_sent_to_current_owner(delivery, legacy_kind):
    company, mails = delivery
    owner = recipient(company, "obsolete-approval-owner")
    action, event = closure_request(company, owner)
    if legacy_kind:
        # Exercise the queued event shape used before closure-specific routing.
        event.kind = "action"
    action.closure_approval_requested = False
    db.session.commit()
    collection = collect(company)
    assert (owner.id, "action", action.id) in collection["items"]
    assert (owner.id, "action-approval", action.id) not in collection["items"]

    assert dispatch_collection(collection, now=SEND_AT) == 0
    assert mails == []
    db.session.refresh(event)
    assert event.status == "cancelled"
    assert event.accepted_at is None
    assert db.session.get(Notification, event.notification_id).email_sent_at is None
    assert NotificationEmailBatch.query.count() == 0
