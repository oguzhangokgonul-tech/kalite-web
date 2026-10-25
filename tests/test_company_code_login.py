"""Public entry and company-scoped password authentication."""

import re

import pytest

from app.extensions import db
from app.config import Config
from app.models import LoginAttempt
from tests.helpers import create_company, create_user, login, make_document


ROOT = "https://volkaportal.com"
PASSWORD = "Valid-password-42"


@pytest.fixture()
def accounts(app):
    app.config.update(
        LOGIN_MAX_FAILED_ATTEMPTS=Config.LOGIN_MAX_FAILED_ATTEMPTS,
        LOGIN_IP_MAX_FAILED_ATTEMPTS=Config.LOGIN_IP_MAX_FAILED_ATTEMPTS,
        LOGIN_LOCKOUT_MINUTES=Config.LOGIN_LOCKOUT_MINUTES,
    )
    a, b = create_company("001"), create_company("002")
    users = [
        create_user("shared-user", company=company, role_key="department_staff",
                    full_name="Ortak Kullanici", permissions=("documents.view",))
        for company in (a, b)
    ]
    users[0].set_password(PASSWORD)
    users[1].set_password("Second-password-84")
    db.session.commit()
    return a, b, *users


def authenticate(client, code="", password=PASSWORD, identity="shared-user", host=ROOT, **extra):
    return client.post("/login", base_url=host, data={
        "company_code": code, "identity": identity, "password": password, **extra,
    })


def assert_session(client, user=None, company=None, host=ROOT):
    with client.session_transaction(base_url=host) as session:
        assert session.get("user_id") == (user.id if user else None)
        if company:
            assert session["company_id"] == company.id


@pytest.mark.parametrize("host", [ROOT, "https://www.volkaportal.com", "http://localhost"])
def test_anonymous_root_renders_approved_landing(client, accounts, host):
    body = client.get("/", base_url=host).get_data(as_text=True)
    assert "data-dynamic-landing" in body
    assert 'href="/login"' in body
    assert "shared-user" not in body


def test_company_options_are_active_codes_only(client, accounts):
    a, b, *_ = accounts
    b.is_active = False
    db.session.commit()
    response = client.get("/login", base_url=ROOT)
    body = response.get_data(as_text=True)
    assert 'name="company_code"' in body
    assert 'value="001"' in body
    assert 'value="002"' not in body
    assert a.name not in body and b.name not in body
    assert "Şirket Kodu" in body
    assert "no-store" in response.headers["Cache-Control"]


@pytest.mark.parametrize("code,password,index", [
    ("001", PASSWORD, 0), ("002", "Second-password-84", 1),
])
def test_same_identity_logs_into_selected_company(client, accounts, code, password, index):
    company = accounts[index]
    user = accounts[index + 2]
    response = authenticate(client, code, password)
    assert response.status_code == 302
    assert_session(client, user, company)
    attempt = LoginAttempt.query.order_by(LoginAttempt.id.desc()).first()
    assert attempt.success and attempt.company_id == company.id


@pytest.mark.parametrize("code", ["", "002", "999", "1", "01", "００１", "001x"])
def test_wrong_missing_or_invalid_code_does_not_authenticate(client, accounts, code):
    response = authenticate(client, code)
    assert response.status_code == 200
    assert_session(client)
    assert 'value="shared-user"' in response.get_data(as_text=True)
    assert PASSWORD not in response.get_data(as_text=True)


def test_inactive_company_cannot_login(client, accounts):
    accounts[0].is_active = False
    db.session.commit()
    assert authenticate(client, "001").status_code == 200
    assert_session(client)


def test_tenant_host_cannot_be_overridden_and_legacy_post_still_works(client, accounts):
    a, b, ua, _ = accounts
    host = f"https://{a.slug}.volkaportal.com"
    body = client.get("/login", base_url=host).get_data(as_text=True)
    assert 'value="001"' in body and 'value="002"' not in body
    assert client.get("/", base_url=host).status_code == 302
    assert authenticate(client, "002", host=host).status_code == 200
    assert_session(client, host=host)
    assert authenticate(client, "", host=host).status_code == 302
    assert_session(client, ua, a, host)


@pytest.mark.parametrize("host,expected_status", [
    ("https://unknown.volkaportal.com", 404),
    ("https://untrusted.example", 200),
    ("http://unknown.local", 200),
])
def test_unknown_host_cannot_select_company(client, accounts, host, expected_status):
    login_response = client.get("/login", base_url=host)
    assert login_response.status_code == expected_status
    assert 'value="001"' not in login_response.get_data(as_text=True)
    assert authenticate(client, "001", host=host).status_code == expected_status
    assert_session(client, host=host)


def test_production_rejects_loopback_as_public_entry(app, client, accounts):
    app.config["APP_ENV"] = "production"
    assert 'value="001"' not in client.get("/login").get_data(as_text=True)
    assert authenticate(client, "001", host="http://localhost").status_code == 200
    assert_session(client, host="http://localhost")


def test_global_superadmin_and_unprivileged_global_user(client, accounts):
    admin = create_user("platform-admin", role_key="super_admin")
    outsider = create_user("global-staff", role_key="department_staff")
    for user in (admin, outsider):
        user.set_password(PASSWORD)
    db.session.commit()
    assert authenticate(client, identity=outsider.username).status_code == 200
    assert_session(client)
    assert authenticate(client, "999", identity=admin.username).status_code == 200
    assert_session(client)
    assert authenticate(client, identity=admin.username).status_code == 302
    assert_session(client, admin)


@pytest.mark.parametrize("tenant_host", [False, True])
def test_company_bound_superadmin_role_cannot_authenticate(client, accounts, tenant_host):
    company = accounts[0]
    invalid_admin = create_user("invalid-company-admin", company=company, role_key="super_admin")
    invalid_admin.set_password(PASSWORD)
    db.session.commit()

    host = f"https://{company.slug}.volkaportal.com" if tenant_host else ROOT
    response = authenticate(client, company.code, identity=invalid_admin.username, host=host)

    assert response.status_code == 200
    assert_session(client, host=host)
    attempt = LoginAttempt.query.order_by(LoginAttempt.id.desc()).first()
    assert not attempt.success and attempt.reason == "invalid_role_scope"


def test_global_superadmin_can_authenticate_on_tenant_host(client, accounts):
    company = accounts[0]
    admin = create_user("superadmin", role_key="super_admin")
    admin.set_password(PASSWORD)
    db.session.commit()
    host = f"https://{company.slug}.volkaportal.com"

    response = authenticate(client, company.code, identity=admin.username, host=host)

    assert response.status_code == 302
    assert_session(client, admin, company, host)


def test_company_deactivation_revokes_existing_session(client, accounts):
    a, _, user, _ = accounts
    assert authenticate(client, "001").status_code == 302
    a.is_active = False
    db.session.commit()
    assert client.get("/documents/list", base_url=ROOT).status_code == 302
    assert_session(client)


def test_root_login_cannot_read_foreign_documents(app, client, accounts):
    a, b, user, _ = accounts
    make_document(app, a, document_code="A01", title="Own confidential document")
    foreign = make_document(app, b, document_code="B01", title="Foreign confidential document")
    authenticate(client, "001")
    with client.session_transaction(base_url=ROOT) as session:
        session["company_id"] = b.id
    response = client.get("/documents/list", base_url=ROOT)
    assert response.status_code == 200
    assert "Own confidential document" in response.get_data(as_text=True)
    assert "Foreign confidential document" not in response.get_data(as_text=True)
    assert_session(client, user, a)
    for path in (f"/documents/{foreign.id}", f"/documents/{foreign.id}/download",
                 f"/documents/{foreign.id}/preview"):
        assert client.get(path, base_url=ROOT).status_code in (403, 404)


@pytest.mark.parametrize("role", [
    "company_admin", "management_representative", "management",
    "department_manager", "department_staff", "viewer",
])
def test_company_code_never_grants_platform_role(client, accounts, role):
    user = create_user("role-user", company=accounts[0], role_key=role)
    user.set_password(PASSWORD)
    db.session.commit()
    assert authenticate(client, "001", identity=user.username).status_code == 302
    assert_session(client, user, accounts[0])
    assert client.get("/companies", base_url=ROOT).status_code == 403


def test_rate_limit_shared_by_root_and_tenant_but_not_other_company(app, client, accounts):
    a, b, *_ = accounts
    app.config.update(LOGIN_MAX_FAILED_ATTEMPTS=2, LOGIN_IP_MAX_FAILED_ATTEMPTS=100)
    authenticate(client, "001", "wrong")
    authenticate(client, "001", "wrong", host=f"https://{a.slug}.volkaportal.com")
    assert authenticate(client, "001").status_code == 200
    assert_session(client)
    assert LoginAttempt.query.order_by(LoginAttempt.id.desc()).first().reason == "locked"
    assert authenticate(client, "002", "Second-password-84").status_code == 302


def test_successful_login_does_not_reset_ip_failure_window(app, client, accounts):
    app.config.update(LOGIN_MAX_FAILED_ATTEMPTS=100, LOGIN_IP_MAX_FAILED_ATTEMPTS=3)
    for identity in ("unknown-one", "unknown-two"):
        assert authenticate(client, "001", "wrong", identity=identity).status_code == 200
    legitimate_client = app.test_client()
    assert authenticate(legitimate_client, "001").status_code == 302
    assert authenticate(client, "001", "wrong", identity="unknown-three").status_code == 200
    assert authenticate(client, "001").status_code == 200
    assert LoginAttempt.query.order_by(LoginAttempt.id.desc()).first().reason == "rate_limited"


def test_csrf_remember_and_safe_next(app, client, accounts):
    app.config["WTF_CSRF_ENABLED"] = True
    assert authenticate(client, "001").status_code == 302  # CSRF error redirects, no login.
    assert_session(client)
    page = client.get("/login", base_url=ROOT).get_data(as_text=True)
    token = re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)
    response = client.post("/login?next=https://evil.example", base_url=ROOT,
        headers={"Referer": ROOT + "/login"}, data={
        "company_code": "001", "identity": "shared-user", "password": PASSWORD,
        "remember_me": "1", "csrf_token": token,
    })
    assert response.status_code == 302
    assert response.headers["Location"].startswith("/")
    assert "evil.example" not in response.headers["Location"]
    assert_session(client, accounts[2], accounts[0])
    with client.session_transaction(base_url=ROOT) as session:
        assert session.permanent


def test_authenticated_root_remains_dashboard(app, client, accounts, monkeypatch):
    from app import routes
    login(client, accounts[2], accounts[0])
    monkeypatch.setattr(routes, "dashboard_context", lambda: {})
    monkeypatch.setattr(routes, "render_template", lambda name, **kw: name)
    assert client.get("/").get_data(as_text=True) == "dashboard.html"
