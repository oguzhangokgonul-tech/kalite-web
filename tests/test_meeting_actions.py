import json
from datetime import date, timedelta
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest
from flask import g

from app import meetings, routes
from app.extensions import db
from app.meeting_models import MeetingDecisionAction
from app.models import (
    Action, ActionHistory, ActionSubTask, AppSetting, AuditLog, CompanyDepartment,
    CompanyModule, MeetingDecision, MeetingParticipant, Role, UserPermission,
)
from app.models import Notification
from tests.helpers import create_company, create_user, login, upload_tuple
from tests.test_action_management import action_payload
from tests.test_meetings import add_decision, create_meeting, transition


@pytest.fixture()
def action_scenario(client):
    company = create_company("MTGA")
    manager = create_user("meeting-action-manager", company=company, role_key="department_manager")
    owner = create_user("meeting-action-owner", company=company, role_key="department_staff")
    db.session.add(CompanyDepartment(company_id=company.id, name="Meeting Quality", is_active=True))
    db.session.commit()
    login(client, manager, company)
    meeting = create_meeting(client, owner, title="Action planning meeting")
    assert add_decision(client, meeting, owner, title="Inspect the production checklist").status_code == 302
    decision = MeetingDecision.query.filter_by(meeting_id=meeting.id).one()
    assert transition(client, meeting, "publish").status_code == 302
    return SimpleNamespace(company=company, manager=manager, owner=owner, meeting=meeting, decision=decision)


@pytest.fixture()
def approver(action_scenario):
    return create_user("meeting-action-approver", company=action_scenario.company, role_key="management_representative")


def generation_path(scenario):
    return f"/toplantilar/{scenario.meeting.id}/kararlar/{scenario.decision.id}/aksiyon"


def generation_data(scenario, **changes):
    data = {
        "department": "Meeting Quality",
        "version_id": scenario.decision.version_id,
        "meeting_version_id": scenario.meeting.version_id,
    }
    data.update(changes)
    return data


def generate(client, scenario, **changes):
    return client.post(generation_path(scenario), data=generation_data(scenario, **changes))


def linked_action(client, scenario):
    assert generate(client, scenario).status_code == 302
    link = MeetingDecisionAction.query.filter_by(decision_id=scenario.decision.id).one()
    return link.action


def business_snapshot(scenario):
    db.session.refresh(scenario.meeting)
    db.session.refresh(scenario.decision)
    return (
        Action.query.count(), MeetingDecisionAction.query.count(), ActionHistory.query.count(),
        Notification.query.count(),
        AuditLog.query.filter_by(action="linked_action_created").count(),
        scenario.meeting.version_id, scenario.decision.version_id,
        tuple((row.key, row.value) for row in AppSetting.query.filter(
            AppSetting.key.like("%next_action_number%"),
        ).order_by(AppSetting.key)),
    )


def workbook_text(response):
    assert response.status_code == 200
    assert response.mimetype == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    with ZipFile(BytesIO(response.data)) as archive:
        return "\n".join(
            " ".join(ET.fromstring(archive.read(name)).itertext())
            for name in archive.namelist() if name.startswith("xl/worksheets/") and name.endswith(".xml")
        )


def request_closure(client, scenario, action):
    login(client, scenario.owner, scenario.company)
    response = client.post(
        f"/actions/{action.id}/request-closure", data={"closure_evidence_note": "Verified evidence"},
    )
    assert response.status_code == 302
    db.session.refresh(action)
    assert action.closure_approval_requested is True


def approve_closure(client, scenario, action, approver):
    login(client, approver, scenario.company)
    assert client.post(f"/actions/{action.id}/complete").status_code == 302
    db.session.refresh(action)
    db.session.refresh(scenario.decision)
    assert action.is_completed is True


@pytest.mark.parametrize("title_length", [80, 160, 240])
def test_generation_preserves_source_and_notifies_only_owner(client, action_scenario, monkeypatch, title_length):
    s = action_scenario
    s.decision.title = "D" * title_length
    db.session.commit()
    before_meeting_version, before_decision_version = s.meeting.version_id, s.decision.version_id
    mail = Mock(side_effect=AssertionError("Generation must not send email"))
    monkeypatch.setattr(routes, "send_action_notification_email", mail)
    action = linked_action(client, s)
    link = MeetingDecisionAction.query.one()
    assert link.decision == s.decision
    assert s.decision.action_link == link
    assert link.action == action
    assert link.company_id == action.company_id == s.company.id
    assert link.created_by_user_id == s.manager.id
    assert link.created_at is not None
    assert action.title == (s.decision.title if title_length <= 160 else s.decision.title[:157] + "...")
    assert len(action.title) <= 160
    assert s.decision.title in action.description
    assert s.meeting.meeting_no in action.description
    assert f"Karar {s.decision.id}" in action.description
    assert action.responsible_user_id == s.owner.id
    assert action.responsible_owner == s.owner.full_name
    assert action.termin_date == s.decision.due_date
    assert action.department == "Meeting Quality"
    assert action.related_user_1_id is None and action.related_user_2_id is None
    assert action.is_completed is False and s.decision.status == "open"
    assert s.meeting.version_id > before_meeting_version
    assert s.decision.version_id > before_decision_version
    notifications = Notification.query.filter_by(action_id=action.id).all()
    assert [item.user_id for item in notifications] == [s.owner.id]
    assert notifications[0].company_id == s.company.id
    assert notifications[0].target_url == f"/actions/{action.id}"
    assert notifications[0].email_sent_at is None
    assert ActionHistory.query.filter_by(action_id=action.id, event_type="meeting_linked").count() == 1
    assert AuditLog.query.filter_by(entity_type="MeetingDecision", entity_id=s.decision.id,
                                   action="linked_action_created").count() == 1
    mail.assert_not_called()
    assert client.get(f"/actions/{action.id}").status_code == 403


def test_repeat_with_original_stale_form_is_idempotent(client, action_scenario):
    s = action_scenario
    data = generation_data(s)
    first = client.post(generation_path(s), data=data)
    assert first.status_code == 302
    before = business_snapshot(s)
    repeat = client.post(generation_path(s), data=data)
    assert repeat.status_code == 302
    assert repeat.location == first.location
    assert business_snapshot(s) == before


@pytest.mark.parametrize("role,expected", [
    ("super_admin", 302), ("management_representative", 302), ("management", 403),
    ("department_manager", 302), ("department_staff", 403), ("viewer", 403),
])
def test_generation_role_matrix_and_form_visibility(client, action_scenario, role, expected):
    s = action_scenario
    actor = create_user("generator-" + role, company=None if role == "super_admin" else s.company, role_key=role)
    s.meeting.created_by_user_id = actor.id
    db.session.commit()
    login(client, actor, s.company)
    detail = client.get(f"/toplantilar/{s.meeting.id}")
    assert detail.status_code == 200
    assert (generation_path(s) in detail.get_data(as_text=True)) == (expected == 302)
    assert generate(client, s).status_code == expected
    assert MeetingDecisionAction.query.count() == int(expected == 302)


@pytest.mark.parametrize("permissions", [
    ("meetings.view", "meetings.create"),
    ("actions.create",),
    ("meetings.view", "actions.create"),
])
def test_generation_requires_both_edit_and_action_creation_authority(client, action_scenario, permissions):
    s = action_scenario
    actor = create_user("partial-generator", company=s.company, permissions=permissions)
    s.meeting.created_by_user_id = actor.id
    db.session.commit()
    login(client, actor, s.company)
    before = business_snapshot(s)
    assert generate(client, s).status_code == 403
    assert business_snapshot(s) == before


def test_legacy_creation_permission_is_honored(client, action_scenario):
    s = action_scenario
    s.manager.roles.clear()
    s.manager.extra_permissions.extend(UserPermission(permission_key=key) for key in ("meetings.view", "meetings.create"))
    s.manager.can_create_actions = True
    db.session.commit()
    assert not s.manager.has_permission("actions.create")
    assert generation_path(s) in client.get(f"/toplantilar/{s.meeting.id}").get_data(as_text=True)
    assert generate(client, s).status_code == 302


def test_repeat_rechecks_authority(client, action_scenario):
    s = action_scenario
    linked_action(client, s)
    s.manager.roles.clear()
    s.manager.extra_permissions.append(UserPermission(permission_key="meetings.view"))
    db.session.commit()
    before = business_snapshot(s)
    assert generate(client, s).status_code == 403
    assert business_snapshot(s) == before


def test_generation_requires_meetings_module(client, action_scenario):
    s = action_scenario
    CompanyModule.query.filter_by(company_id=s.company.id, module_key="meetings").one().is_enabled = False
    db.session.commit()
    before = business_snapshot(s)
    assert generate(client, s).status_code == 403
    assert business_snapshot(s) == before


@pytest.mark.parametrize("identity", ["foreign", "unrelated"])
def test_generation_hides_other_tenant_and_unrelated_meetings(client, action_scenario, identity):
    s = action_scenario
    company = create_company("MTGAF") if identity == "foreign" else s.company
    user = create_user("unauthorized-generator", company=company,
                       role_key="management_representative" if identity == "foreign" else "department_manager")
    login(client, user, company)
    before = business_snapshot(s)
    assert generate(client, s).status_code == 404
    assert business_snapshot(s) == before


def test_forged_decision_from_another_meeting_is_rejected(client, action_scenario):
    s = action_scenario
    other = create_meeting(client, s.owner, title="Other source")
    assert add_decision(client, other, s.owner).status_code == 302
    other_decision = MeetingDecision.query.filter_by(meeting_id=other.id).one()
    before = business_snapshot(s)
    path = f"/toplantilar/{s.meeting.id}/kararlar/{other_decision.id}/aksiyon"
    assert client.post(path, data=generation_data(s, version_id=other_decision.version_id)).status_code == 404
    assert business_snapshot(s) == before


@pytest.mark.parametrize("field", ["version_id", "meeting_version_id"])
@pytest.mark.parametrize("value", [0, "bad", None])
def test_generation_rejects_stale_invalid_and_missing_versions(client, action_scenario, field, value):
    s = action_scenario
    data = generation_data(s, **{field: value})
    if value is None:
        data.pop(field)
    before = business_snapshot(s)
    assert client.post(generation_path(s), data=data).status_code == 409
    assert business_snapshot(s) == before


def test_generation_requires_csrf(client, action_scenario, monkeypatch):
    s = action_scenario
    monkeypatch.setitem(client.application.config, "WTF_CSRF_ENABLED", True)
    before = business_snapshot(s)
    response = client.post(generation_path(s), data=generation_data(s), headers={"Accept": "application/json"})
    assert response.status_code == 400
    assert business_snapshot(s) == before


@pytest.mark.parametrize("meeting_status,decision_status,expected", [
    ("open", "open", 302), ("completed", "open", 302),
    ("draft", "open", 409), ("archived", "open", 409), ("open", "completed", 409),
])
def test_generation_state_matrix(client, action_scenario, meeting_status, decision_status, expected):
    s = action_scenario
    s.meeting.status, s.decision.status = meeting_status, decision_status
    db.session.commit()
    before = business_snapshot(s)
    assert generate(client, s).status_code == expected
    if expected != 302:
        assert business_snapshot(s) == before


@pytest.mark.parametrize("department", ["", "Unknown", "Inactive", "Foreign department"])
def test_generation_rejects_invalid_departments(client, action_scenario, department):
    s = action_scenario
    foreign = create_company("MTGAD")
    db.session.add_all([
        CompanyDepartment(company_id=s.company.id, name="Inactive", is_active=False),
        CompanyDepartment(company_id=foreign.id, name="Foreign department", is_active=True),
    ])
    db.session.commit()
    before = business_snapshot(s)
    assert generate(client, s, department=department).status_code == 400
    assert business_snapshot(s) == before


@pytest.mark.parametrize("kind", ["inactive", "incompatible", "reviewer", "roles_manager", "foreign"])
def test_generation_rejects_owner_who_cannot_complete_workflow(client, action_scenario, kind):
    s = action_scenario
    if kind == "inactive":
        s.owner.is_active = False
    elif kind == "incompatible":
        s.owner.roles.clear()
        s.owner.can_close_assigned_actions = False
    elif kind == "reviewer":
        s.owner.roles.append(Role.query.filter_by(key="management_representative").one())
    elif kind == "roles_manager":
        s.owner.extra_permissions.append(UserPermission(permission_key="roles.manage"))
    else:
        foreign = create_user("foreign-decision-owner", company=create_company("MTGAO"), role_key="department_staff")
        s.decision.owner_user_id = foreign.id
    db.session.commit()
    before = business_snapshot(s)
    assert generate(client, s).status_code == 400
    assert business_snapshot(s) == before


def test_owner_legacy_flag_cannot_bypass_closure_permission(client, action_scenario):
    s = action_scenario
    s.owner.roles.clear()
    s.owner.can_close_assigned_actions = True
    db.session.commit()
    assert not s.owner.has_permission("actions.request_close_assigned")
    before = business_snapshot(s)
    assert generate(client, s).status_code == 400
    assert business_snapshot(s) == before


@pytest.mark.parametrize("failure_point", ["history", "notification"])
def test_generation_rolls_back_every_write_on_failure(client, action_scenario, monkeypatch, failure_point):
    s = action_scenario
    monkeypatch.setitem(client.application.config, "PROPAGATE_EXCEPTIONS", True)
    target, name = (routes, "add_action_history") if failure_point == "history" else (meetings, "add_user_notification")
    original = getattr(target, name)

    def fail_after_write(*args, **kwargs):
        original(*args, **kwargs)
        db.session.flush()
        raise RuntimeError("injected transactional failure")

    before = business_snapshot(s)
    with monkeypatch.context() as patch:
        patch.setattr(target, name, fail_after_write)
        with pytest.raises(RuntimeError, match="injected transactional failure"):
            generate(client, s)
    assert business_snapshot(s) == before
    assert s.decision.action_link is None
    assert generate(client, s).status_code == 302
    assert Action.query.one().action_number == 1


@pytest.mark.parametrize("operation", ["edit", "complete", "reopen"])
def test_linked_decision_cannot_be_mutated_directly(client, action_scenario, operation):
    s = action_scenario
    linked_action(client, s)
    before = business_snapshot(s)
    response = client.post(f"/toplantilar/{s.meeting.id}/kararlar/{s.decision.id}", data={
        "action": operation, "version_id": s.decision.version_id,
        "title": "Forged edit", "owner_user_id": s.owner.id,
        "due_date": s.decision.due_date.isoformat(), "completion_note": "Bypass closure",
    })
    assert response.status_code == 409
    assert business_snapshot(s) == before
    assert s.decision.status == "open" and s.decision.completion_note is None
    body = client.get(f"/toplantilar/{s.meeting.id}").get_data(as_text=True)
    assert f'action="/toplantilar/{s.meeting.id}/kararlar/{s.decision.id}"' not in body
    assert generation_path(s) not in body


def test_linked_decision_has_only_the_action_task(client, action_scenario):
    s = action_scenario
    with client.application.test_request_context():
        g.current_user, g.current_company = s.owner, s.company
        before = meetings.assigned_task_rows("assigned", lambda **kw: kw)
        assert [row["title"] for row in before] == [s.decision.title]
    action = linked_action(client, s)
    with client.application.test_request_context():
        g.current_user, g.current_company = s.owner, s.company
        assert meetings.assigned_task_rows("assigned", lambda **kw: kw) == []
    login(client, s.owner, s.company)
    response = client.get("/uzerime-atananlar?tab=actions")
    assert response.status_code == 200
    assert action.title in response.get_data(as_text=True)
    assert f'/actions/{action.id}' in response.get_data(as_text=True)


def test_closure_approval_completes_decision_with_private_completion_note(client, action_scenario, approver):
    s = action_scenario
    action = linked_action(client, s)
    version = s.decision.version_id
    login(client, approver, s.company)
    assert client.post(f"/actions/{action.id}/complete").status_code == 403
    request_closure(client, s, action)
    db.session.refresh(s.decision)
    assert s.decision.status == "open" and s.decision.completed_at is None
    assert client.post(f"/actions/{action.id}/complete").status_code == 403
    approve_closure(client, s, action, approver)
    assert routes.action_is_finally_completed(action)
    assert s.decision.status == "completed"
    assert s.decision.completed_at is not None
    assert s.decision.version_id > version
    assert s.decision.completion_note and action.number_label not in s.decision.completion_note
    audit = AuditLog.query.filter_by(entity_type="MeetingDecision", entity_id=s.decision.id, action="action_completed").one()
    assert action.number_label not in json.loads(audit.new_values)["completion_note"]
    login(client, s.manager, s.company)
    assert transition(client, s.meeting, "complete").status_code == 302
    assert transition(client, s.meeting, "archive").status_code == 302
    body = client.get(f"/toplantilar/{s.meeting.id}").get_data(as_text=True)
    assert action.number_label not in body
    assert f'href="/actions/{action.id}"' not in body
    assert action.number_label not in workbook_text(client.get(f"/toplantilar/{s.meeting.id}/rapor"))


def test_effectiveness_must_finish_after_closure_before_decision_completes(client, action_scenario, approver):
    s = action_scenario
    action = linked_action(client, s)
    action.effectiveness_required = True
    action.effectiveness_owner_user_id = s.owner.id
    action.effectiveness_due_date = date.today()
    # Completion must reset an old successful review before synchronizing the decision.
    action.effectiveness_result = "Etkin"
    db.session.commit()
    request_closure(client, s, action)
    approve_closure(client, s, action, approver)
    assert action.effectiveness_result == "Bekliyor"
    assert not routes.action_is_finally_completed(action)
    assert s.decision.status == "open" and s.decision.completed_at is None
    assert AuditLog.query.filter_by(entity_type="MeetingDecision", action="action_completed").count() == 0
    login(client, s.manager, s.company)
    assert transition(client, s.meeting, "complete").status_code == 302
    assert transition(client, s.meeting, "archive").status_code == 400
    login(client, s.owner, s.company)
    assert client.post(f"/actions/{action.id}/effectiveness", data={
        "effectiveness_result": "Etkin", "effectiveness_note": "Verified effective",
    }).status_code == 302
    db.session.refresh(action)
    db.session.refresh(s.decision)
    assert routes.action_is_finally_completed(action)
    assert s.decision.status == "completed" and s.decision.completed_at is not None
    login(client, s.manager, s.company)
    assert transition(client, s.meeting, "archive").status_code == 302


def test_ineffective_review_reopens_decision_and_archived_parent(client, action_scenario, approver):
    s = action_scenario
    action = linked_action(client, s)
    request_closure(client, s, action)
    approve_closure(client, s, action, approver)
    login(client, s.manager, s.company)
    assert transition(client, s.meeting, "complete").status_code == 302
    assert transition(client, s.meeting, "archive").status_code == 302
    # Model an archived decision whose Action has subsequently been scheduled for review.
    action.effectiveness_required = True
    action.effectiveness_owner_user_id = s.owner.id
    action.effectiveness_due_date = date.today()
    action.effectiveness_result = "Bekliyor"
    db.session.commit()
    login(client, s.owner, s.company)
    assert client.post(f"/actions/{action.id}/effectiveness", data={
        "effectiveness_result": "Etkin De\u011fil", "effectiveness_note": "Evidence insufficient",
    }).status_code == 302
    db.session.refresh(action)
    db.session.refresh(s.decision)
    db.session.refresh(s.meeting)
    assert action.is_completed is False and action.closure_approval_requested is False
    assert s.decision.status == "open" and s.decision.completed_at is None
    assert s.decision.completion_note is None and s.meeting.status == "completed"
    for entity, row in (("MeetingDecision", s.decision), ("MeetingRecord", s.meeting)):
        assert AuditLog.query.filter_by(entity_type=entity, entity_id=row.id, action="action_reopened").count() == 1
    request_closure(client, s, action)
    approve_closure(client, s, action, approver)
    assert s.decision.status == "open" and action.effectiveness_result == "Bekliyor"


def test_edit_effectiveness_resynchronizes_decision_and_parent(client, action_scenario, approver):
    s = action_scenario
    action = linked_action(client, s)
    request_closure(client, s, action)
    approve_closure(client, s, action, approver)
    assert transition(client, s.meeting, "complete").status_code == 302
    assert transition(client, s.meeting, "archive").status_code == 302
    payload = action_payload(s.owner, title=action.title, description=action.description,
                             department=action.department, termin_date=action.termin_date.isoformat(),
                             effectiveness_required="1", effectiveness_owner_user_id=str(s.owner.id),
                             effectiveness_due_date=(date.today() + timedelta(days=1)).isoformat())
    assert client.post(f"/actions/{action.id}/edit", data=payload).status_code == 302
    db.session.refresh(s.decision)
    db.session.refresh(s.meeting)
    assert s.decision.status == "open" and s.decision.completed_at is None
    assert s.meeting.status == "completed"
    payload["effectiveness_required"] = ""
    assert client.post(f"/actions/{action.id}/edit", data=payload).status_code == 302
    db.session.refresh(s.decision)
    assert s.decision.status == "completed" and s.decision.completed_at is not None


def test_rejected_closure_does_not_complete_decision(client, action_scenario, approver):
    s = action_scenario
    action = linked_action(client, s)
    request_closure(client, s, action)
    login(client, approver, s.company)
    assert client.post(f"/actions/{action.id}/reject-closure", data={
        "closure_rejection_reason": "Missing evidence",
    }).status_code == 302
    db.session.refresh(s.decision)
    db.session.refresh(action)
    assert s.decision.status == "open" and s.decision.completed_at is None
    assert not action.is_completed and not action.closure_approval_requested


@pytest.mark.parametrize("method", ["get", "post"])
def test_linked_action_delete_is_blocked_before_any_file_calls(client, action_scenario, approver, monkeypatch, method):
    s = action_scenario
    action = linked_action(client, s)
    db.session.add(ActionSubTask(company_id=s.company.id, parent_action_id=action.id, title="Evidence subtask",
                                 responsible_id=s.owner.id, due_date=s.decision.due_date))
    db.session.commit()
    mocks = []
    for name in ("delete_sub_action_evidence_file", "delete_uploaded_file", "delete_closure_evidence_file"):
        mock = Mock(side_effect=AssertionError("Linked action file deletion attempted"))
        monkeypatch.setattr(routes, name, mock)
        mocks.append(mock)
    login(client, approver, s.company)
    before = business_snapshot(s)
    assert getattr(client, method)(f"/actions/{action.id}/delete").status_code == 409
    for mock in mocks:
        mock.assert_not_called()
    assert business_snapshot(s) == before
    assert ActionSubTask.query.filter_by(parent_action_id=action.id).count() == 1


def test_link_and_export_visibility_follow_action_permissions(client, action_scenario, approver):
    s = action_scenario
    action = linked_action(client, s)
    for user, visible in ((s.manager, False), (approver, True)):
        login(client, user, s.company)
        detail = client.get(f"/toplantilar/{s.meeting.id}")
        assert detail.status_code == 200
        body = detail.get_data(as_text=True)
        assert (f'href="/actions/{action.id}"' in body) == visible
        assert (action.number_label in body) == visible
        assert (action.number_label in workbook_text(client.get(f"/toplantilar/{s.meeting.id}/rapor"))) == visible
    approver.roles.clear()
    approver.extra_permissions.extend(UserPermission(permission_key=key) for key in ("meetings.view_all", "meetings.export"))
    db.session.commit()
    assert action.number_label not in client.get(f"/toplantilar/{s.meeting.id}").get_data(as_text=True)
    assert action.number_label not in workbook_text(client.get(f"/toplantilar/{s.meeting.id}/rapor"))


@pytest.mark.parametrize("access", ["participant", "unrelated", "no_permission", "module_disabled"])
def test_action_source_meeting_link_requires_meeting_access(client, action_scenario, access):
    s = action_scenario
    action = linked_action(client, s)
    permissions = ("actions.view_all",) if access == "no_permission" else ("actions.view_all", "meetings.view")
    reader = create_user("source-reader", company=s.company, permissions=permissions)
    if access != "unrelated":
        db.session.add(MeetingParticipant(company_id=s.company.id, meeting_id=s.meeting.id, user_id=reader.id))
    if access == "module_disabled":
        CompanyModule.query.filter_by(company_id=s.company.id, module_key="meetings").one().is_enabled = False
    db.session.commit()
    login(client, reader, s.company)
    response = client.get(f"/actions/{action.id}")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert ("Kaynak Toplant\u0131" in body) == (access == "participant")
    if access == "participant":
        assert f'href="/toplantilar/{s.meeting.id}"' in body


def test_lifecycle_endpoints_reject_other_tenant(client, action_scenario):
    s = action_scenario
    action = linked_action(client, s)
    foreign_company = create_company("MTGAL")
    foreign = create_user("foreign-action-admin", company=foreign_company, role_key="management_representative")
    login(client, foreign, foreign_company)
    before = business_snapshot(s)
    for endpoint in ("request-closure", "complete", "effectiveness", "reject-closure", "edit", "delete"):
        assert client.post(f"/actions/{action.id}/{endpoint}").status_code == 404
    assert client.get(f"/actions/{action.id}").status_code == 404
    assert business_snapshot(s) == before


def test_repeated_closure_keeps_previous_evidence(client, action_scenario, approver):
    s = action_scenario
    action = linked_action(client, s)
    login(client, s.owner, s.company)
    assert client.post(f"/actions/{action.id}/request-closure", data={
        "closure_evidence_note": "First evidence", "closure_files": upload_tuple(b"original evidence", "first.pdf"),
    }).status_code == 302
    db.session.refresh(action)
    first_id = action.closure_files[0].id
    login(client, approver, s.company)
    assert client.post(f"/actions/{action.id}/reject-closure", data={"closure_rejection_reason": "More evidence needed"}).status_code == 302
    login(client, s.owner, s.company)
    assert client.post(f"/actions/{action.id}/request-closure", data={
        "closure_evidence_note": "Additional evidence", "closure_files": upload_tuple(b"extra evidence", "second.pdf"),
    }).status_code == 302
    db.session.refresh(action)
    assert len(action.closure_files) == 2
    response = client.get(f"/actions/{action.id}/closure-evidence/{first_id}/download")
    assert response.status_code == 200 and response.data == b"original evidence"


def test_archive_rechecks_actual_action_state(client, action_scenario):
    s = action_scenario
    action = linked_action(client, s)
    # An inconsistent legacy/imported decision cannot bypass the final Action check.
    s.decision.status = "completed"
    s.meeting.status = "completed"
    db.session.commit()
    assert not action.is_completed
    assert transition(client, s.meeting, "archive").status_code == 400
    db.session.refresh(s.meeting)
    assert s.meeting.status == "completed"


def test_link_metadata_does_not_cross_company_on_corrupt_link(client, action_scenario, approver):
    from app.meeting_actions import action_info, sync_decision, visible_source
    s = action_scenario
    action = linked_action(client, s)
    foreign_company = create_company("MTGACORRUPT")
    link = s.decision.action_link
    link.company_id = foreign_company.id
    db.session.commit()
    with client.application.test_request_context():
        g.current_user, g.current_company = approver, s.company
        assert action_info(s.decision) is None
        assert visible_source(action) is None
        sync_decision(action)
        assert s.decision.status == "open"
