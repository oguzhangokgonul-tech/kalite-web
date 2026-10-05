from datetime import date
from io import BytesIO
from zipfile import ZipFile

import pytest
from flask import g

from app.extensions import db
from app.models import AppSetting, AuditLog, CompanyModule, Notification, ProjectRecord, ProjectTask, UserPermission, ReportDefinition
from tests.helpers import create_company, create_user, login


@pytest.fixture()
def scenario(client):
    company = create_company("PRJ")
    manager = create_user("project-manager", company=company, role_key="department_manager")
    staff = create_user("project-staff", company=company, role_key="department_staff", full_name="Çağrı Öztürk")
    login(client, manager, company)
    return company, manager, staff


def create_project(client, manager, **overrides):
    data = dict(title="Üretim Planı", description="Kalite iyileştirmesi", owner_user_id=manager.id,
                start_date="2026-10-01", due_date="2026-10-31")
    data.update(overrides)
    response = client.post("/projeler/yeni", data=data)
    assert response.status_code == 302, response.get_data(as_text=True)
    return ProjectRecord.query.order_by(ProjectRecord.id.desc()).first()


def add_task(client, project, staff, **overrides):
    data = dict(title="Kontrol planı güncelleme", owner_user_id=staff.id,
                start_date="2026-10-02", due_date="2026-10-15", version_id=project.version_id)
    data.update(overrides)
    return client.post(f"/projeler/{project.id}/gorev", data=data)


def transition(client, project, action, **overrides):
    data = dict(action=action, version_id=project.version_id, completion_note="Kontrol edildi.")
    data.update(overrides)
    return client.post(f"/projeler/{project.id}/durum", data=data)


def update_task(client, project, task, action, **overrides):
    data = dict(action=action, version_id=task.version_id, project_version_id=project.version_id,
                completion_note="Kontrol tamamlandı.")
    data.update(overrides)
    return client.post(f"/projeler/{project.id}/gorev/{task.id}", data=data)


def test_end_to_end_audit_tasks_notifications_report_archive(client, scenario):
    company, manager, staff = scenario
    project = create_project(client, manager)
    assert transition(client, project, "activate").status_code == 400
    assert add_task(client, project, staff).status_code == 302
    task = ProjectTask.query.one()
    assert transition(client, project, "activate").status_code == 302
    assert Notification.query.filter_by(user_id=staff.id, company_id=company.id).count() == 1
    assert transition(client, project, "complete").status_code == 400
    login(client, staff, company)
    with client.application.test_request_context():
        from app.projects import assigned_task_rows
        g.current_user, g.current_company = staff, company
        assert [r['title'] for r in assigned_task_rows('assigned', lambda **kw: kw)] == [task.title]
    assert client.get(f"/projeler/{project.id}").status_code == 200
    assert update_task(client, project, task, "start").status_code == 302
    assert update_task(client, project, task, "complete", completion_note="").status_code == 400
    assert update_task(client, project, task, "complete").status_code == 302
    db.session.refresh(project)
    assert project.progress == 100
    login(client, manager, company)
    assert transition(client, project, "complete").status_code == 302
    response = client.get(f"/projeler/{project.id}/rapor")
    assert response.status_code == 200
    with ZipFile(BytesIO(response.data)) as archive:
        xml = archive.read('xl/worksheets/sheet1.xml').decode()
        assert "Çağrı Öztürk" in xml and task.title in xml
    assert transition(client, project, "archive").status_code == 302
    assert project.archive_note == "Kontrol edildi."
    detail = client.get(f"/projeler/{project.id}").get_data(as_text=True)
    assert "Tamamlanarak arşivlendi" in detail and project.archive_note in detail
    with ZipFile(BytesIO(client.get(f"/projeler/{project.id}/rapor").data)) as archive:
        metadata = archive.read("xl/worksheets/sheet2.xml").decode()
        assert "Arşiv Gerekçesi" in metadata and "Kontrol edildi." in metadata
    with client.application.test_request_context():
        from app.projects import report_data
        g.current_user, g.current_company = manager, company
        summary = report_data()
        assert "Arşiv Gerekçesi" in summary["headers"]
        assert "Tamamlanarak arşivlendi" in summary["rows"][0]
        assert project.archive_note in summary["rows"][0]
    assert client.get(f"/projeler/{project.id}/duzenle").status_code == 409
    assert add_task(client, project, staff).status_code == 409
    assert {"created", "activate", "complete", "archive", "exported"} <= {a.action for a in AuditLog.query.filter_by(entity_type="ProjectRecord")}
    assert AuditLog.query.filter_by(entity_type="ProjectTask", action="complete").count() == 1
    assert db.session.get(AppSetting, "sales_readiness:module_project_planning") is None
    assert db.session.get(AppSetting, "sales_readiness:module_project_gantt") is None


def test_unrelated_and_foreign_access_and_report_scoping(client, scenario):
    company, manager, staff = scenario
    project = create_project(client, manager)
    assert add_task(client, project, staff).status_code == 302
    for tenant in (company, create_company("OTHER")):
        outsider = create_user("outside-" + tenant.code, company=tenant, role_key="department_manager", full_name=manager.full_name)
        login(client, outsider, tenant)
        assert project.title not in client.get("/projeler").get_data(as_text=True)
        for suffix in ("", "/duzenle", "/rapor"):
            assert client.get(f"/projeler/{project.id}{suffix}").status_code == 404
        assert add_task(client, project, staff).status_code == 404
        with client.application.test_request_context():
            from app.projects import report_data
            from app.routes import module_activity_definition
            g.current_user, g.current_company = outsider, tenant
            assert report_data()["rows"] == []
            assert module_activity_definition("projects") is None


def test_viewer_can_read_company_projects_without_mutating(client, scenario):
    company, manager, staff = scenario
    project = create_project(client, manager)
    viewer = create_user("project-viewer", company=company, role_key="viewer")
    login(client, viewer, company)
    assert project.title in client.get("/projeler").get_data(as_text=True)
    assert client.get(f"/projeler/{project.id}").status_code == 200
    assert client.get("/projeler/yeni").status_code == 403
    assert client.get(f"/projeler/{project.id}/duzenle").status_code == 403
    assert transition(client, project, "archive").status_code == 403
    assert client.get(f"/projeler/{project.id}/rapor").status_code == 403


@pytest.mark.parametrize("role", ["super_admin", "management_representative", "management", "department_manager", "department_staff", "viewer"])
def test_six_role_menu_and_create(client, scenario, role):
    company, manager, staff = scenario
    user = create_user("role-"+role, company=None if role == "super_admin" else company, role_key=role)
    login(client, user, company)
    assert client.get("/projeler").status_code == 200
    assert 'href="/projeler"' in client.get('/').get_data(as_text=True)
    assert client.get("/projeler/yeni").status_code == (403 if role in {"department_staff", "viewer"} else 200)


def test_dates_foreign_owners_empty_input_and_inactive_users(client, scenario):
    company, manager, staff = scenario
    project = create_project(client, manager)
    foreign = create_user("foreign", company=create_company("F"), role_key="department_staff")
    for changes in ({"owner_user_id":foreign.id},{"start_date":"2026-09-01"},{"due_date":"2026-11-01"},
                    {"due_date":"bad"},{"title":" "},{"start_date":"2026-10-20","due_date":"2026-10-10"}):
        assert add_task(client, project, staff, **changes).status_code == 400
    assert ProjectTask.query.count() == 0
    staff.is_active = False
    db.session.commit()
    assert add_task(client, project, staff).status_code == 400


def test_module_disabled_blocks_all_paths_and_task_feed(client, scenario):
    company, manager, staff = scenario
    project = create_project(client, manager)
    assert add_task(client, project, staff).status_code == 302
    assert transition(client, project, "activate").status_code == 302
    task = ProjectTask.query.one()
    CompanyModule.query.filter_by(company_id=company.id, module_key="projects").one().is_enabled = False
    db.session.commit()
    for path in ("/projeler", "/projeler/yeni", f"/projeler/{project.id}", f"/projeler/{project.id}/rapor"):
        assert client.get(path).status_code in (403,404)
    assert transition(client, project, "complete").status_code in (403,404)
    assert update_task(client, project, task, "complete").status_code in (403,404)
    login(client, staff, company)
    assert task.title not in client.get("/gorevlerim").get_data(as_text=True)


def test_stale_parent_and_task_versions_and_staff_metadata_denied(client, scenario):
    company, manager, staff = scenario
    project = create_project(client, manager)
    original = project.version_id
    assert add_task(client, project, staff).status_code == 302
    assert transition(client, project, "activate", version_id=original).status_code == 409
    assert transition(client, project, "activate").status_code == 302
    task = ProjectTask.query.one()
    login(client, staff, company)
    assert update_task(client, project, task, "edit").status_code == 403
    assert update_task(client, project, task, "cancel").status_code == 403
    assert update_task(client, project, task, "complete", project_version_id=original).status_code == 409
    assert update_task(client, project, task, "start").status_code == 302
    assert update_task(client, project, task, "complete", version_id=1).status_code == 409


def test_project_date_change_cannot_exclude_tasks_and_child_id_guard(client, scenario):
    company, manager, staff = scenario
    project = create_project(client, manager)
    assert add_task(client, project, staff).status_code == 302
    task = ProjectTask.query.one()
    second = create_project(client, manager, title="İkinci")
    assert update_task(client, second, task, "edit").status_code == 404
    response = client.post(f"/projeler/{project.id}/duzenle", data=dict(title="Yeni", owner_user_id=manager.id,
        start_date="2026-10-01", due_date="2026-10-03", version_id=project.version_id))
    assert response.status_code == 400
    db.session.refresh(project)
    assert project.title == "Üretim Planı"


def test_cancel_reopen_and_progress(client, scenario):
    company, manager, staff = scenario
    project = create_project(client, manager)
    assert add_task(client, project, staff).status_code == 302
    task = ProjectTask.query.one()
    assert update_task(client, project, task, "cancel", completion_note="").status_code == 400
    assert update_task(client, project, task, "cancel").status_code == 302
    assert transition(client, project, "activate").status_code == 400
    assert update_task(client, project, task, "reopen").status_code == 302
    assert transition(client, project, "activate").status_code == 302
    assert update_task(client, project, task, "complete").status_code == 302
    assert transition(client, project, "complete").status_code == 302
    assert update_task(client, project, task, "reopen").status_code == 409
    assert transition(client, project, "reopen").status_code == 302
    assert update_task(client, project, task, "reopen").status_code == 302
    db.session.refresh(project)
    assert project.progress == 0


def test_no_selected_company_and_anonymous(client, scenario):
    company, manager, staff = scenario
    superadmin = create_user("superadmin", role_key="super_admin")
    login(client, superadmin)
    assert client.get("/projeler").status_code == 403
    assert client.get("/rapor-merkezi").status_code == 200
    with client.session_transaction() as session:
        session.clear()
    assert client.get("/projeler").status_code == 302


def test_csrf_enabled_requires_token(client, scenario):
    company, manager, staff = scenario
    client.application.config["WTF_CSRF_ENABLED"] = True
    assert client.post("/projeler/yeni", data={}, headers={"Accept": "application/json"}).status_code == 400
    assert ProjectRecord.query.count() == 0


def test_standard_custom_reports_and_export_permission_revocation(client, scenario):
    from app.routes import build_custom_report_data, report_center_export_data, report_definition_access_allowed, REPORT_CENTER_REPORTS
    company, manager, staff = scenario
    visible = create_project(client, manager)
    outsider = create_user("other-project-manager", company=company, role_key="department_manager", full_name=manager.full_name)
    login(client, outsider, company)
    hidden = create_project(client, outsider, title="Gizli Proje")
    report = ReportDefinition(name="Proje Raporu", source_key="projects", configuration_json='{}')
    with client.application.test_request_context():
        g.current_user, g.current_company = manager, company
        g.enabled_company_modules = {"projects":True}
        for result in (report_center_export_data("projects"), build_custom_report_data(report, export=True)):
            assert any(visible.title in row for row in result['rows'])
            assert not any(hidden.title in row for row in result['rows'])
        manager.roles.clear()
        manager.extra_permissions.extend([UserPermission(permission_key=k) for k in ("projects.view", "reports.manage", "reports.export")])
        db.session.commit()
        definition = next(d for d in REPORT_CENTER_REPORTS if d['key'] == 'projects')
        assert not report_definition_access_allowed(definition, export=True)
        assert report_center_export_data('projects') is None
    login(client, manager, company)
    assert client.get(f'/projeler/{visible.id}/rapor').status_code == 403


def test_reassignment_removes_old_assignee_access(client, scenario):
    company, manager, staff = scenario
    project = create_project(client, manager)
    assert add_task(client, project, staff).status_code == 302
    task = ProjectTask.query.one()
    replacement = create_user('replacement', company=company, role_key='department_staff')
    assert transition(client, project, 'activate').status_code == 302
    assert update_task(client, project, task, 'edit', title=task.title, owner_user_id=replacement.id,
        start_date=str(task.start_date), due_date=str(task.due_date)).status_code == 302
    login(client, staff, company)
    assert client.get(f'/projeler/{project.id}').status_code == 404
    assert update_task(client, project, task, 'complete').status_code == 404
    assert Notification.query.filter_by(user_id=replacement.id).count() == 1
    assert Notification.query.filter_by(user_id=staff.id).count() == 0


def test_all_cancelled_active_project_can_archive_with_reason(client, scenario):
    company, manager, staff = scenario
    project = create_project(client, manager)
    assert add_task(client, project, staff).status_code == 302
    task = ProjectTask.query.one()
    assert transition(client, project, 'activate').status_code == 302
    assert transition(client, project, 'archive').status_code == 409
    assert update_task(client, project, task, 'cancel').status_code == 302
    assert transition(client, project, 'complete').status_code == 400
    assert transition(client, project, 'archive', completion_note='').status_code == 400
    assert transition(client, project, 'archive').status_code == 302
    db.session.refresh(project)
    assert project.status == 'archived' and project.progress == 0
    assert project.archive_note == 'Kontrol edildi.' and project.completion_note is None
    assert 'Tamamlanmadan arşivlendi' in client.get(f'/projeler/{project.id}').get_data(as_text=True)


def test_active_purpose_required_and_reschedule_notifies(client, scenario):
    company, manager, staff = scenario
    project = create_project(client, manager)
    assert add_task(client, project, staff).status_code == 302
    task = ProjectTask.query.one()
    assert transition(client, project, 'activate').status_code == 302
    response = client.post(f'/projeler/{project.id}/duzenle', data=dict(title=project.title,
        description='', owner_user_id=manager.id, start_date=project.start_date,
        due_date=project.due_date, version_id=project.version_id))
    assert response.status_code == 400
    assert update_task(client, project, task, 'edit', title=task.title, owner_user_id=staff.id,
        start_date=task.start_date, due_date='2026-10-20').status_code == 302
    notices = Notification.query.filter_by(user_id=staff.id).order_by(Notification.id).all()
    assert len(notices) == 1 and notices[-1].due_date == date(2026,10,20)


def test_no_company_activity_report_and_export_formula_safety(client, scenario):
    company, manager, staff = scenario
    project = create_project(client, manager, title='=HYPERLINK("example")')
    response = client.get(f'/projeler/{project.id}/rapor')
    with ZipFile(BytesIO(response.data)) as archive:
        xml = ''.join(archive.read(name).decode() for name in archive.namelist() if name.startswith('xl/worksheets/') and name.endswith('.xml'))
        assert 'HYPERLINK' in xml and '<f>' not in xml
    admin = create_user('activity-admin',role_key='super_admin')
    with client.application.test_request_context():
        from app.routes import module_activity_definition
        g.current_user, g.current_user_is_super_admin = admin, True
        g.current_company = None
        assert module_activity_definition('projects') is None


def test_two_sessions_parent_version_conflict(client, scenario):
    from sqlalchemy.orm import Session
    from sqlalchemy.orm.exc import StaleDataError
    company, manager, staff = scenario
    project = create_project(client, manager)
    with Session(db.engine) as first, Session(db.engine) as second:
        first_copy = first.get(ProjectRecord, project.id)
        stale_copy = second.get(ProjectRecord, project.id)
        first_copy.version_id += 1
        first.commit()
        stale_copy.version_id += 1
        with pytest.raises(StaleDataError):
            second.commit()


def test_release_defaults_preserve_explicit_modules_and_are_idempotent(client, scenario):
    from scripts.project_planning_release import configure_defaults
    from app.models import Role, RolePermission
    company, manager, staff = scenario
    module = CompanyModule.query.filter_by(company_id=company.id,module_key='projects').one()
    module.is_enabled = False
    custom = create_company('custom-project',package_key='custom')
    CompanyModule.query.filter_by(company_id=custom.id,module_key='projects').delete()
    role = Role.query.filter_by(key='department_staff').one()
    role.permissions[:] = [p for p in role.permissions if not p.permission_key.startswith('projects.')]
    role.permissions.append(RolePermission(permission_key='custom.keep'))
    db.session.commit()
    assert configure_defaults()
    assert configure_defaults() == []
    db.session.refresh(module)
    assert module.is_enabled is False
    assert CompanyModule.query.filter_by(company_id=custom.id,module_key='projects').one().is_enabled is False
    assert role.permission_keys >= {'projects.view','projects.update','custom.keep'}


def test_release_mark_only_project_checklist(client, scenario):
    from scripts.project_planning_release import mark
    company,manager,staff=scenario
    create_user('superadmin',role_key='super_admin')
    db.session.add_all([AppSetting(key='sales_readiness:module_project_gantt',value='0'),
        AppSetting(key='sales_readiness:module_meeting_notes',value='1')])
    db.session.commit()
    client.application.config['WTF_CSRF_ENABLED']=True
    assert mark(client.application)=='module_project_planning'
    assert db.session.get(AppSetting,'sales_readiness:module_project_gantt').value=='0'
    assert db.session.get(AppSetting,'sales_readiness:module_meeting_notes').value=='1'


def test_release_smoke_checks_domains_roles_and_cross_tenant_host(client, scenario):
    from scripts.project_planning_release import smoke
    company, manager, staff = scenario
    company.primary_domain = 'projects-a.volkaportal.test'
    second = create_company('projects-b')
    second.primary_domain = 'projects-b.volkaportal.test'
    create_user('second-viewer', company=second, role_key='viewer')
    db.session.commit()
    result = smoke(client.application)
    assert result['checks'] == 3
    assert f'company:{company.id}:viewer' in result['roles_without_live_users']
    assert f'company:{second.id}:department_staff' in result['roles_without_live_users']


def test_sqlite_application_connections_guard_project_tenant_links(client, scenario):
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError
    company,manager,staff=scenario
    project=create_project(client,manager)
    assert add_task(client,project,staff).status_code==302
    other=create_company('guard-other')
    task=ProjectTask.query.one()
    project_id, task_id, other_id = project.id,task.id,other.id
    with db.engine.connect() as connection:
        connection.exec_driver_sql('PRAGMA foreign_keys=OFF')
        assert connection.exec_driver_sql('PRAGMA foreign_keys').scalar()==0
        for statement,params in (
            ('UPDATE project_tasks SET company_id=:company WHERE id=:id', {'company':other_id,'id':task_id}),
            ('UPDATE project_tasks SET project_id=99999999 WHERE id=:id', {'id':task_id}),
            ('DELETE FROM project_records WHERE id=:id', {'id':project_id}),
        ):
            with pytest.raises(IntegrityError):
                connection.execute(text(statement),params)
            connection.rollback()
    db.session.expire_all()
    assert db.session.get(ProjectTask,task_id).company_id==company.id
