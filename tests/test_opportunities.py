from datetime import date
import json

import pytest
from flask import g, template_rendered
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError
from werkzeug.exceptions import Forbidden, NotFound

from app.extensions import db
from app.models import Action, AuditLog, CompanyModule, Notification, RiskRecord, UserPermission
from app.opportunity_models import Opportunity
from app import opportunities
from tests.helpers import create_company, create_user, login, sheet_values


BASE = "/risk-firsat-portfoyu"


@pytest.fixture()
def scenario(client):
    company = create_company("OPPORTUNITY")
    manager = create_user("opportunity-manager", company=company, permissions=(
        "opportunity.manage", "opportunity.export", "risk.manage", "actions.view_all"))
    owner = create_user("opportunity-owner", company=company, full_name="Çağrı Öztürk",
                        permissions=("opportunity.view", "opportunity.create", "opportunity.export"))
    reviewer = create_user("opportunity-reviewer", company=company,
        permissions=("opportunity.view_all", "opportunity.review", "opportunity.export"))
    login(client, manager, company)
    return company, manager, owner, reviewer


@pytest.fixture()
def rendered(app):
    contexts = []
    def capture(sender, template, context, **extra):
        contexts.append(context)
    template_rendered.connect(capture, app)
    yield contexts
    template_rendered.disconnect(capture, app)


def form_data(owner, **overrides):
    values = dict(title="Üretimde verimlilik fırsatı", description="Enerji tüketimini azaltma",
        expected_benefit="Yüzde 10 tasarruf", planned_action="Pilot uygulama",
        success_criteria="Birim başına tüketimde yüzde 10 azalma", source_reference="Ekim bağlam toplantısı",
        analysis_date="2026-10-01", due_date="2026-11-01", review_date="2026-11-05",
        owner_user_id=owner.id, likelihood="4", benefit="5", action_id="")
    values.update(overrides)
    return values


def create_opportunity(client, owner, **overrides):
    response = client.post(f"{BASE}/firsat/yeni", data=form_data(owner, **overrides))
    assert response.status_code == 302, response.get_data(as_text=True)
    return Opportunity.query.order_by(Opportunity.id.desc()).first()


def transition(client, item, action, **overrides):
    values = dict(action=action, version_id=item.version_id, note="Gerekçe kaydedildi.",
                  result_note="Ölçüm tamamlandı.", evidence_sources="2026 pilot sonuç raporu")
    values.update(overrides)
    return client.post(f"{BASE}/firsat/{item.id}/durum", data=values)


def grant_only(user, *permissions):
    user.roles.clear()
    user.extra_permissions[:] = [UserPermission(permission_key=key) for key in permissions]
    db.session.commit()


def make_action(company, owner, **overrides):
    values = dict(company_id=company.id, title="Gizli aksiyon başlığı", responsible_owner=owner.full_name,
                  responsible_user_id=owner.id, department="Kalite", termin_date=date(2026, 11, 1), is_completed=False)
    values.update(overrides)
    item = Action(**values)
    db.session.add(item)
    db.session.commit()
    return item


def test_lifecycle_edit_result_reopen_archive_and_export(client, scenario, rendered):
    company, manager, owner, reviewer = scenario
    item = create_opportunity(client, owner)
    reference = item.record_no
    assert reference == f"FRS-{item.created_at.year}-{item.id:04d}"
    assert item.priority_score == 20 and item.version_id == 1
    assert item.status == "draft"
    login(client, owner, company)
    assert client.get(f"{BASE}/firsat/{item.id}/duzenle").status_code == 200
    assert rendered[-1]["values"]["success_criteria"] == item.success_criteria
    assert client.post(f"{BASE}/firsat/{item.id}/duzenle", data=form_data(owner,
        version_id=1, title="Güncel fırsat", analysis_date="2025-10-01")).status_code == 302
    assert item.version_id == 2 and item.record_no == reference
    assert transition(client, item, "activate").status_code == 302
    assert item.status == "active"
    assert transition(client, item, "archive").status_code == 409
    assert transition(client, item, "realized").status_code == 403
    login(client, reviewer, company)
    assert transition(client, item, "realized").status_code == 302
    assert item.status == "realized" and item.reviewed_by_user_id == reviewer.id
    reviewed_at = item.reviewed_at.isoformat()
    login(client, manager, company)
    assert client.get(f"{BASE}/firsat/{item.id}/duzenle").status_code == 409
    assert transition(client, item, "reopen", note=" \t").status_code == 400
    assert transition(client, item, "reopen").status_code == 302
    assert item.status == "draft"
    assert (item.result_note, item.evidence_sources, item.reviewed_at, item.reviewed_by_user_id) == (None, None, None, None)
    log = AuditLog.query.filter_by(entity_type="Opportunity", action="reopen").one()
    old, new = json.loads(log.old_values), json.loads(log.new_values)
    assert old["reviewed_at"] == reviewed_at and old["reviewed_by_user_id"] == reviewer.id
    assert old["result_note"] and old["evidence_sources"]
    assert new["result_note"] is None and new["reason"] == "Gerekçe kaydedildi."
    assert transition(client, item, "activate").status_code == 302
    assert transition(client, item, "not_realized").status_code == 302
    assert transition(client, item, "archive", note="").status_code == 400
    assert transition(client, item, "archive").status_code == 302
    assert item.status == "archived" and item.result_note
    assert transition(client, item, "reopen").status_code == 409
    assert Notification.query.filter(Notification.source_key.like("opportunity:%")).count() == 0
    response = client.get(f"{BASE}/firsat/{item.id}/rapor")
    assert response.status_code == 200
    headers, row = sheet_values(response.data)
    assert len(headers) == len(row) == len(opportunities.REPORT_HEADERS)
    values = dict(zip(headers, row))
    assert values["Başarı Ölçütü"] == item.success_criteria
    assert values["Gözden Geçirme Tarihi"] == "05.11.2026"
    assert values["Sorumlu"] == "Çağrı Öztürk"
    assert values["Analiz Tarihi"] == "01.10.2025"
    assert values["Öncelik Puanı"] == "20"
    logs = AuditLog.query.filter_by(entity_type="Opportunity").all()
    assert {"created", "updated", "activate", "realized", "not_realized", "reopen", "archive", "exported"} <= {log.action for log in logs}
    assert all(log.company_id == company.id for log in logs)


@pytest.mark.parametrize("field", ["description", "expected_benefit", "planned_action", "success_criteria", "review_date"])
def test_activation_requires_content_owner_and_review_date(client, scenario, field):
    company, manager, owner, reviewer = scenario
    item = create_opportunity(client, owner, **{field: ""})
    assert transition(client, item, "activate").status_code == 400
    assert item.status == "draft" and item.version_id == 1


@pytest.mark.parametrize("field", ["result_note", "evidence_sources"])
def test_close_requires_result_and_evidence(client, scenario, field):
    item = create_opportunity(client, scenario[2])
    assert transition(client, item, "activate").status_code == 302
    assert transition(client, item, "realized", **{field: "\t\u2003"}).status_code == 400
    assert item.status == "active" and item.reviewed_at is None and item.version_id == 2


@pytest.mark.parametrize("overrides", [
    {"title": ""}, {"title": "x" * 241}, {"success_criteria": "x" * 20001},
    {"analysis_date": "bad"}, {"due_date": "2026-09-30"}, {"review_date": "2026-09-30"},
    {"owner_user_id": "bad"}, {"owner_user_id": 999999}, {"likelihood": "1.5"}, {"likelihood": 0},
    {"benefit": 6}, {"benefit": ""}, {"action_id": "bad"}, {"action_id": 999999},
    {"action_id": "9" * 200}, {"owner_user_id": "9" * 200},
])
def test_malformed_forms_do_not_mutate(client, scenario, overrides, rendered):
    owner = scenario[2]
    assert client.post(f"{BASE}/firsat/yeni", data=form_data(owner, **overrides)).status_code == 400
    assert Opportunity.query.count() == 0
    assert rendered[-1]["values"]["expected_benefit"] == "Yüzde 10 tasarruf"
    item = create_opportunity(client, owner)
    assert client.post(f"{BASE}/firsat/{item.id}/duzenle", data=form_data(owner,
        version_id=item.version_id, **overrides)).status_code == 400
    assert item.version_id == 1 and item.title == "Üretimde verimlilik fırsatı"


def test_date_equality_and_score_extremes(client, scenario):
    item = create_opportunity(client, scenario[2], likelihood=1, benefit=1, due_date="2026-10-01", review_date="2026-10-01")
    assert item.priority_score == 1
    item2 = create_opportunity(client, scenario[2], likelihood=5, benefit=5)
    assert item2.priority_score == 25


def test_inactive_owner_recovery_and_reassignment(client, scenario):
    company, manager, owner, reviewer = scenario
    item = create_opportunity(client, owner)
    owner.is_active = False
    db.session.commit()
    assert transition(client, item, "activate").status_code == 400
    owner.is_active = True
    db.session.commit()
    assert transition(client, item, "activate").status_code == 302
    assert transition(client, item, "recover").status_code == 409
    owner.is_active = False
    db.session.commit()
    assert transition(client, item, "recover", note="").status_code == 400
    assert transition(client, item, "recover").status_code == 302
    assert item.status == "draft"
    assert client.post(f"{BASE}/firsat/{item.id}/duzenle", data=form_data(manager, version_id=item.version_id)).status_code == 302
    assert item.owner_user_id == manager.id


def test_row_visibility_reviewer_not_privileged_and_foreign_tenant(client, scenario):
    company, manager, owner, reviewer = scenario
    item = create_opportunity(client, owner)
    grant_only(reviewer, "opportunity.view", "opportunity.review", "opportunity.export")
    login(client, reviewer, company)
    for suffix in ("", "/duzenle", "/rapor"):
        assert client.get(f"{BASE}/firsat/{item.id}{suffix}").status_code == 404
    assert transition(client, item, "realized").status_code == 404
    other = create_company("OPP-OTHER")
    outsider = create_user("opp-outsider", company=other, permissions=("opportunity.manage", "opportunity.export"))
    login(client, outsider, other)
    assert client.get(f"{BASE}/firsat/{item.id}").status_code == 404
    assert client.post(f"{BASE}/firsat/yeni", data=form_data(owner)).status_code == 400
    assert item.title not in client.get(BASE).get_data(as_text=True)


@pytest.mark.parametrize("permissions", [(), ("opportunity.create",), ("opportunity.review",), ("opportunity.export",), ("risk.view_all",)])
def test_strict_combined_guard(client, scenario, permissions):
    company, manager, owner, reviewer = scenario
    grant_only(manager, *permissions)
    assert client.get(BASE).status_code == 403
    assert client.get(f"{BASE}/firsat/yeni").status_code == 403


def test_module_off_and_no_company_even_global_admin(client, scenario):
    company, manager, owner, reviewer = scenario
    item = create_opportunity(client, owner)
    company_module = CompanyModule.query.filter_by(company_id=company.id, module_key="risk_management").one()
    company_module.is_enabled = False
    db.session.commit()
    for suffix in ("", "/firsat/yeni", f"/firsat/{item.id}", f"/firsat/{item.id}/rapor"):
        assert client.get(BASE + suffix).status_code == 403
    with client.application.test_request_context():
        g.current_user, g.current_company = manager, company
        with pytest.raises(NotFound):
            opportunities.report_data()
        assert opportunities.assigned_task_rows("all", lambda **row: row) == []
    admin = create_user("opp-global", role_key="super_admin")
    login(client, admin)
    assert client.get(BASE).status_code == 403
    with client.application.test_request_context():
        g.current_user, g.current_company, g.current_user_is_super_admin = admin, None, True
        with pytest.raises(Forbidden):
            opportunities.report_data()


def test_stale_edit_transition_and_concurrent_orm_cas(client, scenario):
    item = create_opportunity(client, scenario[2])
    for version in ("", "bad", "0", "2"):
        assert client.post(f"{BASE}/firsat/{item.id}/duzenle", data=form_data(scenario[2], version_id=version)).status_code == 409
        assert transition(client, item, "activate", version_id=version).status_code == 409
    with Session(db.engine) as first, Session(db.engine) as second:
        left, right = first.get(Opportunity, item.id), second.get(Opportunity, item.id)
        left.title = "İlk değişiklik"
        first.commit()
        right.title = "Eski değişiklik"
        with pytest.raises(StaleDataError):
            second.commit()
    db.session.expire_all()
    assert item.title == "İlk değişiklik" and item.version_id == 2


@pytest.mark.parametrize("operation", ["create", "edit", "transition"])
def test_audit_failure_rolls_back_record_and_notices(client, scenario, monkeypatch, operation):
    owner = scenario[2]
    item = create_opportunity(client, owner) if operation != "create" else None
    before_notices = [(notice.id, notice.source_key) for notice in Notification.query.all()]
    before_logs = AuditLog.query.filter_by(entity_type="Opportunity").count()
    def fail(*args, **kwargs):
        raise RuntimeError("audit unavailable")
    monkeypatch.setattr(opportunities, "record_audit_event", fail)
    client.application.config["PROPAGATE_EXCEPTIONS"] = True
    with pytest.raises(RuntimeError, match="audit unavailable"):
        if operation == "create":
            client.post(f"{BASE}/firsat/yeni", data=form_data(owner))
        elif operation == "edit":
            client.post(f"{BASE}/firsat/{item.id}/duzenle", data=form_data(owner, title="Changed", version_id=1))
        else:
            transition(client, item, "activate")
    assert Opportunity.query.count() == (1 if item else 0)
    if item:
        db.session.refresh(item)
        assert item.version_id == 1 and item.status == "draft" and item.title == "Üretimde verimlilik fırsatı"
    assert AuditLog.query.filter_by(entity_type="Opportunity").count() == before_logs
    assert [(notice.id, notice.source_key) for notice in Notification.query.all()] == before_notices


def test_notifications_are_inapp_deduplicated_and_skip_actor(client, scenario, monkeypatch):
    company, manager, owner, reviewer = scenario
    original = opportunities.add_user_notification
    def onsite_only(*args, **kwargs):
        assert kwargs.get("email_event") is None
        return original(*args, **kwargs)
    monkeypatch.setattr(opportunities, "add_user_notification", onsite_only)
    item = create_opportunity(client, owner)
    assert Notification.query.filter_by(user_id=owner.id).count() == 1
    with client.application.test_request_context():
        g.current_user, g.current_company = manager, company
        opportunities.notify(item)
        db.session.commit()
    assert Notification.query.filter_by(user_id=owner.id).count() == 1
    create_opportunity(client, manager)
    assert Notification.query.filter_by(user_id=manager.id).count() == 0
    login(client, owner, company)
    assert client.post(f"{BASE}/firsat/{item.id}/duzenle", data=form_data(manager, version_id=1)).status_code == 302
    assert Notification.query.filter_by(user_id=owner.id).count() == 0
    assert client.get(f"{BASE}/firsat/{item.id}").status_code == 404


def test_action_visibility_no_title_leak_and_completion_gate(client, scenario):
    company, manager, owner, reviewer = scenario
    action = make_action(company, manager)
    item = create_opportunity(client, owner, action_id=action.id)
    assert transition(client, item, "activate").status_code == 302
    login(client, owner, company)
    assert action.title not in client.get(f"{BASE}/firsat/{item.id}").get_data(as_text=True)
    headers, row = sheet_values(client.get(f"{BASE}/firsat/{item.id}/rapor").data)
    assert dict(zip(headers, row))["Bağlı Aksiyon"] == ""
    assert client.post(f"{BASE}/firsat/{item.id}/duzenle", data=form_data(owner, version_id=item.version_id, action_id=action.id)).status_code == 400
    assert client.post(f"{BASE}/firsat/{item.id}/duzenle", data=form_data(owner, version_id=item.version_id, action_id="__keep__")).status_code == 302
    assert item.action_id == action.id
    login(client, reviewer, company)
    response = transition(client, item, "realized")
    assert response.status_code == 400 and action.title not in response.get_data(as_text=True)
    action.is_completed = True
    db.session.commit()
    assert transition(client, item, "realized").status_code == 302
    assert action.is_completed


def test_action_selection_requires_module_permission_visibility_and_tenant(client, scenario, monkeypatch):
    company, manager, owner, reviewer = scenario
    action = make_action(company, manager)
    foreign = create_company("OPP-ACTION")
    foreign_action = make_action(foreign, create_user("opp-foreign-owner", company=foreign))
    assert client.post(f"{BASE}/firsat/yeni", data=form_data(owner, action_id=foreign_action.id)).status_code == 400
    login(client, owner, company)
    assert client.post(f"{BASE}/firsat/yeni", data=form_data(owner, action_id=action.id)).status_code == 400
    grant_only(owner, "opportunity.view", "opportunity.create", "actions.comment_assigned")
    assert client.post(f"{BASE}/firsat/yeni", data=form_data(owner, action_id=action.id)).status_code == 400
    action.responsible_user_id = owner.id
    db.session.commit()
    create_opportunity(client, owner, action_id=action.id)
    original = opportunities.module_enabled
    monkeypatch.setattr(opportunities, "module_enabled", lambda key: False if key == "actions" else original(key))
    assert client.post(f"{BASE}/firsat/yeni", data=form_data(owner, action_id=action.id)).status_code == 400


def test_export_xml_controls_and_export_permission(client, scenario):
    company, manager, owner, reviewer = scenario
    item = create_opportunity(client, owner, source_reference="Kaynak\x01\x0bÖlçüm", title="=2+2")
    response = client.get(f"{BASE}/firsat/{item.id}/rapor")
    assert response.status_code == 200
    headers, row = sheet_values(response.data)
    assert dict(zip(headers, row))["Kaynak Referansı"] == "Kaynak\ufffd\ufffdÖlçüm"
    assert dict(zip(headers, row))["Başlık"] == "=2+2"
    assert item.source_reference == "Kaynak\x01\x0bÖlçüm"
    grant_only(manager, "opportunity.manage")
    assert client.get(f"{BASE}/firsat/{item.id}/rapor").status_code == 403
    with client.application.test_request_context():
        g.current_user, g.current_company = manager, company
        assert opportunities.report_data()["rows"][0][0] == item.record_no


def test_tasks_only_owned_open_and_reports_only_visible_opportunities(client, scenario):
    company, manager, owner, reviewer = scenario
    draft = create_opportunity(client, owner)
    active = create_opportunity(client, owner)
    assert transition(client, active, "activate").status_code == 302
    closed = create_opportunity(client, owner)
    assert transition(client, closed, "activate").status_code == 302
    assert transition(client, closed, "not_realized").status_code == 302
    other = create_opportunity(client, manager)
    with client.application.test_request_context():
        g.current_user, g.current_company = owner, company
        tasks = opportunities.assigned_task_rows("all", lambda **row: row)
        assert {row["reference_no"] for row in tasks} == {draft.record_no, active.record_no}
        assert opportunities.assigned_task_rows("created", lambda **row: row) == []
        report = opportunities.report_data()
        assert {row[0] for row in report["rows"]} == {draft.record_no, active.record_no, closed.record_no}
        assert "Analiz Tarihi" in report["headers"]
        assert other.record_no not in {row[0] for row in report["rows"]}


def test_unified_portfolio_separate_counts_filters_and_links(client, scenario, rendered):
    company, manager, owner, reviewer = scenario
    item = create_opportunity(client, owner)
    risk = RiskRecord(company_id=company.id, risk_no="RSK-2026-9001", title="Risk bağımsız",
        likelihood=4, severity=4, status="Açık", owner_user_id=owner.id, created_by_user_id=manager.id)
    db.session.add(risk)
    db.session.commit()
    assert client.get(BASE).status_code == 200
    context = rendered[-1]
    assert context["counts"] == dict(open_risks=1, high_risks=1, open_opportunities=1, high_benefit=1)
    assert {row["kind"] for row in context["rows"]} == {"risk", "opportunity"}
    risk_row = next(row for row in context["rows"] if row["kind"] == "risk")
    assert "search=RSK-2026-9001" in risk_row["url"] and "edit" not in risk_row["url"]
    assert client.get(BASE + "?type=opportunity&status=draft").status_code == 200
    assert [row["reference"] for row in rendered[-1]["rows"]] == [item.record_no]
    assert client.get(BASE + "?q=" + item.record_no).status_code == 200
    assert rendered[-1]["total"] == 1
    grant_only(manager, "risk.view")
    response = client.get(BASE)
    assert response.status_code == 200 and item.title not in response.get_data(as_text=True)
    assert not rendered[-1]["can_create_risk"] and not rendered[-1]["can_create_opportunity"]
    assert rendered[-1]["counts"]["open_opportunities"] == 0
    login(client, owner, company)
    response = client.get(BASE)
    assert response.status_code == 200 and risk.title not in response.get_data(as_text=True)
    assert rendered[-1]["counts"]["open_risks"] == 0
    assert risk.rpn == 16 and risk.status == "Açık" and risk.action_id is None


def test_bounded_pagination(client, scenario, rendered):
    company, manager, owner, reviewer = scenario
    for index in range(28):
        db.session.add(Opportunity(company_id=company.id, title=f"Fırsat {index}", owner_user_id=owner.id,
            created_by_user_id=manager.id, analysis_date=date(2026, 10, 1), due_date=date(2026, 11, 1)))
    db.session.commit()
    assert client.get(BASE + "?page=-5").status_code == 200
    assert len(rendered[-1]["rows"]) == 25 and rendered[-1]["page"] == 1
    assert client.get(BASE + "?page=999999999999999999").status_code == 200
    assert len(rendered[-1]["rows"]) == 3 and rendered[-1]["page"] == 2
    assert client.get(BASE + "?q=FRS-2026-" + "9" * 200).status_code == 200
    assert client.get(BASE + "/firsat/" + "9" * 200).status_code == 404


def test_sqlite_cross_tenant_and_referenced_record_guards(client, scenario):
    company, manager, owner, reviewer = scenario
    other = create_company("OPP-GUARDS")
    foreign_owner = create_user("opp-guard-owner", company=other)
    action = make_action(company, manager)
    foreign_action = make_action(other, foreign_owner)
    item = create_opportunity(client, owner, action_id=action.id)
    attempts = (
        ("UPDATE opportunities SET company_id=:value WHERE id=:id", other.id, item.id),
        ("UPDATE opportunities SET owner_user_id=:value WHERE id=:id", foreign_owner.id, item.id),
        ("UPDATE opportunities SET created_by_user_id=:value WHERE id=:id", foreign_owner.id, item.id),
        ("UPDATE opportunities SET action_id=:value WHERE id=:id", foreign_action.id, item.id),
        ("UPDATE opportunities SET action_id=:value WHERE id=:id", 999999, item.id),
        ("UPDATE users SET company_id=:value WHERE id=:id", other.id, owner.id),
        ("UPDATE actions SET company_id=:value WHERE id=:id", other.id, action.id),
        ("DELETE FROM users WHERE id=:id", None, owner.id),
        ("DELETE FROM actions WHERE id=:id", None, action.id),
        ("DELETE FROM companies WHERE id=:id", None, company.id),
        ("UPDATE opportunities SET title=:value WHERE id=:id", "\t\u2003", item.id),
    )
    for statement, value, identifier in attempts:
        with pytest.raises(IntegrityError), db.session.begin_nested():
            db.session.execute(text(statement), {"id": identifier, "value": value})
    assert item.company_id == company.id and item.action_id == action.id
    action.title = "Normal aksiyon düzenlemesi"
    owner.full_name = "Yeni ad"
    owner.is_active = False
    db.session.commit()
    assert action.title == "Normal aksiyon düzenlemesi"
