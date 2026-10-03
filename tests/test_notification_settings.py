"""UI contract tests; the main application owns policy defaults and registration."""

import importlib
import json

import pytest
from werkzeug.datastructures import MultiDict

from app.extensions import db
from app.models import AppSetting, AuditLog
from app.notification_settings import bp
from .helpers import create_company, create_user, login


BASE = "/notifications/settings"


@pytest.fixture(autouse=True)
def settings_app(app):
    app.config.update(TESTING=True, NOTIFICATION_AUTO_REMINDERS_ENABLED=False)
    if bp.name not in app.blueprints:
        app.register_blueprint(bp)
    return importlib.import_module("app.notification_policy")


def company_form(policy):
    result = {"enabled": "1", "weekly_day": "0"}
    for kind, values in policy.POLICY_DEFAULTS.items():
        result[f"modules.{kind}.days"] = ", ".join(map(str, values["days"]))
        for field in ("email", "weekly"):
            if values[field]:
                result[f"modules.{kind}.{field}"] = "1"
    return result


def policy_settings():
    return AppSetting.query.filter(AppSetting.key.like("notification_policy:%")).all()


def test_login_required_for_all_endpoints(client):
    for path, method in ((BASE, client.get), (BASE + "/preferences", client.post), (BASE + "/company", client.post)):
        response = method(path)
        assert response.status_code == 302
        assert "/login" in response.location


def test_own_settings_default_and_notifications_link(app, client):
    company = create_company()
    user = create_user("settings-person", company=company)
    login(client, user)
    response = client.get(BASE)
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'value="important" checked' in html
    assert "08:30 (Europe/Istanbul)" in html
    assert "Saat dışı kritik e-posta" in html
    assert 'id="company-policy-title"' not in html
    assert BASE in client.get("/notifications").get_data(as_text=True)
    assert not policy_settings()


@pytest.mark.parametrize("mode", ["important", "weekly", "site"])
def test_user_preference_is_own_and_audited(app, client, mode):
    company = create_company()
    user = create_user("settings-user", company=company)
    other = create_user("settings-other", company=company)
    login(client, user)
    response = client.post(BASE + "/preferences", data={"mode": mode}, follow_redirects=True)
    assert response.status_code == 200
    assert f'value="{mode}" checked' in response.get_data(as_text=True)
    row = db.session.get(AppSetting, f"notification_policy:user:{company.id}:{user.id}")
    assert json.loads(row.value) == {"mode": mode}
    assert db.session.get(AppSetting, f"notification_policy:user:{company.id}:{other.id}") is None
    audit = AuditLog.query.filter_by(entity_type="NotificationPreference").one()
    assert audit.company_id == company.id and audit.user_id == user.id
    assert json.loads(audit.new_values) == {"mode": mode}
    client.post(BASE + "/preferences", data={"mode": mode})
    assert AuditLog.query.filter_by(entity_type="NotificationPreference").count() == 1


@pytest.mark.parametrize("payload", [
    {}, {"mode": "daily"}, {"mode": ""}, {"mode": None}, {"mode": []},
    {"mode": "site", "user_id": 2}, {"mode": "site", "company_id": 2},
    {"mode": "site", "enabled": True},
])
def test_reject_invalid_user_json(app, client, payload):
    company = create_company()
    login(client, create_user("settings-user", company=company))
    assert client.post(BASE + "/preferences", json=payload).status_code == 400
    assert not policy_settings()


@pytest.mark.parametrize("role_key", [None, "management", "department_manager", "department_staff", "viewer"])
def test_only_exact_management_roles_can_change_company(app, client, settings_app, role_key):
    company = create_company()
    user = create_user("settings-user", company=company, role_key=role_key, title="Yönetim Temsilcisi", permissions=("users.manage",))
    login(client, user)
    assert client.post(BASE + "/company", data=company_form(settings_app)).status_code == 403
    assert 'id="company-policy-title"' not in client.get(BASE).get_data(as_text=True)
    assert not policy_settings()


@pytest.mark.parametrize("role_key", ["management_representative", "super_admin"])
def test_company_policy_authorized_scoped_and_audited(app, client, settings_app, role_key):
    company = create_company("101")
    other = create_company("102")
    user = create_user("settings-admin", company=company if role_key != "super_admin" else None, role_key=role_key)
    login(client, user, company)
    assert 'id="company-policy-title"' in client.get(BASE).get_data(as_text=True)
    form = company_form(settings_app)
    kind = next(iter(settings_app.POLICY_DEFAULTS))
    form[f"modules.{kind}.days"] = "90, 0, 7"
    form.pop(f"modules.{kind}.email", None)
    form["weekly_day"] = "6"
    response = client.post(BASE + "/company", data=form, follow_redirects=True)
    assert response.status_code == 200
    key = f"notification_policy:company:{company.id}"
    stored = json.loads(db.session.get(AppSetting, key).value)
    assert stored["weekly_day"] == 6
    assert stored["modules"][kind] == {"email": False, "days": [90, 0, 7], "weekly": settings_app.POLICY_DEFAULTS[kind]["weekly"]}
    assert set(stored["modules"]) == set(settings_app.POLICY_DEFAULTS)
    assert db.session.get(AppSetting, f"notification_policy:company:{other.id}") is None
    audit = AuditLog.query.filter_by(entity_type="NotificationPolicy").one()
    assert audit.company_id == company.id and audit.user_id == user.id
    assert json.loads(audit.new_values) == stored
    assert json.loads(audit.old_values)["weekly_day"] == 0
    client.post(BASE + "/company", data=form)
    assert AuditLog.query.filter_by(entity_type="NotificationPolicy").count() == 1


def test_blank_days_and_unchecked_toggles(app, client, settings_app):
    company = create_company()
    login(client, create_user("settings-admin", company=company, role_key="management_representative"))
    form = {"weekly_day": "2"}
    for kind in settings_app.POLICY_DEFAULTS:
        form[f"modules.{kind}.days"] = "  "
    assert client.post(BASE + "/company", data=form).status_code == 302
    stored = json.loads(db.session.get(AppSetting, f"notification_policy:company:{company.id}").value)
    assert stored["enabled"] is False
    assert all(values == {"days": [], "email": False, "weekly": False} for values in stored["modules"].values())


@pytest.mark.parametrize("days", ["7,7", "7,07", "-1", "91", "1.5", "7,,0", "7,", "word", "1e1", "0;7"])
def test_reject_invalid_days_without_partial_write(app, client, settings_app, days):
    company = create_company()
    login(client, create_user("settings-admin", company=company, role_key="management_representative"))
    form = company_form(settings_app)
    kind = next(iter(settings_app.POLICY_DEFAULTS))
    form[f"modules.{kind}.days"] = days
    assert client.post(BASE + "/company", data=form).status_code == 400
    assert not policy_settings()
    assert AuditLog.query.filter_by(entity_type="NotificationPolicy").count() == 0


@pytest.mark.parametrize("change", [
    {"weekly_day": "7"}, {"weekly_day": "-1"}, {"weekly_day": "1.0"},
    {"enabled": "unexpected"}, {"modules.unknown.days": "7"},
    {"company_id": "2"}, {"critical_out_of_hours": "1"}, {"send_time": "09:00"},
])
def test_reject_unknown_or_invalid_company_fields(app, client, settings_app, change):
    company = create_company()
    login(client, create_user("settings-admin", company=company, role_key="management_representative"))
    form = company_form(settings_app)
    form.update(change)
    assert client.post(BASE + "/company", data=form).status_code == 400
    assert not policy_settings()


@pytest.mark.parametrize("days", [[True], [1.2], ["7"], [91], [-1], [7, 7], "7", None, {}])
def test_json_days_require_unique_integers(app, client, settings_app, days):
    company = create_company()
    login(client, create_user("settings-admin", company=company, role_key="management_representative"))
    kind = next(iter(settings_app.POLICY_DEFAULTS))
    payload = {"enabled": True, "weekly_day": 0, "modules": {kind: {"email": True, "weekly": True, "days": days}}}
    assert client.post(BASE + "/company", json=payload).status_code == 400
    assert not policy_settings()


def test_partial_json_preserves_other_modules(app, client, settings_app):
    company = create_company()
    login(client, create_user("settings-admin", company=company, role_key="management_representative"))
    kind = next(iter(settings_app.POLICY_DEFAULTS))
    payload = {"enabled": True, "weekly_day": 1, "modules": {kind: {"email": False, "weekly": False, "days": []}}}
    assert client.post(BASE + "/company", json=payload).status_code == 302
    stored = json.loads(db.session.get(AppSetting, f"notification_policy:company:{company.id}").value)
    assert stored["modules"][kind] == payload["modules"][kind]
    for other, defaults in settings_app.POLICY_DEFAULTS.items():
        if other != kind:
            assert stored["modules"][other] == {field: defaults[field] for field in ("email", "weekly", "days")}


def test_duplicate_fields_and_incomplete_form_rejected(app, client, settings_app):
    company = create_company()
    login(client, create_user("settings-admin", company=company, role_key="management_representative"))
    assert client.post(BASE + "/preferences", data=MultiDict([("mode", "site"), ("mode", "weekly")])).status_code == 400
    assert client.post(BASE + "/company", data={"weekly_day": "0"}).status_code == 400
    assert not policy_settings()


def test_company_context_cannot_be_overridden_by_session_or_query(app, client, settings_app):
    company = create_company("101")
    other = create_company("102", name="Other company secret")
    user = create_user("settings-admin", company=company, role_key="management_representative")
    outsider = create_user("outsider", company=other)
    login(client, user, other)
    response = client.get(f"{BASE}?company_id={other.id}&user_id={outsider.id}")
    assert response.status_code == 200
    assert "Other company secret" not in response.get_data(as_text=True)
    assert client.post(f"{BASE}/company?company_id={other.id}", data=company_form(settings_app)).status_code == 302
    assert db.session.get(AppSetting, f"notification_policy:company:{company.id}") is not None
    assert db.session.get(AppSetting, f"notification_policy:company:{other.id}") is None
    assert client.post(f"{BASE}/preferences?user_id={outsider.id}", data={"mode": "site"}).status_code == 302
    assert db.session.get(AppSetting, f"notification_policy:user:{company.id}:{user.id}") is not None
    assert db.session.get(AppSetting, f"notification_policy:user:{other.id}:{outsider.id}") is None


def test_superadmin_requires_selected_company(app, client, settings_app):
    login(client, create_user("settings-super", role_key="super_admin"))
    assert client.get(BASE).status_code == 400
    assert client.post(BASE + "/preferences", data={"mode": "site"}).status_code == 400
    assert client.post(BASE + "/company", data=company_form(settings_app)).status_code == 400
    assert not policy_settings()


def test_superadmin_preferences_are_separate_per_company(app, client):
    first, second = create_company("101"), create_company("102")
    user = create_user("settings-super", role_key="super_admin")
    for company, mode in ((first, "weekly"), (second, "site")):
        login(client, user, company)
        assert client.post(BASE + "/preferences", data={"mode": mode}).status_code == 302
    assert json.loads(db.session.get(AppSetting, f"notification_policy:user:{first.id}:{user.id}").value) == {"mode": "weekly"}
    assert json.loads(db.session.get(AppSetting, f"notification_policy:user:{second.id}:{user.id}").value) == {"mode": "site"}


def test_csrf_is_inherited_for_both_posts(app, client, settings_app):
    company = create_company()
    login(client, create_user("settings-admin", company=company, role_key="management_representative"))
    app.config["WTF_CSRF_ENABLED"] = True
    for path, payload in (("/preferences", {"mode": "site"}), ("/company", {"enabled": True, "weekly_day": 0, "modules": {}})):
        response = client.post(BASE + path, json=payload)
        assert response.status_code == 400
        assert "Güvenlik doğrulaması" in response.get_json()["message"]
    assert not policy_settings()
