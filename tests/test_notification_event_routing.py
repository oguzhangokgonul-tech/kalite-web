from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app import mail, notification_policy, routes
from app.extensions import db
from app.models import Action, ActionSubTask, Dof, DocumentRevisionRequest, Notification
from app.notification_models import NotificationEmailEvent
from app.notifications import add_user_notification

from .helpers import create_company, create_user, login, make_document
from .test_action_management import action_payload, make_action


@pytest.fixture()
def queue(monkeypatch):
    queue = Mock(return_value=None)
    monkeypatch.setattr(notification_policy, "queue_notification_event", queue)
    return queue


@pytest.fixture()
def recipients(app):
    company = create_company("901")
    other_company = create_company("902")
    owner = create_user("event-owner", company=company)
    creator = create_user("event-creator", company=company)
    foreign = create_user("event-foreign", company=other_company)
    inactive = create_user("event-inactive", company=company)
    platform = create_user("event-platform", role_key="super_admin")
    inactive.is_active = False
    db.session.commit()
    return company, owner, creator, foreign, inactive, platform


@pytest.mark.parametrize("event", ["assignment", "approval", "rejected", "rescheduled"])
def test_action_events_only_queue_original_active_tenant_recipients(recipients, queue, event):
    company, owner, creator, foreign, inactive, platform = recipients
    action = make_action(company, owner)
    routes.notify_users(
        {user.id for user in (owner, creator, foreign, inactive, platform)},
        action, "Important event", exclude_user_id=creator.id, email_event=event,
    )
    notification = Notification.query.one()
    assert notification.user_id == owner.id
    assert notification.company_id == company.id
    assert notification.email_sent_at is None
    assert notification.due_date == action.termin_date
    queue.assert_called_once_with(notification, "action", action.id, event)


def test_routine_notifications_are_site_only(recipients, queue):
    company, owner, *_ = recipients
    action = make_action(company, owner)
    for message in ("Comment", "File uploaded", "Progress updated"):
        routes.notify_users({owner.id}, action, message)
    assert Notification.query.count() == 3
    assert all(row.email_sent_at is None for row in Notification.query.all())
    queue.assert_not_called()


def test_previous_action_owner_gets_site_only(recipients, queue):
    company, owner, old_owner, *_ = recipients
    action = make_action(company, owner)
    routes.notify_action_participants(
        action, "Reassigned", extra_user_ids={old_owner.id, owner.id}, email_event="assignment",
    )
    assert {row.user_id for row in Notification.query.all()} == {owner.id, old_owner.id}
    assert queue.call_count == 1
    assert queue.call_args.args[0].user_id == owner.id


def test_related_action_user_stays_site_only(recipients, queue):
    company, owner, related, *_ = recipients
    action = make_action(company, owner, related_user_1_id=related.id)
    routes.notify_action_participants(action, "Assigned", email_event="assignment")
    assert {row.user_id for row in Notification.query.all()} == {owner.id, related.id}
    queue.assert_called_once()
    assert queue.call_args.args[0].user_id == owner.id


@pytest.mark.parametrize("event", [None, "assignment", "rescheduled"])
def test_sub_action_uses_its_own_identity_and_only_current_owner(recipients, queue, event):
    company, owner, parent_owner, foreign, *_ = recipients
    action = make_action(company, parent_owner)
    sub_action = ActionSubTask(
        company_id=company.id, parent_action=action, title="Sub task",
        responsible_id=owner.id, related_user_1_id=foreign.id,
    )
    db.session.add(sub_action)
    db.session.flush()
    routes.notify_sub_action_participants(sub_action, "Sub task update", email_event=event)
    assert {row.user_id for row in Notification.query.all()} == {owner.id, parent_owner.id}
    if event:
        queue.assert_called_once()
        assert queue.call_args.args[0].user_id == owner.id
        assert queue.call_args.args[1:] == ("sub-action", sub_action.id, event)
    else:
        queue.assert_not_called()


@pytest.mark.parametrize("event", [None, "assignment", "approval", "rejected", "rescheduled", "result"])
def test_dof_events_preserve_site_recipients_but_results_only_go_to_creator(recipients, queue, event):
    company, owner, creator, foreign, inactive, platform = recipients
    dof = Dof(company_id=company.id, dof_no="IF-901", responsible=owner, created_by=creator)
    db.session.add(dof)
    db.session.flush()
    routes.notify_dof_users(
        [owner, creator, foreign, inactive, platform, owner], dof, "Event", email_event=event,
    )
    notifications = Notification.query.all()
    assert {row.user_id for row in notifications} == {owner.id, creator.id}
    assert all(row.email_sent_at is None for row in notifications)
    expected = set() if event is None else {creator.id} if event == "result" else {owner.id, creator.id}
    assert {call.args[0].user_id for call in queue.call_args_list} == expected
    assert all(call.args[1:] == ("dof", dof.id, event) for call in queue.call_args_list)


@pytest.mark.parametrize("event", [None, "approval", "result"])
def test_document_events_only_queue_valid_requester_or_explicit_approvers(app, recipients, queue, event):
    company, owner, requester, foreign, inactive, platform = recipients
    document = make_document(app, company)
    revision = DocumentRevisionRequest(
        company_id=company.id, document=document, requested_by=requester, explanation="Revision",
    )
    db.session.add(revision)
    db.session.flush()
    routes.notify_document_revision_request(
        [owner, requester, foreign, inactive, platform], revision, "Event", email_event=event,
    )
    assert {row.user_id for row in Notification.query.all()} == {owner.id, requester.id}
    expected = set() if event is None else {requester.id} if event == "result" else {owner.id, requester.id}
    assert {call.args[0].user_id for call in queue.call_args_list} == expected
    assert all(call.args[1:] == ("document-revision", revision.id, event) for call in queue.call_args_list)
    assert all(row.email_sent_at is None for row in Notification.query.all())


def test_foreign_creator_cannot_receive_result(recipients, queue):
    company, owner, _, foreign, *_ = recipients
    dof = Dof(company_id=company.id, dof_no="IF-902", responsible=owner, created_by=foreign)
    db.session.add(dof)
    db.session.flush()
    routes.notify_dof_users([owner, foreign], dof, "Completed", email_event="result")
    assert Notification.query.one().user_id == owner.id
    queue.assert_not_called()


def test_notification_record_company_must_match_recipient(recipients, queue):
    company, owner, _, foreign, *_ = recipients
    action = make_action(company, owner)
    assert add_user_notification(foreign, "No leak", action=action) is None
    assert add_user_notification(
        foreign, "No explicit override", action=action, company_id=foreign.company_id,
    ) is None
    assert Notification.query.count() == 0
    queue.assert_not_called()


def test_deduped_site_notification_does_not_enqueue_twice(recipients, queue):
    company, owner, *_ = recipients
    action = make_action(company, owner)
    kwargs = dict(action=action, source_key="assignment:901", email_event="assignment")
    first = add_user_notification(owner, "Assigned", **kwargs)
    second = add_user_notification(owner, "Assigned", **kwargs)
    assert first is not None and second is None
    assert first.email_sent_at is None
    queue.assert_called_once_with(first, "action", action.id, "assignment")


def test_notification_and_real_event_roll_back_together(recipients):
    company, owner, *_ = recipients
    action = make_action(company, owner)
    routes.notify_users({owner.id}, action, "Assigned", email_event="assignment")
    assert Notification.query.count() == 1
    event = NotificationEmailEvent.query.one()
    assert event.kind == "action" and event.record_id == action.id
    assert event.phase.startswith("event:assignment:")
    assert event.status == "pending" and event.accepted_at is None
    assert Notification.query.one().email_sent_at is None
    db.session.rollback()
    assert Notification.query.count() == 0
    assert NotificationEmailEvent.query.count() == 0


@pytest.mark.parametrize("entry_point,args", [
    ("send_action_notification_email", ([], None, "Assigned")),
    ("send_dof_notification_email", ([], None, "Approval")),
    ("send_document_revision_request_email", ([], None, "Approval")),
    ("send_vehicle_reminder_email", ([], None, "Due", None, "Today")),
    ("send_generic_notification_email", ([], "Internal portal update")),
])
def test_legacy_operational_mail_never_submits_or_reports_delivery(app, monkeypatch, entry_point, args):
    submit = Mock()
    smtp = Mock()
    monkeypatch.setattr(mail._mail_executor, "submit", submit)
    monkeypatch.setattr(mail, "send_mail_now", smtp)
    app.config.update(MAIL_ENABLED=True, MAIL_SERVER="smtp.test", MAIL_DEFAULT_SENDER="mail@test")
    users = [SimpleNamespace(email="owner@test")]
    assert getattr(mail, entry_point)(users, *args[1:]) is False
    submit.assert_not_called()
    smtp.assert_not_called()


def test_transactional_verification_mail_is_unchanged(app, monkeypatch):
    submit = Mock()
    monkeypatch.setattr(mail._mail_executor, "submit", submit)
    app.config.update(MAIL_ENABLED=True, MAIL_SERVER="smtp.test", MAIL_DEFAULT_SENDER="mail@test")
    assert mail.send_recipient_email("customer@test", "Verify", "Requested verification") is True
    assert submit.call_args.args[2:5] == (["customer@test"], "Verify", "Requested verification")


def test_vehicle_dashboard_does_not_send_or_commit(app, monkeypatch):
    vehicle_query = Mock()
    vehicle_query.return_value.all.return_value = []
    send = Mock()
    commit = Mock()
    monkeypatch.setattr(routes, "vehicle_query", vehicle_query)
    monkeypatch.setattr(routes, "can_manage_vehicles", lambda: True)
    monkeypatch.setattr(routes, "send_vehicle_due_reminders", send)
    monkeypatch.setattr(db.session, "commit", commit)
    assert routes.vehicle_dashboard_context()["vehicles"] == []
    send.assert_not_called()
    commit.assert_not_called()


def test_action_route_classifies_creation_comment_reassignment_and_deadline(client, queue):
    company = create_company("903")
    manager = create_user("event-manager", company=company, role_key="management_representative")
    owner = create_user("event-first-owner", company=company)
    new_owner = create_user("event-next-owner", company=company)
    login(client, manager, company)

    assert client.post("/actions/new", data=action_payload(owner)).status_code == 302
    action = Action.query.one()
    assert queue.call_args.args[1:] == ("action", action.id, "assignment")
    assert queue.call_args.args[0].user_id == owner.id

    queue.reset_mock()
    assert client.post(f"/actions/{action.id}/comments", data={"comment": "Routine note"}).status_code == 302
    queue.assert_not_called()

    assert client.post(f"/actions/{action.id}/reassign", data={"responsible_user_id": new_owner.id}).status_code == 302
    assert queue.call_count == 1
    assert queue.call_args.args[0].user_id == new_owner.id
    assert queue.call_args.args[-1] == "assignment"

    queue.reset_mock()
    deadline = (date.today() + timedelta(days=300)).isoformat()
    assert client.post(f"/actions/{action.id}/revise-termin", data={"termin_date": deadline}).status_code == 302
    assert queue.call_count == 1
    assert queue.call_args.args[0].user_id == new_owner.id
    assert queue.call_args.args[-1] == "rescheduled"
    assert all(row.email_sent_at is None for row in Notification.query.all())
