from datetime import date, timedelta
from io import BytesIO
import importlib.util
import json
from pathlib import Path
import zipfile
from xml.etree import ElementTree as ET

import pytest
from flask import g, template_rendered
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError
from werkzeug.exceptions import Forbidden, NotFound

from app.extensions import db
from app.models import AuditLog, CompanyModule, Notification, UserPermission
from app.org_context import CLIMATE_LABELS, TEXT_FIELDS, FACTORS, assigned_task_rows, report_data
from app.context_models import OrganizationContext
from tests.helpers import create_company, create_user, login, sheet_values


@pytest.fixture()
def scenario(client):
    company = create_company("CONTEXT")
    manager = create_user("context-manager", company=company, role_key="department_manager")
    owner = create_user("context-owner", company=company, role_key="department_manager", full_name="Çağrı Öztürk")
    reviewer = create_user("context-reviewer", company=company, role_key="management")
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
    values = dict(title="Üretim Kuruluş Bağlamı", scope="İç ve dış bağlam", owner_user_id=owner.id,
        analysis_date="2026-10-01", review_date="2026-11-01",
        internal_issues="İşgücü beklentileri", external_issues="Mevzuat değişikliği",
        climate_relevance="relevant", climate_reason="İklim etkileri ve kaynak ihtiyacı",
        evidence_sources="Kullanıcı değerlendirmesi ve 2026 bağlam toplantısı",
        strategy="Eğitim ve tedarik geliştirme")
    values.update(overrides)
    return values


def create_analysis(client, owner, **overrides):
    response = client.post("/kurulus-baglami/yeni", data=form_data(owner, **overrides))
    assert response.status_code == 302, response.get_data(as_text=True)
    return OrganizationContext.query.order_by(OrganizationContext.id.desc()).first()


def transition(client, analysis, action, **overrides):
    values = dict(action=action, version_id=analysis.version_id, note="Gerekçe açıklandı.",
                  review_note="Yönetim tarafından değerlendirildi.")
    values.update(overrides)
    return client.post(f"/kurulus-baglami/{analysis.id}/durum", data=values)


def grant_only(user, *permissions):
    user.roles.clear()
    user.extra_permissions[:] = [UserPermission(permission_key=key) for key in permissions]
    db.session.commit()


def test_crud_review_reopen_archive_audit_and_turkish_export(client, scenario, rendered):
    company, manager, owner, reviewer = scenario
    analysis = create_analysis(client, owner)
    assert analysis.record_no == f"BAG-{analysis.created_at.year}-{analysis.id:04d}"
    assert analysis.status == "draft" and analysis.version_id == 1
    assert client.get("/kurulus-baglami?q=Üretim&status=draft").status_code == 200
    assert rendered[-1]["analyses"] == [analysis]
    assert rendered[-1]["factors"] == FACTORS
    assert "quadrants" not in rendered[-1]
    assert rendered[-1]["climate_labels"] == CLIMATE_LABELS
    login(client, owner, company)
    assert client.get(f"/kurulus-baglami/{analysis.id}/duzenle").status_code == 200
    assert str(rendered[-1]["values"]["analysis_date"]) == "2026-10-01"
    for field in TEXT_FIELDS:
        assert rendered[-1]["values"][field] == getattr(analysis, field)
    assert client.post(f"/kurulus-baglami/{analysis.id}/duzenle", data=form_data(owner,
        version_id=analysis.version_id, title="Güncel Kuruluş Bağlamı")).status_code == 302
    assert analysis.version_id == 2
    assert transition(client, analysis, "review").status_code == 403
    login(client, reviewer, company)
    assert transition(client, analysis, "review").status_code == 302
    assert analysis.status == "reviewed" and analysis.reviewed_by_user_id == reviewer.id
    original_review = analysis.reviewed_at.isoformat()
    login(client, manager, company)
    assert client.get(f"/kurulus-baglami/{analysis.id}/duzenle").status_code == 409
    assert transition(client, analysis, "reopen", note="").status_code == 400
    login(client, reviewer, company)
    assert transition(client, analysis, "reopen", note="").status_code == 400
    assert transition(client, analysis, "reopen").status_code == 302
    assert analysis.status == "draft"
    assert (analysis.review_note, analysis.reviewed_by_user_id, analysis.reviewed_at) == (None, None, None)
    log = AuditLog.query.filter_by(entity_type="OrganizationContext", action="reopen").one()
    old, new = json.loads(log.old_values), json.loads(log.new_values)
    assert old["reviewed_at"] == original_review and old["reviewed_by_user_id"] == reviewer.id
    assert old["review_note"] == "Yönetim tarafından değerlendirildi."
    assert new["reviewed_at"] is None and new["reason"] == "Gerekçe açıklandı."
    assert transition(client, analysis, "review").status_code == 302
    login(client, manager, company)
    assert transition(client, analysis, "archive", note="").status_code == 400
    assert transition(client, analysis, "archive").status_code == 302
    assert analysis.status == "archived" and analysis.archive_note == "Gerekçe açıklandı."
    assert analysis.reviewed_by_user_id == reviewer.id
    assert Notification.query.filter_by(company_id=company.id).count() == 0
    assert client.get(f"/kurulus-baglami/{analysis.id}").status_code == 200
    assert not rendered[-1]["can_edit"] and not rendered[-1]["can_archive"] and not rendered[-1]["can_reopen"]
    response = client.get(f"/kurulus-baglami/{analysis.id}/rapor")
    assert response.status_code == 200 and response.mimetype.endswith("spreadsheetml.sheet")
    headers, row = sheet_values(response.data)
    assert "Analiz Tarihi" in headers and "Sonraki Gözden Geçirme" in headers
    assert "Çağrı Öztürk" in row and "İşgücü beklentileri" in row and analysis.archive_note in row
    assert row[7:9] == [getattr(analysis, key) for key in FACTORS]
    assert row[9] == analysis.evidence_sources
    assert row[-2:] == [reviewer.full_name, analysis.reviewed_at.strftime("%d.%m.%Y %H:%M")]
    logs = AuditLog.query.filter_by(entity_type="OrganizationContext").all()
    assert {"created", "updated", "review", "reopen", "archive", "exported"} <= {log.action for log in logs}
    for log in logs:
        assert log.company_id == company.id and json.loads(log.new_values)["company_id"] == company.id
    assert transition(client, analysis, "archive").status_code == 409


@pytest.mark.parametrize("field", [*TEXT_FIELDS, "review_note"])
def test_review_requires_every_factor_sources_strategy_and_note(client, scenario, field, rendered):
    company, manager, owner, reviewer = scenario
    analysis = create_analysis(client, owner, **({field: " "} if field != "review_note" else {}))
    login(client, reviewer, company)
    response = transition(client, analysis, "review", **({field: " "} if field == "review_note" else {}))
    assert response.status_code == 400
    assert analysis.status == "draft" and analysis.version_id == 1
    assert rendered[-1]["values"]["action"] == "review"
    assert AuditLog.query.filter_by(entity_type="OrganizationContext", action="review").count() == 0


def test_review_accepts_template_note_field(client, scenario):
    company, manager, owner, reviewer = scenario
    analysis = create_analysis(client, owner)
    login(client, reviewer, company)
    assert client.post(f"/kurulus-baglami/{analysis.id}/durum", data={"action": "review", "note": "Kontrol edildi.",
        "version_id": analysis.version_id}).status_code == 302
    assert analysis.review_note == "Kontrol edildi."


def test_owner_can_reopen_and_manager_can_recover_inactive_owner(client, scenario):
    company, manager, owner, reviewer = scenario
    analysis = create_analysis(client, owner)
    login(client, reviewer, company)
    assert transition(client, analysis, "review").status_code == 302
    login(client, owner, company)
    assert transition(client, analysis, "reopen", note="Yeni dönem").status_code == 302
    assert transition(client, analysis, "review").status_code == 403
    login(client, reviewer, company)
    assert transition(client, analysis, "review").status_code == 302
    owner.is_active = False
    db.session.commit()
    assert transition(client, analysis, "reopen", note="Sorumlu değişikliği").status_code == 302
    assert analysis.status == "draft"


@pytest.mark.parametrize("overrides", [
    {"title": ""}, {"title": "x" * 241}, {"internal_issues": "x" * 20001},
    {"analysis_date": "wrong"}, {"review_date": "2026-10-01"}, {"review_date": "2026-09-30"},
    {"review_date": ""}, {"owner_user_id": "bad"}, {"owner_user_id": 999999},
])
def test_invalid_forms_retain_data_without_mutation(client, scenario, rendered, overrides):
    company, manager, owner, reviewer = scenario
    data = form_data(owner, **overrides)
    assert client.post("/kurulus-baglami/yeni", data=data).status_code == 400
    assert rendered[-1]["values"]["internal_issues"] == data["internal_issues"]
    assert rendered[-1]["factors"] == FACTORS
    assert OrganizationContext.query.count() == 0
    analysis = create_analysis(client, owner)
    assert client.post(f"/kurulus-baglami/{analysis.id}/duzenle", data=dict(data, version_id=analysis.version_id)).status_code == 400
    assert rendered[-1]["values"]["external_issues"] == "Mevzuat değişikliği"
    assert analysis.title == "Üretim Kuruluş Bağlamı" and analysis.version_id == 1


@pytest.mark.parametrize("owner_kind", ["foreign", "inactive", "read_only", "create_only"])
def test_owner_must_be_active_same_tenant_reader_and_editor(client, scenario, owner_kind):
    company, manager, owner, reviewer = scenario
    if owner_kind == "foreign":
        owner = create_user("foreign-owner", company=create_company("foreign"), role_key="department_manager")
    elif owner_kind == "inactive":
        owner.is_active = False
        db.session.commit()
    else:
        grant_only(owner, "context.view" if owner_kind == "read_only" else "context.create")
    assert client.post("/kurulus-baglami/yeni", data=form_data(owner)).status_code == 400
    assert OrganizationContext.query.count() == 0


def test_visibility_reassignment_and_notification_retirement(client, scenario, monkeypatch):
    from app import org_context
    company, manager, owner, reviewer = scenario
    calls = []
    original = org_context.add_user_notification

    def onsite_only(*args, **kwargs):
        assert kwargs.get("email_event") is None
        calls.append(kwargs["source_key"])
        return original(*args, **kwargs)

    monkeypatch.setattr(org_context, "add_user_notification", onsite_only)
    analysis = create_analysis(client, owner)
    assert Notification.query.filter_by(user_id=owner.id).count() == 1
    with client.application.test_request_context():
        g.current_user, g.current_company = manager, company
        org_context.notify(analysis)
        db.session.commit()
    assert Notification.query.filter_by(user_id=owner.id).count() == 1
    replacement = create_user("new-owner", company=company, role_key="department_manager")
    assert client.post(f"/kurulus-baglami/{analysis.id}/duzenle", data=form_data(replacement,
        review_date="2026-12-01", version_id=analysis.version_id)).status_code == 302
    assert Notification.query.filter_by(user_id=owner.id).count() == 0
    notice = Notification.query.filter_by(user_id=replacement.id).one()
    assert notice.due_date == date(2026, 12, 1) and notice.target_url == f"/kurulus-baglami/{analysis.id}"
    assert calls[0] == calls[1] and calls[0] != calls[-1]
    login(client, owner, company)
    for suffix in ("", "/duzenle", "/rapor"):
        assert client.get(f"/kurulus-baglami/{analysis.id}{suffix}").status_code == 404
    assert transition(client, analysis, "archive").status_code == 404
    login(client, replacement, company)
    assert client.get(f"/kurulus-baglami/{analysis.id}").status_code == 200
    assert transition(client, analysis, "archive").status_code == 302
    assert Notification.query.filter_by(user_id=replacement.id).count() == 0


def test_assignee_handover_redirects_to_list_after_losing_access(client, scenario):
    company, creator, owner, reviewer = scenario
    analysis = create_analysis(client, owner)
    replacement = create_user("context-handover", company=company, role_key="department_manager")
    login(client, owner, company)
    response = client.post(f"/kurulus-baglami/{analysis.id}/duzenle", data=form_data(replacement,
        version_id=analysis.version_id), follow_redirects=True)
    assert response.status_code == 200
    assert response.request.path == "/kurulus-baglami"
    assert "Analiz sorumluluğu devredildi." in response.get_data(as_text=True)
    assert client.get(f"/kurulus-baglami/{analysis.id}").status_code == 404


@pytest.mark.parametrize("same_company", [True, False])
def test_unrelated_and_cross_tenant_access(client, scenario, same_company, rendered):
    company, manager, owner, reviewer = scenario
    analysis = create_analysis(client, owner)
    tenant = company if same_company else create_company("OTHER")
    outsider = create_user("outside", company=tenant, role_key="department_manager", full_name=owner.full_name)
    login(client, outsider, tenant)
    assert client.get("/kurulus-baglami").status_code == 200 and rendered[-1]["analyses"] == []
    for suffix in ("", "/duzenle", "/rapor"):
        assert client.get(f"/kurulus-baglami/{analysis.id}{suffix}").status_code == 404
    assert transition(client, analysis, "review").status_code == 404
    assert client.post(f"/kurulus-baglami/{analysis.id}/duzenle", data=form_data(outsider,
        version_id=analysis.version_id)).status_code == 404
    with client.application.test_request_context():
        g.current_user, g.current_company = outsider, tenant
        assert report_data()["rows"] == [] and assigned_task_rows("assigned", lambda **kw: kw) == []
    if not same_company:
        grant_only(outsider, "context.manage", "context.export")
        assert client.get(f"/kurulus-baglami/{analysis.id}").status_code == 404


def test_view_all_manage_and_review_do_not_bypass_other_permissions(client, scenario, rendered):
    company, manager, owner, reviewer = scenario
    analysis = create_analysis(client, owner)
    viewer = create_user("all-reader", company=company, permissions=("context.view_all",))
    login(client, viewer, company)
    assert client.get(f"/kurulus-baglami/{analysis.id}").status_code == 200
    assert not rendered[-1]["can_edit"] and not rendered[-1]["can_review"]
    assert client.get(f"/kurulus-baglami/{analysis.id}/rapor").status_code == 403
    assert client.get("/kurulus-baglami/yeni").status_code == 403
    assert transition(client, analysis, "archive").status_code == 403
    grant_only(viewer, "context.view_all", "context.review")
    assert transition(client, analysis, "review").status_code == 302
    assert transition(client, analysis, "reopen").status_code == 302
    assert client.get(f"/kurulus-baglami/{analysis.id}/duzenle").status_code == 403
    grant_only(viewer, "context.manage")
    assert client.get(f"/kurulus-baglami/{analysis.id}/duzenle").status_code == 200
    assert transition(client, analysis, "archive").status_code == 302
    assert client.get(f"/kurulus-baglami/{analysis.id}/rapor").status_code == 403


@pytest.mark.parametrize("role,can_create,can_see,can_review", [
    ("super_admin", True, True, True), ("management_representative", True, True, True),
    ("management", True, True, True), ("department_manager", True, False, False),
    ("department_staff", False, False, False), ("viewer", False, False, False),
])
def test_default_role_matrix(client, scenario, role, can_create, can_see, can_review, rendered):
    company, manager, owner, reviewer = scenario
    analysis = create_analysis(client, owner)
    user = create_user("role-" + role, company=None if role == "super_admin" else company, role_key=role)
    login(client, user, company)
    assert client.get("/kurulus-baglami/yeni").status_code == (200 if can_create else 403)
    assert client.get(f"/kurulus-baglami/{analysis.id}").status_code == (200 if can_see else 404)
    if can_see:
        assert rendered[-1]["can_review"] == can_review


@pytest.mark.parametrize("version", [None, "", "bad", "0", "999"])
def test_all_mutations_reject_missing_or_stale_versions(client, scenario, version):
    company, manager, owner, reviewer = scenario
    analysis = create_analysis(client, owner)
    data = form_data(owner)
    if version is not None:
        data["version_id"] = version
    assert client.post(f"/kurulus-baglami/{analysis.id}/duzenle", data=data).status_code == 409
    login(client, reviewer, company)
    for action in ("review", "reopen"):
        payload = dict(action=action, note="Gerekçe")
        if version is not None:
            payload["version_id"] = version
        assert client.post(f"/kurulus-baglami/{analysis.id}/durum", data=payload).status_code == 409
    login(client, manager, company)
    assert transition(client, analysis, "archive", version_id=version or "").status_code == 409
    assert analysis.version_id == 1 and analysis.status == "draft"


def test_two_session_optimistic_lock(client, scenario):
    company, manager, owner, reviewer = scenario
    analysis = create_analysis(client, owner)
    with Session(db.engine) as first, Session(db.engine) as second:
        current = first.get(OrganizationContext, analysis.id)
        stale = second.get(OrganizationContext, analysis.id)
        current.title = "First update"
        first.commit()
        stale.title = "Lost update"
        with pytest.raises(StaleDataError):
            second.commit()


def test_csrf_and_disabled_user_module_and_no_company(client, scenario):
    company, manager, owner, reviewer = scenario
    client.application.config["WTF_CSRF_ENABLED"] = True
    assert client.post("/kurulus-baglami/yeni", data=form_data(owner), headers={"Accept": "application/json"}).status_code == 400
    assert OrganizationContext.query.count() == 0
    client.application.config["WTF_CSRF_ENABLED"] = False
    module = CompanyModule.query.filter_by(company_id=company.id, module_key="stakeholder_management").one()
    module.is_enabled = False
    db.session.commit()
    assert client.get("/kurulus-baglami").status_code in (403, 404)
    with client.application.test_request_context():
        g.current_user, g.current_company = manager, company
        g.company_module_enabled = lambda key: False
        with pytest.raises(NotFound):
            report_data()
        assert assigned_task_rows("assigned", lambda **kw: kw) == []
    module.is_enabled = True
    manager.is_active = False
    db.session.commit()
    assert client.get("/kurulus-baglami").status_code in (302, 403)
    with client.application.test_request_context():
        g.current_user, g.current_company = manager, company
        with pytest.raises(Forbidden):
            report_data()
    admin = create_user("global-admin", role_key="super_admin")
    login(client, admin)
    assert client.get("/kurulus-baglami").status_code == 403
    with client.session_transaction() as session:
        session.clear()
    assert client.get("/kurulus-baglami").status_code == 302


def test_report_builder_read_only_and_export_revocation(client, scenario):
    company, manager, owner, reviewer = scenario
    analysis = create_analysis(client, owner, title='=HYPERLINK("https://example.test")')
    response = client.get(f"/kurulus-baglami/{analysis.id}/rapor")
    assert sheet_values(response.data)[1][1] == analysis.title
    grant_only(manager, "context.view")
    with client.application.test_request_context():
        g.current_user, g.current_company = manager, company
        data = report_data()
        assert data["rows"][0][1] == analysis.title
        assert data["rows"][0][4:6] == ("01.10.2026", "01.11.2026")
        assert len(data["headers"]) == len(data["rows"][0]) == len(data["column_widths"])
    assert client.get(f"/kurulus-baglami/{analysis.id}/rapor").status_code == 403
    grant_only(manager, "context.export")
    assert client.get(f"/kurulus-baglami/{analysis.id}/rapor").status_code == 403


def test_assigned_tasks_status_boundary_scope_and_permissions(client, scenario):
    company, manager, owner, reviewer = scenario
    today = date.today()
    expected = []
    for status, days in (("draft", 100), ("reviewed", 30), ("reviewed", 31), ("reviewed", -1), ("archived", 1)):
        login(client, manager, company)
        analysis = create_analysis(client, owner, title=f"{status}-{days}",
            analysis_date=str(today - timedelta(days=365)), review_date=str(today + timedelta(days=days)))
        if status == "reviewed":
            login(client, reviewer, company)
            assert transition(client, analysis, "review").status_code == 302
        elif status == "archived":
            assert transition(client, analysis, "archive").status_code == 302
        if status != "archived" and not (status == "reviewed" and days > 30):
            expected.append(analysis.title)
    with client.application.test_request_context():
        g.current_user, g.current_company = owner, company
        rows = assigned_task_rows("assigned", lambda **kw: kw)
        assert {row["title"] for row in rows} == set(expected)
        assert all(row["module_key"] == "context" and row["module_icon"] == "building" for row in rows)
        assert next(row for row in rows if row["title"] == "reviewed--1")["status_key"] == "delayed"
        assert assigned_task_rows("created", lambda **kw: kw) == []
        g.current_user = manager
        assert assigned_task_rows("assigned", lambda **kw: kw) == []
        g.current_user = owner
        grant_only(owner, "context.view")
        assert assigned_task_rows("assigned", lambda **kw: kw) == []
        grant_only(owner, "context.create")
        assert assigned_task_rows("assigned", lambda **kw: kw) == []


@pytest.mark.parametrize("failure", ["audit", "notify"])
def test_audit_and_notification_failures_rollback_entire_mutation(client, scenario, monkeypatch, failure):
    from app import org_context
    company, manager, owner, reviewer = scenario
    analysis = create_analysis(client, owner)
    previous_notice = Notification.query.filter_by(user_id=owner.id).one().source_key

    def fail(*args, **kwargs):
        raise RuntimeError("Simulated persistence failure")

    monkeypatch.setattr(org_context, failure, fail)
    client.application.config["TESTING"] = True
    with pytest.raises(RuntimeError):
        client.post(f"/kurulus-baglami/{analysis.id}/duzenle", data=form_data(owner,
            version_id=analysis.version_id, title="Must roll back"))
    db.session.refresh(analysis)
    assert analysis.title == "Üretim Kuruluş Bağlamı" and analysis.version_id == 1
    assert AuditLog.query.filter_by(entity_type="OrganizationContext", action="updated").count() == 0
    assert Notification.query.filter_by(user_id=owner.id).one().source_key == previous_notice


@pytest.mark.parametrize("statement", [
    "UPDATE organization_contexts SET owner_user_id=:foreign_user WHERE id=:id",
    "UPDATE organization_contexts SET created_by_user_id=:foreign_user WHERE id=:id",
    "UPDATE organization_contexts SET reviewed_by_user_id=:foreign_user WHERE id=:id",
    "UPDATE organization_contexts SET company_id=:foreign_company, owner_user_id=:foreign_user, created_by_user_id=:foreign_user WHERE id=:id",
    "UPDATE organization_contexts SET review_date=analysis_date WHERE id=:id",
    "UPDATE organization_contexts SET status='other' WHERE id=:id",
    "UPDATE organization_contexts SET status='reviewed' WHERE id=:id",
    "UPDATE organization_contexts SET status='archived' WHERE id=:id",
    "UPDATE organization_contexts SET version_id=0 WHERE id=:id",
    "UPDATE organization_contexts SET owner_user_id=999999 WHERE id=:id",
    "UPDATE organization_contexts SET created_by_user_id=999999 WHERE id=:id",
    "UPDATE organization_contexts SET reviewed_by_user_id=999999 WHERE id=:id",
    "UPDATE organization_contexts SET company_id=999999 WHERE id=:id",
    "DELETE FROM users WHERE id=:owner",
    "DELETE FROM users WHERE id=:creator",
    "UPDATE users SET company_id=:foreign_company WHERE id=:owner",
    "UPDATE users SET id=999999 WHERE id=:creator",
    "DELETE FROM companies WHERE id=:company",
    "UPDATE companies SET id=999999 WHERE id=:company",
])
def test_sqlite_fk_off_constraints_and_reference_guards(client, scenario, statement):
    company, manager, owner, reviewer = scenario
    analysis = create_analysis(client, owner)
    foreign_company = create_company("FK-OTHER")
    foreign_user = create_user("foreign-guard", company=foreign_company, role_key="department_manager")
    params = dict(id=analysis.id, company=company.id, creator=manager.id, owner=owner.id,
                  foreign_user=foreign_user.id, foreign_company=foreign_company.id)
    db.session.commit()
    db.session.execute(text("PRAGMA foreign_keys=OFF"))
    assert db.session.execute(text("PRAGMA foreign_keys")).scalar() == 0
    with pytest.raises(IntegrityError):
        db.session.execute(text(statement), params)
        db.session.commit()
    db.session.rollback()
    assert db.session.get(OrganizationContext, params["id"]).company_id == params["company"]


def test_reviewed_user_delete_and_move_protected(client, scenario):
    company, manager, owner, reviewer = scenario
    analysis = create_analysis(client, owner)
    login(client, reviewer, company)
    assert transition(client, analysis, "review").status_code == 302
    reviewer_id = reviewer.id
    for sql in ("DELETE FROM users WHERE id=:id", "UPDATE users SET company_id=NULL WHERE id=:id"):
        with pytest.raises(IntegrityError):
            db.session.execute(text(sql), {"id": reviewer_id})
            db.session.commit()
        db.session.rollback()


@pytest.mark.parametrize("runtime_created", [False, True])
def test_migration_idempotence_runtime_compatibility_and_roundtrip(runtime_created, monkeypatch):
    import sqlalchemy as sa
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from app.context_schema import drop_context_sqlite_guards, ensure_context_sqlite_guards

    path = Path(__file__).resolve().parents[1] / "migrations/versions/202610050004_add_org_context.py"
    spec = importlib.util.spec_from_file_location("context_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.revision == "202610050004"
    assert migration.down_revision == "202610050003"
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE companies (id INTEGER PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY, company_id INTEGER)"))
        connection.execute(text("INSERT INTO companies VALUES (1), (2)"))
        connection.execute(text("INSERT INTO users VALUES (1, 1), (2, 2)"))
        connection.execute(text("CREATE TABLE unrelated (id INTEGER PRIMARY KEY, note TEXT)"))
        connection.execute(text("INSERT INTO unrelated VALUES (1, 'Preserve me')"))
        connection.execute(text("PRAGMA foreign_keys=OFF"))
        assert connection.execute(text("PRAGMA foreign_keys")).scalar() == 0
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        insert = text("INSERT INTO organization_contexts (id,company_id,title,owner_user_id,created_by_user_id,analysis_date,review_date) "
                      "VALUES (1,1,'Kuruluş Bağlamı',1,1,'2026-10-01','2026-11-01')")
        if runtime_created:
            metadata = sa.MetaData()
            sa.Table("companies", metadata, autoload_with=connection)
            sa.Table("users", metadata, autoload_with=connection)
            OrganizationContext.__table__.to_metadata(metadata).create(connection)
            ensure_context_sqlite_guards(connection)
            connection.execute(insert)
        migration.upgrade()
        if not runtime_created:
            connection.execute(insert)
        before = connection.execute(text("SELECT * FROM organization_contexts")).all()
        migration.upgrade()
        assert connection.execute(text("SELECT * FROM organization_contexts")).all() == before
        assert connection.execute(text("SELECT title FROM organization_contexts")).scalar() == "Kuruluş Bağlamı"
        assert connection.execute(text("SELECT climate_relevance FROM organization_contexts")).scalar() == "under_review"
        context = MigrationContext.configure(connection, opts={
            "compare_type": True, "compare_server_default": True,
            "include_object": lambda obj, name, kind, reflected, compare_to:
                name == "organization_contexts" if kind == "table" else True,
        })
        assert compare_metadata(context, db.metadata) == []
        schema = inspect(connection)
        assert {c["name"] for c in schema.get_columns("organization_contexts")} == set(OrganizationContext.__table__.columns.keys())
        assert len(schema.get_check_constraints("organization_contexts")) == 8
        assert {item["name"]: item["sqltext"] for item in schema.get_check_constraints("organization_contexts")} == {
            item.name: str(item.sqltext) for item in OrganizationContext.__table__.constraints
            if isinstance(item, sa.CheckConstraint)
        }
        assert len(schema.get_indexes("organization_contexts")) == 5
        trigger_sql = connection.execute(text("SELECT sql FROM sqlite_master WHERE type='trigger' ORDER BY name")).scalars().all()
        assert len(trigger_sql) == 9
        drop_context_sqlite_guards(connection)
        ensure_context_sqlite_guards(connection)
        ensure_context_sqlite_guards(connection)
        assert connection.execute(text("SELECT sql FROM sqlite_master WHERE type='trigger' ORDER BY name")).scalars().all() == trigger_sql
        with pytest.raises(IntegrityError):
            connection.execute(text("UPDATE organization_contexts SET owner_user_id=2 WHERE id=1"))
        for assignment in ("climate_relevance='unknown'", "climate_relevance=NULL",
                           "status='reviewed'", "created_by_user_id=2", "company_id=999999"):
            with pytest.raises(IntegrityError):
                connection.execute(text(f"UPDATE organization_contexts SET {assignment} WHERE id=1"))
        migration.downgrade()
        assert not inspect(connection).has_table("organization_contexts")
        assert not connection.execute(text("SELECT name FROM sqlite_master WHERE type='trigger'")).all()
        connection.execute(text("UPDATE users SET company_id=2 WHERE id=1"))
        migration.upgrade()
        assert inspect(connection).has_table("organization_contexts")
        assert connection.execute(text("SELECT sql FROM sqlite_master WHERE type='trigger' ORDER BY name")).scalars().all() == trigger_sql
        assert connection.execute(text("SELECT * FROM unrelated")).all() == [(1, "Preserve me")]
        assert connection.execute(text("SELECT * FROM companies ORDER BY id")).all() == [(1,), (2,)]
        assert connection.execute(text("PRAGMA integrity_check")).scalar() == "ok"
        assert not connection.execute(text("PRAGMA foreign_key_check")).all()
    engine.dispose()


def test_factor_contract_and_stable_record_number(client, scenario):
    company, manager, owner, reviewer = scenario
    assert FACTORS == {"internal_issues": "İç Hususlar", "external_issues": "Dış Hususlar"}
    analysis = create_analysis(client, owner, analysis_date="2020-01-01")
    record_no = analysis.record_no
    assert record_no == f"BAG-{analysis.created_at.year}-{analysis.id:04d}"
    assert client.post(f"/kurulus-baglami/{analysis.id}/duzenle", data=form_data(owner,
        analysis_date="2021-01-01", version_id=analysis.version_id)).status_code == 302
    assert analysis.record_no == record_no
    notice = Notification.query.filter_by(user_id=owner.id).one()
    assert notice.message.startswith(record_no) and notice.source_key.startswith("context:")
    response = client.get(f"/kurulus-baglami/{analysis.id}/rapor")
    assert record_no in response.headers["Content-Disposition"]
    assert sheet_values(response.data)[1][0] == record_no
    legacy = OrganizationContext(id=42, analysis_date=date(2020, 1, 1))
    assert legacy.record_no == "BAG-2020-0042"


def test_manage_only_can_create_and_recover_inactive_owner(client, scenario, rendered):
    company, manager, owner, reviewer = scenario
    grant_only(manager, "context.manage")
    assert client.get("/kurulus-baglami").status_code == 200
    assert rendered[-1]["can_create"]
    analysis = create_analysis(client, owner)
    assert transition(client, analysis, "review").status_code == 302
    owner.is_active = False
    db.session.commit()
    assert transition(client, analysis, "reopen", note=" ").status_code == 400
    assert transition(client, analysis, "reopen", note="Sorumlu artık aktif değil.").status_code == 302
    assert transition(client, analysis, "review").status_code == 400
    assert client.post(f"/kurulus-baglami/{analysis.id}/duzenle", data=form_data(manager,
        version_id=analysis.version_id)).status_code == 302
    assert analysis.owner_user_id == manager.id
    assert transition(client, analysis, "review").status_code == 302
    assert Notification.query.filter_by(user_id=owner.id).count() == 0
    assert Notification.query.filter_by(user_id=manager.id).count() == 1


def test_reviewed_and_archived_records_reject_content_edits(client, scenario):
    company, manager, owner, reviewer = scenario
    analysis = create_analysis(client, owner)
    grant_only(manager, "context.manage")
    assert transition(client, analysis, "reopen").status_code == 409
    assert transition(client, analysis, "unknown").status_code == 400
    assert transition(client, analysis, "review").status_code == 302
    assert transition(client, analysis, "review").status_code == 409
    for status in ("reviewed", "archived"):
        if status == "archived":
            assert transition(client, analysis, "archive").status_code == 302
        old_version = analysis.version_id
        assert client.post(f"/kurulus-baglami/{analysis.id}/duzenle", data=form_data(owner,
            title="Must not change", version_id=old_version)).status_code == 409
        assert analysis.title == "Üretim Kuruluş Bağlamı" and analysis.version_id == old_version
    assert transition(client, analysis, "reopen").status_code == 409
    assert transition(client, analysis, "review").status_code == 409


@pytest.mark.parametrize("prefix", ["=", "+", "-", "@", "\t="])
def test_export_keeps_untrusted_values_as_text(client, scenario, prefix):
    company, manager, owner, reviewer = scenario
    value = prefix + '<script>"Çağrı & çevre"</script>'
    analysis = create_analysis(client, owner, **{
        field: value for field in ("title", *TEXT_FIELDS)
    })
    response = client.get(f"/kurulus-baglami/{analysis.id}/rapor")
    assert response.status_code == 200
    namespace = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(BytesIO(response.data)) as archive:
        sheet = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
    assert not sheet.findall(".//m:f", namespace)
    assert all(cell.attrib["t"] == "inlineStr" for cell in sheet.findall(".//m:c", namespace))
    row = sheet_values(response.data)[1]
    for index in (1, 2, *range(7, 11), 12):
        assert row[index] == value.strip()


@pytest.mark.parametrize("character", ["\x01", "\x0b", "\x1f", "\ufffe", "\uffff"])
def test_export_replaces_invalid_xml_characters_without_changing_source(client, scenario, character):
    from app.org_context import report_row
    value = f"Valid{character}control"
    analysis = create_analysis(client, scenario[2], internal_issues=value, title=value)
    response = client.get(f"/kurulus-baglami/{analysis.id}/rapor")
    assert response.status_code == 200
    with zipfile.ZipFile(BytesIO(response.data)) as archive:
        for name in archive.namelist():
            if name.endswith('.xml'):
                ET.fromstring(archive.read(name))
    assert sheet_values(response.data)[1][7] == "Valid\ufffdcontrol"
    assert report_row(analysis)[1] == "Valid\ufffdcontrol"
    db.session.refresh(analysis)
    assert analysis.internal_issues == value and analysis.title == value


@pytest.mark.parametrize("field", [*TEXT_FIELDS, "review_note"])
def test_database_review_required_fields(client, scenario, field):
    company, manager, owner, reviewer = scenario
    analysis = create_analysis(client, owner)
    login(client, reviewer, company)
    assert transition(client, analysis, "review").status_code == 302
    analysis_id = analysis.id
    for invalid in (None, "", "   ", "\t", "\n", "\r\n", "\u00a0", "\u2003\u202f\u3000"):
        with pytest.raises(IntegrityError):
            db.session.execute(OrganizationContext.__table__.update().where(
                OrganizationContext.id == analysis_id).values({field: invalid}))
            db.session.commit()
        db.session.rollback()
    db.session.refresh(analysis)
    assert analysis.status == "reviewed" and getattr(analysis, field)


def test_database_rejects_whitespace_title_and_archive_reason(client, scenario):
    analysis = create_analysis(client, scenario[2])
    analysis_id = analysis.id
    for blank in ("\t", "\n", "\u00a0", "\u2003\u202f\u3000"):
        for values in ({"title": blank}, {"status": "archived", "archive_note": blank}):
            with pytest.raises(IntegrityError):
                db.session.execute(OrganizationContext.__table__.update().where(
                    OrganizationContext.id == analysis_id).values(**values))
                db.session.commit()
            db.session.rollback()


@pytest.mark.parametrize("field", [*TEXT_FIELDS])
def test_text_limits_retain_submitted_fields(client, scenario, rendered, field):
    company, manager, owner, reviewer = scenario
    data = form_data(owner, **{field: "x" * 20001})
    assert client.post("/kurulus-baglami/yeni", data=data).status_code == 400
    assert rendered[-1]["values"][field] == data[field]
    assert OrganizationContext.query.count() == 0


@pytest.mark.parametrize("action", ["created", "review", "reopen", "archive", "exported"])
def test_audit_failure_rolls_back_all_workflow_actions(client, scenario, monkeypatch, action):
    from app import org_context
    company, manager, owner, reviewer = scenario
    analysis = create_analysis(client, owner)
    grant_only(manager, "context.manage", "context.export")
    if action == "reopen":
        assert transition(client, analysis, "review").status_code == 302
    old = org_context.snapshot(analysis)
    notice_keys = [row.source_key for row in Notification.query.all()]
    log_count = AuditLog.query.filter_by(entity_type="OrganizationContext").count()

    def fail(*args, **kwargs):
        raise RuntimeError("Audit persistence failure")

    monkeypatch.setattr(org_context, "record_audit_event", fail)
    client.application.config["TESTING"] = True
    with pytest.raises(RuntimeError):
        if action == "created":
            client.post("/kurulus-baglami/yeni", data=form_data(owner))
        elif action == "exported":
            client.get(f"/kurulus-baglami/{analysis.id}/rapor")
        else:
            transition(client, analysis, action)
    db.session.refresh(analysis)
    assert org_context.snapshot(analysis) == old
    assert OrganizationContext.query.count() == 1
    assert AuditLog.query.filter_by(entity_type="OrganizationContext").count() == log_count
    assert [row.source_key for row in Notification.query.all()] == notice_keys


def test_csrf_blocks_edit_and_transition_without_mutation(client, scenario):
    company, manager, owner, reviewer = scenario
    analysis = create_analysis(client, owner)
    grant_only(manager, "context.manage")
    client.application.config["WTF_CSRF_ENABLED"] = True
    headers = {"Accept": "application/json"}
    assert client.post(f"/kurulus-baglami/{analysis.id}/duzenle", headers=headers,
        data=form_data(owner, version_id=analysis.version_id)).status_code == 400
    assert client.post(f"/kurulus-baglami/{analysis.id}/durum", headers=headers,
        data=dict(action="review", note="Review", version_id=analysis.version_id)).status_code == 400
    assert analysis.status == "draft" and analysis.version_id == 1


def test_partial_draft_defaults_and_no_delete_endpoint(client, scenario, rendered):
    company, manager, owner, reviewer = scenario
    data = form_data(owner)
    for field in (*TEXT_FIELDS, "climate_relevance"):
        data.pop(field)
    assert client.post("/kurulus-baglami/yeni", data=data).status_code == 302
    analysis = OrganizationContext.query.one()
    assert analysis.status == "draft" and analysis.climate_relevance == "under_review"
    assert all(not getattr(analysis, field) for field in TEXT_FIELDS)
    assert client.get(f"/kurulus-baglami/{analysis.id}/duzenle").status_code == 200
    assert rendered[-1]["values"]["climate_relevance"] == "under_review"
    login(client, reviewer, company)
    assert transition(client, analysis, "review").status_code == 400
    assert client.delete(f"/kurulus-baglami/{analysis.id}").status_code == 405
    assert client.post(f"/kurulus-baglami/{analysis.id}/sil").status_code == 404
    assert OrganizationContext.query.count() == 1


@pytest.mark.parametrize("decision", ["under_review", "relevant", "not_relevant"])
def test_review_climate_gate_and_audit(client, scenario, decision):
    company, manager, owner, reviewer = scenario
    analysis = create_analysis(client, owner, climate_relevance=decision)
    login(client, reviewer, company)
    result = transition(client, analysis, "review")
    if decision == "under_review":
        assert result.status_code == 400
        assert analysis.status == "draft" and analysis.version_id == 1
        assert analysis.reviewed_at is None and analysis.reviewed_by_user_id is None
        assert AuditLog.query.filter_by(entity_type="OrganizationContext", action="review").count() == 0
    else:
        assert result.status_code == 302
        log = AuditLog.query.filter_by(entity_type="OrganizationContext", action="review").one()
        old, new = json.loads(log.old_values), json.loads(log.new_values)
        assert old["status"] == "draft" and new["status"] == "reviewed"
        assert old["climate_relevance"] == new["climate_relevance"] == decision
        assert new["scope"] == analysis.scope and new["climate_reason"] == analysis.climate_reason
        assert new["reviewed_by_user_id"] == reviewer.id and new["reviewed_at"]
        response = client.get(f"/kurulus-baglami/{analysis.id}/rapor")
        assert sheet_values(response.data)[1][11:13] == [CLIMATE_LABELS[decision], analysis.climate_reason]


@pytest.mark.parametrize("invalid", ["", "unknown", "RELEVANT", " relevant ", "x" * 20001])
def test_invalid_climate_field_retained_without_mutation(client, scenario, rendered, invalid):
    company, manager, owner, reviewer = scenario
    data = form_data(owner, climate_relevance=invalid)
    assert client.post("/kurulus-baglami/yeni", data=data).status_code == 400
    assert rendered[-1]["values"]["climate_relevance"] == invalid
    assert rendered[-1]["climate_labels"] == CLIMATE_LABELS
    assert OrganizationContext.query.count() == 0
    analysis = create_analysis(client, owner)
    assert client.post(f"/kurulus-baglami/{analysis.id}/duzenle",
        data=dict(data, version_id=analysis.version_id)).status_code == 400
    assert analysis.climate_relevance == "relevant" and analysis.version_id == 1
    assert AuditLog.query.filter_by(entity_type="OrganizationContext", action="updated").count() == 0


@pytest.mark.parametrize("status", ["draft", "reviewed"])
@pytest.mark.parametrize("invalid", [None, "", "other", "under_review"])
def test_database_climate_enum_and_decided_gate(client, scenario, status, invalid):
    company, manager, owner, reviewer = scenario
    analysis = create_analysis(client, owner)
    if status == "reviewed":
        login(client, reviewer, company)
        assert transition(client, analysis, "review").status_code == 302
    statement = OrganizationContext.__table__.update().where(
        OrganizationContext.id == analysis.id).values(climate_relevance=invalid)
    if status == "draft" and invalid == "under_review":
        db.session.execute(statement)
        db.session.commit()
    else:
        with pytest.raises(IntegrityError):
            db.session.execute(statement)
            db.session.commit()
        db.session.rollback()


@pytest.mark.parametrize("field", ["reviewed_by_user_id", "reviewed_at"])
def test_database_review_requires_reviewer_and_timestamp(client, scenario, field):
    company, manager, owner, reviewer = scenario
    analysis = create_analysis(client, owner)
    login(client, reviewer, company)
    assert transition(client, analysis, "review").status_code == 302
    with pytest.raises(IntegrityError):
        db.session.execute(OrganizationContext.__table__.update().where(
            OrganizationContext.id == analysis.id).values({field: None}))
        db.session.commit()
    db.session.rollback()


def test_shared_module_gate_only_checks_stakeholder_management(client, scenario):
    company, manager, owner, reviewer = scenario
    create_analysis(client, owner)
    with client.application.test_request_context():
        g.current_user, g.current_company = owner, company
        g.company_module_enabled = lambda key: key == "stakeholder_management"
        assert len(report_data()["rows"]) == 1
        assert len(assigned_task_rows("assigned", lambda **kw: kw)) == 1
        g.company_module_enabled = lambda key: key != "stakeholder_management"
        with pytest.raises(NotFound):
            report_data()
        assert assigned_task_rows("assigned", lambda **kw: kw) == []


def test_all_export_text_is_xml_safe_without_source_or_audit_mutation(client, scenario):
    from app.org_context import report_row
    company, manager, owner, reviewer = scenario
    value = "Çağrı\x01 & <kaynak>\uffff"
    clean = "Çağrı\ufffd & <kaynak>\ufffd"
    owner.full_name = reviewer.full_name = value
    db.session.commit()
    analysis = create_analysis(client, owner, **{field: value for field in ("title", *TEXT_FIELDS)})
    login(client, reviewer, company)
    assert transition(client, analysis, "review", review_note=value).status_code == 302
    login(client, manager, company)
    assert transition(client, analysis, "archive", note=value).status_code == 302
    response = client.get(f"/kurulus-baglami/{analysis.id}/rapor")
    assert response.status_code == 200
    row = sheet_values(response.data)[1]
    for index in (1, 2, 3, 7, 8, 9, 10, 12, 13, 14, 15):
        assert row[index] == clean
    with zipfile.ZipFile(BytesIO(response.data)) as archive:
        for name in archive.namelist():
            if name.endswith(".xml"):
                ET.fromstring(archive.read(name))
    with client.application.test_request_context():
        g.current_user, g.current_company = manager, company
        assert report_data()["rows"] == [report_row(analysis)]
    db.session.refresh(analysis)
    for field in ("title", *TEXT_FIELDS, "review_note", "archive_note"):
        assert getattr(analysis, field) == value
    for log in AuditLog.query.filter_by(entity_type="OrganizationContext"):
        assert json.loads(log.new_values)["climate_reason"] == value


@pytest.mark.parametrize("character", ["\ud800", "\udfff"])
def test_report_row_sanitizes_unpaired_surrogates(character):
    from app.org_context import report_row
    analysis = OrganizationContext(id=1, title=character, scope=character,
        analysis_date=date(2026, 10, 1), review_date=date(2026, 11, 1),
        status="draft", climate_relevance="under_review", climate_reason=character)
    row = report_row(analysis)
    assert row[1] == row[2] == row[12] == "\ufffd"


@pytest.mark.parametrize("failure", [IntegrityError("test", {}, Exception()), StaleDataError("test")])
def test_racing_http_update_returns_conflict_and_rolls_back(client, scenario, monkeypatch, failure):
    from app import org_context
    analysis = create_analysis(client, scenario[2])
    before = org_context.snapshot(analysis)

    def fail(*args, **kwargs):
        raise failure

    monkeypatch.setattr(org_context, "touch", fail)
    assert client.post(f"/kurulus-baglami/{analysis.id}/duzenle", data=form_data(scenario[2],
        title="Race", version_id=analysis.version_id)).status_code == 409
    db.session.refresh(analysis)
    assert org_context.snapshot(analysis) == before


def test_notifications_retire_only_this_context_record(client, scenario):
    from app.org_context import retire_notices
    company, manager, owner, reviewer = scenario
    first = create_analysis(client, owner)
    second = create_analysis(client, owner)
    db.session.add(Notification(company_id=company.id, user_id=owner.id,
        message="PESTLE unrelated", source_key=f"pestle:{first.id}:owner:{owner.id}:1"))
    db.session.commit()
    retire_notices(first)
    db.session.commit()
    keys = [notice.source_key for notice in Notification.query.all()]
    assert len(keys) == 2
    assert any(key.startswith(f"context:{second.id}:") for key in keys)
    assert any(key.startswith("pestle:") for key in keys)


def test_owner_picker_excludes_foreign_inactive_and_read_only_users(client, scenario, rendered):
    company, manager, owner, reviewer = scenario
    foreign = create_user("picker-foreign", company=create_company("PICKER"), role_key="department_manager")
    inactive = create_user("picker-inactive", company=company, role_key="department_manager")
    inactive.is_active = False
    reader = create_user("picker-reader", company=company, permissions=("context.view",))
    creator = create_user("picker-creator", company=company, permissions=("context.create",))
    assert client.get("/kurulus-baglami/yeni").status_code == 200
    ids = {user.id for user in rendered[-1]["users"]}
    assert {owner.id, manager.id, reviewer.id} <= ids
    assert not ids & {foreign.id, inactive.id, reader.id, creator.id}


def test_global_admin_can_create_and_review_with_company_scoped_owner(client, scenario):
    company, manager, owner, reviewer = scenario
    admin = create_user("context-global-admin", role_key="super_admin")
    login(client, admin, company)
    assert client.post("/kurulus-baglami/yeni", data=form_data(admin)).status_code == 400
    analysis = create_analysis(client, owner)
    assert analysis.created_by_user_id == admin.id
    assert transition(client, analysis, "review").status_code == 302
    assert analysis.reviewed_by_user_id == admin.id
    assert client.get(f"/kurulus-baglami/{analysis.id}/rapor").status_code == 200
