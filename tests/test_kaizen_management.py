from datetime import date, timedelta
from io import BytesIO

from app.extensions import db
from app.models import AppSetting, AuditLog, KaizenProject, KaizenProjectFile, KaizenProjectUpdate, Notification
from app.seed import ensure_runtime_schema
from .helpers import create_company, create_user, login


ALL_PERMISSIONS = ("kaizen.view", "kaizen.view_all", "kaizen.create", "kaizen.manage", "kaizen.update", "kaizen.archive", "kaizen.file_download")


def payload(owner, team=(), **overrides):
    values = {
        "title": "Fire Oranını Azaltma", "department": "Üretim", "owner_user_id": str(owner.id),
        "team_user_ids": [str(user.id) for user in team], "stage": "Fikir", "status": "Açık",
        "priority": "Yüksek", "start_date": date.today().isoformat(),
        "target_date": (date.today() + timedelta(days=30)).isoformat(),
        "problem_statement": "Üretim hattında fire oranı hedefin üzerinde.",
        "current_state": "Yüzde 8", "target_state": "Yüzde 3", "metric_name": "Fire oranı",
        "baseline_value": "8", "target_value": "3", "estimated_cost": "1000", "estimated_benefit": "10000",
    }
    values.update(overrides)
    return values


def test_kaizen_workflow_tasks_isolation_completion_and_archive(app, client):
    company = create_company("701")
    other_company = create_company("702")
    manager = create_user("kaizen-manager", company=company, permissions=ALL_PERMISSIONS)
    owner = create_user("kaizen-owner", company=company, permissions=("kaizen.view", "kaizen.update", "kaizen.file_download"))
    member = create_user("kaizen-member", company=company, permissions=("kaizen.view", "kaizen.update"))
    outsider = create_user("kaizen-outsider", company=company, permissions=("kaizen.view",))
    foreign = create_user("kaizen-foreign", company=other_company, permissions=ALL_PERMISSIONS)
    login(client, manager)
    response = client.post("/kaizen/yeni", data=payload(owner, (member,), attachment=(BytesIO(b"evidence"), "analiz.xlsx")), content_type="multipart/form-data", follow_redirects=True)
    assert response.status_code == 200
    assert "KZN-2026-0001" in response.get_data(as_text=True)
    project = KaizenProject.query.one()
    assert {row.user_id for row in project.team_members} == {member.id}
    assert KaizenProjectFile.query.one().sha256_hash
    assert KaizenProjectUpdate.query.filter_by(note="Kaizen projesi oluşturuldu.").one()
    assert Notification.query.filter_by(source_key=f"kaizen-assignment:{project.id}:{owner.id}").one()
    assert Notification.query.filter_by(source_key=f"kaizen-assignment:{project.id}:{member.id}").one()

    login(client, outsider)
    assert client.get(f"/kaizen/{project.id}").status_code == 404
    login(client, foreign)
    assert client.get(f"/kaizen/{project.id}").status_code == 404

    login(client, member)
    assert project.project_no in client.get("/uzerime-atananlar?module=kaizen").get_data(as_text=True)
    response = client.post(f"/kaizen/{project.id}/ilerleme", data={"stage": "Doğrulama", "status": "Devam Ediyor", "note": "Pilot sonuçları doğrulandı.", "actual_value": "4", "realized_cost": "900", "realized_benefit": "7500"})
    assert response.status_code == 302
    db.session.refresh(project)
    assert project.actual_value == 4
    assert project.realized_benefit == 7500
    assert KaizenProjectUpdate.query.filter_by(stage="Doğrulama").one()

    login(client, manager)
    assert client.post(f"/kaizen/{project.id}/arsivle", follow_redirects=True).status_code == 200
    assert project.archived_at is None
    client.post(f"/kaizen/{project.id}/ilerleme", data={"stage": "Tamamlandı", "status": "Tamamlandı", "note": "Sonuç standartlaştırıldı."})
    assert client.post(f"/kaizen/{project.id}/arsivle").status_code == 302
    db.session.refresh(project)
    assert project.archived_at is not None
    assert AuditLog.query.filter_by(entity_type="KaizenProject").count() >= 1
    assert AuditLog.query.filter_by(entity_type="KaizenProjectUpdate").count() >= 1


def test_kaizen_sequence_and_invalid_file_rolls_back(client):
    company = create_company("703")
    manager = create_user("kaizen-sequence", company=company, permissions=ALL_PERMISSIONS)
    login(client, manager)
    for title in ("Bir", "İki"):
        assert client.post("/kaizen/yeni", data=payload(manager, title=title)).status_code == 302
    assert [row.project_no for row in KaizenProject.query.order_by(KaizenProject.id)] == ["KZN-2026-0001", "KZN-2026-0002"]
    response = client.post("/kaizen/yeni", data=payload(manager, title="Üç", attachment=(BytesIO(b"x"), "zararli.exe")), content_type="multipart/form-data", follow_redirects=True)
    assert response.status_code == 200
    assert KaizenProject.query.count() == 2


def test_runtime_schema_marks_kaizen_done(app):
    AppSetting.query.filter_by(key="sales_readiness:competitor_kaizen_projects").delete()
    db.session.commit()
    ensure_runtime_schema()
    setting = db.session.get(AppSetting, "sales_readiness:competitor_kaizen_projects")
    assert setting and setting.value == "1"
