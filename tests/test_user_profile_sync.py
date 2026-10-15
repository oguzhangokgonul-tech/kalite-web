"""User edits are authoritative only for submitted, same-company profile fields."""

from datetime import date
from html.parser import HTMLParser
import json
from types import SimpleNamespace

import pytest

from app.extensions import db
from app.models import Action, AuditLog, OrientationNode, PersonnelContact, Role, User
from tests.helpers import create_company, create_user, login


@pytest.fixture()
def profile(client):
    own = create_company("profile-own")
    other = create_company("profile-other")
    actor = create_user("profile-admin", company=own, role_key="company_admin")
    user = create_user(
        "profile-user", company=own, role_key="department_staff",
        full_name="Original Person", title="Original Title",
    )
    user.email = "original@example.test"
    user.preferred_locale = "tr"
    contact = PersonnelContact(
        company_id=own.id, full_name=user.full_name, title=user.title,
        email=user.email, department="Quality", phone="5550001234",
        notes="Keep personnel notes", is_active=True,
    )
    user.personnel_contact = contact
    db.session.add(contact)
    db.session.flush()
    node = OrientationNode(
        company_id=own.id, personnel_contact_id=contact.id, node_type="person",
        name=user.full_name, title=user.title, x=240, y=180, color="#198754",
    )
    foreign_contact = PersonnelContact(
        company_id=other.id, full_name=user.full_name, title="Foreign Title",
        email="foreign@example.test", is_active=True,
    )
    db.session.add_all([node, foreign_contact])
    db.session.flush()
    foreign_user = create_user(
        "profile-foreign", company=other, role_key="department_staff",
        full_name=user.full_name, title=foreign_contact.title,
    )
    foreign_user.email = foreign_contact.email
    foreign_user.personnel_contact = foreign_contact
    foreign_node = OrientationNode(
        company_id=other.id, personnel_contact_id=foreign_contact.id,
        node_type="person", name=foreign_contact.full_name, title=foreign_contact.title,
    )
    db.session.add(foreign_node)
    db.session.commit()
    login(client, actor)
    return SimpleNamespace(
        own=own, other=other, actor=actor, user=user, contact=contact, node=node,
        foreign_user=foreign_user, foreign_contact=foreign_contact, foreign_node=foreign_node,
    )


def form(user, **changes):
    data = {
        "username": user.username, "full_name": user.full_name,
        "title": user.title or "", "email": user.email or "",
        "preferred_locale": user.preferred_locale or "", "password": "",
        "is_active": "on",
    }
    data.update(changes)
    return data


def state(profile):
    db.session.expire_all()
    return tuple(
        tuple(getattr(record, column.name) for column in record.__table__.columns)
        for record in (
            profile.user, profile.contact, profile.node, profile.foreign_user,
            profile.foreign_contact, profile.foreign_node,
        )
    ) + (frozenset(profile.user.role_keys),)


def post_edit(client, profile, data):
    response = client.post(f"/users/{profile.user.id}/edit", data=data)
    assert response.status_code == 302
    assert response.location.endswith("/users")
    db.session.expire_all()
    return response


def assert_profile(profile, *, name="Original Person", title="Original Title", email="original@example.test"):
    user, contact, node = profile.user, profile.contact, profile.node
    assert user.full_name == contact.full_name == node.name == name
    assert (user.title or "") == (contact.title or "") == title
    assert node.title == title
    assert user.email == contact.email == email
    assert user.personnel_contact_id == node.personnel_contact_id == contact.id
    assert user.company_id == contact.company_id == node.company_id == profile.own.id


def assert_foreign_unchanged(profile):
    assert profile.foreign_user.full_name == profile.foreign_contact.full_name == profile.foreign_node.name == "Original Person"
    assert profile.foreign_user.title == profile.foreign_contact.title == profile.foreign_node.title == "Foreign Title"
    assert profile.foreign_user.email == profile.foreign_contact.email == "foreign@example.test"
    assert profile.foreign_user.personnel_contact_id == profile.foreign_contact.id


class InputValues(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.values = {}
        self.controls = {}
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "input" and "name" in attrs:
            self.values[attrs["name"]] = attrs.get("value", "")
            self.controls[attrs["name"]] = attrs


@pytest.mark.parametrize("actor_role", ["company_admin", "management_representative", "super_admin"])
def test_explicit_title_persists_in_user_personnel_org_and_reopened_form(client, profile, actor_role):
    actor = create_user(f"editor-{actor_role}", company=profile.own, role_key=actor_role)
    login(client, actor, company=profile.own)
    counts = (PersonnelContact.query.count(), OrientationNode.query.count())
    post_edit(client, profile, form(profile.user, title="  Updated Title  "))
    assert_profile(profile, title="Updated Title")
    assert_foreign_unchanged(profile)
    assert (PersonnelContact.query.count(), OrientationNode.query.count()) == counts
    for path in ("/users", "/organization", f"/users/{profile.user.id}/edit"):
        response = client.get(path)
        assert response.status_code == 200
    values = InputValues(response.get_data(as_text=True)).values
    assert values["title"] == "Updated Title"
    db.session.expire_all()
    assert_profile(profile, title="Updated Title")


@pytest.mark.parametrize("blank", ["", "   "])
@pytest.mark.parametrize("field", ["title", "email"])
def test_explicit_blank_clears_profile_without_resurrection(client, profile, field, blank):
    expected = {field: "" if field == "title" else None}
    post_edit(client, profile, form(profile.user, **{field: blank}))
    assert_profile(profile, **expected)
    if field == "title":
        assert profile.contact.title == ""
    assert profile.contact.department == "Quality"
    assert client.get("/users").status_code == 200
    response = client.get(f"/users/{profile.user.id}/edit")
    assert response.status_code == 200
    assert InputValues(response.get_data(as_text=True)).values[field] == ""
    db.session.expire_all()
    assert_profile(profile, **expected)
    from app.routes import sync_orientation_node_from_personnel_contact, sync_user_from_personnel_contact

    sync_user_from_personnel_contact(profile.user, profile.contact)
    sync_orientation_node_from_personnel_contact(profile.node, profile.contact)
    db.session.commit()
    db.session.expire_all()
    assert_profile(profile, **expected)
    assert profile.contact.department == "Quality"


def test_cleared_profile_stays_blank_after_personnel_phone_edit_and_repeated_reads(client, profile):
    post_edit(client, profile, form(profile.user, title="", email=""))
    assert_profile(profile, title="", email=None)
    personnel_path = f"/insan-kaynaklari/personel-listesi/{profile.contact.id}/duzenle"
    response = client.get(personnel_path)
    assert response.status_code == 200
    values = InputValues(response.get_data(as_text=True)).values
    assert values["title"] == values["email"] == ""
    data = {field: values[field] for field in ("full_name", "phone", "title", "email")}
    data.update(phone="5550005678", is_active="on")
    response = client.post(personnel_path, data=data)
    assert response.status_code == 302
    assert response.location.endswith("/insan-kaynaklari/personel-listesi")

    for _ in range(2):
        for path in ("/organization", "/users", f"/users/{profile.user.id}/edit", personnel_path):
            response = client.get(path)
            assert response.status_code == 200
            if path.endswith("/edit") or path == personnel_path:
                values = InputValues(response.get_data(as_text=True)).values
                assert values["title"] == values["email"] == ""
            db.session.expire_all()
            assert_profile(profile, title="", email=None)
            assert profile.contact.title == ""
            assert profile.contact.department == "Quality"
            assert profile.contact.phone == "5550005678"
            assert profile.node.to_dict()["title"] == ""
            assert_foreign_unchanged(profile)


def test_explicit_name_and_email_update_existing_link_not_new_personnel(client, profile):
    count = PersonnelContact.query.count()
    post_edit(client, profile, form(
        profile.user, full_name="  Renamed Person  ", email="  updated@example.test  ",
    ))
    assert_profile(profile, name="Renamed Person", email="updated@example.test")
    assert PersonnelContact.query.count() == count
    assert_foreign_unchanged(profile)


@pytest.mark.parametrize("omitted", ["title", "email"])
def test_omitted_optional_profile_field_preserves_existing_value(client, profile, omitted):
    data = form(profile.user)
    data.pop(omitted)
    post_edit(client, profile, data)
    assert_profile(profile)


def test_profile_change_preserves_unrelated_personnel_and_account_fields(client, profile):
    password_hash = profile.user.password_hash
    role_keys = profile.user.role_keys.copy()
    post_edit(client, profile, form(profile.user, title="Updated Title"))
    assert profile.contact.phone == "5550001234"
    assert profile.contact.department == "Quality"
    assert profile.contact.notes == "Keep personnel notes"
    assert profile.contact.is_active is True
    assert (profile.node.x, profile.node.y, profile.node.color) == (240, 180, "#198754")
    assert profile.user.username == "profile-user"
    assert profile.user.password_hash == password_hash
    assert profile.user.preferred_locale == "tr"
    assert profile.user.is_active is True
    assert profile.user.role_keys == role_keys
    assert not profile.user.has_permission("users.manage")
    assert_foreign_unchanged(profile)
    assert_profile(profile, title="Updated Title")


def test_username_password_locale_and_active_changes_still_work(client, profile):
    post_edit(client, profile, form(
        profile.user, username="renamed-login", password="Changed-password-42",
        preferred_locale="en", is_active="",
    ))
    assert profile.user.username == "renamed-login"
    assert profile.user.check_password("Changed-password-42")
    assert profile.user.preferred_locale == "en"
    assert profile.user.is_active is False
    assert profile.contact.is_active is True
    assert_profile(profile)


def test_forged_company_and_contact_ids_cannot_redirect_profile_updates(client, profile):
    post_edit(client, profile, form(
        profile.user, title="Updated Title", company_id=str(profile.other.id),
        personnel_contact_id=str(profile.foreign_contact.id),
    ))
    assert_foreign_unchanged(profile)
    assert_profile(profile, title="Updated Title")


def test_foreign_user_edit_is_denied_without_mutation(client, profile):
    before = state(profile)
    response = client.post(
        f"/users/{profile.foreign_user.id}/edit",
        data=form(profile.foreign_user, title="Forbidden"),
    )
    assert response.status_code == 404
    assert state(profile) == before


@pytest.mark.parametrize("role_key", ["viewer", "department_staff", "department_manager", "management"])
def test_non_manager_cannot_edit_profile_or_linked_records(client, profile, role_key):
    actor = create_user(f"unprivileged-{role_key}", company=profile.own, role_key=role_key)
    login(client, actor)
    before = state(profile)
    response = client.post(f"/users/{profile.user.id}/edit", data=form(profile.user, title="Forbidden"))
    assert response.status_code == 403
    assert state(profile) == before


@pytest.mark.parametrize("role_key", ["super_admin", "company_admin"])
def test_forbidden_role_escalation_rolls_back_linked_profile_changes(client, profile, role_key):
    role = Role.query.filter_by(key=role_key).one()
    before = state(profile)
    response = client.post(f"/users/{profile.user.id}/edit", data=form(
        profile.user, title="Must Roll Back", email="rollback@example.test",
        role_form_present="1", role_ids=[str(role.id)],
    ))
    assert response.status_code == 403
    assert state(profile) == before


def test_invalid_form_rolls_back_all_linked_profile_changes(client, profile):
    before = state(profile)
    response = client.post(f"/users/{profile.user.id}/edit", data=form(
        profile.user, title="Must Roll Back", preferred_locale="invalid",
    ))
    assert response.status_code == 200
    assert state(profile) == before


@pytest.mark.parametrize("global_admin", [False, True])
def test_corrupt_foreign_dependents_cannot_receive_same_company_profile_updates(client, profile, global_admin):
    # Deliberately model legacy cross-tenant links; editing must not spread data.
    profile.foreign_user.personnel_contact_id = profile.contact.id
    profile.foreign_node.personnel_contact_id = profile.contact.id
    db.session.commit()
    if global_admin:
        root = create_user("superadmin", role_key="super_admin")
        login(client, root, company=profile.own)
    before = state(profile)
    response = client.post(f"/users/{profile.user.id}/edit", data=form(profile.user, title="Updated Title"))
    db.session.expire_all()
    if not global_admin:
        assert response.status_code == 403
        assert state(profile) == before
        return
    assert response.status_code == 302
    assert profile.foreign_user.title == "Foreign Title"
    assert profile.foreign_node.title == "Foreign Title"
    assert profile.foreign_contact.title == "Foreign Title"
    assert_profile(profile, title="Updated Title")


@pytest.mark.parametrize("protected_role", ["company_admin", "super_admin"])
def test_protected_shared_contact_rejects_profile_changes_atomically(client, profile, protected_role):
    protected = create_user(
        f"protected-{protected_role}", company=profile.own,
        role_key=protected_role, full_name=profile.contact.full_name,
        title=profile.contact.title,
    )
    protected.personnel_contact = profile.contact
    protected.email = profile.contact.email
    db.session.commit()
    before = state(profile)
    protected_before = (protected.full_name, protected.title, protected.email, protected.role_keys.copy())
    response = client.post(f"/users/{profile.user.id}/edit", data=form(
        profile.user, full_name="Attempted Rename", title="Forbidden Title",
        email="forbidden@example.test",
    ))
    assert response.status_code == 403
    assert state(profile) == before
    assert (protected.full_name, protected.title, protected.email, protected.role_keys) == protected_before


def test_existing_foreign_personnel_link_rejects_edit_atomically(client, profile):
    profile.user.personnel_contact = profile.foreign_contact
    db.session.commit()
    before = state(profile)
    response = client.post(f"/users/{profile.user.id}/edit", data=form(
        profile.user, full_name="Attempted Rename", title="Forbidden Title",
        email="forbidden@example.test",
    ))
    assert response.status_code == 404
    assert state(profile) == before


def test_rename_updates_same_company_action_owner_but_not_foreign_action(client, profile):
    own = Action(
        company_id=profile.own.id, title="Own Action", responsible_user_id=profile.user.id,
        responsible_owner=profile.user.full_name, termin_date=date(2030, 1, 1),
    )
    foreign = Action(
        company_id=profile.other.id, title="Foreign Action", responsible_user_id=profile.user.id,
        responsible_owner="Foreign Owner", termin_date=date(2030, 1, 1),
    )
    db.session.add_all([own, foreign])
    db.session.commit()
    post_edit(client, profile, form(profile.user, full_name="Renamed Person"))
    assert own.responsible_owner == "Renamed Person"
    assert foreign.responsible_owner == "Foreign Owner"
    assert_profile(profile, name="Renamed Person")


@pytest.mark.parametrize("operation", ["create", "unlinked-edit"])
def test_matching_contact_compatibility_applies_explicit_profile_fields(client, profile, operation):
    count = PersonnelContact.query.count()
    if operation == "create":
        path = "/users/new"
        data = form(profile.user, username="new-profile-user", password="New-password-42", title="Updated Title")
    else:
        profile.user.personnel_contact = None
        db.session.commit()
        path = f"/users/{profile.user.id}/edit"
        data = form(profile.user, title="Updated Title")
    response = client.post(path, data=data)
    assert response.status_code == 302
    db.session.expire_all()
    saved = User.query.filter_by(username=data["username"], company_id=profile.own.id).one()
    assert saved.personnel_contact_id == profile.contact.id
    assert saved.title == profile.contact.title == profile.node.title == "Updated Title"
    assert PersonnelContact.query.count() == count
    assert_foreign_unchanged(profile)


@pytest.mark.parametrize("field", ["title", "email"])
def test_omitted_field_does_not_clear_legacy_user_value_when_personnel_is_empty(client, profile, field):
    setattr(profile.contact, field, None)
    if field == "title":
        profile.contact.department = None
        profile.node.title = ""
    db.session.commit()
    expected = getattr(profile.user, field)
    data = form(profile.user)
    data.pop(field)
    post_edit(client, profile, data)
    assert getattr(profile.user, field) == expected
    assert_foreign_unchanged(profile)


@pytest.mark.parametrize("field,limit", [("username", 80), ("full_name", 160), ("title", 160), ("email", 255)])
def test_oversized_profile_field_rejects_without_partial_sync(client, profile, field, limit):
    before = state(profile)
    response = client.post(f"/users/{profile.user.id}/edit", data=form(profile.user, **{field: "x" * (limit + 1)}))
    assert response.status_code == 200
    assert state(profile) == before


def test_brand_new_contact_does_not_modify_or_guard_against_unlinked_accounts(client, profile):
    unlinked_admin = create_user("unlinked-admin", company=profile.own, role_key="company_admin")
    original = (unlinked_admin.full_name, unlinked_admin.title, unlinked_admin.personnel_contact_id)
    count = PersonnelContact.query.count()
    response = client.post("/users/new", data=form(
        profile.user, username="brand-new-user", full_name="Brand New Person",
        title="New Title", email="new@example.test", password="New-password-42",
    ))
    assert response.status_code == 302
    db.session.expire_all()
    saved = User.query.filter_by(username="brand-new-user", company_id=profile.own.id).one()
    assert saved.personnel_contact_id is not None
    assert saved.title == saved.personnel_contact.title == "New Title"
    assert saved.email == saved.personnel_contact.email == "new@example.test"
    assert saved.personnel_contact.company_id == profile.own.id
    assert PersonnelContact.query.count() == count + 1
    assert (unlinked_admin.full_name, unlinked_admin.title, unlinked_admin.personnel_contact_id) == original
    assert_profile(profile)


@pytest.mark.parametrize("title,expected", [(None, "Quality"), ("", ""), ("Explicit Title", "Explicit Title")])
def test_personnel_display_title_distinguishes_explicit_clear_from_legacy_unset(title, expected):
    from app.routes import personnel_contact_display_title

    contact = PersonnelContact(company_id=1, full_name="Person", title=title, department="Quality")
    node = OrientationNode(company_id=1, node_type="person", name="Person", personnel_contact=contact)
    assert contact.display_title == expected
    assert personnel_contact_display_title(contact) == expected
    assert node.to_dict()["title"] == expected
    assert contact.department == "Quality"


def test_org_serialization_does_not_expose_foreign_linked_personnel():
    contact = PersonnelContact(company_id=2, full_name="Foreign Secret Name", title="Foreign Secret Title")
    node = OrientationNode(
        company_id=1, node_type="person", name="Own Name", title="Own Title",
        personnel_contact=contact,
    )
    serialized = node.to_dict()
    assert serialized["name"] == "Own Name"
    assert serialized["title"] == "Own Title"


LEGACY_PERMISSIONS = {
    "can_create_actions": "actions.create",
    "can_edit_actions": "actions.edit",
    "can_delete_actions": "actions.delete",
    "can_comment_assigned_actions": "actions.comment_assigned",
    "can_close_assigned_actions": "actions.request_close_assigned",
    "can_manage_users": "users.manage",
}
LEGACY_FIELDS = tuple(LEGACY_PERMISSIONS)


def test_role_form_legacy_summary_is_disabled_and_matches_effective_permissions(client, profile):
    response = client.get(f"/users/{profile.user.id}/edit")
    assert response.status_code == 200
    controls = InputValues(response.get_data(as_text=True)).controls
    assert controls["role_form_present"]["value"] == "1"
    assert "legacy_permissions_present" not in controls
    for field in LEGACY_FIELDS:
        assert "disabled" in controls[field]
        expected = profile.user.has_permission(LEGACY_PERMISSIONS[field]) or bool(getattr(profile.user, field))
        assert ("checked" in controls[field]) == expected
    assert "disabled" not in controls["is_active"]


def test_role_form_uses_validated_roles_not_forged_legacy_checkboxes(client, profile):
    viewer = Role.query.filter_by(key="viewer").one()
    post_edit(client, profile, form(
        profile.user, title="Updated Title", role_form_present="1",
        role_ids=[str(viewer.id)], **{field: "on" for field in LEGACY_FIELDS},
    ))
    assert profile.user.role_keys == {"viewer"}
    for field in LEGACY_FIELDS:
        assert getattr(profile.user, field) is False
    assert not profile.user.has_permission("users.manage")
    assert_profile(profile, title="Updated Title")


@pytest.mark.parametrize("marker,expected", [(False, True), (True, False)])
def test_legacy_permission_clearing_requires_explicit_form_marker(client, profile, marker, expected):
    actor = create_user(
        "legacy-editor", company=profile.own, permissions=("users.manage", "actions.create"),
    )
    profile.user.can_create_actions = True
    db.session.commit()
    login(client, actor)
    response = client.get(f"/users/{profile.user.id}/edit")
    assert response.status_code == 200
    controls = InputValues(response.get_data(as_text=True)).controls
    assert controls["legacy_permissions_present"]["value"] == "1"
    assert "disabled" not in controls["can_create_actions"]
    data = form(profile.user)
    if marker:
        data["legacy_permissions_present"] = "1"
    post_edit(client, profile, data)
    assert profile.user.can_create_actions is expected
    assert profile.user.role_keys == {"department_staff"}
    assert_profile(profile)


@pytest.mark.parametrize("field", LEGACY_FIELDS)
def test_authorized_legacy_permission_submission_persists(client, profile, field):
    assert profile.actor.has_permission(LEGACY_PERMISSIONS[field])
    post_edit(client, profile, form(
        profile.user, title="Updated Title", legacy_permissions_present="1", **{field: "on"},
    ))
    for permission in LEGACY_FIELDS:
        assert getattr(profile.user, permission) is (permission == field)
    assert profile.user.role_keys == {"department_staff"}
    assert_profile(profile, title="Updated Title")


@pytest.mark.parametrize("field", [field for field in LEGACY_FIELDS if field != "can_manage_users"])
def test_unheld_legacy_permission_rejects_entire_profile_edit(client, profile, field):
    actor = create_user("limited-editor", company=profile.own, permissions=("users.manage",))
    assert not actor.has_permission(LEGACY_PERMISSIONS[field])
    login(client, actor)
    # Initialize request-time legal documents before measuring mutation audits.
    assert client.get(f"/users/{profile.user.id}/edit").status_code == 200
    before = state(profile)
    audit_count = AuditLog.query.count()
    response = client.post(f"/users/{profile.user.id}/edit", data=form(
        profile.user, title="Forbidden Title", legacy_permissions_present="1", **{field: "on"},
    ))
    assert response.status_code == 403
    assert state(profile) == before
    assert AuditLog.query.count() == audit_count


@pytest.mark.parametrize("title", ["Audited Title", ""])
def test_profile_sync_audits_old_new_values_actor_and_company(client, profile, title):
    last_id = db.session.query(db.func.max(AuditLog.id)).scalar() or 0
    password = "Audited-password-42"
    post_edit(client, profile, form(
        profile.user, full_name="Audited Person", title=title,
        email="audited@example.test", password=password,
    ))
    logs = AuditLog.query.filter(AuditLog.id > last_id).order_by(AuditLog.id).all()
    assert logs
    for entity_type, record, name_field, fields in (
        ("User", profile.user, "full_name", ("full_name", "title", "email")),
        ("PersonnelContact", profile.contact, "full_name", ("full_name", "title", "email")),
        ("OrientationNode", profile.node, "name", ("name", "title")),
    ):
        updates = [
            log for log in logs if log.entity_type == entity_type
            and log.entity_id == str(record.id) and log.action == "updated"
        ]
        assert updates, entity_type
        expected_old = {name_field: "Original Person", "title": "Original Title", "email": "original@example.test"}
        expected_new = {name_field: "Audited Person", "title": title, "email": "audited@example.test"}
        for field in fields:
            changes = [
                (json.loads(log.old_values or "{}"), json.loads(log.new_values or "{}"))
                for log in updates if field in json.loads(log.new_values or "{}")
            ]
            assert changes, (entity_type, field)
            assert changes[0][0][field] == expected_old[field]
            assert changes[-1][1][field] == expected_new[field]
        for log in updates:
            assert log.user_id == profile.actor.id
            assert log.company_id == profile.own.id
    for log in logs:
        payload = f"{log.old_values or ''} {log.new_values or ''}"
        assert "password_hash" not in payload
        assert password not in payload
        assert profile.user.password_hash not in payload
        assert log.company_id != profile.other.id


@pytest.mark.parametrize("collision_active", [True, False], ids=["active", "inactive"])
def test_personnel_name_phone_collision_returns_form_and_rolls_back(client, profile, collision_active):
    collision = PersonnelContact(
        company_id=profile.own.id, full_name="Existing Person", phone=profile.contact.phone,
        title="Existing Title", email="existing@example.test", is_active=collision_active,
    )
    db.session.add(collision)
    db.session.commit()
    # Initialize request-time legal documents before measuring mutation audits.
    assert client.get(f"/users/{profile.user.id}/edit").status_code == 200
    before = state(profile)
    collision_before = (collision.full_name, collision.phone, collision.title, collision.email, collision.is_active)
    count = PersonnelContact.query.count()
    audit_count = AuditLog.query.count()
    response = client.post(f"/users/{profile.user.id}/edit", data=form(
        profile.user, full_name="Existing Person", title="Must Roll Back",
        email="rollback@example.test", password="Rollback-password-42",
    ))
    assert response.status_code == 200
    assert state(profile) == before
    assert (collision.full_name, collision.phone, collision.title, collision.email, collision.is_active) == collision_before
    assert PersonnelContact.query.count() == count
    assert AuditLog.query.count() == audit_count
    values = InputValues(response.get_data(as_text=True)).values
    assert values["full_name"] == "Existing Person"
    assert values["title"] == "Must Roll Back"
    assert values["password"] == ""
    assert client.get(f"/users/{profile.user.id}/edit").status_code == 200
    assert state(profile) == before


@pytest.mark.parametrize("distinction", ["company", "phone", "null-phone"])
def test_non_conflicting_personnel_name_keeps_original_identity(client, profile, distinction):
    company_id = profile.other.id if distinction == "company" else profile.own.id
    phone = "5559990000" if distinction == "phone" else profile.contact.phone
    if distinction == "null-phone":
        profile.contact.phone = None
        phone = None
    existing = PersonnelContact(
        company_id=company_id, full_name="Existing Person", phone=phone,
        title="Keep Existing Title", email="keep@example.test", is_active=True,
    )
    db.session.add(existing)
    db.session.commit()
    count = PersonnelContact.query.count()
    existing_id = existing.id
    post_edit(client, profile, form(profile.user, full_name="Existing Person", title="Updated Title"))
    assert_profile(profile, name="Existing Person", title="Updated Title")
    assert profile.user.personnel_contact_id != existing_id
    assert existing.full_name == "Existing Person"
    assert existing.title == "Keep Existing Title"
    assert existing.email == "keep@example.test"
    assert existing.company_id == company_id
    assert existing.phone == phone
    assert PersonnelContact.query.count() == count
    assert_foreign_unchanged(profile)
