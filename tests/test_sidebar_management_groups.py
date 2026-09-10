from tests.helpers import create_company, create_user, login


ADMIN_LINKS = (
    "/kurulum-sihirbazi",
    "/satisa-hazirlik",
    "/sistem/yedekler",
    "/sistem/admin-paneli",
    "/pilot-programi",
    "/sistem/legal-metinler",
    "/denetim-logu",
)


def test_management_status_group_respects_role_permissions(app, client):
    company = create_company("941")
    manager = create_user(
        "management-status-user",
        company=company,
        role_key="management_representative",
    )
    login(client, manager, company)

    response = client.get("/")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Şirket İçi Yönetim Durumu" in body
    assert 'data-bs-target="#companyManagementStatusNav"' in body
    assert 'href="/iso-9001-yonetici-ozeti"' in body
    assert 'href="/yonetici-termin-paneli"' in body
    assert 'id="adminPanelNav"' not in body


def test_management_status_group_only_lists_authorized_children(app, client):
    company = create_company("942")
    manager = create_user(
        "department-status-user",
        company=company,
        role_key="department_manager",
    )
    login(client, manager, company)

    response = client.get("/")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Şirket İçi Yönetim Durumu" in body
    assert 'href="/iso-9001-yonetici-ozeti"' not in body
    assert 'href="/yonetici-termin-paneli"' in body


def test_management_status_group_opens_on_active_child(app, client):
    company = create_company("943")
    manager = create_user(
        "active-management-status-user",
        company=company,
        role_key="management_representative",
    )
    login(client, manager, company)

    response = client.get("/iso-9001-yonetici-ozeti")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 'data-bs-target="#companyManagementStatusNav" aria-expanded="true"' in body
    assert 'class="dashboard-subnav collapse show" id="companyManagementStatusNav"' in body


def test_admin_panel_group_and_children_are_exact_superadmin_only(app, client):
    role_admin = create_user("role-super-admin", role_key="super_admin")
    login(client, role_admin)

    response = client.get("/")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 'id="adminPanelNav"' not in body
    for href in ADMIN_LINKS:
        assert f'href="{href}"' not in body
    assert client.get("/kurulum-sihirbazi").status_code == 403
    assert client.get("/denetim-logu").status_code == 403

    superadmin = create_user("superadmin")
    login(client, superadmin)

    response = client.get("/")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 'data-bs-target="#adminPanelNav"' in body
    for href in ADMIN_LINKS:
        assert body.count(f'href="{href}"') == 1


def test_company_management_hides_restricted_onboarding_links(app, client):
    company = create_company("944")
    role_admin = create_user("company-role-admin", role_key="super_admin")
    login(client, role_admin)

    response = client.get("/companies")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 'href="/kurulum-sihirbazi"' not in body
    assert f'href="/companies/{company.id}/onboarding"' not in body
    assert client.get(f"/companies/{company.id}/onboarding").status_code == 403
    assert client.post(f"/companies/{company.id}/onboarding/repair").status_code == 403


def test_admin_panel_group_opens_on_active_child(app, client):
    superadmin = create_user("superadmin")
    login(client, superadmin)

    response = client.get("/satisa-hazirlik")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 'data-bs-target="#adminPanelNav" aria-expanded="true"' in body
    assert 'class="dashboard-subnav collapse show" id="adminPanelNav"' in body
