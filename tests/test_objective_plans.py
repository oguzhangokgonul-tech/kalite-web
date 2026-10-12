from datetime import date, datetime, timedelta
from decimal import Decimal
from html.parser import HTMLParser
import json
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import urlsplit

import pytest
from flask import template_rendered, url_for
from sqlalchemy import String, cast, event, select, update
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import (
    Action, ActionHistory, AppSetting, AuditLog, CompanyDepartment, CompanyModule,
    Notification, ProjectRecord, ProjectTask, QualityObjective, QualityObjectiveMeasurement,
    QUALITY_OBJECTIVE_STATUS_ACTIVE, QUALITY_OBJECTIVE_STATUS_ARCHIVED,
    QUALITY_OBJECTIVE_STATUS_CANCELLED, QUALITY_OBJECTIVE_STATUS_COMPLETED,
    UserPermission,
)
from app.objective_plan_models import ObjectivePlanLink
from tests.helpers import create_company, create_user, login
from tests.test_projects import transition, update_task
from tests.test_quality_objectives import create_objective


class FormHTML(HTMLParser):
    def __init__(self, response):
        super().__init__(convert_charrefs=True)
        self.inputs = {}
        self.selects = {}
        self.links = []
        self.forms = []
        self.select = None
        self.feed(response.get_data(as_text=True))

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "input" and attrs.get("name"):
            self.inputs[attrs["name"]] = attrs
        elif tag == "a":
            self.links.append(attrs.get("href", ""))
        elif tag == "form":
            self.forms.append(attrs)
        elif tag == "select":
            self.select = attrs.get("name")
            self.selects[self.select] = set()
        elif tag == "option" and self.select:
            self.selects[self.select].add(attrs.get("value", ""))

    def handle_endtag(self, tag):
        if tag == "select":
            self.select = None


@pytest.fixture()
def plan_scenario(client):
    company = create_company("OBJPLAN")
    manager = create_user("objective-plan-manager", company=company,
                          role_key="management_representative")
    owner = create_user("objective-plan-owner", company=company,
                        role_key="department_manager", title="Kalite")
    staff = create_user("objective-plan-staff", company=company,
                        role_key="department_staff", title="Kalite")
    db.session.add(CompanyDepartment(company_id=company.id, name="Kalite", is_active=True))
    db.session.commit()
    objective = create_objective(
        company, staff, manager, description="Objective evidence",
        period_start=date.today() - timedelta(days=30),
        period_end=date.today() + timedelta(days=30),
    )
    login(client, manager, company)
    # Complete runtime initialization before measuring endpoint side effects.
    assert client.get("/").status_code == 200
    return SimpleNamespace(company=company, manager=manager, owner=owner,
                           staff=staff, objective=objective)


def plan_path(s, kind):
    return f"/kalite-hedefleri/{s.objective.id}/plan/{kind}"


def objective_path(s):
    return f"/kalite-hedefleri/{s.objective.id}"


def plan_form(client, s, kind):
    response = client.get(plan_path(s, kind))
    assert response.status_code == 200, response.get_data(as_text=True)
    form = FormHTML(response)
    token = form.inputs["objective_token"]
    assert token.get("type") == "hidden"
    assert token.get("value")
    return form


def plan_payload(client, s, kind, **changes):
    form = plan_form(client, s, kind)
    data = {
        "objective_token": form.inputs["objective_token"]["value"],
        "title": "Objective delivery plan",
        "description": "Verify the delivery process and retain evidence.",
        "owner_user_id": s.owner.id if kind == "project" else s.staff.id,
        "start_date": date.today().isoformat(),
        "due_date": (date.today() + timedelta(days=10)).isoformat(),
    }
    if kind == "project":
        data.update(task_title="Inspect delivery evidence", task_owner_user_id=s.staff.id,
                    estimated_hours="12.5")
    else:
        data["department"] = "Kalite"
    data.update(changes)
    return data


def create_plan(client, s, kind, **changes):
    data = plan_payload(client, s, kind, **changes)
    response = client.post(plan_path(s, kind), data=data)
    assert response.status_code == 302, response.get_data(as_text=True)
    assert urlsplit(response.location).path == objective_path(s)
    return ObjectivePlanLink.query.filter_by(objective_id=s.objective.id, kind=kind).one()


def business_snapshot(s):
    db.session.refresh(s.objective)
    return (
        tuple(model.query.count() for model in (
            ObjectivePlanLink, ProjectRecord, ProjectTask, Action, ActionHistory,
            Notification, AuditLog, QualityObjectiveMeasurement,
        )),
        tuple((row.key, row.value) for row in AppSetting.query.order_by(AppSetting.key)),
        tuple((column.name, getattr(s.objective, column.name))
              for column in s.objective.__table__.columns),
    )


def set_permissions(user, permissions):
    user.roles.clear()
    user.extra_permissions[:] = [UserPermission(permission_key=key) for key in permissions]
    db.session.commit()


@pytest.mark.parametrize("kind", ["project", "action"])
def test_form_has_signed_state_and_source_return_without_writes(client, plan_scenario, kind):
    s = plan_scenario
    before = business_snapshot(s)
    form = plan_form(client, s, kind)
    assert objective_path(s) in form.links
    assert {"title", "start_date", "due_date"} <= form.inputs.keys()
    assert "owner_user_id" in form.selects
    with client.application.test_request_context():
        assert url_for("objective_plans.create", objective_id=s.objective.id, kind=kind) == plan_path(s, kind)
    assert business_snapshot(s) == before
    detail = client.get(objective_path(s))
    assert detail.status_code == 200
    assert plan_path(s, kind) in FormHTML(detail).links


def test_project_creation_persists_draft_task_link_audit_and_actor(client, plan_scenario):
    s = plan_scenario
    data = plan_payload(client, s, "project", created_by_user_id=s.staff.id,
                        company_id=999999, status="completed")
    response = client.post(plan_path(s, "project"), data=data)
    assert response.status_code == 302
    db.session.expire_all()
    project, task, link = ProjectRecord.query.one(), ProjectTask.query.one(), ObjectivePlanLink.query.one()
    assert link.company_id == project.company_id == task.company_id == s.company.id
    assert link.objective_id == s.objective.id and link.kind == "project"
    assert link.project_id == project.id and link.action_id is None
    assert link.created_by_user_id == project.created_by_user_id == s.manager.id
    assert link.created_at is not None
    assert project.title == data["title"] and data["description"] in project.description
    assert project.owner_user_id == s.owner.id and project.status == "draft"
    assert project.start_date == task.start_date == date.fromisoformat(data["start_date"])
    assert project.due_date == task.due_date == date.fromisoformat(data["due_date"])
    assert task.project_id == project.id and task.title == data["task_title"]
    assert task.owner_user_id == s.staff.id and task.status == "pending"
    assert task.estimated_hours == Decimal("12.5")
    assert Notification.query.count() == Action.query.count() == 0
    assert s.objective.status == QUALITY_OBJECTIVE_STATUS_ACTIVE
    audit = AuditLog.query.filter_by(entity_type="ObjectivePlanLink", entity_id=str(link.id)).one()
    assert audit.company_id == s.company.id and audit.user_id == s.manager.id
    assert f"/projeler/{project.id}" in FormHTML(client.get(objective_path(s))).links
    assert objective_path(s) in FormHTML(client.get(f"/projeler/{project.id}")).links


def test_action_creation_uses_reservation_in_app_only_and_preserves_old_action(client, plan_scenario, monkeypatch):
    from app import routes

    s = plan_scenario
    old_action = Action(company_id=s.company.id, action_number=41, title="Existing source action",
                        responsible_owner=s.staff.full_name, responsible_user_id=s.staff.id,
                        department="Kalite", termin_date=date.today())
    db.session.add(old_action)
    db.session.flush()
    s.objective.action_id = old_action.id
    db.session.commit()
    reserve = Mock(wraps=routes.reserve_action_number)
    monkeypatch.setattr(routes, "reserve_action_number", reserve)
    mail = Mock(side_effect=AssertionError("Plan creation must not send mail"))
    monkeypatch.setattr("app.mail.send_mail_now", mail)
    link = create_plan(client, s, "action", created_by_user_id=s.staff.id, is_completed="1")
    db.session.expire_all()
    action = db.session.get(Action, link.action_id)
    assert reserve.call_count == 1
    assert action.action_number == 42
    assert link.project_id is None and link.kind == "action"
    assert link.company_id == action.company_id == s.company.id
    assert link.created_by_user_id == s.manager.id and link.created_at is not None
    assert action.title == "Objective delivery plan"
    assert "Verify the delivery process" in action.description
    assert s.objective.objective_no in action.description
    assert s.objective.title in action.description
    assert s.objective.metric_name in action.description
    assert str(s.objective.period_start) in action.description
    assert str(s.objective.period_end) in action.description
    assert action.responsible_user_id == s.staff.id
    assert action.responsible_owner == s.staff.full_name
    assert action.department == "Kalite" and action.is_completed is False
    assert action.termin_date == date.today() + timedelta(days=10)
    assert action.related_user_1_id is None and action.related_user_2_id is None
    assert s.objective.action_id == old_action.id
    notices = Notification.query.filter_by(action_id=action.id).all()
    assert len(notices) == 1
    assert notices[0].user_id == s.staff.id and notices[0].company_id == s.company.id
    assert notices[0].target_url == f"/actions/{action.id}" and notices[0].email_sent_at is None
    audit = AuditLog.query.filter_by(entity_type="ObjectivePlanLink", entity_id=str(link.id)).one()
    assert audit.company_id == s.company.id and audit.user_id == s.manager.id
    assert objective_path(s) in FormHTML(client.get(f"/actions/{action.id}")).links
    assert f"/actions/{action.id}" in FormHTML(client.get(objective_path(s))).links
    mail.assert_not_called()


def test_project_estimated_hours_can_be_omitted(client, plan_scenario):
    create_plan(client, plan_scenario, "project", estimated_hours="")
    assert ProjectTask.query.one().estimated_hours is None


@pytest.mark.parametrize("kind", ["project", "action"])
def test_duplicate_valid_post_redirects_to_source_without_any_new_writes(client, plan_scenario, kind):
    s = plan_scenario
    data = plan_payload(client, s, kind)
    first = client.post(plan_path(s, kind), data=data)
    assert first.status_code == 302
    before = business_snapshot(s)
    second = client.post(plan_path(s, kind), data=data)
    assert second.status_code == 302 and second.location == first.location
    assert urlsplit(second.location).path == objective_path(s)
    assert business_snapshot(s) == before


def test_one_project_and_one_action_can_coexist_for_same_objective(client, plan_scenario):
    s = plan_scenario
    project_link = create_plan(client, s, "project")
    action_link = create_plan(client, s, "action")
    assert project_link.id != action_link.id
    assert ObjectivePlanLink.query.count() == 2
    assert ProjectRecord.query.count() == ProjectTask.query.count() == Action.query.count() == 1
    assert s.objective.action_id is None


@pytest.mark.parametrize("kind", ["project", "action"])
@pytest.mark.parametrize("token_change", ["missing", "forged", "changed", "other_objective", "other_kind"])
def test_signed_token_rejects_tampering_and_wrong_context(client, plan_scenario, kind, token_change):
    s = plan_scenario
    data = plan_payload(client, s, kind)
    if token_change == "missing":
        data.pop("objective_token")
    elif token_change == "forged":
        data["objective_token"] = "forged.objective.state"
    elif token_change == "changed":
        token = data["objective_token"]
        data["objective_token"] = ("A" if token[0] != "A" else "B") + token[1:]
    elif token_change == "other_kind":
        other_kind = "action" if kind == "project" else "project"
        data["objective_token"] = plan_form(client, s, other_kind).inputs["objective_token"]["value"]
    else:
        other = create_objective(s.company, s.staff, s.manager, objective_no="KH-2026-0002")
        other_s = SimpleNamespace(objective=other)
        data["objective_token"] = plan_form(client, other_s, kind).inputs["objective_token"]["value"]
    before = business_snapshot(s)
    assert client.post(plan_path(s, kind), data=data).status_code == 409
    assert business_snapshot(s) == before


@pytest.mark.parametrize("kind", ["project", "action"])
@pytest.mark.parametrize("field,value", [("title", "Changed source title"), ("target_value", 110)])
def test_source_edit_makes_existing_form_stale(client, plan_scenario, kind, field, value):
    s = plan_scenario
    data = plan_payload(client, s, kind)
    setattr(s.objective, field, value)
    db.session.commit()
    before = business_snapshot(s)
    assert client.post(plan_path(s, kind), data=data).status_code == 409
    assert business_snapshot(s) == before


@pytest.mark.parametrize("kind", ["project", "action"])
@pytest.mark.parametrize("status", [QUALITY_OBJECTIVE_STATUS_COMPLETED,
                                    QUALITY_OBJECTIVE_STATUS_CANCELLED,
                                    QUALITY_OBJECTIVE_STATUS_ARCHIVED])
def test_closed_goals_reject_form_and_previously_valid_post(client, plan_scenario, kind, status):
    s = plan_scenario
    data = plan_payload(client, s, kind)
    s.objective.status = status
    db.session.commit()
    before = business_snapshot(s)
    assert client.get(plan_path(s, kind)).status_code == 409
    assert client.post(plan_path(s, kind), data=data).status_code == 409
    assert business_snapshot(s) == before


@pytest.mark.parametrize("kind", ["project", "action"])
@pytest.mark.parametrize("missing", ["source_access", "source_manage", "target_create"])
def test_each_required_permission_is_checked_on_get_and_post(client, plan_scenario, kind, missing):
    s = plan_scenario
    data = plan_payload(client, s, kind)
    permissions = {"source_view": "quality_objective.view", "source_manage": "quality_objective.manage",
                   "target_create": "projects.create" if kind == "project" else "actions.create"}
    granted = [permission for key, permission in permissions.items() if key != missing]
    if missing == "source_access":
        granted = [key for key in granted if not key.startswith("quality_objective.")]
    granted.append("projects.view" if kind == "project" else "actions.view_all")
    set_permissions(s.manager, granted)
    before = business_snapshot(s)
    assert client.get(plan_path(s, kind)).status_code == 403
    assert client.post(plan_path(s, kind), data=data).status_code == 403
    assert business_snapshot(s) == before


def test_project_create_without_target_read_permission_is_forbidden(client, plan_scenario):
    s = plan_scenario
    data = plan_payload(client, s, "project")
    set_permissions(s.manager, ("quality_objective.view", "quality_objective.manage", "projects.create"))
    before = business_snapshot(s)
    assert client.get(plan_path(s, "project")).status_code == 403
    assert client.post(plan_path(s, "project"), data=data).status_code == 403
    assert business_snapshot(s) == before


@pytest.mark.parametrize("kind", ["project", "action"])
@pytest.mark.parametrize("role,allowed", [
    ("super_admin", True), ("management_representative", True), ("management", False),
    ("department_manager", True), ("department_staff", False), ("viewer", False),
])
def test_default_role_matrix(client, plan_scenario, kind, role, allowed):
    s = plan_scenario
    actor = create_user("plan-role-" + role, company=None if role == "super_admin" else s.company,
                        role_key=role, title="Kalite")
    s.objective.created_by_user_id = actor.id
    db.session.commit()
    login(client, actor, s.company)
    if allowed:
        link = create_plan(client, s, kind)
        assert link.created_by_user_id == actor.id
    else:
        before = business_snapshot(s)
        assert client.get(plan_path(s, kind)).status_code == 403
        assert client.post(plan_path(s, kind), data={}).status_code == 403
        assert business_snapshot(s) == before


@pytest.mark.parametrize("kind", ["project", "action"])
def test_unrelated_department_manager_cannot_manage_source(client, plan_scenario, kind):
    s = plan_scenario
    outsider = create_user("plan-unrelated-manager", company=s.company,
                           role_key="department_manager", title="Sevkiyat")
    login(client, outsider, s.company)
    before = business_snapshot(s)
    assert client.get(plan_path(s, kind)).status_code == 403
    assert client.post(plan_path(s, kind), data={}).status_code == 403
    assert business_snapshot(s) == before


@pytest.mark.parametrize("kind,module", [("project", "source"), ("project", "target"), ("action", "source")])
def test_disabled_module_denies_both_methods_and_removes_entry(client, plan_scenario, kind, module):
    s = plan_scenario
    data = plan_payload(client, s, kind)
    key = "quality_objectives" if module == "source" else ("projects" if kind == "project" else "actions")
    CompanyModule.query.filter_by(company_id=s.company.id, module_key=key).one().is_enabled = False
    db.session.commit()
    before = business_snapshot(s)
    assert client.get(plan_path(s, kind)).status_code in (403, 404)
    assert client.post(plan_path(s, kind), data=data).status_code in (403, 404)
    assert business_snapshot(s) == before
    detail = client.get(objective_path(s))
    if module == "target":
        assert detail.status_code == 200
        assert plan_path(s, kind) not in FormHTML(detail).links
    else:
        assert detail.status_code in (403, 404)


@pytest.mark.parametrize("kind", ["project", "action"])
def test_foreign_objective_is_hidden_even_with_valid_token(client, plan_scenario, kind):
    s = plan_scenario
    data = plan_payload(client, s, kind)
    other_company = create_company("OBJPLAN-FOREIGN")
    actor = create_user("plan-foreign-manager", company=other_company, role_key="management_representative")
    login(client, actor, other_company)
    before = business_snapshot(s)
    for response in (client.get(plan_path(s, kind)), client.post(plan_path(s, kind), data=data)):
        assert response.status_code == 404
        assert s.objective.title not in response.get_data(as_text=True)
    assert business_snapshot(s) == before


@pytest.mark.parametrize("kind", ["project", "action"])
def test_selected_tenant_required_and_anonymous_redirected(client, plan_scenario, kind):
    s = plan_scenario
    admin = create_user("plan-global-admin", role_key="super_admin")
    login(client, admin)
    before = business_snapshot(s)
    assert client.get(plan_path(s, kind)).status_code == 403
    assert client.post(plan_path(s, kind), data={}).status_code == 403
    login(client, admin, s.company)
    assert client.get(plan_path(s, kind)).status_code == 200
    with client.session_transaction() as session:
        session.clear()
    assert client.get(plan_path(s, kind)).status_code == 302
    assert client.post(plan_path(s, kind), data={}).status_code == 302
    assert business_snapshot(s) == before


@pytest.mark.parametrize("kind", ["project", "action"])
def test_csrf_rejects_missing_token_and_accepts_html_token(client, plan_scenario, kind, monkeypatch):
    s = plan_scenario
    monkeypatch.setitem(client.application.config, "WTF_CSRF_ENABLED", True)
    data = plan_payload(client, s, kind)
    form = plan_form(client, s, kind)
    before = business_snapshot(s)
    html_error = client.post(plan_path(s, kind), data=data)
    assert html_error.status_code == 302 and urlsplit(html_error.location).path == '/'
    assert business_snapshot(s) == before
    json_headers = {'Accept': 'application/json'}
    assert client.post(plan_path(s, kind), data=data, headers=json_headers).status_code == 400
    assert business_snapshot(s) == before
    assert client.post(plan_path(s, kind), data={**data, "csrf_token": "forged"}, headers=json_headers).status_code == 400
    assert business_snapshot(s) == before
    data["csrf_token"] = form.inputs["csrf_token"]["value"]
    assert client.post(plan_path(s, kind), data=data).status_code == 302
    assert ObjectivePlanLink.query.count() == 1
    before = business_snapshot(s)
    data.pop("csrf_token")
    assert client.post(plan_path(s, kind), data=data, headers=json_headers).status_code == 400
    assert business_snapshot(s) == before


@pytest.mark.parametrize("kind", ["project", "action"])
@pytest.mark.parametrize("changes", [
    {"title": " "}, {"description": " "}, {"owner_user_id": ""}, {"owner_user_id": "bad"},
    {"start_date": "invalid"}, {"due_date": "invalid"}, {"due_date": ""},
    {"start_date": "2026-10-10", "due_date": "2026-10-09"},
])
def test_invalid_common_fields_create_nothing(client, plan_scenario, kind, changes):
    s = plan_scenario
    data = plan_payload(client, s, kind, **changes)
    before = business_snapshot(s)
    assert client.post(plan_path(s, kind), data=data).status_code == 400
    assert business_snapshot(s) == before


@pytest.mark.parametrize("changes", [
    {"task_title": " "}, {"task_owner_user_id": ""}, {"task_owner_user_id": "bad"},
    {"estimated_hours": "bad"}, {"estimated_hours": "NaN"}, {"estimated_hours": "Infinity"},
    {"estimated_hours": "-1"}, {"estimated_hours": "10001"}, {"estimated_hours": "1.25"},
])
def test_invalid_project_task_rolls_back_parent(client, plan_scenario, changes):
    s = plan_scenario
    data = plan_payload(client, s, "project", **changes)
    before = business_snapshot(s)
    assert client.post(plan_path(s, "project"), data=data).status_code == 400
    assert business_snapshot(s) == before


@pytest.mark.parametrize("department", ["", "Unknown department"])
def test_action_requires_valid_company_department(client, plan_scenario, department):
    s = plan_scenario
    data = plan_payload(client, s, "action", department=department)
    before = business_snapshot(s)
    assert client.post(plan_path(s, "action"), data=data).status_code == 400
    assert business_snapshot(s) == before


@pytest.mark.parametrize("kind,field", [("project", "owner_user_id"),
                                       ("project", "task_owner_user_id"), ("action", "owner_user_id")])
@pytest.mark.parametrize("identity", ["foreign", "inactive", "unqualified"])
def test_owner_filters_match_post_validation(client, plan_scenario, kind, field, identity):
    s = plan_scenario
    company = create_company("OBJPLAN-OWNER") if identity == "foreign" else s.company
    invalid = create_user("plan-invalid-owner", company=company,
                          role_key="department_manager" if identity != "unqualified" else "viewer")
    if identity == "inactive":
        invalid.is_active = False
        db.session.commit()
    form = plan_form(client, s, kind)
    assert str(invalid.id) not in form.selects[field]
    data = plan_payload(client, s, kind, **{field: invalid.id})
    before = business_snapshot(s)
    assert client.post(plan_path(s, kind), data=data).status_code == 400
    assert business_snapshot(s) == before


@pytest.mark.parametrize("kind", ["project", "action"])
def test_failure_after_audit_insert_rolls_back_all_writes(client, plan_scenario, kind, monkeypatch):
    s = plan_scenario
    data = plan_payload(client, s, kind)
    monkeypatch.setitem(client.application.config, "PROPAGATE_EXCEPTIONS", True)
    before = business_snapshot(s)
    seen = []

    def fail_after_audit(mapper, connection, target):
        if target.entity_type == "ObjectivePlanLink":
            seen.append(target.entity_id)
            raise RuntimeError("Injected plan audit failure")

    event.listen(AuditLog, "after_insert", fail_after_audit)
    try:
        with pytest.raises(RuntimeError, match="Injected plan audit failure"):
            client.post(plan_path(s, kind), data=data)
    finally:
        event.remove(AuditLog, "after_insert", fail_after_audit)
    assert seen
    assert business_snapshot(s) == before
    assert client.post(plan_path(s, kind), data=data).status_code == 302
    assert ObjectivePlanLink.query.count() == 1
    if kind == "action":
        assert Action.query.one().action_number == 1


@pytest.mark.parametrize("kind", ["project", "action"])
def test_existing_link_redirect_precedes_token_check_but_rechecks_authority(client, plan_scenario, kind):
    s = plan_scenario
    data = plan_payload(client, s, kind)
    assert client.post(plan_path(s, kind), data=data).status_code == 302
    before = business_snapshot(s)
    repeat = client.post(plan_path(s, kind), data={**data, "objective_token": "forged"})
    assert repeat.status_code == 302 and urlsplit(repeat.location).path == objective_path(s)
    assert business_snapshot(s) == before
    set_permissions(s.manager, ("quality_objective.view",))
    before = business_snapshot(s)
    assert client.post(plan_path(s, kind), data=data).status_code == 403
    assert business_snapshot(s) == before


@pytest.mark.parametrize("kind", ["project", "action"])
@pytest.mark.parametrize("disabled", ["source_permission", "source_module"])
def test_target_backlink_requires_source_visibility(client, plan_scenario, kind, disabled):
    s = plan_scenario
    link = create_plan(client, s, kind)
    target_path = f"/projeler/{link.project_id}" if kind == "project" else f"/actions/{link.action_id}"
    assert objective_path(s) in FormHTML(client.get(target_path)).links
    if disabled == "source_permission":
        set_permissions(s.manager, ("projects.view_all", "actions.view_all"))
    else:
        CompanyModule.query.filter_by(company_id=s.company.id, module_key="quality_objectives").one().is_enabled = False
        db.session.commit()
    response = client.get(target_path)
    assert response.status_code == 200
    assert objective_path(s) not in FormHTML(response).links


@pytest.mark.parametrize("kind", ["project", "action"])
def test_source_detail_does_not_leak_hidden_target_metadata(client, plan_scenario, kind):
    s = plan_scenario
    link = create_plan(client, s, kind, title="Confidential target title")
    reader = create_user("plan-source-only-reader", company=s.company,
                         permissions=("quality_objective.view", "projects.view"))
    login(client, reader, s.company)
    target_path = f"/projeler/{link.project_id}" if kind == "project" else f"/actions/{link.action_id}"
    response = client.get(objective_path(s))
    assert response.status_code == 200
    assert target_path not in FormHTML(response).links
    assert "Confidential target title" not in response.get_data(as_text=True)
    assert client.get(target_path).status_code in (403, 404)


def test_project_and_task_completion_do_not_complete_or_measure_objective(client, plan_scenario):
    s = plan_scenario
    link = create_plan(client, s, "project")
    project = db.session.get(ProjectRecord, link.project_id)
    task = ProjectTask.query.one()
    before_status, before_target = s.objective.status, s.objective.target_value
    assert transition(client, project, "activate").status_code == 302
    login(client, s.staff, s.company)
    assert update_task(client, project, task, "start").status_code == 302
    assert update_task(client, project, task, "complete").status_code == 302
    db.session.refresh(s.objective)
    assert s.objective.status == before_status
    login(client, s.manager, s.company)
    assert transition(client, project, "complete").status_code == 302
    db.session.refresh(project)
    db.session.refresh(s.objective)
    assert project.status == "completed" and project.progress == 100
    assert s.objective.status == QUALITY_OBJECTIVE_STATUS_ACTIVE
    assert s.objective.target_value == before_target
    assert QualityObjectiveMeasurement.query.count() == 0


def test_unknown_kind_and_missing_objective_are_404(client, plan_scenario):
    s = plan_scenario
    before = business_snapshot(s)
    for path in (plan_path(s, "unknown"), "/kalite-hedefleri/999999/plan/project"):
        assert client.get(path).status_code == 404
        assert client.post(path, data={}).status_code == 404
    assert business_snapshot(s) == before


@pytest.mark.parametrize("kind", ["project", "action"])
def test_token_is_bound_to_actor_even_when_both_can_generate(client, plan_scenario, kind):
    s = plan_scenario
    data = plan_payload(client, s, kind)
    other_manager = create_user("plan-second-manager", company=s.company,
                                role_key="management_representative")
    login(client, other_manager, s.company)
    plan_form(client, s, kind)
    before = business_snapshot(s)
    assert client.post(plan_path(s, kind), data=data).status_code == 409
    assert business_snapshot(s) == before
    assert create_plan(client, s, kind).created_by_user_id == other_manager.id


@pytest.mark.parametrize("kind", ["project", "action"])
@pytest.mark.parametrize("boundary", ["before", "after"])
def test_plan_dates_must_stay_inside_source_period(client, plan_scenario, kind, boundary):
    s = plan_scenario
    changes = {"start_date": (s.objective.period_start - timedelta(days=1)).isoformat()} if boundary == "before" else {
        "due_date": (s.objective.period_end + timedelta(days=1)).isoformat(),
    }
    data = plan_payload(client, s, kind, **changes)
    before = business_snapshot(s)
    assert client.post(plan_path(s, kind), data=data).status_code == 400
    assert business_snapshot(s) == before


@pytest.mark.parametrize("kind,change", [("project", "closed"), ("action", "closed"),
    ("project", "source_module"), ("action", "source_module"), ("project", "target_module")])
def test_existing_link_still_requires_open_goal_and_enabled_modules(client, plan_scenario, kind, change):
    s = plan_scenario
    data = plan_payload(client, s, kind)
    assert client.post(plan_path(s, kind), data=data).status_code == 302
    if change == "closed":
        s.objective.status = QUALITY_OBJECTIVE_STATUS_COMPLETED
    else:
        module = "quality_objectives" if change == "source_module" else (
            "projects" if kind == "project" else "actions")
        CompanyModule.query.filter_by(company_id=s.company.id, module_key=module).one().is_enabled = False
    db.session.commit()
    before = business_snapshot(s)
    response = client.post(plan_path(s, kind), data=data)
    assert response.status_code in ((409,) if change == "closed" else (403, 404))
    assert business_snapshot(s) == before


@pytest.mark.parametrize("kind", ["project", "action"])
def test_database_rejects_duplicate_objective_kind(client, plan_scenario, kind):
    s = plan_scenario
    link = create_plan(client, s, kind)
    before = business_snapshot(s)
    duplicate = ObjectivePlanLink(company_id=s.company.id, objective_id=s.objective.id,
                                  kind=kind, project_id=link.project_id, action_id=link.action_id,
                                  created_by_user_id=s.manager.id)
    db.session.add(duplicate)
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()
    assert business_snapshot(s) == before


@pytest.mark.parametrize("kind", ["project", "action"])
def test_foreign_target_is_hidden_and_forged_session_cannot_switch_company(client, plan_scenario, kind):
    s = plan_scenario
    link = create_plan(client, s, kind, title="Tenant private plan")
    target_path = f"/projeler/{link.project_id}" if kind == "project" else f"/actions/{link.action_id}"
    foreign = create_company("OBJPLAN-SESSION")
    outsider = create_user("plan-session-outsider", company=foreign, role_key="management_representative")
    login(client, outsider, s.company)
    assert client.get(target_path).status_code == 404
    assert client.get(objective_path(s)).status_code == 404
    assert client.get(plan_path(s, kind)).status_code == 404
    with client.session_transaction() as session:
        assert session["company_id"] == foreign.id


@pytest.mark.parametrize("kind", ["project"])
def test_disabled_target_module_hides_existing_link_metadata(client, plan_scenario, kind):
    s = plan_scenario
    link = create_plan(client, s, kind, title="Disabled module private plan")
    target_path = f"/projeler/{link.project_id}" if kind == "project" else f"/actions/{link.action_id}"
    module = "projects" if kind == "project" else "actions"
    CompanyModule.query.filter_by(company_id=s.company.id, module_key=module).one().is_enabled = False
    db.session.commit()
    response = client.get(objective_path(s))
    assert response.status_code == 200
    assert target_path not in FormHTML(response).links
    assert "Disabled module private plan" not in response.get_data(as_text=True)


def test_action_completion_does_not_complete_or_measure_source_goal(client, plan_scenario):
    s = plan_scenario
    link = create_plan(client, s, "action")
    action = db.session.get(Action, link.action_id)
    login(client, s.staff, s.company)
    response = client.post(f"/actions/{action.id}/request-closure",
                           data={"closure_evidence_note": "Verified plan evidence"})
    assert response.status_code == 302
    db.session.refresh(action)
    assert action.closure_approval_requested is True
    login(client, s.manager, s.company)
    assert client.post(f"/actions/{action.id}/complete").status_code == 302
    db.session.refresh(action)
    db.session.refresh(s.objective)
    assert action.is_completed is True
    assert s.objective.status == QUALITY_OBJECTIVE_STATUS_ACTIVE
    assert QualityObjectiveMeasurement.query.count() == 0


@pytest.mark.parametrize("kind", ["project", "action"])
@pytest.mark.parametrize("timestamp_source", ["server_default", "orm_written"])
def test_creation_accepts_server_default_and_orm_timestamps(client, plan_scenario, kind, timestamp_source):
    s = plan_scenario
    if timestamp_source == "orm_written":
        s.objective.created_at = datetime(2026, 1, 1, 12, 30, 0, 123456)
        s.objective.updated_at = datetime(2026, 1, 2, 12, 30, 0, 654321)
        db.session.commit()
    raw = db.session.execute(select(
        cast(QualityObjective.created_at, String), cast(QualityObjective.updated_at, String),
    ).where(QualityObjective.id == s.objective.id)).one()
    assert all(("." in value) == (timestamp_source == "orm_written") for value in raw)
    link = create_plan(client, s, kind)
    assert link.objective_id == s.objective.id


@pytest.mark.parametrize("kind", ["project", "action"])
@pytest.mark.parametrize("race", ["before_timestamp_review", "after_timestamp_review", "after_title_review"])
def test_compare_and_swap_rejects_source_race_after_token_validation(client, plan_scenario, kind, race, monkeypatch):
    from app import objective_plans

    s = plan_scenario
    data = plan_payload(client, s, kind)
    before = business_snapshot(s)
    original = objective_plans.reviewed_conditions
    seen = []

    def changed_source_conditions(objective):
        seen.append(objective.id)
        values = {"updated_at": objective.updated_at + timedelta(seconds=1)}
        if race == "after_title_review":
            values = {"title": "Changed between review and allocation", "updated_at": objective.updated_at}
        statement = update(QualityObjective.__table__).where(QualityObjective.id == objective.id).values(**values)
        # Mutate the database without refreshing the reviewed ORM identity.
        if race == "before_timestamp_review":
            db.session.connection().execute(statement)
            return original(objective)
        conditions = original(objective)
        db.session.connection().execute(statement)
        return conditions

    with monkeypatch.context() as patch:
        patch.setattr(objective_plans, "reviewed_conditions", changed_source_conditions)
        assert client.post(plan_path(s, kind), data=data).status_code == 409
    assert seen == [s.objective.id]
    assert business_snapshot(s) == before
    assert client.post(plan_path(s, kind), data=data).status_code == 302


@pytest.mark.parametrize("kind", ["project", "action"])
def test_submitted_plan_dates_survive_in_description_and_audit(client, plan_scenario, kind):
    s = plan_scenario
    start = s.objective.period_start + timedelta(days=3)
    due = s.objective.period_end - timedelta(days=4)
    link = create_plan(client, s, kind, start_date=start.isoformat(), due_date=due.isoformat())
    target = db.session.get(ProjectRecord, link.project_id) if kind == "project" else db.session.get(Action, link.action_id)
    assert str(start) in target.description and str(due) in target.description
    assert str(s.objective.period_start) in target.description and str(s.objective.period_end) in target.description
    audit = AuditLog.query.filter_by(entity_type="ObjectivePlanLink", entity_id=str(link.id), action="created").one()
    values = json.loads(audit.new_values)
    assert values["plan_start_date"] == start.isoformat()
    assert values["plan_due_date"] == due.isoformat()
    assert values["source_snapshot"]["period_start"] == s.objective.period_start.isoformat()
    assert values["source_snapshot"]["period_end"] == s.objective.period_end.isoformat()
    if kind == "project":
        task = ProjectTask.query.one()
        assert target.start_date == task.start_date == start
        assert target.due_date == task.due_date == due
    else:
        assert target.termin_date == due


@pytest.mark.parametrize("state,expected", [
    ("pending_effectiveness", "Etkinlik Kontrol\u00fc Bekliyor"),
    ("failed_effectiveness", "Etkin De\u011fil"),
    ("pending_closure", "Kapanma Onay\u0131 Beklemede"),
    ("rejected_closure", "Kapanma Onay\u0131 Reddedildi"),
])
def test_objective_plan_shows_action_workflow_status(client, plan_scenario, state, expected):
    s = plan_scenario
    link = create_plan(client, s, "action")
    action = db.session.get(Action, link.action_id)
    if state in {"pending_effectiveness", "failed_effectiveness"}:
        action.effectiveness_required = True
        action.effectiveness_result = "Bekliyor" if state == "pending_effectiveness" else "Etkin De\u011fil"
        action.is_completed = state == "pending_effectiveness"
        action.completed_at = date.today() if action.is_completed else None
    elif state == "pending_closure":
        action.closure_approval_requested = True
    else:
        action.closure_rejection_reason = "Insufficient closure evidence"
        action.closure_rejected_at = datetime(2026, 1, 2, 12)
        action.closure_rejected_by_user_id = s.manager.id
    db.session.commit()
    contexts = []

    def capture(sender, template, context, **extra):
        contexts.append(context)

    with template_rendered.connected_to(capture, client.application):
        response = client.get(objective_path(s))
    assert response.status_code == 200
    entries = [entry for context in contexts for entry in context.get("execution_plans", [])]
    assert len(entries) == 1
    assert entries[0]["status"] == expected
    assert entries[0]["url"] == f"/actions/{action.id}"
    assert expected in response.get_data(as_text=True)
    db.session.refresh(s.objective)
    assert s.objective.status == QUALITY_OBJECTIVE_STATUS_ACTIVE
