from app.extensions import db
from app.models import CompanyModule

from .helpers import create_company, create_user, login, make_document


def test_non_superadmin_cannot_scope_session_to_another_company(app, client):
    company_a = create_company("371")
    company_b = create_company("372")
    user = create_user(
        "tenant-user-a",
        company=company_a,
        permissions=("documents.view",),
    )
    make_document(app, company_a, document_code="PR.371", title="Firma A Dokumani")
    make_document(app, company_b, document_code="PR.372", title="Firma B Gizli Dokuman")

    login(client, user, company=company_b)
    response = client.get("/documents/list")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Firma A Dokumani" in body
    assert "Firma B Gizli Dokuman" not in body
    with client.session_transaction() as session:
        assert session["company_id"] == company_a.id


def test_cross_tenant_host_clears_non_superadmin_session(app, client):
    app.config["SESSION_COOKIE_DOMAIN"] = ".volkaportal.com"
    company_a = create_company("373")
    company_b = create_company("374")
    user = create_user(
        "tenant-user-host",
        company=company_a,
        permissions=("documents.view",),
    )
    make_document(app, company_b, document_code="PR.374", title="B Host Gizli Dokuman")

    with client.session_transaction(
        base_url=f"https://{company_a.slug}.volkaportal.com"
    ) as session:
        session["user_id"] = user.id
        session["company_id"] = company_a.id
    response = client.get(
        "/documents/list",
        base_url=f"https://{company_b.slug}.volkaportal.com",
    )

    assert response.status_code == 302
    assert "/login" in response.headers["Location"]
    with client.session_transaction(
        base_url=f"https://{company_b.slug}.volkaportal.com"
    ) as session:
        assert "user_id" not in session


def test_company_bound_super_admin_role_cannot_cross_tenant_host(app, client):
    app.config["SESSION_COOKIE_DOMAIN"] = ".volkaportal.com"
    company_a = create_company("378")
    company_b = create_company("379")
    invalid_admin = create_user(
        "invalid-company-root", company=company_a, role_key="super_admin"
    )
    make_document(app, company_b, document_code="PR.379", title="Other Company Secret")

    with client.session_transaction(
        base_url=f"https://{company_a.slug}.volkaportal.com"
    ) as session:
        session["user_id"] = invalid_admin.id
        session["user_session_version"] = invalid_admin.session_version
        session["company_id"] = company_a.id

    response = client.get(
        "/documents/list", base_url=f"https://{company_b.slug}.volkaportal.com"
    )

    assert response.status_code == 302
    assert "/login" in response.headers["Location"]
    assert "Other Company Secret" not in response.get_data(as_text=True)
    with client.session_transaction(
        base_url=f"https://{company_b.slug}.volkaportal.com"
    ) as session:
        assert "user_id" not in session


def test_company_bound_super_admin_role_cannot_mutate_own_company(app, client):
    company = create_company("380")
    invalid_admin = create_user("invalid-local-root", company=company, role_key="super_admin")
    target = create_user("protected-target", company=company)
    host = f"https://{company.slug}.volkaportal.com"
    with client.session_transaction(base_url=host) as session:
        session["user_id"] = invalid_admin.id
        session["user_session_version"] = invalid_admin.session_version
        session["company_id"] = company.id

    for method, path, data in (
        ("get", f"/users/{target.id}/edit", None),
        ("post", f"/users/{target.id}/edit", {"full_name": "Changed"}),
        ("post", f"/users/{target.id}/delete", None),
    ):
        response = getattr(client, method)(path, base_url=host, data=data)
        assert response.status_code == 302
        assert "/login" in response.headers["Location"]

    db.session.refresh(target)
    assert target.full_name != "Changed"
    assert target.deleted_at is None
    with client.session_transaction(base_url=host) as session:
        assert "user_id" not in session


def test_unknown_tenant_host_rejects_shared_cookie_without_clearing_known_host(app, client):
    app.config["SESSION_COOKIE_DOMAIN"] = ".volkaportal.com"
    company = create_company("376")
    user = create_user(
        "tenant-user-unknown-host",
        company=company,
        permissions=("documents.view",),
    )
    make_document(app, company, document_code="PR.376", title="Known Host Document")
    known_url = f"https://{company.slug}.volkaportal.com"

    with client.session_transaction(base_url=known_url) as session:
        session["user_id"] = user.id
        session["company_id"] = company.id

    unknown_response = client.get(
        "/documents/list", base_url="https://unregistered.volkaportal.com"
    )
    assert unknown_response.status_code == 404
    assert "Known Host Document" not in unknown_response.get_data(as_text=True)

    known_response = client.get("/documents/list", base_url=known_url)
    assert known_response.status_code == 200
    assert "Known Host Document" in known_response.get_data(as_text=True)


def test_inactive_tenant_host_is_rejected(app, client):
    company = create_company("377")
    company.is_active = False
    db.session.commit()

    assert client.get("/login", base_url=f"https://{company.slug}.volkaportal.com").status_code == 404


def test_platform_apex_remains_available(app, client):
    apex_url = "https://volkaportal.com"
    assert client.get("/", base_url=apex_url).status_code == 200
    assert client.get("/login", base_url=apex_url).status_code == 200

    superadmin = create_user("superadmin", role_key="super_admin")
    with client.session_transaction(base_url=apex_url) as session:
        session["user_id"] = superadmin.id
    assert client.get("/sistem/admin-paneli", base_url=apex_url).status_code == 200


def test_disabled_company_module_blocks_route_even_with_permission(app, client):
    company = create_company("375")
    user = create_user(
        "tenant-module-user",
        company=company,
        permissions=("calibration.manage",),
    )
    CompanyModule.query.filter(
        CompanyModule.company_id == company.id,
        CompanyModule.module_key.in_(("calibration", "human_resources")),
    ).update({"is_enabled": False}, synchronize_session=False)
    db.session.commit()

    login(client, user)
    response = client.get("/kalibrasyon")

    assert response.status_code == 403

    report_response = client.get("/insan-kaynaklari/personel-listesi/rapor")
    assert report_response.status_code == 403
