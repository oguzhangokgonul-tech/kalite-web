"""Category isolation across scheduled mail, assignment queues and integrations."""

from datetime import date, datetime, timedelta
import json
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from app.extensions import db
from app.integrations import dispatch_webhooks, publish_integration_event
from app.models import (
    Action, ActionSubTask, CompanyModule, IntegrationEvent, Notification,
    WebhookDelivery, WebhookDeliveryAttempt, WebhookEndpoint,
)
from app.notification_models import NotificationEmailEvent
from app.notification_policy import (
    _add_event, collect_reminder, dispatch_collection, queue_notification_event,
    reminder_collection, reminder_timezone,
)
from app.reminder_sources import linked_action_duplicates
from app.reminders import generate_due_reminders
from app.routes import notify_action_participants, notify_sub_action_participants, notify_users

from .helpers import create_company, create_user
from .test_action_management import make_action
from .test_integrations import api_headers, create_api_client


DAY = date(2026, 10, 6)  # Tuesday: no weekly digest can mask milestone behavior.
KINDS = ("action", "sub-action", "action-approval", "action-effectiveness")
OHS_LABEL = "\u0130SG Aksiyonu"


@pytest.fixture()
def scenario(app, monkeypatch):
    company = create_company("ohi-a")
    other = create_company("ohi-b")
    permissions = ("actions.request_close_assigned", "actions.approve_closure")
    owner = create_user("ohi-owner", company=company, permissions=permissions)
    foreign = create_user("ohi-foreign", company=other, permissions=permissions)
    owner.email, foreign.email = "owner@example.test", "foreign@example.test"
    db.session.commit()
    app.config.update(
        MAIL_ENABLED=True, MAIL_SUPPRESS_SEND=False, MAIL_SERVER="smtp.example.test",
        MAIL_DEFAULT_SENDER="notify@example.test", NOTIFICATION_AUTO_REMINDERS_ENABLED=False,
    )
    smtp = Mock(return_value=True)
    monkeypatch.setattr("app.mail.send_mail_now", smtp)
    return SimpleNamespace(company=company, other=other, owner=owner, foreign=foreign, smtp=smtp)


def set_enabled(company, enabled):
    CompanyModule.query.filter_by(company_id=company.id, module_key="ohs_actions").one().is_enabled = enabled
    db.session.commit()


def source(s, kind="action", category="ohs", due=DAY):
    action = make_action(
        s.company, s.owner, action_category=category, termin_date=due,
        action_number=Action.query.filter_by(company_id=s.company.id).count() + 1,
    )
    record = action
    if kind == "sub-action":
        record = ActionSubTask(
            company_id=s.company.id, parent_action=action, title="Inspect guard",
            responsible_id=s.owner.id, due_date=due, status="Devam Ediyor",
        )
        db.session.add(record)
    elif kind == "action-approval":
        action.closure_approval_requested = True
    elif kind == "action-effectiveness":
        action.is_completed = True
        action.effectiveness_required = True
        action.effectiveness_owner_user_id = s.owner.id
        action.effectiveness_due_date = due
    db.session.commit()
    return action, record


def collection_for(s, day=DAY):
    result = generate_due_reminders(s.company.id, day, kinds=set(KINDS))
    db.session.commit()
    return result["_collection"]


def send(collection, hour=8, minute=30):
    now = datetime.combine(collection["run_date"], datetime.min.time()).replace(
        hour=hour, minute=minute, tzinfo=reminder_timezone(),
    )
    return dispatch_collection(collection, now=now)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("enabled", [True, False])
def test_sources_obey_category_module_and_keep_general(scenario, kind, enabled):
    s = scenario
    ohs, ohs_record = source(s, kind)
    general, general_record = source(s, kind, "general")
    set_enabled(s.company, enabled)
    collection = collection_for(s)
    assert ((s.owner.id, kind, ohs_record.id) in collection["items"]) is enabled
    assert (s.owner.id, kind, general_record.id) in collection["items"]
    assert all(n.company_id == s.company.id and n.user_id == s.owner.id for n in Notification.query.all())
    if enabled:
        item = collection["items"][(s.owner.id, kind, ohs_record.id)]
        assert item["title"].startswith(OHS_LABEL)
        assert item["message"].startswith(OHS_LABEL)
        assert item["target_url"] == f"/actions/{ohs.id}"
        assert item["notification"].action_id == ohs.id
    else:
        assert not Notification.query.filter_by(action_id=ohs.id).count()
    assert send(collection) == 1
    body = s.smtp.call_args.args[3]
    assert f"https://{s.company.slug}.volkaportal.com/actions/{general.id}" in body
    assert (f"https://{s.company.slug}.volkaportal.com/actions/{ohs.id}" in body) is enabled


def test_collect_rejects_foreign_records_and_recipients(scenario):
    s = scenario
    own, _ = source(s)
    foreign = make_action(s.other, s.foreign, action_category="ohs", termin_date=DAY)
    with reminder_collection(s.company.id, DAY) as collection:
        for action in (own, foreign):
            collect_reminder(
                [s.owner, s.foreign], company_id=s.company.id, kind="action", record_id=action.id,
                title="Assigned", message="Inspect", target_url=f"/actions/{action.id}", due_date=DAY,
            )
    db.session.commit()
    assert set(collection["items"]) == {(s.owner.id, "action", own.id)}
    assert send(collection) == 1
    _, recipients, _, body = s.smtp.call_args.args
    assert recipients == [s.owner.email]
    assert f"https://{s.company.slug}.volkaportal.com/actions/{own.id}" in body
    assert f"/actions/{foreign.id}" not in body
    assert s.other.slug not in body


@pytest.mark.parametrize("kind", ["action", "sub-action"])
def test_assignment_queues_without_immediate_mail_and_uses_tenant_url(scenario, kind):
    s = scenario
    action, record = source(s, kind, due=DAY + timedelta(days=20))
    action.related_user_1_id = s.foreign.id
    if kind == "action":
        notify_action_participants(action, "Assigned", email_event="assignment")
    else:
        record.related_user_1_id = s.foreign.id
        notify_sub_action_participants(record, "Assigned", email_event="assignment")
    db.session.commit()
    event = NotificationEmailEvent.query.one()
    assert (event.company_id, event.user_id, event.kind, event.record_id) == (
        s.company.id, s.owner.id, kind, record.id,
    )
    assert event.phase.startswith("event:assignment:") and event.status == "pending"
    assert event.title.startswith(OHS_LABEL) and event.message.startswith(OHS_LABEL)
    assert Notification.query.one().email_sent_at is None
    s.smtp.assert_not_called()
    with reminder_collection(s.company.id, DAY) as collection:
        pass
    assert send(collection, hour=8, minute=29) == 0
    assert send(collection) == 1
    assert send(collection) == 0
    _, recipients, _, body = s.smtp.call_args.args
    assert recipients == [s.owner.email]
    assert f"https://{s.company.slug}.volkaportal.com/actions/{action.id}" in body
    assert OHS_LABEL in body and s.other.slug not in body


@pytest.mark.parametrize("kind", KINDS)
def test_disabled_or_foreign_action_cannot_enter_assignment_queue(scenario, kind):
    s = scenario
    action, record = source(s, kind)
    notification = Notification(
        company_id=s.company.id, user_id=s.owner.id, message="Assigned",
        target_url=f"/actions/{action.id}", due_date=DAY,
    )
    db.session.add(notification)
    db.session.commit()
    set_enabled(s.company, False)
    queue_notification_event(notification, kind, record.id, "assignment")
    assert NotificationEmailEvent.query.count() == 0
    set_enabled(s.company, True)
    notification.company_id, notification.user_id = s.other.id, s.foreign.id
    db.session.commit()
    queue_notification_event(notification, kind, record.id, "assignment")
    assert NotificationEmailEvent.query.count() == 0
    s.smtp.assert_not_called()


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("status", ["pending", "failed"])
@pytest.mark.parametrize("phase", ["due:0", "event:assignment:legacy"])
def test_disabling_module_cancels_queued_events_even_with_stale_collection(scenario, kind, status, phase):
    s = scenario
    _, record = source(s, kind)
    collection = collection_for(s)
    item = collection["items"][(s.owner.id, kind, record.id)]
    event = _add_event(s.company.id, item, phase)
    event.status = status
    event.attempts = int(status == "failed")
    db.session.commit()
    set_enabled(s.company, False)
    collection["refresh_sources"] = False
    assert send(collection) == 0
    assert event.status == "cancelled"
    assert event.attempts == int(status == "failed")
    assert NotificationEmailEvent.query.count() == 1
    assert item["notification"].email_sent_at is None
    s.smtp.assert_not_called()


def test_failed_assignment_is_not_resent_after_module_disabled(scenario):
    s = scenario
    action, _ = source(s, due=DAY + timedelta(days=20))
    notify_action_participants(action, "Assigned", email_event="assignment")
    db.session.commit()
    s.smtp.return_value = False
    assert send(collection_for(s)) == 0
    event = NotificationEmailEvent.query.one()
    assert event.status == "failed" and event.attempts == 1
    set_enabled(s.company, False)
    s.smtp.return_value = True
    assert send(collection_for(s, DAY + timedelta(days=1))) == 0
    assert event.status == "cancelled" and event.attempts == 1
    assert s.smtp.call_count == 1


@pytest.mark.parametrize("kind", ["action-approval", "action-effectiveness"])
def test_ohs_approval_event_routes_to_existing_review_kind(scenario, kind):
    s = scenario
    action, _ = source(s, kind, due=DAY + timedelta(days=20))
    notify_users({s.owner.id}, action, "Review requested", email_event="approval")
    db.session.commit()
    event = NotificationEmailEvent.query.one()
    assert event.kind == kind and event.record_id == action.id
    assert event.phase.startswith("event:approval:")
    assert send(collection_for(s)) == 1
    assert event.status == "accepted"
    assert OHS_LABEL in s.smtp.call_args.args[3]


def test_module_disable_between_recipients_revokes_second_digest(scenario):
    s = scenario
    source(s)
    second = create_user("ohi-second", company=s.company, permissions=("actions.request_close_assigned",))
    second.email = "second@example.test"
    make_action(s.company, second, action_category="ohs", action_number=2, termin_date=DAY)
    collection = collection_for(s)

    def disable_after_first(*args):
        set_enabled(s.company, False)
        return True

    s.smtp.side_effect = disable_after_first
    assert send(collection) == 1
    s.smtp.assert_called_once()
    events = NotificationEmailEvent.query.all()
    assert len(events) == 2
    assert sorted(event.status for event in events) == ["accepted", "cancelled"]
    assert sum(n.email_sent_at is not None for n in Notification.query.all()) == 1


@pytest.mark.parametrize("offset,expected", [(7, 1), (6, 0), (0, 1), (-1, 0)])
def test_ohs_keeps_existing_action_milestones(scenario, offset, expected):
    source(scenario, due=DAY + timedelta(days=offset))
    assert send(collection_for(scenario)) == expected


def test_ohs_keeps_weekly_overdue_policy(scenario):
    source(scenario, due=DAY - timedelta(days=30))
    assert send(collection_for(scenario)) == 0
    assert send(collection_for(scenario, DAY + timedelta(days=6))) == 1


def test_disabled_linked_action_does_not_suppress_other_source(scenario):
    s = scenario
    action, _ = source(s)
    assert linked_action_duplicates(action, s.company.id, s.owner.id, DAY)
    set_enabled(s.company, False)
    assert not linked_action_duplicates(action, s.company.id, s.owner.id, DAY)


@pytest.mark.parametrize("enabled", [True, False])
def test_api_remains_general_only_with_tenant_and_status_filters(scenario, client, enabled):
    s = scenario
    general, _ = source(s, category="general")
    ohs, _ = source(s)
    foreign = make_action(s.other, s.foreign, action_category="general")
    set_enabled(s.company, enabled)
    _, token = create_api_client(s.company, scopes=["actions:read"])
    headers = api_headers(token)
    for query in ("", "?status=open", "?action_category=ohs"):
        response = client.get("/api/v1/actions" + query, headers=headers,
                              base_url=f"https://{s.other.slug}.volkaportal.com")
        assert response.status_code == 200
        assert [row["id"] for row in response.get_json()["data"]] == [general.id]
    assert client.get(f"/api/v1/actions/{general.id}", headers=headers).status_code == 200
    for hidden in (ohs, foreign):
        assert client.get(f"/api/v1/actions/{hidden.id}", headers=headers).status_code == 404
    ohs.is_completed = True
    db.session.commit()
    assert client.get("/api/v1/actions?status=completed", headers=headers).get_json()["data"] == []


@pytest.mark.parametrize("enabled", [True, False])
def test_ohs_never_emits_general_action_domain_events(scenario, enabled):
    s = scenario
    set_enabled(s.company, enabled)
    ohs, _ = source(s)
    general, _ = source(s, category="general")
    for action in (ohs, general):
        action.title = "Updated"
        db.session.commit()
        action.is_completed = True
        db.session.commit()
    events = IntegrationEvent.query.filter(IntegrationEvent.event_type.like("action.%")).all()
    assert {e.subject_id for e in events} == {str(general.id)}
    assert {e.event_type for e in events} == {"action.created", "action.updated", "action.completed"}


@pytest.mark.parametrize("queued_status", [None, "pending", "retry"])
@pytest.mark.parametrize("enabled", [True, False])
@pytest.mark.parametrize("action_state", ["present", "deleted"])
def test_legacy_ohs_webhooks_are_blocked_before_network(scenario, monkeypatch, queued_status, enabled, action_state):
    s = scenario
    ohs, _ = source(s)
    general, _ = source(s, category="general")
    set_enabled(s.company, enabled)
    endpoint = WebhookEndpoint(
        company_id=s.company.id, name="ERP", endpoint_url="https://hooks.example.test/events",
        events_json=json.dumps(["action.created"]), secret_ciphertext="test", secret_hint="test",
    )
    db.session.add(endpoint)
    legacy = publish_integration_event(
        company_id=s.company.id, event_type="action.created", subject_type="Action",
        subject_id=ohs.id, payload={"id": ohs.id, "title": "Legacy private OHS"},
    )
    delivery = None
    if queued_status:
        legacy.dispatched_at = datetime.now()
        delivery = WebhookDelivery(
            company_id=s.company.id, delivery_uuid=str(uuid4()), endpoint=endpoint,
            event=legacy, status=queued_status, attempt_count=int(queued_status == "retry"),
        )
        db.session.add(delivery)
    db.session.commit()
    if action_state == "deleted":
        db.session.delete(ohs)
        db.session.commit()
    resolve = Mock(return_value=SimpleNamespace())
    post = Mock(return_value=(204, {}))
    monkeypatch.setattr("app.integrations.resolve_webhook_target", resolve)
    monkeypatch.setattr("app.integrations.decrypt_secret", lambda value: "test-secret")
    monkeypatch.setattr("app.integrations._post_webhook", post)
    dispatch_webhooks()
    post.assert_called_once()
    resolve.assert_called_once()
    assert json.loads(post.call_args.args[1])["data"]["id"] == general.id
    assert legacy.dispatched_at is not None
    if delivery:
        assert delivery.status == "failed"
        assert delivery.last_error_code == "action_category_not_exported"
        assert delivery.next_attempt_at is None and delivery.locked_at is None
        assert delivery.attempt_count == int(queued_status == "retry")
        assert not WebhookDeliveryAttempt.query.filter_by(delivery_id=delivery.id).count()
    else:
        assert not WebhookDelivery.query.filter_by(integration_event_id=legacy.id).count()


@pytest.mark.parametrize("queued_status", [None, "pending", "retry"])
def test_deleted_general_action_events_fail_closed(scenario, monkeypatch, queued_status):
    s = scenario
    deleted, _ = source(s, category="general")
    retained, _ = source(s, category="general")
    event = IntegrationEvent.query.filter_by(
        company_id=s.company.id, event_type="action.created", subject_id=str(deleted.id),
    ).one()
    endpoint = WebhookEndpoint(
        company_id=s.company.id, name="ERP", endpoint_url="https://hooks.example.test/events",
        events_json=json.dumps(["action.created"]), secret_ciphertext="test", secret_hint="test",
    )
    db.session.add(endpoint)
    delivery = None
    if queued_status:
        event.dispatched_at = datetime.now()
        delivery = WebhookDelivery(
            company_id=s.company.id, delivery_uuid=str(uuid4()), endpoint=endpoint,
            event=event, status=queued_status, attempt_count=int(queued_status == "retry"),
        )
        db.session.add(delivery)
    db.session.commit()
    db.session.delete(deleted)
    db.session.commit()
    resolve = Mock(return_value=SimpleNamespace())
    post = Mock(return_value=(204, {}))
    monkeypatch.setattr("app.integrations.resolve_webhook_target", resolve)
    monkeypatch.setattr("app.integrations.decrypt_secret", lambda value: "test-secret")
    monkeypatch.setattr("app.integrations._post_webhook", post)
    dispatch_webhooks()
    post.assert_called_once()
    resolve.assert_called_once()
    assert json.loads(post.call_args.args[1])["data"]["id"] == retained.id
    assert event.dispatched_at is not None
    if delivery:
        assert delivery.status == "failed"
        assert delivery.last_error_code == "action_category_not_exported"
        assert delivery.attempt_count == int(queued_status == "retry")
        assert delivery.next_attempt_at is None and delivery.locked_at is None
        assert not WebhookDeliveryAttempt.query.filter_by(delivery_id=delivery.id).count()
    else:
        assert not WebhookDelivery.query.filter_by(integration_event_id=event.id).count()
