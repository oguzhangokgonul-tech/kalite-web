from unittest.mock import patch

from itsdangerous import URLSafeTimedSerializer
from app.models import AuditLog

from .helpers import create_company, create_user, login


def test_logout_refresh_token_requires_authenticated_session(app, client):
    response = client.get("/session/csrf-token")
    assert response.status_code == 401
    assert response.cache_control.no_store


def test_logout_with_refreshed_csrf_clears_session_and_writes_audit(app, client):
    company = create_company("751")
    user = create_user("logout-user", company=company, role_key="department_staff")
    login(client, user, company)
    app.config["WTF_CSRF_ENABLED"] = True

    token_response = client.get("/session/csrf-token")
    assert token_response.status_code == 200
    assert token_response.cache_control.no_store
    token = token_response.get_json()["csrf_token"]

    response = client.post("/logout", data={"csrf_token": token})
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/login")
    assert response.cache_control.no_store
    deleted_cookies = response.headers.getlist("Set-Cookie")
    assert any(value.startswith("session=;") and "Domain=" not in value for value in deleted_cookies)
    with client.session_transaction() as session:
        assert "user_id" not in session
        assert "company_id" not in session
    audit = AuditLog.query.filter_by(
        entity_type="UserSession",
        entity_id=str(user.id),
        action="logged_out",
    ).one()
    assert audit.company_id == company.id
    assert audit.user_id == user.id


def test_logout_deletes_legacy_host_and_shared_domain_cookies(app, client):
    company = create_company("753")
    user = create_user("logout-cookie-user", company=company)
    login(client, user, company)
    app.config["SESSION_COOKIE_DOMAIN"] = ".volkaportal.com"

    response = client.post("/logout")
    deleted_cookies = response.headers.getlist("Set-Cookie")
    assert any(value.startswith("session=;") and "Domain=" not in value for value in deleted_cookies)
    assert any(
        value.startswith("session=;") and "Domain=volkaportal.com" in value
        for value in deleted_cookies
    )


def test_real_host_and_domain_sessions_cannot_restore_login_after_logout(app, client):
    company = create_company("754")
    user = create_user("logout-two-cookies", company=company)
    app.config.update(SESSION_COOKIE_DOMAIN=".volkaportal.com", WTF_CSRF_ENABLED=True)
    host = f"{company.slug}.volkaportal.com"
    base = f"https://{host}"
    serializer = app.session_interface.get_signing_serializer(app)
    cookie = serializer.dumps({"user_id": user.id, "company_id": company.id, "_permanent": True})
    client.set_cookie("session", cookie, domain=host, origin_only=True)
    client.set_cookie("session", cookie, domain="volkaportal.com", origin_only=False)
    token = client.get("/session/csrf-token", base_url=base).get_json()["csrf_token"]
    # The refreshed domain cookie may differ from the legacy host cookie.
    response = client.post("/logout", base_url=base, headers={"Referer": base + "/"}, data={"csrf_token": token}, follow_redirects=True)
    assert response.status_code == 200
    assert response.request.path == "/login"
    assert client.get("/session/csrf-token", base_url=base).status_code == 401
    assert client.get("/", base_url=base).status_code == 302


def test_expired_token_is_rejected_and_fresh_token_can_logout(app, client):
    company = create_company("755")
    user = create_user("logout-expired", company=company)
    login(client, user, company)
    app.config["WTF_CSRF_ENABLED"] = True
    client.get("/session/csrf-token")
    with client.session_transaction() as session:
        raw_token = session["csrf_token"]
    with patch("itsdangerous.timed.time.time", return_value=1000000000):
        old_token = URLSafeTimedSerializer(app.secret_key, salt="wtf-csrf-token").dumps(raw_token)
    client.post("/logout", data={"csrf_token": old_token})
    with client.session_transaction() as session:
        assert session["user_id"] == user.id
    fresh_token = client.get("/session/csrf-token").get_json()["csrf_token"]
    response = client.post("/logout", data={"csrf_token": fresh_token}, follow_redirects=True)
    assert response.request.path == "/login"
    assert client.get("/session/csrf-token").status_code == 401


def test_get_logout_does_not_change_authenticated_session(app, client):
    company = create_company("752")
    user = create_user("logout-get-user", company=company)
    login(client, user, company)

    response = client.get("/logout")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/")
    with client.session_transaction() as session:
        assert session["user_id"] == user.id
    assert AuditLog.query.filter_by(entity_type="UserSession", action="logged_out").count() == 0


def test_audit_failure_does_not_prevent_logout(app, client):
    company = create_company("756")
    user = create_user("logout-audit-failure", company=company)
    login(client, user, company)
    app.config["WTF_CSRF_ENABLED"] = True
    token = client.get("/session/csrf-token").get_json()["csrf_token"]
    with patch("app.routes.record_audit_event", side_effect=RuntimeError("audit unavailable")):
        response = client.post("/logout", data={"csrf_token": token})
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/login")
    assert client.get("/session/csrf-token").status_code == 401
