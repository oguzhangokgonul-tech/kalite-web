from app.extensions import db
from app.models import Dof, UserPermission

from .helpers import (
    assert_xlsx_response,
    create_company,
    create_user,
    login,
    make_document,
    sheet_values,
)
from .test_action_management import make_action
from .test_dof_management import dof_payload, make_dof


def test_viewer_cannot_create_dof_by_direct_post(client):
    company = create_company("841")
    viewer = create_user("matrix-viewer", company=company, role_key="viewer")
    login(client, viewer)

    assert "Yeni İF Kaydı" not in client.get("/dofs").get_data(as_text=True)
    assert client.get("/dofs/new").status_code == 403
    response = client.post("/dofs/new", data=dof_payload(viewer))
    assert response.status_code == 403
    assert Dof.query.count() == 0


def test_dof_create_permission_follows_personal_overrides(client):
    company = create_company("842")
    manager = create_user("matrix-manager", company=company, role_key="management_representative")
    viewer = create_user("matrix-granted-viewer", company=company, role_key="viewer")

    login(client, manager)
    assert "Yeni İF Kaydı" in client.get("/dofs").get_data(as_text=True)
    assert client.get("/dofs/new").status_code == 200

    manager.extra_permissions.append(UserPermission(permission_key="if.create", is_allowed=False))
    viewer.extra_permissions.append(UserPermission(permission_key="if.create", is_allowed=True))
    db.session.commit()

    assert client.get("/dofs/new").status_code == 403
    login(client, viewer)
    assert client.get("/dofs/new").status_code == 200


def test_dof_edit_requires_distinct_permission_even_for_record_owner(client):
    company = create_company("847")
    viewer = create_user("matrix-dof-viewer", company=company, role_key="viewer")
    staff = create_user("matrix-dof-staff", company=company, role_key="department_staff")
    manager = create_user("matrix-dof-manager", company=company, role_key="management_representative")
    viewer_dof = make_dof(company, viewer, dof_no="IF-2026-0847", title="Unchanged viewer record")
    staff_dof = make_dof(company, staff, dof_no="IF-2026-0848")

    login(client, viewer)
    assert client.get(f"/dofs/{viewer_dof.id}").status_code == 200
    assert client.get(f"/dofs/{viewer_dof.id}/edit").status_code == 302
    assert client.post(
        f"/dofs/{viewer_dof.id}/edit",
        data=dof_payload(viewer, title="Unauthorized change"),
    ).status_code == 302
    db.session.refresh(viewer_dof)
    assert viewer_dof.title == "Unchanged viewer record"

    login(client, staff)
    assert client.get(f"/dofs/{staff_dof.id}/edit").status_code == 200
    assert client.get(f"/dofs/{viewer_dof.id}").status_code == 403

    login(client, manager)
    assert client.get(f"/dofs/{viewer_dof.id}/edit").status_code == 200
    manager.extra_permissions.append(UserPermission(permission_key="if.edit_all", is_allowed=False))
    db.session.commit()
    assert client.get(f"/dofs/{viewer_dof.id}/edit").status_code == 302


def test_foreign_company_records_and_downloads_are_not_accessible(app, client):
    company_a = create_company("843")
    company_b = create_company("844")
    manager_a = create_user("matrix-manager-a", company=company_a, role_key="management_representative")
    manager_b = create_user("matrix-manager-b", company=company_b, role_key="management_representative")
    action_b = make_action(company_b, manager_b, title="Foreign action matrix")
    dof_b = make_dof(company_b, manager_b, title="Foreign dof matrix")
    document_b = make_document(app, company_b, title="Foreign document matrix")

    login(client, manager_a)
    requests = (
        ("GET", f"/actions/{action_b.id}"),
        ("GET", f"/actions/{action_b.id}/edit"),
        ("POST", f"/actions/{action_b.id}/delete"),
        ("GET", f"/actions/{action_b.id}/download"),
        ("GET", f"/dofs/{dof_b.id}"),
        ("GET", f"/dofs/{dof_b.id}/edit"),
        ("POST", f"/dofs/{dof_b.id}/delete"),
        ("POST", f"/dofs/{dof_b.id}/approve-management"),
        ("GET", f"/dofs/{dof_b.id}/files/999/download"),
        ("GET", f"/documents/{document_b.id}"),
        ("GET", f"/documents/{document_b.id}/edit"),
        ("POST", f"/documents/{document_b.id}/delete"),
        ("GET", f"/documents/{document_b.id}/download"),
    )
    for method, path in requests:
        assert client.open(path, method=method).status_code == 404, path

    assert Dof.query.get(dof_b.id).approval_step == "management_representative"


def test_report_export_respects_role_and_company_scope(client):
    company_a = create_company("845")
    company_b = create_company("846")
    manager_a = create_user("matrix-exporter-a", company=company_a, role_key="management_representative")
    viewer_a = create_user("matrix-report-viewer", company=company_a, role_key="viewer")
    manager_b = create_user("matrix-exporter-b", company=company_b, role_key="management_representative")
    make_action(company_a, manager_a, title="Visible action matrix")
    make_action(company_b, manager_b, title="Foreign action matrix")

    login(client, viewer_a)
    assert client.get("/rapor-merkezi/actions_master/excel").status_code == 403

    login(client, manager_a)
    response = client.get("/rapor-merkezi/actions_master/excel")
    assert_xlsx_response(response)
    values = str(sheet_values(response.data))
    assert "Visible action matrix" in values
    assert "Foreign action matrix" not in values
