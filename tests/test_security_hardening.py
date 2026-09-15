import re
import os
import subprocess
import sys
from pathlib import Path

from app.config import Config
from app.request_security import request_client_ip
from app.routes import NOTIFICATION_FILTERS


def test_default_password_policy_is_not_weak():
    assert Config.PASSWORD_MIN_LENGTH >= 10
    assert Config.PASSWORD_MAX_LENGTH >= Config.PASSWORD_MIN_LENGTH


def test_client_ip_headers_are_only_trusted_from_configured_proxy(app):
    app.config["TRUSTED_PROXY_IPS"] = ("127.0.0.1", "::1")

    with app.test_request_context(
        "/",
        environ_base={"REMOTE_ADDR": "198.51.100.44"},
        headers={"X-Real-IP": "203.0.113.10", "X-Forwarded-For": "203.0.113.11"},
    ):
        assert request_client_ip() == "198.51.100.44"

    with app.test_request_context(
        "/",
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
        headers={"X-Real-IP": "203.0.113.25", "X-Forwarded-For": "192.0.2.8"},
    ):
        assert request_client_ip() == "203.0.113.25"

    with app.test_request_context(
        "/",
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
        headers={"X-Forwarded-For": "192.0.2.99, 203.0.113.30"},
    ):
        assert request_client_ip() == "203.0.113.30"


def test_security_headers_and_sensitive_page_cache_policy(client):
    response = client.get("/login")

    assert response.status_code == 200
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "SAMEORIGIN"
    assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert response.headers["Permissions-Policy"] == "camera=(), geolocation=(), microphone=()"
    assert "frame-ancestors 'self'" in response.headers["Content-Security-Policy"]
    assert "form-action 'self'" in response.headers["Content-Security-Policy"]
    assert response.headers["Cache-Control"] == "no-store, private"


def test_authenticated_json_is_not_cached(client):
    from tests.helpers import create_company, create_user, login

    company = create_company("CACHE")
    user = create_user("cache-user", company=company, role_key="department_staff")
    login(client, user, company)
    response = client.get("/notifications/count")
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store, private"


def test_csrf_error_does_not_redirect_to_external_referrer(app, client):
    app.config["WTF_CSRF_ENABLED"] = True
    response = client.post(
        "/login",
        data={"identity": "nobody", "password": "invalid"},
        headers={"Referer": "https://attacker.example/phishing"},
    )

    assert response.status_code == 302
    assert response.headers["Location"].startswith("/")
    assert "attacker.example" not in response.headers["Location"]


def test_notification_filter_keys_are_unique():
    keys = [key for key, _label in NOTIFICATION_FILTERS]
    assert len(keys) == len(set(keys))


def test_internal_get_routes_do_not_render_for_anonymous_users(app, client):
    public_endpoints = {
        "main.login",
        "main.landing",
        "main.landing_dynamic_preview",
        "main.legal_index",
        "main.legal_policy",
        "static",
        "customer_portal.public_form",
        "customer_portal.verify",
        "customer_portal.track",
        "customer_portal.public_file",
    }
    adapter = app.url_map.bind("volkaportal.com")

    for rule in app.url_map.iter_rules():
        if "GET" not in rule.methods or rule.endpoint in public_endpoints:
            continue
        values = {
            argument: (
                1
                if rule._converters[argument].__class__.__name__ == "IntegerConverter"
                else "x"
            )
            for argument in rule.arguments
        }
        url = adapter.build(rule.endpoint, values=values)
        response = client.get(url, headers={"Host": "volkaportal.com"})
        assert not 200 <= response.status_code < 300, (rule.endpoint, url)


def test_internal_post_routes_do_not_accept_anonymous_requests(app, client):
    public_endpoints = {
        "main.login",
        "customer_portal.public_form",
        "customer_portal.track",
        "customer_portal.rate",
    }
    adapter = app.url_map.bind("volkaportal.com")

    for rule in app.url_map.iter_rules():
        if "POST" not in rule.methods or rule.endpoint in public_endpoints:
            continue
        values = {
            argument: (
                1
                if rule._converters[argument].__class__.__name__ == "IntegerConverter"
                else "x"
            )
            for argument in rule.arguments
        }
        url = adapter.build(rule.endpoint, values=values)
        response = client.post(url, headers={"Host": "volkaportal.com"})
        assert not 200 <= response.status_code < 300, (rule.endpoint, url)


def test_server_rendered_post_forms_include_csrf_token():
    template_root = Path(__file__).parents[1] / "app" / "templates"
    missing = []

    for template_path in template_root.rglob("*.html"):
        source = template_path.read_text(encoding="utf-8")
        post_forms = re.findall(
            r"<form\b(?=[^>]*\bmethod\s*=\s*['\"]post['\"])[^>]*>.*?</form>",
            source,
            flags=re.IGNORECASE | re.DOTALL,
        )
        for index, form in enumerate(post_forms, start=1):
            if "csrf_token" not in form:
                missing.append(f"{template_path.relative_to(template_root)} form #{index}")

    assert not missing, "CSRF token eksik POST formlari: " + ", ".join(missing)


def test_wsgi_import_does_not_create_or_seed_production_database(tmp_path):
    database_path = tmp_path / "production-import.db"
    environment = os.environ.copy()
    environment.update(
        {
            "APP_ENV": "production",
            "SECRET_KEY": "production-import-test-secret",
            "DATABASE_URL": f"sqlite:///{database_path.as_posix()}",
            "DATA_DIR": str(tmp_path / "data"),
            "UPLOAD_FOLDER": str(tmp_path / "uploads"),
            "AUTO_BOOTSTRAP_DATABASE": "false",
        }
    )

    result = subprocess.run(
        [sys.executable, "-c", "import run"],
        cwd=Path(__file__).parents[1],
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert not database_path.exists()
