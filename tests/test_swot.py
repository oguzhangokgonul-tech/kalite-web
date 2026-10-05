from datetime import date, timedelta
import importlib.util
import json
from pathlib import Path

import pytest
from flask import g, template_rendered
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError
from werkzeug.exceptions import Forbidden, NotFound

from app.extensions import db
from app.models import AuditLog, CompanyModule, Notification, UserPermission
from app.swot import QUADRANTS, assigned_task_rows, report_data
from app.swot_models import SwotAnalysis
from tests.helpers import create_company, create_user, login, sheet_values


@pytest.fixture()
def scenario(client):
    company = create_company("SWOT")
    manager = create_user("swot-manager", company=company, role_key="department_manager")
    owner = create_user("swot-owner", company=company, role_key="department_manager", full_name="Çağrı Öztürk")
    reviewer = create_user("swot-reviewer", company=company, role_key="management")
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
    values = dict(title="Üretim SWOT Analizi", scope="İç ve dış bağlam", owner_user_id=owner.id,
        analysis_date="2026-10-01", review_date="2026-11-01", strengths="Güçlü ekip",
        weaknesses="Eğitim açığı", opportunities="İhracat fırsatları", threats="Tedarik riski",
        strategy="Eğitim ve tedarik geliştirme")
    values.update(overrides)
    return values


def create_analysis(client, owner, **overrides):
    response = client.post("/swot/yeni", data=form_data(owner, **overrides))
    assert response.status_code == 302, response.get_data(as_text=True)
    return SwotAnalysis.query.order_by(SwotAnalysis.id.desc()).first()


def transition(client, analysis, action, **overrides):
    values = dict(action=action, version_id=analysis.version_id, note="Gerekçe açıklandı.",
                  review_note="Yönetim tarafından değerlendirildi.")
    values.update(overrides)
    return client.post(f"/swot/{analysis.id}/durum", data=values)


def grant_only(user, *permissions):
    user.roles.clear()
    user.extra_permissions[:] = [UserPermission(permission_key=key) for key in permissions]
    db.session.commit()


def test_crud_review_reopen_archive_audit_and_turkish_export(client, scenario, rendered):
    company, manager, owner, reviewer = scenario
    analysis = create_analysis(client, owner)
    assert analysis.record_no == f"SWOT-2026-{analysis.id:04d}"
    assert analysis.status == "draft" and analysis.version_id == 1
    assert client.get("/swot?q=Üretim&status=draft").status_code == 200
    assert rendered[-1]["analyses"] == [analysis]
    assert rendered[-1]["quadrants"] == QUADRANTS
    login(client, owner, company)
    assert client.get(f"/swot/{analysis.id}/duzenle").status_code == 200
    assert str(rendered[-1]["values"]["analysis_date"]) == "2026-10-01"
    assert client.post(f"/swot/{analysis.id}/duzenle", data=form_data(owner,
        version_id=analysis.version_id, title="Güncel SWOT")).status_code == 302
    assert analysis.version_id == 2
    assert transition(client, analysis, "review").status_code == 403
    login(client, reviewer, company)
    assert transition(client, analysis, "review").status_code == 302
    assert analysis.status == "reviewed" and analysis.reviewed_by_user_id == reviewer.id
    original_review = analysis.reviewed_at.isoformat()
    login(client, manager, company)
    assert client.get(f"/swot/{analysis.id}/duzenle").status_code == 409
    assert transition(client, analysis, "reopen", note="").status_code == 400
    login(client, reviewer, company)
    assert transition(client, analysis, "reopen", note="").status_code == 400
    assert transition(client, analysis, "reopen").status_code == 302
    assert analysis.status == "draft"
    assert (analysis.review_note, analysis.reviewed_by_user_id, analysis.reviewed_at) == (None, None, None)
    log = AuditLog.query.filter_by(entity_type="SwotAnalysis", action="reopen").one()
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
    assert client.get(f"/swot/{analysis.id}").status_code == 200
    assert not rendered[-1]["can_edit"] and not rendered[-1]["can_archive"] and not rendered[-1]["can_reopen"]
    response = client.get(f"/swot/{analysis.id}/rapor")
    assert response.status_code == 200 and response.mimetype.endswith("spreadsheetml.sheet")
    headers, row = sheet_values(response.data)
    assert "Analiz Tarihi" in headers and "Sonraki Gözden Geçirme" in headers
    assert "Çağrı Öztürk" in row and "İhracat fırsatları" in row and analysis.archive_note in row
    logs = AuditLog.query.filter_by(entity_type="SwotAnalysis").all()
    assert {"created", "updated", "review", "reopen", "archive", "exported"} <= {log.action for log in logs}
    for log in logs:
        assert log.company_id == company.id and json.loads(log.new_values)["company_id"] == company.id
    assert transition(client, analysis, "archive").status_code == 409


@pytest.mark.parametrize("field", [*QUADRANTS, "strategy", "review_note"])
def test_review_requires_every_quadrant_strategy_and_note(client, scenario, field, rendered):
    company, manager, owner, reviewer = scenario
    analysis = create_analysis(client, owner, **({field: " "} if field != "review_note" else {}))
    login(client, reviewer, company)
    response = transition(client, analysis, "review", **({field: " "} if field == "review_note" else {}))
    assert response.status_code == 400
    assert analysis.status == "draft" and analysis.version_id == 1
    assert rendered[-1]["values"]["action"] == "review"
    assert AuditLog.query.filter_by(entity_type="SwotAnalysis", action="review").count() == 0


def test_review_accepts_template_note_field(client, scenario):
    company, manager, owner, reviewer = scenario
    analysis = create_analysis(client, owner)
    login(client, reviewer, company)
    assert client.post(f"/swot/{analysis.id}/durum", data={"action": "review", "note": "Kontrol edildi.",
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
    {"title": ""}, {"title": "x" * 241}, {"scope": ""}, {"strengths": "x" * 20001},
    {"analysis_date": "wrong"}, {"review_date": "2026-10-01"}, {"review_date": "2026-09-30"},
    {"review_date": ""}, {"owner_user_id": "bad"}, {"owner_user_id": 999999},
])
def test_invalid_forms_retain_data_without_mutation(client, scenario, rendered, overrides):
    company, manager, owner, reviewer = scenario
    data = form_data(owner, **overrides)
    assert client.post("/swot/yeni", data=data).status_code == 400
    assert rendered[-1]["values"]["opportunities"] == "İhracat fırsatları"
    assert rendered[-1]["quadrants"] == QUADRANTS
    assert SwotAnalysis.query.count() == 0
    analysis = create_analysis(client, owner)
    assert client.post(f"/swot/{analysis.id}/duzenle", data=dict(data, version_id=analysis.version_id)).status_code == 400
    assert rendered[-1]["values"]["threats"] == "Tedarik riski"
    assert analysis.title == "Üretim SWOT Analizi" and analysis.version_id == 1


@pytest.mark.parametrize("owner_kind", ["foreign", "inactive", "read_only", "create_only"])
def test_owner_must_be_active_same_tenant_reader_and_editor(client, scenario, owner_kind):
    company, manager, owner, reviewer = scenario
    if owner_kind == "foreign":
        owner = create_user("foreign-owner", company=create_company("foreign"), role_key="department_manager")
    elif owner_kind == "inactive":
        owner.is_active = False
        db.session.commit()
    else:
        grant_only(owner, "swot.view" if owner_kind == "read_only" else "swot.create")
    assert client.post("/swot/yeni", data=form_data(owner)).status_code == 400
    assert SwotAnalysis.query.count() == 0


def test_visibility_reassignment_and_notification_retirement(client, scenario, monkeypatch):
    from app import swot
    company, manager, owner, reviewer = scenario
    calls = []
    original = swot.add_user_notification

    def onsite_only(*args, **kwargs):
        assert kwargs.get("email_event") is None
        calls.append(kwargs["source_key"])
        return original(*args, **kwargs)

    monkeypatch.setattr(swot, "add_user_notification", onsite_only)
    analysis = create_analysis(client, owner)
    assert Notification.query.filter_by(user_id=owner.id).count() == 1
    with client.application.test_request_context():
        g.current_user, g.current_company = manager, company
        swot.notify(analysis)
        db.session.commit()
    assert Notification.query.filter_by(user_id=owner.id).count() == 1
    replacement = create_user("new-owner", company=company, role_key="department_manager")
    assert client.post(f"/swot/{analysis.id}/duzenle", data=form_data(replacement,
        review_date="2026-12-01", version_id=analysis.version_id)).status_code == 302
    assert Notification.query.filter_by(user_id=owner.id).count() == 0
    notice = Notification.query.filter_by(user_id=replacement.id).one()
    assert notice.due_date == date(2026, 12, 1) and notice.target_url == f"/swot/{analysis.id}"
    assert calls[0] == calls[1] and calls[0] != calls[-1]
    login(client, owner, company)
    for suffix in ("", "/duzenle", "/rapor"):
        assert client.get(f"/swot/{analysis.id}{suffix}").status_code == 404
    assert transition(client, analysis, "archive").status_code == 404
    login(client, replacement, company)
    assert client.get(f"/swot/{analysis.id}").status_code == 200
    assert transition(client, analysis, "archive").status_code == 302
    assert Notification.query.filter_by(user_id=replacement.id).count() == 0


def test_assignee_handover_redirects_to_list_after_losing_access(client, scenario):
    company, creator, owner, reviewer = scenario
    analysis = create_analysis(client, owner)
    replacement = create_user("swot-handover", company=company, role_key="department_manager")
    login(client, owner, company)
    response = client.post(f"/swot/{analysis.id}/duzenle", data=form_data(replacement,
        version_id=analysis.version_id), follow_redirects=True)
    assert response.status_code == 200
    assert response.request.path == "/swot"
    assert "Analiz sorumluluğu devredildi." in response.get_data(as_text=True)
    assert client.get(f"/swot/{analysis.id}").status_code == 404


@pytest.mark.parametrize("same_company", [True, False])
def test_unrelated_and_cross_tenant_access(client, scenario, same_company, rendered):
    company, manager, owner, reviewer = scenario
    analysis = create_analysis(client, owner)
    tenant = company if same_company else create_company("OTHER")
    outsider = create_user("outside", company=tenant, role_key="department_manager", full_name=owner.full_name)
    login(client, outsider, tenant)
    assert client.get("/swot").status_code == 200 and rendered[-1]["analyses"] == []
    for suffix in ("", "/duzenle", "/rapor"):
        assert client.get(f"/swot/{analysis.id}{suffix}").status_code == 404
    assert transition(client, analysis, "review").status_code == 404
    assert client.post(f"/swot/{analysis.id}/duzenle", data=form_data(outsider,
        version_id=analysis.version_id)).status_code == 404
    with client.application.test_request_context():
        g.current_user, g.current_company = outsider, tenant
        assert report_data()["rows"] == [] and assigned_task_rows("assigned", lambda **kw: kw) == []
    if not same_company:
        grant_only(outsider, "swot.manage", "swot.export")
        assert client.get(f"/swot/{analysis.id}").status_code == 404


def test_view_all_manage_and_review_do_not_bypass_other_permissions(client, scenario, rendered):
    company, manager, owner, reviewer = scenario
    analysis = create_analysis(client, owner)
    viewer = create_user("all-reader", company=company, permissions=("swot.view_all",))
    login(client, viewer, company)
    assert client.get(f"/swot/{analysis.id}").status_code == 200
    assert not rendered[-1]["can_edit"] and not rendered[-1]["can_review"]
    assert client.get(f"/swot/{analysis.id}/rapor").status_code == 403
    assert client.get("/swot/yeni").status_code == 403
    assert transition(client, analysis, "archive").status_code == 403
    grant_only(viewer, "swot.view_all", "swot.review")
    assert transition(client, analysis, "review").status_code == 302
    assert transition(client, analysis, "reopen").status_code == 302
    assert client.get(f"/swot/{analysis.id}/duzenle").status_code == 403
    grant_only(viewer, "swot.manage")
    assert client.get(f"/swot/{analysis.id}/duzenle").status_code == 200
    assert transition(client, analysis, "archive").status_code == 302
    assert client.get(f"/swot/{analysis.id}/rapor").status_code == 403


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
    assert client.get("/swot/yeni").status_code == (200 if can_create else 403)
    assert client.get(f"/swot/{analysis.id}").status_code == (200 if can_see else 404)
    if can_see:
        assert rendered[-1]["can_review"] == can_review


@pytest.mark.parametrize("version", [None, "", "bad", "0", "999"])
def test_all_mutations_reject_missing_or_stale_versions(client, scenario, version):
    company, manager, owner, reviewer = scenario
    analysis = create_analysis(client, owner)
    data = form_data(owner)
    if version is not None:
        data["version_id"] = version
    assert client.post(f"/swot/{analysis.id}/duzenle", data=data).status_code == 409
    login(client, reviewer, company)
    for action in ("review", "reopen"):
        payload = dict(action=action, note="Gerekçe")
        if version is not None:
            payload["version_id"] = version
        assert client.post(f"/swot/{analysis.id}/durum", data=payload).status_code == 409
    login(client, manager, company)
    assert transition(client, analysis, "archive", version_id=version or "").status_code == 409
    assert analysis.version_id == 1 and analysis.status == "draft"


def test_two_session_optimistic_lock(client, scenario):
    company, manager, owner, reviewer = scenario
    analysis = create_analysis(client, owner)
    with Session(db.engine) as first, Session(db.engine) as second:
        current = first.get(SwotAnalysis, analysis.id)
        stale = second.get(SwotAnalysis, analysis.id)
        current.title = "First update"
        first.commit()
        stale.title = "Lost update"
        with pytest.raises(StaleDataError):
            second.commit()


def test_csrf_and_disabled_user_module_and_no_company(client, scenario):
    company, manager, owner, reviewer = scenario
    client.application.config["WTF_CSRF_ENABLED"] = True
    assert client.post("/swot/yeni", data=form_data(owner), headers={"Accept": "application/json"}).status_code == 400
    assert SwotAnalysis.query.count() == 0
    client.application.config["WTF_CSRF_ENABLED"] = False
    module = CompanyModule.query.filter_by(company_id=company.id, module_key="swot").one()
    module.is_enabled = False
    db.session.commit()
    assert client.get("/swot").status_code in (403, 404)
    with client.application.test_request_context():
        g.current_user, g.current_company = manager, company
        g.company_module_enabled = lambda key: False
        with pytest.raises(NotFound):
            report_data()
        assert assigned_task_rows("assigned", lambda **kw: kw) == []
    module.is_enabled = True
    manager.is_active = False
    db.session.commit()
    assert client.get("/swot").status_code in (302, 403)
    with client.application.test_request_context():
        g.current_user, g.current_company = manager, company
        with pytest.raises(Forbidden):
            report_data()
    admin = create_user("global-admin", role_key="super_admin")
    login(client, admin)
    assert client.get("/swot").status_code == 403
    with client.session_transaction() as session:
        session.clear()
    assert client.get("/swot").status_code == 302


def test_report_builder_read_only_and_export_revocation(client, scenario):
    company, manager, owner, reviewer = scenario
    analysis = create_analysis(client, owner, title='=HYPERLINK("https://example.test")')
    response = client.get(f"/swot/{analysis.id}/rapor")
    assert sheet_values(response.data)[1][1] == analysis.title
    grant_only(manager, "swot.view")
    with client.application.test_request_context():
        g.current_user, g.current_company = manager, company
        data = report_data()
        assert data["rows"][0][1] == analysis.title
        assert data["rows"][0][4:6] == ("01.10.2026", "01.11.2026")
        assert len(data["headers"]) == len(data["rows"][0]) == len(data["column_widths"])
    assert client.get(f"/swot/{analysis.id}/rapor").status_code == 403
    grant_only(manager, "swot.export")
    assert client.get(f"/swot/{analysis.id}/rapor").status_code == 403


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
        assert next(row for row in rows if row["title"] == "reviewed--1")["status_key"] == "delayed"
        assert assigned_task_rows("created", lambda **kw: kw) == []
        g.current_user = manager
        assert assigned_task_rows("assigned", lambda **kw: kw) == []
        g.current_user = owner
        grant_only(owner, "swot.view")
        assert assigned_task_rows("assigned", lambda **kw: kw) == []
        grant_only(owner, "swot.create")
        assert assigned_task_rows("assigned", lambda **kw: kw) == []


@pytest.mark.parametrize("failure", ["audit", "notify"])
def test_audit_and_notification_failures_rollback_entire_mutation(client, scenario, monkeypatch, failure):
    from app import swot
    company, manager, owner, reviewer = scenario
    analysis = create_analysis(client, owner)
    previous_notice = Notification.query.filter_by(user_id=owner.id).one().source_key

    def fail(*args, **kwargs):
        raise RuntimeError("Simulated persistence failure")

    monkeypatch.setattr(swot, failure, fail)
    client.application.config["TESTING"] = True
    with pytest.raises(RuntimeError):
        client.post(f"/swot/{analysis.id}/duzenle", data=form_data(owner,
            version_id=analysis.version_id, title="Must roll back"))
    db.session.refresh(analysis)
    assert analysis.title == "Üretim SWOT Analizi" and analysis.version_id == 1
    assert AuditLog.query.filter_by(entity_type="SwotAnalysis", action="updated").count() == 0
    assert Notification.query.filter_by(user_id=owner.id).one().source_key == previous_notice


@pytest.mark.parametrize("statement", [
    "UPDATE swot_analyses SET owner_user_id=:foreign_user WHERE id=:id",
    "UPDATE swot_analyses SET created_by_user_id=:foreign_user WHERE id=:id",
    "UPDATE swot_analyses SET reviewed_by_user_id=:foreign_user WHERE id=:id",
    "UPDATE swot_analyses SET company_id=:foreign_company, owner_user_id=:foreign_user, created_by_user_id=:foreign_user WHERE id=:id",
    "UPDATE swot_analyses SET review_date=analysis_date WHERE id=:id",
    "UPDATE swot_analyses SET status='other' WHERE id=:id",
    "UPDATE swot_analyses SET status='reviewed' WHERE id=:id",
    "UPDATE swot_analyses SET status='archived' WHERE id=:id",
    "UPDATE swot_analyses SET version_id=0 WHERE id=:id",
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
    assert db.session.get(SwotAnalysis, params["id"]).company_id == params["company"]


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
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from app.swot_schema import ensure_swot_sqlite_guards

    path = Path(__file__).resolve().parents[1] / "migrations/versions/202610050002_add_swot.py"
    spec = importlib.util.spec_from_file_location("swot_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.down_revision == "202610050001"
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE companies (id INTEGER PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY, company_id INTEGER)"))
        connection.execute(text("INSERT INTO companies VALUES (1), (2)"))
        connection.execute(text("INSERT INTO users VALUES (1, 1), (2, 2)"))
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        if runtime_created:
            metadata = sa.MetaData()
            sa.Table("companies", metadata, autoload_with=connection)
            sa.Table("users", metadata, autoload_with=connection)
            SwotAnalysis.__table__.to_metadata(metadata).create(connection)
            ensure_swot_sqlite_guards(connection)
        migration.upgrade()
        connection.execute(text("INSERT INTO swot_analyses (id,company_id,title,owner_user_id,created_by_user_id,analysis_date,review_date) "
                                "VALUES (1,1,'SWOT',1,1,'2026-10-01','2026-11-01')"))
        migration.upgrade()
        assert connection.execute(text("SELECT title FROM swot_analyses")).scalar() == "SWOT"
        schema = inspect(connection)
        assert {c["name"] for c in schema.get_columns("swot_analyses")} == set(SwotAnalysis.__table__.columns.keys())
        assert len(schema.get_check_constraints("swot_analyses")) == 7
        assert len(schema.get_indexes("swot_analyses")) == 5
        trigger_sql = connection.execute(text("SELECT sql FROM sqlite_master WHERE type='trigger' ORDER BY name")).scalars().all()
        assert len(trigger_sql) == 7
        with pytest.raises(IntegrityError):
            connection.execute(text("UPDATE swot_analyses SET owner_user_id=2 WHERE id=1"))
        migration.downgrade()
        assert not inspect(connection).has_table("swot_analyses")
        assert not connection.execute(text("SELECT name FROM sqlite_master WHERE type='trigger'")).all()
        connection.execute(text("UPDATE users SET company_id=2 WHERE id=1"))
        migration.upgrade()
        assert inspect(connection).has_table("swot_analyses")
        assert connection.execute(text("SELECT sql FROM sqlite_master WHERE type='trigger' ORDER BY name")).scalars().all() == trigger_sql
    engine.dispose()
