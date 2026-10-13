"""Independent company-admin route checks using an isolated in-memory database."""

import json
from html.parser import HTMLParser
from pathlib import Path

import pytest

from app import create_app
from app.extensions import db
from app.models import AuditLog, Company, PersonnelContact, Role, RolePermission, User
from app.routes import is_management_representative
from app.seed import COMPANY_ADMIN_DELEGATABLE_ROLE_KEYS, ensure_default_roles


@pytest.fixture()
def app(tmp_path):
    class TestConfig:
        TESTING = True
        SECRET_KEY = "test"
        SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        WTF_CSRF_ENABLED = False
        UPLOAD_FOLDER = str(Path(tmp_path) / "uploads")
        TENANT_BASE_DOMAIN = "volkaportal.com"
        PASSWORD_MIN_LENGTH = 4
        MAIL_ENABLED = False

    test_app = create_app(TestConfig)
    with test_app.app_context():
        assert db.engine.url.database == ":memory:"
        db.create_all()
        ensure_default_roles()
        db.session.commit()
        yield test_app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


def create_user(username, role_key=None, company=None):
    user = User(
        company_id=company.id if company else None,
        username=username,
        full_name=username.title(),
        password_hash="not-used",
        is_active=True,
    )
    if role_key:
        role = Role.query.filter_by(key=role_key).one_or_none()
        assert role is not None, f"Missing seeded role: {role_key}"
        user.roles.append(role)
    db.session.add(user)
    db.session.commit()
    return user


def login(client, user, company=None):
    with client.session_transaction() as session:
        session.clear()
        session["user_id"] = user.id
        if company:
            session["company_id"] = company.id


@pytest.fixture()
def companies(app):
    own = Company(code="qa-a", name="QA Company A", slug="qa-a", is_active=True)
    other = Company(code="qa-b", name="QA Company B", slug="qa-b", is_active=True)
    db.session.add_all([own, other])
    db.session.commit()
    return own, other


@pytest.fixture()
def admin(companies):
    return create_user("company-admin", "company_admin", companies[0])


def payload(username="ordinary", role=None, **overrides):
    data = {
        "username": username,
        "full_name": "QA Ordinary User",
        "password": "test-password-42",
        "is_active": "on",
    }
    if role is not None:
        data.update(role_form_present="1", role_ids=[str(role.id)])
    data.update(overrides)
    return data


def assign(client, route, target, role, company=None):
    if route == "new":
        data = payload("new-assignee", role)
        if company:
            data["company_id"] = str(company.id)
        return client.post("/users/new", data=data)
    if route == "edit":
        return client.post(
            f"/users/{target.id}/edit", data=payload(target.username, role)
        )
    return client.post(
        "/roles/user-assignments",
        data={
            "managed_user_ids": [str(target.id)],
            f"user_{target.id}_roles": [str(role.id)],
        },
    )


def snapshot(user):
    db.session.expire_all()
    return (
        user.username,
        user.full_name,
        user.company_id,
        user.password_hash,
        user.is_active,
        frozenset(user.role_keys),
    )


class FormControls(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.links = set()
        self.actions = set()
        self.role_ids = set()
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a":
            self.links.add(attrs.get("href"))
        elif tag == "form":
            self.actions.add(attrs.get("action"))
        elif tag == "input" and attrs.get("name") == "role_ids":
            self.role_ids.add(attrs.get("value"))


def test_company_admin_seed_is_exact_and_idempotent(app):
    role = Role.query.filter_by(key="company_admin").one_or_none()
    assert role is not None, "company_admin must be seeded"
    expected = {"users.delete", "users.assign_roles"}
    for lower_role in Role.query.filter(Role.key.in_(COMPANY_ADMIN_DELEGATABLE_ROLE_KEYS)).all():
        expected |= lower_role.permission_keys
    assert role.is_system is True
    assert role.hierarchy_level == 5
    assert role.permission_keys == expected
    assert "roles.manage" not in role.permission_keys
    ensure_default_roles()
    db.session.commit()
    assert Role.query.filter_by(key="company_admin").count() == 1
    assert role.permission_keys == expected
    assert len(role.permissions) == len(expected)


def test_company_admin_is_not_superadmin(admin):
    assert admin.has_permission("users.manage")
    assert admin.has_permission("users.delete")
    assert admin.has_permission("users.assign_roles")
    assert not admin.has_role("super_admin")
    assert not admin.has_permission("roles.manage")
    assert not admin.has_permission("qa.nonexistent.permission")
    assert is_management_representative(admin) is True


@pytest.mark.parametrize("route", ["new", "edit", "bulk"])
def test_global_superadmin_assigns_company_admin(client, companies, route):
    root = create_user("superadmin", "super_admin")
    target = create_user("assignee", company=companies[0])
    role = Role.query.filter_by(key="company_admin").one()
    login(client, root)
    response = assign(client, route, target, role, companies[0])
    assert response.status_code == 302
    db.session.expire_all()
    if route == "new":
        target = User.query.filter_by(username="new-assignee").one()
    assert target.company_id == companies[0].id
    assert target.role_keys == {"company_admin"}
    assert target.can_manage_users is True


@pytest.mark.parametrize("route", ["new", "edit", "bulk"])
def test_global_superadmin_cannot_assign_company_admin_without_company(app, client, route):
    root = create_user("superadmin", "super_admin")
    target = create_user("global-ordinary")
    original = snapshot(target)
    role = Role.query.filter_by(key="company_admin").one()
    login(client, root)
    response = assign(client, route, target, role)
    assert response.status_code in {200, 302, 400, 403}
    assert snapshot(target) == original
    assert User.query.filter_by(username="new-assignee").first() is None


@pytest.mark.parametrize("route", ["new", "edit", "bulk"])
def test_global_superadmin_cannot_assign_super_admin_to_tenant(client, companies, route):
    root = create_user("superadmin", "super_admin")
    target = create_user("tenant-ordinary", company=companies[0])
    original = snapshot(target)
    login(client, root, companies[0])
    role = Role.query.filter_by(key="super_admin").one()
    response = assign(client, route, target, role, companies[0])
    assert response.status_code in {200, 302, 400, 403}
    assert snapshot(target) == original
    assert User.query.filter_by(username="new-assignee").first() is None


@pytest.mark.parametrize("route", ["new", "edit"])
def test_company_admin_assigns_lower_role_and_ignores_foreign_company_id(
    client, companies, admin, route
):
    target = create_user("ordinary", company=companies[0])
    role = Role.query.filter_by(key="management_representative").one()
    assert role.hierarchy_level > admin.roles[0].hierarchy_level
    assert role.permission_keys <= admin.roles[0].permission_keys
    login(client, admin, companies[1])
    url = "/users/new" if route == "new" else f"/users/{target.id}/edit"
    username = "new-ordinary" if route == "new" else target.username
    response = client.post(
        url, data=payload(username, role, company_id=str(companies[1].id))
    )
    assert response.status_code == 302
    db.session.expire_all()
    saved = User.query.filter_by(username=username).one()
    assert saved.company_id == companies[0].id
    assert saved.role_keys == {"management_representative"}
    assert saved.full_name == "QA Ordinary User"
    assert saved.check_password("test-password-42")


def test_company_admin_can_remove_lower_role(client, companies, admin):
    target = create_user("ordinary", "management_representative", companies[0])
    login(client, admin)
    response = client.post(
        f"/users/{target.id}/edit",
        data=payload(target.username, role_form_present="1", role_ids=[]),
    )
    assert response.status_code == 302
    db.session.expire_all()
    assert target.role_keys == set()
    assert target.can_manage_users is False


def test_company_admin_deletes_ordinary_own_company_user(client, companies, admin):
    target = create_user("ordinary", company=companies[0])
    login(client, admin)
    response = client.post(f"/users/{target.id}/delete")
    assert response.status_code == 302
    db.session.expire_all()
    assert target.is_active is False
    assert target.company_id == companies[0].id


@pytest.mark.parametrize("route", ["new", "edit"])
@pytest.mark.parametrize(
    "forbidden", ["company_admin", "super_admin", "overpowered", "equal", "higher"]
)
def test_company_admin_rejects_escalating_role_assignments(
    client, companies, admin, route, forbidden
):
    target = create_user("ordinary", company=companies[0])
    original = snapshot(target)
    if forbidden in {"overpowered", "equal", "higher"}:
        role = Role.query.filter_by(key="management_representative").one()
        if forbidden == "overpowered":
            role.permissions.append(RolePermission(permission_key="roles.manage"))
        else:
            role.hierarchy_level = 5 if forbidden == "equal" else 4
        db.session.commit()
    else:
        role = Role.query.filter_by(key=forbidden).one()
    login(client, admin)
    response = assign(client, route, target, role, companies[0])
    assert response.status_code in {200, 302, 400, 403}
    assert snapshot(target) == original
    assert User.query.filter_by(username="new-assignee").first() is None


@pytest.mark.parametrize("operation", ["get-edit", "edit", "delete", "bulk"])
@pytest.mark.parametrize("protected", ["self", "peer", "superadmin", "foreign", "global"])
def test_company_admin_cannot_modify_protected_users(
    client, companies, admin, operation, protected
):
    if protected == "self":
        target = admin
    elif protected == "peer":
        target = create_user("peer-admin", "company_admin", companies[0])
    elif protected == "superadmin":
        target = create_user("superadmin", "super_admin")
    else:
        target = create_user(
            "protected", company=companies[1] if protected == "foreign" else None
        )
    original = snapshot(target)
    login(client, admin)
    if operation == "get-edit":
        response = client.get(f"/users/{target.id}/edit")
        assert response.status_code in {403, 404}
    elif operation == "edit":
        response = client.post(f"/users/{target.id}/edit", data=payload("changed"))
        assert response.status_code in {403, 404}
    elif operation == "delete":
        response = client.post(f"/users/{target.id}/delete")
        assert response.status_code in {302, 403, 404}
    else:
        role = Role.query.filter_by(key="management_representative").one()
        response = assign(client, "bulk", target, role)
        assert response.status_code in {302, 403, 404}
    assert snapshot(target) == original


@pytest.mark.parametrize("route", ["new", "edit"])
@pytest.mark.parametrize("actor_role", ["company_admin", "management_representative"])
def test_non_superadmin_cannot_claim_reserved_username(client, companies, route, actor_role):
    # No existing global superadmin: uniqueness must not mask authorization bugs.
    actor = create_user("actor", actor_role, companies[0])
    target = create_user("ordinary", company=companies[0])
    original = snapshot(target)
    login(client, actor)
    url = "/users/new" if route == "new" else f"/users/{target.id}/edit"
    response = client.post(url, data=payload("  SuPeRaDmIn  "))
    assert response.status_code in {200, 302, 400, 403}
    assert snapshot(target) == original
    assert User.query.filter_by(username="superadmin").first() is None


def test_users_ui_hides_protected_controls_and_other_tenant(client, companies, admin):
    ordinary = create_user("ordinary", company=companies[0])
    peer = create_user("peer-admin", "company_admin", companies[0])
    foreign = create_user("foreign-unique-user", company=companies[1])
    root = create_user("superadmin", "super_admin")
    login(client, admin)
    response = client.get("/users")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    controls = FormControls(body)
    assert f"/users/{ordinary.id}/edit" in controls.links
    assert f"/users/{ordinary.id}/delete" in controls.actions
    assert peer.full_name in body
    assert foreign.username not in body
    for protected in [admin, peer, foreign, root]:
        assert f"/users/{protected.id}/edit" not in controls.links
        assert f"/users/{protected.id}/delete" not in controls.actions


@pytest.mark.parametrize("route", ["new", "edit"])
def test_company_admin_role_form_only_offers_allowed_roles(client, companies, admin, route):
    target = create_user("ordinary", company=companies[0])
    login(client, admin)
    url = "/users/new" if route == "new" else f"/users/{target.id}/edit"
    response = client.get(url)
    assert response.status_code == 200
    controls = FormControls(response.get_data(as_text=True))
    representative = Role.query.filter_by(key="management_representative").one()
    assert str(representative.id) in controls.role_ids
    for role in Role.query.filter(Role.key.in_(COMPANY_ADMIN_DELEGATABLE_ROLE_KEYS)).all():
        assert str(role.id) in controls.role_ids
    for role in Role.query.all():
        if role.hierarchy_level <= 5 or not role.permission_keys <= admin.roles[0].permission_keys:
            assert str(role.id) not in controls.role_ids


@pytest.mark.parametrize(
    "path", ["/roles", "/companies", "/companies/new", "/kurulum-sihirbazi",
             "/satisa-hazirlik", "/sistem/yedekler", "/sistem/admin-paneli",
             "/pilot-programi", "/denetim-logu"]
)
def test_company_admin_cannot_access_platform_pages(client, admin, path):
    login(client, admin)
    assert client.get(path).status_code == 403


def test_company_admin_cannot_change_global_role_permissions(client, admin):
    role = Role.query.filter_by(key="management_representative").one()
    original = role.permission_keys.copy()
    login(client, admin)
    response = client.post(
        "/roles", data={"role_id": str(role.id), "permission_keys": ["roles.manage"]}
    )
    assert response.status_code == 403
    db.session.expire_all()
    assert role.permission_keys == original


@pytest.mark.parametrize("route", ["edit", "bulk"])
def test_role_assignment_records_actor_tenant_and_role_change(client, companies, route):
    root = create_user("superadmin", "super_admin")
    target = create_user("ordinary", company=companies[0])
    role = Role.query.filter_by(key="company_admin").one()
    login(client, root)
    before_id = db.session.query(db.func.max(AuditLog.id)).scalar() or 0
    response = assign(client, route, target, role)
    assert response.status_code == 302
    logs = AuditLog.query.filter(
        AuditLog.id > before_id,
        AuditLog.user_id == root.id,
        AuditLog.company_id == companies[0].id,
        AuditLog.entity_id == str(target.id),
    ).all()
    assert logs, "Role assignment must identify the actor, target, and tenant in audit"
    assert any(
        "company_admin" in json.dumps(json.loads(log.new_values or "{}"))
        for log in logs
    ), "Role assignment audit must capture the new role"


@pytest.mark.parametrize("route", ["new", "edit", "bulk"])
def test_role_only_superadmin_cannot_assign_company_admin(client, companies, route):
    actor = create_user("not-the-global-account", "super_admin", companies[0])
    target = create_user("ordinary", company=companies[0])
    original = snapshot(target)
    role = Role.query.filter_by(key="company_admin").one()
    login(client, actor, companies[0])
    response = assign(client, route, target, role, companies[0])
    assert response.status_code in {200, 302, 400, 403}
    assert snapshot(target) == original
    assert User.query.filter_by(username="new-assignee").first() is None


@pytest.mark.parametrize("operation", ["get-edit", "edit", "delete"])
@pytest.mark.parametrize("protected", ["self", "peer"])
def test_company_admin_cannot_modify_protected_personnel(
    client, companies, admin, operation, protected
):
    target = admin if protected == "self" else create_user(
        "peer-admin", "company_admin", companies[0]
    )
    contact = PersonnelContact(
        company_id=companies[0].id,
        full_name=target.full_name,
        email="protected@example.test",
        is_active=True,
    )
    db.session.add(contact)
    target.personnel_contact = contact
    db.session.commit()
    original_user = snapshot(target)
    original_contact = (contact.full_name, contact.email, contact.is_active)
    login(client, admin)
    url = f"/insan-kaynaklari/personel-listesi/{contact.id}"
    if operation == "get-edit":
        response = client.get(f"{url}/duzenle")
    elif operation == "edit":
        response = client.post(
            f"{url}/duzenle",
            data={"full_name": "Changed", "email": "changed@example.test"},
        )
    else:
        response = client.post(f"{url}/sil")
    assert response.status_code == 403
    assert snapshot(target) == original_user
    assert (contact.full_name, contact.email, contact.is_active) == original_contact
    assert target.personnel_contact_id == contact.id


@pytest.mark.parametrize("route", ["edit", "bulk"])
def test_superadmin_demotion_audits_and_revokes_legacy_permissions(
    client, companies, admin, route
):
    root = create_user("superadmin", "super_admin")
    for field in [
        "can_manage_users", "can_create_actions", "can_edit_actions",
        "can_delete_actions", "can_comment_assigned_actions", "can_close_assigned_actions",
    ]:
        setattr(admin, field, True)
    db.session.commit()
    login(client, root)
    viewer = Role.query.filter_by(key="viewer").one()
    response = assign(client, route, admin, viewer)
    assert response.status_code == 302
    db.session.expire_all()
    assert admin.role_keys == {"viewer"}
    for field in [
        "can_manage_users", "can_create_actions", "can_edit_actions",
        "can_delete_actions", "can_comment_assigned_actions", "can_close_assigned_actions",
    ]:
        assert getattr(admin, field) is False, f"Demotion left stale {field}"
    assert not admin.has_permission("users.assign_roles")
    assert not admin.has_permission("users.delete")
    logs = AuditLog.query.filter_by(
        entity_type="User", entity_id=str(admin.id), action="roles_changed",
        company_id=companies[0].id, user_id=root.id,
    ).all()
    assert len(logs) == 1
    assert json.loads(logs[0].old_values)["roles"] == ["company_admin"]
    assert json.loads(logs[0].new_values)["roles"] == ["viewer"]
    login(client, admin)
    assert client.get("/users").status_code == 403


@pytest.mark.parametrize("route", ["new", "edit"])
def test_company_admin_cannot_grant_legacy_permission_it_lacks(
    client, companies, admin, route
):
    role = admin.roles[0]
    for permission in list(role.permissions):
        if permission.permission_key == "actions.delete":
            role.permissions.remove(permission)
    db.session.commit()
    assert not admin.has_permission("actions.delete")
    target = create_user("ordinary", company=companies[0])
    original = snapshot(target)
    login(client, admin)
    url = "/users/new" if route == "new" else f"/users/{target.id}/edit"
    username = "new-ordinary" if route == "new" else target.username
    response = client.post(url, data=payload(username, can_delete_actions="on"))
    assert response.status_code == 403
    assert snapshot(target) == original
    assert target.can_delete_actions is False
    assert User.query.filter_by(username="new-ordinary").first() is None


def test_user_cannot_self_grant_legacy_permission(client, companies):
    actor = create_user("limited-manager", company=companies[0])
    actor.can_manage_users = True
    db.session.commit()
    login(client, actor)
    response = client.post(f"/users/{actor.id}/edit", data=payload(
        actor.username, can_manage_users="on", can_delete_actions="on",
    ))
    assert response.status_code == 403
    db.session.expire_all()
    assert actor.can_delete_actions is False


def test_global_creation_links_personnel_in_selected_company(client, companies):
    root = create_user("superadmin", "super_admin")
    foreign_contact = PersonnelContact(company_id=companies[1].id, full_name="QA Ordinary User", is_active=True)
    db.session.add(foreign_contact)
    db.session.commit()
    login(client, root)
    role = Role.query.filter_by(key="company_admin").one()
    response = client.post("/users/new", data=payload(
        "selected-admin", role, company_id=str(companies[0].id),
    ))
    assert response.status_code == 302
    saved = User.query.filter_by(username="selected-admin").one()
    assert saved.personnel_contact.company_id == saved.company_id == companies[0].id
    assert saved.personnel_contact_id != foreign_contact.id
    logs = AuditLog.query.filter_by(entity_type="User", entity_id=str(saved.id), action="roles_changed").all()
    assert len(logs) == 1 and logs[0].company_id == companies[0].id


def test_null_company_admin_session_fails_closed(client, app):
    invalid = create_user("invalid-admin", "company_admin")
    login(client, invalid)
    response = client.get("/users")
    assert response.status_code == 302
    with client.session_transaction() as saved_session:
        assert "user_id" not in saved_session


def test_company_admin_mutations_require_csrf(app, client, companies, admin):
    target = create_user("ordinary", company=companies[0])
    login(client, admin)
    app.config["WTF_CSRF_ENABLED"] = True
    headers = {"Accept": "application/json"}
    assert client.post(f"/users/{target.id}/delete", headers=headers).status_code == 400
    assert client.post("/users/new", data=payload("blocked"), headers=headers).status_code == 400
    db.session.expire_all()
    assert target.is_active
    assert User.query.filter_by(username="blocked").first() is None


def test_global_superadmin_can_disable_and_reenable_company_admin(client, companies, admin):
    root = create_user("superadmin", "super_admin")
    login(client, root)
    data = payload(admin.username, full_name=admin.full_name, password="", is_active="")
    assert client.post(f"/users/{admin.id}/edit", data=data).status_code == 302
    db.session.expire_all()
    assert admin.is_active is False
    assert admin.has_role("company_admin")
    assert client.get("/users").status_code == 200
    data["is_active"] = "on"
    assert client.post(f"/users/{admin.id}/edit", data=data).status_code == 302
    db.session.expire_all()
    assert admin.is_active is True


def test_onboarding_company_admin_assignment_has_role_audit(client):
    from tests.test_company_onboarding_wizard import onboarding_payload
    root = create_user("superadmin", "super_admin")
    login(client, root)
    response = client.post("/kurulum-sihirbazi", data=onboarding_payload(
        initial_role_keys=["company_admin"],
    ))
    assert response.status_code == 302
    company = Company.query.filter_by(code="222").one()
    user = User.query.filter_by(company_id=company.id, username="ayse").one()
    assert user.role_keys == {"company_admin"}
    event = AuditLog.query.filter_by(entity_type="User", entity_id=str(user.id),
                                    action="roles_changed", company_id=company.id,
                                    user_id=root.id).one()
    assert json.loads(event.old_values) == {"roles": []}
    assert json.loads(event.new_values) == {"roles": ["company_admin"]}
