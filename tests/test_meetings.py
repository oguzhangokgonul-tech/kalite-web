from datetime import datetime
from io import BytesIO
from zipfile import ZipFile

import pytest

from app.extensions import db
from app.models import Action, AppSetting, AuditLog, CompanyModule, MeetingRecord, MeetingDecision, Notification, UserPermission, ReportDefinition
from tests.helpers import create_company, create_user, login


@pytest.fixture()
def scenario(client):
    company = create_company("MTG")
    manager = create_user("meeting-manager", company=company, role_key="department_manager")
    staff = create_user("meeting-staff", company=company, role_key="department_staff", full_name="Çağrı Öztürk")
    login(client, manager, company)
    return company, manager, staff


def create_meeting(client, staff, **changes):
    data = dict(title="Üretim toplantısı", meeting_at="2026-09-01T10:30", location="Kalite",
                agenda="Kontroller", minutes="Kararlar görüşüldü.", participant_ids=str(staff.id))
    data.update(changes)
    response = client.post("/toplantilar/yeni", data=data)
    assert response.status_code == 302, response.get_data(as_text=True)
    return MeetingRecord.query.order_by(MeetingRecord.id.desc()).first()


def transition(client, meeting, action):
    return client.post(f"/toplantilar/{meeting.id}/durum", data={"action": action, "version_id": meeting.version_id})


def add_decision(client, meeting, staff, **changes):
    data = dict(title="Kontrol listesini güncelle", owner_user_id=staff.id, due_date="2026-09-10", version_id=meeting.version_id)
    data.update(changes)
    return client.post(f"/toplantilar/{meeting.id}/kararlar", data=data)


def test_complete_workflow_audit_notifications_tasks_and_archive(client, scenario):
    company, manager, staff = scenario
    before_actions = Action.query.count()
    meeting = create_meeting(client, staff)
    assert add_decision(client, meeting, staff).status_code == 302
    decision = MeetingDecision.query.one()
    assert transition(client, meeting, "publish").status_code == 302
    count = Notification.query.filter_by(user_id=staff.id).count()
    assert count >= 1
    assert transition(client, meeting, "publish").status_code == 409
    assert Notification.query.filter_by(user_id=staff.id).count() == count
    assert transition(client, meeting, "complete").status_code == 302
    assert transition(client, meeting, "archive").status_code == 400
    login(client, staff, company)
    assert client.get(f"/toplantilar/{meeting.id}").status_code == 200
    with client.application.test_request_context():
        from flask import g
        from app.meetings import assigned_task_rows
        g.current_user, g.current_company = staff, company
        tasks = assigned_task_rows("assigned", lambda **kw: kw)
        assert [task["title"] for task in tasks] == [decision.title]
    path = f"/toplantilar/{meeting.id}/kararlar/{decision.id}"
    assert client.post(path, data=dict(action="complete", version_id=decision.version_id)).status_code == 400
    assert client.post(path, data=dict(action="complete", version_id=decision.version_id, completion_note="Kontrol edildi.")).status_code == 302
    login(client, manager, company)
    assert transition(client, meeting, "archive").status_code == 302
    assert client.post(path, data=dict(action="reopen", version_id=decision.version_id)).status_code == 409
    assert client.get(f"/toplantilar/{meeting.id}/duzenle").status_code == 409
    assert client.get(f"/toplantilar/{meeting.id}").status_code == 200
    actions = {row.action for row in AuditLog.query.filter_by(entity_type="MeetingRecord").all()}
    assert {"created", "published", "completed", "archived"} <= actions
    assert AuditLog.query.filter_by(entity_type="MeetingDecision", action="completed").count() == 1
    assert Action.query.count() == before_actions
    assert db.session.get(AppSetting, "sales_readiness:module_meeting_action_decisions") is None
    assert db.session.get(AppSetting, "sales_readiness:module_meeting_notes") is None


def test_tenant_and_unrelated_user_cannot_read_edit_or_export(client, scenario):
    company, manager, staff = scenario
    meeting = create_meeting(client, staff)
    other = create_user("meeting-other", company=company, role_key="department_manager")
    foreign_company = create_company("MTG2")
    foreign = create_user("foreign", company=foreign_company, role_key="management_representative")
    for user, tenant in ((other, company), (foreign, foreign_company)):
        login(client, user, tenant)
        assert meeting.title not in client.get("/toplantilar").get_data(as_text=True)
        for suffix in ("", "/duzenle", "/rapor"):
            assert client.get(f"/toplantilar/{meeting.id}{suffix}").status_code == 404
        assert transition(client, meeting, "publish").status_code == 404


def test_forged_users_and_invalid_dates_do_not_write(client, scenario):
    company, manager, staff = scenario
    foreign = create_user("foreign-owner", company=create_company("MTG3"), role_key="department_staff")
    meeting = create_meeting(client, staff)
    for changes in ({"owner_user_id": foreign.id}, {"owner_user_id": "bad"}, {"due_date": "bad"}, {"due_date": "2026-08-01"}, {"title": " "}):
        assert add_decision(client, meeting, staff, **changes).status_code == 400
    assert MeetingDecision.query.count() == 0
    result = client.post(f"/toplantilar/{meeting.id}/duzenle", data=dict(
        version_id=meeting.version_id, title="Should not persist", meeting_at="2026-09-01T10:30", participant_ids=foreign.id))
    assert result.status_code == 400
    db.session.refresh(meeting)
    assert meeting.title == "Üretim toplantısı"


def test_stale_versions_and_revoked_authority(client, scenario):
    company, manager, staff = scenario
    meeting = create_meeting(client, staff)
    old_version = meeting.version_id
    assert add_decision(client, meeting, staff).status_code == 302
    assert client.post(f"/toplantilar/{meeting.id}/durum", data=dict(action="publish", version_id=old_version)).status_code == 409
    manager.roles.clear()
    manager.extra_permissions.append(UserPermission(permission_key="meetings.view"))
    db.session.commit()
    assert client.get(f"/toplantilar/{meeting.id}").status_code == 200
    assert client.get(f"/toplantilar/{meeting.id}/duzenle").status_code == 403


@pytest.mark.parametrize("role", ["super_admin", "management_representative", "management", "department_manager", "department_staff", "viewer"])
def test_role_permissions_and_sidebar(client, scenario, role):
    company, manager, staff = scenario
    user = create_user("role-" + role, company=None if role == "super_admin" else company, role_key=role)
    login(client, user, company)
    assert client.get("/toplantilar").status_code == 200
    expected = 403 if role in {"department_staff", "viewer"} else 200
    assert client.get("/toplantilar/yeni").status_code == expected
    assert '/toplantilar' in client.get("/").get_data(as_text=True)


def test_module_disabled_and_csrf(client, scenario):
    company, manager, staff = scenario
    client.application.config["WTF_CSRF_ENABLED"] = True
    client.post("/toplantilar/yeni", data=dict(title="CSRF rejected"))
    assert MeetingRecord.query.count() == 0
    setting = CompanyModule.query.filter_by(company_id=company.id, module_key="meetings").one()
    setting.is_enabled = False
    db.session.commit()
    assert client.get("/toplantilar").status_code == 403
    assert '/toplantilar' not in client.get("/").get_data(as_text=True)


def test_excel_contains_turkish_and_plain_text_cells(client, scenario):
    company, manager, staff = scenario
    meeting = create_meeting(client, staff, title="=HYPERLINK(\"example\")")
    assert add_decision(client, meeting, staff).status_code == 302
    response = client.get(f"/toplantilar/{meeting.id}/rapor")
    assert response.status_code == 200
    assert response.mimetype == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    with ZipFile(BytesIO(response.data)) as archive:
        sheets = archive.read("xl/worksheets/sheet1.xml").decode() + archive.read("xl/worksheets/sheet2.xml").decode()
        assert "Çağrı Öztürk" in sheets
        assert "HYPERLINK" in sheets and "<f>" not in sheets
    login(client, staff, company)
    assert client.get(f"/toplantilar/{meeting.id}/rapor").status_code == 403


def test_global_admin_without_company_and_stable_reference(client, scenario):
    company, manager, staff = scenario
    meeting = create_meeting(client, staff)
    reference = meeting.meeting_no
    meeting.meeting_at = datetime(2027, 1, 1, 10)
    db.session.commit()
    assert meeting.meeting_no == reference
    admin = create_user("meeting-admin", role_key="super_admin")
    login(client, admin)
    assert client.get("/toplantilar").status_code == 403
    assert client.get("/rapor-merkezi").status_code == 200


def test_participant_removal_has_explicit_audit(client, scenario):
    company, manager, staff = scenario
    meeting = create_meeting(client, staff)
    response = client.post(f"/toplantilar/{meeting.id}/duzenle", data=dict(
        version_id=meeting.version_id, title=meeting.title, meeting_at="2026-09-01T10:30"))
    assert response.status_code == 302
    log = AuditLog.query.filter_by(entity_type="MeetingRecord", action="participants_updated").one()
    assert str(staff.id) in log.old_values
    assert '[]' in log.new_values


def test_custom_report_keeps_only_authorized_meetings(client, scenario):
    from flask import g
    from app.routes import build_custom_report_data
    company, manager, staff = scenario
    meeting = create_meeting(client, staff)
    outsider = create_user("outsider-report", company=company, role_key="department_manager")
    login(client, outsider, company)
    hidden = create_meeting(client, outsider, title="Private meeting")
    report = ReportDefinition(name="Toplantı Raporu", source_key="meetings", configuration_json='{}')
    with client.application.test_request_context():
        g.current_user, g.current_company = manager, company
        g.enabled_company_modules = {"meetings": True}
        rows = build_custom_report_data(report, export=True)["rows"]
        assert any(meeting.title in row for row in rows)
        assert not any(hidden.title in row for row in rows)
