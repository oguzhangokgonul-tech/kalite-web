"""Users controls under production-length password policy and real login."""

from html.parser import HTMLParser

import pytest

from app.config import Config
from app.extensions import db
from app.models import AuditLog, PersonnelContact, Role, User
from tests.helpers import create_user, login
from tests.test_user_profile_sync import (
    InputValues,
    assert_foreign_unchanged,
    form,
    profile,
    state,
)


OLD_PASSWORD = "Original-password-42"
NEW_PASSWORD = "Changed-password-84"


@pytest.fixture(autouse=True)
def production_password_policy(app):
    app.config.update(
        PASSWORD_MIN_LENGTH=10,
        PASSWORD_MAX_LENGTH=128,
        LOGIN_MAX_FAILED_ATTEMPTS=Config.LOGIN_MAX_FAILED_ATTEMPTS,
        LOGIN_IP_MAX_FAILED_ATTEMPTS=Config.LOGIN_IP_MAX_FAILED_ATTEMPTS,
        LOGIN_LOCKOUT_MINUTES=Config.LOGIN_LOCKOUT_MINUTES,
    )


@pytest.fixture()
def account(client, profile):
    profile.user.set_password(OLD_PASSWORD)
    db.session.commit()
    # Let request-time seeds finish before recording rollback/audit baselines.
    assert client.get(f"/users/{profile.user.id}/edit").status_code == 200
    return profile


def browser_form(user, **changes):
    data = form(user, role_form_present="1", role_ids=[str(role.id) for role in user.roles])
    data.update(changes)
    return data


def real_login(app, company, username, password, expected_user_id=None):
    client = app.test_client()
    base_url = f"https://{company.slug}.volkaportal.com"
    response = client.post("/login", base_url=base_url, data={
        "identity": username, "password": password,
    })
    assert response.status_code == (302 if expected_user_id is not None else 200)
    with client.session_transaction(base_url=base_url) as session:
        assert session.get("user_id") == expected_user_id
        if expected_user_id is not None:
            assert session["company_id"] == company.id
    return client


def assert_no_password_in_audit(*secrets):
    for entry in AuditLog.query.all():
        payload = f"{entry.old_values or ''} {entry.new_values or ''}"
        assert "password_hash" not in payload
        for secret in secrets:
            assert secret not in payload


class ServerFeedback(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.nodes = []
        self.active = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "data-server-error" in attrs or attrs.get("id") == "userFormError":
            node = {"tag": tag, "attrs": attrs, "text": "", "links": []}
            self.nodes.append(node)
            self.active.append(node)
        if tag == "a":
            for node in self.active:
                node["links"].append(attrs.get("href"))

    def handle_data(self, data):
        for node in self.active:
            node["text"] += data

    def handle_endtag(self, tag):
        if self.active and self.active[-1]["tag"] == tag:
            self.active.pop()


def assert_server_error(response, field, message, *secrets):
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    nodes = ServerFeedback(html).nodes
    errors = [node for node in nodes if "data-server-error" in node["attrs"]]
    assert len(errors) == 1
    error = errors[0]
    assert error["attrs"]["data-server-error"] == field
    assert error["attrs"]["id"] == f"{field}Error"
    assert "d-block" in error["attrs"]["class"].split()
    assert error["text"].strip() == message
    summary = next(node for node in nodes if node["attrs"].get("id") == "userFormError")
    assert "hidden" not in summary["attrs"]
    assert summary["attrs"]["role"] == "alert"
    assert "Kaydedilmedi." in summary["text"]
    assert message in summary["text"]
    assert f"#{field}" in summary["links"]
    assert InputValues(html).values["password"] == ""
    for secret in secrets:
        assert secret not in html


@pytest.mark.parametrize("operation", ["create", "edit"])
def test_password_control_matches_policy_and_never_prefills(client, account, operation):
    path = "/users/new" if operation == "create" else f"/users/{account.user.id}/edit"
    response = client.get(path)
    assert response.status_code == 200
    control = InputValues(response.get_data(as_text=True)).controls["password"]
    assert control["type"] == "password"
    assert control["minlength"] == "10"
    assert control["maxlength"] == "128"
    assert ("required" in control) == (operation == "create")
    assert control.get("value", "") == ""
    assert control["autocomplete"] == "new-password"
    assert "passwordPolicy" in control["aria-describedby"].split()
    assert "passwordError" in control["aria-describedby"].split()


def test_password_change_invalidates_old_password_and_allows_real_new_login(app, client, account):
    user = account.user
    real_login(app, account.own, user.username, OLD_PASSWORD, user.id)
    old_hash = user.password_hash
    last_audit_id = db.session.query(db.func.max(AuditLog.id)).scalar() or 0
    response = client.post(f"/users/{user.id}/edit", data=browser_form(user, password=NEW_PASSWORD))
    assert response.status_code == 302
    assert response.location.endswith("/users")
    db.session.expire_all()
    assert user.password_hash != old_hash
    assert not user.check_password(OLD_PASSWORD)
    assert user.check_password(NEW_PASSWORD)
    assert user.role_keys == {"department_staff"}
    events = AuditLog.query.filter(
        AuditLog.id > last_audit_id, AuditLog.action == "password_changed",
    ).all()
    assert len(events) == 1
    event = events[0]
    assert event.entity_type == "User"
    assert event.entity_id == str(user.id)
    assert event.user_id == account.actor.id
    assert event.company_id == account.own.id
    assert event.old_values is None
    assert event.new_values is None
    with client.session_transaction() as session:
        assert ("success", "Kullan\u0131c\u0131 ve \u015fifresi g\u00fcncellendi.") in session.get("_flashes", [])
    listed = client.get(response.location)
    assert listed.status_code == 200
    assert "Kullan\u0131c\u0131 ve \u015fifresi g\u00fcncellendi." in listed.get_data(as_text=True)
    assert_foreign_unchanged(account)
    real_login(app, account.own, user.username, OLD_PASSWORD)
    real_login(app, account.own, user.username, NEW_PASSWORD, user.id)
    assert_no_password_in_audit(OLD_PASSWORD, NEW_PASSWORD, user.password_hash)
    response = client.get(f"/users/{user.id}/edit")
    assert InputValues(response.get_data(as_text=True)).values["password"] == ""


def test_global_root_password_audit_does_not_inherit_selected_tenant(client, account):
    root = create_user("superadmin", role_key="super_admin")
    root.set_password(OLD_PASSWORD)
    db.session.commit()
    login(client, root, company=account.own)
    assert client.get(f"/users/{root.id}/edit").status_code == 200
    with client.session_transaction() as session:
        assert session["user_id"] == root.id
        assert session["company_id"] == account.own.id
    before = state(account)
    last_audit_id = db.session.query(db.func.max(AuditLog.id)).scalar() or 0
    response = client.post(f"/users/{root.id}/edit", data=browser_form(root, password=NEW_PASSWORD))
    assert response.status_code == 302
    assert response.location.endswith("/users")
    db.session.expire_all()
    assert root.company_id is None
    assert root.role_keys == {"super_admin"}
    assert root.check_password(NEW_PASSWORD)
    assert not root.check_password(OLD_PASSWORD)
    events = AuditLog.query.filter(
        AuditLog.id > last_audit_id, AuditLog.action == "password_changed",
    ).all()
    assert len(events) == 1
    event = events[0]
    assert event.company_id is None
    assert event.entity_type == "User"
    assert event.entity_id == str(root.id)
    assert event.user_id == root.id
    assert event.old_values is None
    assert event.new_values is None
    assert state(account) == before
    assert_no_password_in_audit(OLD_PASSWORD, NEW_PASSWORD, root.password_hash)
    with client.session_transaction() as session:
        assert session["company_id"] == account.own.id
        assert ("success", "Kullan\u0131c\u0131 ve \u015fifresi g\u00fcncellendi.") in session.get("_flashes", [])


@pytest.mark.parametrize("omitted", [False, True], ids=["blank", "omitted"])
def test_blank_or_omitted_password_preserves_hash_and_login(app, client, account, omitted):
    old_hash = account.user.password_hash
    data = browser_form(account.user, title="Updated Without Password")
    if omitted:
        data.pop("password")
    response = client.post(f"/users/{account.user.id}/edit", data=data)
    assert response.status_code == 302
    db.session.expire_all()
    assert account.user.password_hash == old_hash
    assert account.user.title == "Updated Without Password"
    assert AuditLog.query.filter_by(action="password_changed").count() == 0
    with client.session_transaction() as session:
        flashes = session.get("_flashes", [])
        assert ("success", "Kullan\u0131c\u0131 g\u00fcncellendi.") in flashes
        assert ("success", "Kullan\u0131c\u0131 ve \u015fifresi g\u00fcncellendi.") not in flashes
    real_login(app, account.own, account.user.username, OLD_PASSWORD, account.user.id)


@pytest.mark.parametrize("operation", ["create", "edit"])
@pytest.mark.parametrize("length", [9, 10, 128, 129])
def test_password_length_boundaries_are_enforced_atomically(app, client, account, operation, length):
    password = "A1!" + "x" * (length - 3)
    data = browser_form(account.user, password=password, title="Boundary Title")
    path = f"/users/{account.user.id}/edit"
    if operation == "create":
        path = "/users/new"
        data.update(username="boundary-user", full_name="Boundary Person")
    before = state(account)
    counts = (User.query.count(), PersonnelContact.query.count(), AuditLog.query.count())
    response = client.post(path, data=data)
    db.session.expire_all()
    if length in (9, 129):
        assert response.status_code == 200
        assert state(account) == before
        assert (User.query.count(), PersonnelContact.query.count(), AuditLog.query.count()) == counts
        values = InputValues(response.get_data(as_text=True)).values
        assert values["password"] == ""
        assert values["title"] == "Boundary Title"
        assert password not in response.get_data(as_text=True)
        assert AuditLog.query.filter_by(action="password_changed").count() == 0
        message = (
            "Parola en az 10 karakter olmal\u0131d\u0131r." if length == 9
            else "Parola en fazla 128 karakter olabilir."
        )
        assert_server_error(response, "password", message, password, account.user.password_hash)
    else:
        assert response.status_code == 302
        saved = User.query.filter_by(company_id=account.own.id, username=data["username"]).one()
        assert saved.check_password(password)
        assert saved.is_active is True
        assert saved.role_keys == {"department_staff"}
        assert saved.title == saved.personnel_contact.title == "Boundary Title"
        real_login(app, account.own, saved.username, password, saved.id)
    assert_foreign_unchanged(account)


def test_create_requires_password_without_creating_partial_records(client, account):
    before = (User.query.count(), PersonnelContact.query.count(), AuditLog.query.count())
    response = client.post("/users/new", data=browser_form(
        account.user, username="missing-password", full_name="Missing Password", password="",
    ))
    assert response.status_code == 200
    assert (User.query.count(), PersonnelContact.query.count(), AuditLog.query.count()) == before
    assert InputValues(response.get_data(as_text=True)).values["password"] == ""
    assert_server_error(response, "password", "\u015eifre girin.", account.user.password_hash)


@pytest.mark.parametrize("operation", ["create", "edit"])
@pytest.mark.parametrize("active", [False, True])
def test_active_and_role_controls_persist_with_password_and_real_login(app, client, account, operation, active):
    viewer = Role.query.filter_by(key="viewer").one()
    data = browser_form(account.user, password=NEW_PASSWORD, role_ids=[str(viewer.id)])
    if not active:
        data.pop("is_active")
    path = f"/users/{account.user.id}/edit"
    if operation == "create":
        path = "/users/new"
        data.update(username="active-control", full_name="Active Control")
    response = client.post(path, data=data)
    assert response.status_code == 302
    db.session.expire_all()
    saved = User.query.filter_by(company_id=account.own.id, username=data["username"]).one()
    assert saved.is_active is active
    assert saved.role_keys == {"viewer"}
    assert not saved.has_permission("users.manage")
    assert saved.check_password(NEW_PASSWORD)
    real_login(app, account.own, saved.username, NEW_PASSWORD, saved.id if active else None)


def test_username_locale_and_extra_permission_controls_preserve_password(app, client, account):
    before_hash = account.user.password_hash
    response = client.post(f"/users/{account.user.id}/edit", data=browser_form(
        account.user, username="renamed-password-user", preferred_locale="en",
        extra_permissions=["quality.create"],
    ))
    assert response.status_code == 302
    db.session.expire_all()
    assert account.user.password_hash == before_hash
    assert account.user.preferred_locale == "en"
    assert account.user.has_permission("quality.create")
    real_login(app, account.own, "profile-user", OLD_PASSWORD)
    real_login(app, account.own, "renamed-password-user", OLD_PASSWORD, account.user.id)
    response = client.post(f"/users/{account.user.id}/edit", data=browser_form(account.user))
    assert response.status_code == 302
    db.session.expire_all()
    assert not any(p.permission_key == "quality.create" for p in account.user.extra_permissions)


@pytest.mark.parametrize("role_key", ["viewer", "department_staff", "department_manager", "management"])
def test_unauthorized_roles_cannot_create_or_reset_password(client, account, role_key):
    actor = create_user(f"password-{role_key}", company=account.own, role_key=role_key)
    login(client, actor)
    before = state(account)
    count = User.query.count()
    assert client.get("/users").status_code == 403
    for path in ("/users/new", f"/users/{account.user.id}/edit"):
        assert client.get(path).status_code == 403
        response = client.post(path, data=browser_form(account.user, password=NEW_PASSWORD))
        assert response.status_code == 403
    assert User.query.count() == count
    assert state(account) == before


@pytest.mark.parametrize("role_key", ["company_admin", "super_admin"])
def test_forbidden_role_assignment_rolls_back_password_change(client, account, role_key):
    role = Role.query.filter_by(key=role_key).one()
    before = state(account)
    response = client.post(f"/users/{account.user.id}/edit", data=browser_form(
        account.user, password=NEW_PASSWORD, role_ids=[str(role.id)],
    ))
    assert response.status_code == 403
    assert state(account) == before
    assert account.user.check_password(OLD_PASSWORD)
    assert AuditLog.query.filter_by(action="password_changed").count() == 0


def test_foreign_user_password_edit_and_delete_are_denied(client, account):
    before = state(account)
    path = f"/users/{account.foreign_user.id}"
    assert client.get(path + "/edit").status_code == 404
    assert client.post(path + "/edit", data=browser_form(account.foreign_user, password=NEW_PASSWORD)).status_code == 404
    assert client.post(path + "/delete").status_code == 404
    assert state(account) == before


@pytest.mark.parametrize("operation", ["create", "edit"])
def test_forged_company_cannot_redirect_password_write(app, client, account, operation):
    data = browser_form(account.user, password=NEW_PASSWORD, company_id=str(account.other.id))
    path = f"/users/{account.user.id}/edit"
    if operation == "create":
        path = "/users/new"
        data.update(username="tenant-password", full_name="Tenant Password")
    response = client.post(path, data=data)
    assert response.status_code == 302
    db.session.expire_all()
    saved = User.query.filter_by(username=data["username"], company_id=account.own.id).one()
    assert saved.personnel_contact.company_id == account.own.id
    real_login(app, account.other, saved.username, NEW_PASSWORD)
    real_login(app, account.own, saved.username, NEW_PASSWORD, saved.id)
    assert_foreign_unchanged(account)


@pytest.mark.parametrize("operation", ["create", "edit", "delete"])
@pytest.mark.parametrize("token_kind", ["missing", "invalid", "valid"])
def test_users_mutations_require_csrf(app, client, account, operation, token_kind):
    app.config["WTF_CSRF_ENABLED"] = True
    edit_path = f"/users/{account.user.id}/edit"
    form_path = "/users/new" if operation == "create" else edit_path
    response = client.get(form_path)
    assert response.status_code == 200
    token = InputValues(response.get_data(as_text=True)).values["csrf_token"]
    assert token
    data = browser_form(account.user, password=NEW_PASSWORD)
    path = form_path
    if operation == "create":
        data.update(username="csrf-created", full_name="CSRF Created")
    elif operation == "delete":
        path = f"/users/{account.user.id}/delete"
        data = {}
    if token_kind != "missing":
        data["csrf_token"] = token if token_kind == "valid" else "invalid-token"
    before = state(account)
    count = User.query.count()
    response = client.post(path, data=data)
    db.session.expire_all()
    if token_kind != "valid":
        assert response.status_code in (302, 400)
        assert state(account) == before
        assert User.query.count() == count
        assert AuditLog.query.filter_by(action="password_changed").count() == 0
    else:
        assert response.status_code == 302
        assert response.location.endswith("/users")
        if operation == "create":
            assert User.query.count() == count + 1
            assert User.query.filter_by(username="csrf-created").one().check_password(NEW_PASSWORD)
        elif operation == "edit":
            assert account.user.check_password(NEW_PASSWORD)
        else:
            assert account.user.is_active is False
            assert account.user.username.startswith("silindi_")


def test_delete_disables_real_login_and_self_delete_is_blocked(app, client, account):
    response = client.post(f"/users/{account.actor.id}/delete")
    assert response.status_code in (302, 403)
    db.session.expire_all()
    assert account.actor.is_active is True
    assert account.actor.username == "profile-admin"
    username = account.user.username
    response = client.post(f"/users/{account.user.id}/delete")
    assert response.status_code == 302
    db.session.expire_all()
    assert account.user.is_active is False
    real_login(app, account.own, username, OLD_PASSWORD)
    real_login(app, account.own, account.user.username, OLD_PASSWORD)


def test_duplicate_username_rejects_password_and_profile_changes(client, account):
    other = create_user("occupied-login", company=account.own, role_key="viewer")
    before = state(account)
    response = client.post(f"/users/{account.user.id}/edit", data=browser_form(
        account.user, username=other.username, password=NEW_PASSWORD, title="Must Roll Back",
    ))
    assert response.status_code == 200
    assert state(account) == before
    assert InputValues(response.get_data(as_text=True)).values["password"] == ""
    assert AuditLog.query.filter_by(action="password_changed").count() == 0
    assert_server_error(
        response, "username", "Bu kullan\u0131c\u0131 ad\u0131 zaten kullan\u0131l\u0131yor.",
        NEW_PASSWORD, account.user.password_hash,
    )


def test_invalid_locale_does_not_audit_or_report_password_success(client, account):
    before = state(account)
    response = client.post(f"/users/{account.user.id}/edit", data=browser_form(
        account.user, password=NEW_PASSWORD, preferred_locale="invalid",
    ))
    assert response.status_code == 200
    assert state(account) == before
    assert AuditLog.query.filter_by(action="password_changed").count() == 0
    html = response.get_data(as_text=True)
    assert "Kullan\u0131c\u0131 ve \u015fifresi g\u00fcncellendi." not in html
    assert InputValues(html).values["password"] == ""
    assert_server_error(
        response, "preferred_locale", "Desteklenmeyen bir dil se\u00e7ildi.",
        NEW_PASSWORD, account.user.password_hash,
    )


def test_complete_users_create_read_edit_roles_deactivate_reactivate_delete(app, client, account):
    response = client.post("/users/new", data=browser_form(
        account.user, username="workflow-user", full_name="Workflow Person", password=OLD_PASSWORD,
    ))
    assert response.status_code == 302
    saved = User.query.filter_by(username="workflow-user", company_id=account.own.id).one()
    user_id = saved.id
    contact_id = saved.personnel_contact_id
    assert contact_id is not None
    response = client.get("/users")
    assert response.status_code == 200
    assert "workflow-user" in response.get_data(as_text=True)
    response = client.get(f"/users/{user_id}/edit")
    assert response.status_code == 200
    assert InputValues(response.get_data(as_text=True)).values["full_name"] == "Workflow Person"
    real_login(app, account.own, saved.username, OLD_PASSWORD, user_id)

    viewer = Role.query.filter_by(key="viewer").one()
    response = client.post(f"/users/{user_id}/edit", data=browser_form(
        saved, full_name="Renamed Workflow", title="Workflow Title", email="workflow@example.test",
        preferred_locale="en", password=NEW_PASSWORD, role_ids=[str(viewer.id)],
        extra_permissions=["quality.create"],
    ))
    assert response.status_code == 302
    db.session.expire_all()
    assert saved.personnel_contact_id == contact_id
    assert saved.full_name == saved.personnel_contact.full_name == "Renamed Workflow"
    assert saved.title == saved.personnel_contact.title == "Workflow Title"
    assert saved.email == saved.personnel_contact.email == "workflow@example.test"
    assert saved.preferred_locale == "en"
    assert saved.role_keys == {"viewer"}
    assert saved.has_permission("quality.create")
    real_login(app, account.own, saved.username, OLD_PASSWORD)
    real_login(app, account.own, saved.username, NEW_PASSWORD, user_id)

    for active in (False, True):
        data = browser_form(saved)
        if not active:
            data.pop("is_active")
        assert client.post(f"/users/{user_id}/edit", data=data).status_code == 302
        db.session.expire_all()
        assert saved.is_active is active
        assert saved.check_password(NEW_PASSWORD)
        real_login(app, account.own, saved.username, NEW_PASSWORD, user_id if active else None)
    assert client.post(f"/users/{user_id}/delete").status_code == 302
    db.session.expire_all()
    assert saved.is_active is False
    assert saved.personnel_contact_id == contact_id
    assert saved.personnel_contact.is_active is True
    real_login(app, account.own, "workflow-user", NEW_PASSWORD)
    assert_foreign_unchanged(account)
