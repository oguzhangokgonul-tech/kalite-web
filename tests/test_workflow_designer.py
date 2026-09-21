from datetime import date, timedelta

from app.extensions import db
from app.models import (
    AppSetting,
    AuditLog,
    CompanyDepartment,
    Notification,
    WorkflowEvent,
    WorkflowInstance,
    WorkflowStepRecipient,
    WorkflowTemplate,
    WorkflowVersion,
)
from app.reminders import generate_due_reminders
from app.seed import ensure_runtime_schema

from .helpers import assert_xlsx_response, create_company, create_user, login


MANAGER_PERMISSIONS = (
    "workflow.view", "workflow.start", "workflow.act", "workflow.design",
    "workflow.publish", "workflow.manage_all", "workflow.archive", "workflow.export",
    "reports.view", "reports.export",
)


def designer_payload(approver, worker, name="Satın Alma Onay Akışı"):
    return {
        "name": name,
        "description": "Talep onayı ve uygulama görevi",
        "step_name": ["Yönetici Onayı", "Talebi Uygula"],
        "step_type": ["approval", "task"],
        "assignment_mode": ["user", "user"],
        "assigned_user_id": [str(approver.id), str(worker.id)],
        "assigned_role_key": ["", ""],
        "due_days": ["2", "5"],
        "approval_policy": ["any", "any"],
        "rejection_mode": ["return", "return"],
        "instructions": ["Talebi kontrol edin.", "Onaylanan işi tamamlayın."],
    }


def setup_workflow(client, code="951"):
    company = create_company(code)
    department = CompanyDepartment(company_id=company.id, name="Üretim", sort_order=1, is_active=True)
    manager = create_user(f"workflow-manager-{code}", company=company, permissions=MANAGER_PERMISSIONS, full_name="Kalite Yöneticisi")
    worker = create_user(f"workflow-worker-{code}", company=company, permissions=("workflow.view", "workflow.start", "workflow.act"), full_name="Üretim Personeli")
    db.session.add(department)
    db.session.commit()
    login(client, manager)
    response = client.post("/is-akislari/sablon/yeni", data={"name": "Satın Alma Onayı"})
    assert response.status_code == 302
    version = WorkflowVersion.query.one()
    response = client.post(f"/is-akislari/surum/{version.id}/tasarla", data=designer_payload(manager, worker))
    assert response.status_code == 302
    response = client.post(f"/is-akislari/surum/{version.id}/yayinla")
    assert response.status_code == 302
    db.session.refresh(version)
    assert version.status == "published"
    return company, department, manager, worker, version.template, version


def test_versioned_designer_runs_real_approval_task_and_archives(client):
    _company, department, manager, worker, template, version = setup_workflow(client)
    original_steps = [(row.name, row.sort_order) for row in version.steps]

    assert client.post(f"/is-akislari/surum/{version.id}/tasarla", data=designer_payload(manager, worker, "Değişemez")).status_code == 409
    db.session.refresh(version)
    assert [(row.name, row.sort_order) for row in version.steps] == original_steps

    login(client, worker)
    response = client.post(
        f"/is-akislari/sablon/{template.id}/baslat",
        data={"title": "Yeni pres satın alımı", "description": "Kapasite artışı için pres talebi", "department_id": str(department.id)},
    )
    assert response.status_code == 302
    instance = WorkflowInstance.query.one()
    assert instance.status == "in_progress"
    assert instance.active_step.name_snapshot == "Yönetici Onayı"
    assert {row.user_id for row in instance.active_step.recipients} == {manager.id}

    login(client, manager)
    assert client.post(f"/is-akislari/adim/{instance.active_step.id}/karar", data={"decision": "approve", "note": "Uygundur."}).status_code == 302
    db.session.refresh(instance)
    assert instance.active_step.name_snapshot == "Talebi Uygula"

    login(client, worker)
    task_page = client.get("/uzerime-atananlar?module=workflow")
    assert task_page.status_code == 200 and "Talebi Uygula" in task_page.get_data(as_text=True)
    assert client.post(f"/is-akislari/adim/{instance.active_step.id}/karar", data={"decision": "approve", "note": "Sipariş açıldı."}).status_code == 302
    db.session.refresh(instance)
    assert instance.status == "completed" and instance.active_step is None
    assert WorkflowEvent.query.filter_by(instance_id=instance.id, event_type="completed").count() == 1

    login(client, manager)
    detail_page = client.get(f"/is-akislari/kayit/{instance.id}")
    assert detail_page.status_code == 200 and "Arşivle" in detail_page.get_data(as_text=True)
    assert client.post(f"/is-akislari/kayit/{instance.id}/arsivle").status_code == 302
    db.session.refresh(instance)
    assert instance.status == "archived"
    assert AuditLog.query.filter_by(entity_type="WorkflowInstanceStep", action="decision").count() == 2


def test_self_approval_is_blocked_and_return_can_be_resubmitted(client):
    _company, department, manager, worker, template, _version = setup_workflow(client, "952")

    login(client, manager)
    response = client.post(
        f"/is-akislari/sablon/{template.id}/baslat",
        data={"title": "Kendi onayım", "description": "Ayrı onaylayan yok", "department_id": str(department.id)},
        follow_redirects=True,
    )
    assert "uygun ve aktif bir sorumlu bulunamadı" in response.get_data(as_text=True)
    assert WorkflowInstance.query.count() == 0

    login(client, worker)
    client.post(
        f"/is-akislari/sablon/{template.id}/baslat",
        data={"title": "Revizyonlu talep", "description": "İlk açıklama", "department_id": str(department.id)},
    )
    instance = WorkflowInstance.query.one()
    first_step_id = instance.active_step.id
    login(client, manager)
    assert client.post(f"/is-akislari/adim/{first_step_id}/karar", data={"decision": "return", "note": "Bütçe bilgisini ekleyin."}).status_code == 302
    db.session.refresh(instance)
    assert instance.status == "revision_requested"

    login(client, worker)
    revision_page = client.get(f"/is-akislari/kayit/{instance.id}")
    assert revision_page.status_code == 200 and "Yeniden Gönder" in revision_page.get_data(as_text=True)
    assert client.post(f"/is-akislari/kayit/{instance.id}/yeniden-gonder", data={"description": "Bütçe bilgisi eklendi."}).status_code == 302
    db.session.refresh(instance)
    assert instance.status == "in_progress"
    assert instance.active_step.round_number == 2
    assert instance.active_step.id != first_step_id
    assert {row.user_id for row in instance.active_step.recipients} == {manager.id}


def test_tenant_scope_permissions_export_reminder_and_checklist(client):
    company, department, manager, worker, template, _version = setup_workflow(client, "953")
    other_company = create_company("954")
    outsider = create_user("workflow-outsider-954", company=other_company, permissions=MANAGER_PERMISSIONS)

    login(client, worker)
    client.post(
        f"/is-akislari/sablon/{template.id}/baslat",
        data={"title": "Terminli talep", "description": "Hatırlatma testi", "department_id": str(department.id)},
    )
    instance = WorkflowInstance.query.one()
    instance.active_step.due_date = date.today() + timedelta(days=1)
    db.session.commit()

    login(client, outsider)
    assert client.get(f"/is-akislari/kayit/{instance.id}").status_code == 404
    assert client.get(f"/is-akislari/surum/{instance.version_id}/tasarla").status_code == 404

    login(client, manager)
    assert_xlsx_response(client.get("/is-akislari/rapor.xlsx"))
    stats = generate_due_reminders(company.id, run_date=date.today())
    assert stats["notifications"] >= 1
    assert Notification.query.filter_by(user_id=manager.id, due_date=instance.active_step.due_date).count() >= 1

    ensure_runtime_schema()
    assert db.session.get(AppSetting, "sales_readiness:competitor_workflow_designer").value == "1"
    dashboard = client.get("/is-akislari")
    assert dashboard.status_code == 200 and "Satın Alma Onay Akışı" in dashboard.get_data(as_text=True)


def test_new_version_copies_steps_and_published_version_stays_available(client):
    _company, _department, manager, _worker, template, version = setup_workflow(client, "955")
    login(client, manager)
    response = client.post(f"/is-akislari/sablon/{template.id}/yeni-surum")
    assert response.status_code == 302
    draft = WorkflowVersion.query.filter_by(template_id=template.id, status="draft").one()
    assert draft.version_number == 2
    assert [(row.name, row.sort_order) for row in draft.steps] == [(row.name, row.sort_order) for row in version.steps]
    db.session.refresh(template)
    assert template.published_version.id == version.id
    assert client.get(f"/is-akislari/sablon/{template.id}/baslat").status_code == 200


def test_role_assignment_all_policy_waits_for_every_recipient(client):
    company = create_company("956")
    department = CompanyDepartment(company_id=company.id, name="Kalite", sort_order=1, is_active=True)
    designer = create_user("workflow-designer-956", company=company, permissions=MANAGER_PERMISSIONS)
    approver_one = create_user("workflow-approver-a-956", company=company, role_key="management", full_name="Birinci Yönetici")
    approver_two = create_user("workflow-approver-b-956", company=company, role_key="management", full_name="İkinci Yönetici")
    requester = create_user("workflow-requester-956", company=company, permissions=("workflow.view", "workflow.start"))
    db.session.add(department)
    db.session.commit()

    login(client, designer)
    client.post("/is-akislari/sablon/yeni", data={"name": "Kurul Onayı"})
    version = WorkflowVersion.query.one()
    payload = {
        "name": "Kurul Onayı", "description": "İki yönetici kararı",
        "step_name": ["Kurul Kararı"], "step_type": ["approval"],
        "assignment_mode": ["role"], "assigned_user_id": [""],
        "assigned_role_key": ["management"], "due_days": ["3"],
        "approval_policy": ["all"], "rejection_mode": ["reject"],
        "instructions": ["Tüm yöneticiler değerlendirsin."],
    }
    assert client.post(f"/is-akislari/surum/{version.id}/tasarla", data=payload).status_code == 302
    assert client.post(f"/is-akislari/surum/{version.id}/yayinla").status_code == 302

    login(client, requester)
    client.post(
        f"/is-akislari/sablon/{version.template_id}/baslat",
        data={"title": "Yatırım kararı", "description": "Kurul onayına sunulur.", "department_id": str(department.id)},
    )
    instance = WorkflowInstance.query.one()
    assert {row.user_id for row in instance.active_step.recipients} == {approver_one.id, approver_two.id}

    login(client, approver_one)
    client.post(f"/is-akislari/adim/{instance.active_step.id}/karar", data={"decision": "approve"})
    db.session.refresh(instance)
    assert instance.status == "in_progress" and instance.active_step is not None
    assert WorkflowStepRecipient.query.filter_by(instance_step_id=instance.active_step.id, status="pending").count() == 1

    login(client, approver_two)
    client.post(f"/is-akislari/adim/{instance.active_step.id}/karar", data={"decision": "approve"})
    db.session.refresh(instance)
    assert instance.status == "completed"


def test_designer_permission_does_not_grant_company_wide_instance_access(client):
    company, department, manager, worker, template, _version = setup_workflow(client, "957")
    designer = create_user(
        "workflow-designer-only-957",
        company=company,
        permissions=("workflow.view", "workflow.design"),
        full_name="Akış Tasarımcısı",
    )
    viewer = create_user(
        "workflow-viewer-957",
        company=company,
        permissions=("workflow.view",),
        full_name="Sadece Görüntüleyici",
    )

    login(client, worker)
    client.post(
        f"/is-akislari/sablon/{template.id}/baslat",
        data={"title": "Gizli satın alma", "description": "Yalnızca ilgililer görür.", "department_id": str(department.id)},
    )
    instance = WorkflowInstance.query.one()

    login(client, manager)
    client.post("/is-akislari/sablon/yeni", data={"name": "Henüz Yayınlanmayan Akış"})
    client.post(f"/is-akislari/sablon/{template.id}/yeni-surum")

    login(client, designer)
    dashboard = client.get("/is-akislari")
    assert dashboard.status_code == 200
    assert "Gizli satın alma" not in dashboard.get_data(as_text=True)
    assert client.get(f"/is-akislari/kayit/{instance.id}").status_code == 404

    login(client, viewer)
    dashboard = client.get("/is-akislari")
    assert dashboard.status_code == 200
    assert "Henüz Yayınlanmayan Akış" not in dashboard.get_data(as_text=True)
    assert "Satın Alma Onay Akışı" in dashboard.get_data(as_text=True)
    assert "v1" in dashboard.get_data(as_text=True)
    assert "v2" not in dashboard.get_data(as_text=True)


def test_department_manager_step_requires_manager_for_every_active_department(client):
    company = create_company("958")
    production = CompanyDepartment(company_id=company.id, name="Üretim", sort_order=1, is_active=True)
    sales = CompanyDepartment(company_id=company.id, name="Satış", sort_order=2, is_active=True)
    designer = create_user(
        "workflow-manager-validator-958",
        company=company,
        permissions=MANAGER_PERMISSIONS,
        full_name="Kalite Yöneticisi",
    )
    create_user(
        "production-manager-958",
        company=company,
        role_key="department_manager",
        full_name="Üretim Yöneticisi",
        title="Üretim Müdürü",
    )
    db.session.add_all((production, sales))
    db.session.commit()

    login(client, designer)
    client.post("/is-akislari/sablon/yeni", data={"name": "Departman Onayı"})
    version = WorkflowVersion.query.one()
    payload = {
        "name": "Departman Onayı",
        "description": "Her departmanın yöneticisi onaylar.",
        "step_name": ["Departman Yöneticisi Onayı"],
        "step_type": ["approval"],
        "assignment_mode": ["department_manager"],
        "assigned_user_id": [""],
        "assigned_role_key": [""],
        "due_days": ["3"],
        "approval_policy": ["any"],
        "rejection_mode": ["return"],
        "instructions": ["Talebi kontrol edin."],
    }
    assert client.post(f"/is-akislari/surum/{version.id}/tasarla", data=payload).status_code == 302
    response = client.post(f"/is-akislari/surum/{version.id}/yayinla", follow_redirects=True)
    assert response.status_code == 200
    assert "Satış" in response.get_data(as_text=True)
    db.session.refresh(version)
    assert version.status == "draft"
