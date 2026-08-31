from pathlib import Path
import sqlite3

import pytest
from sqlalchemy import text

from app import create_app
from app.extensions import db
from app.models import OrientationNode, PersonnelContact, User, UserPermission
from app.routes import sync_personnel_contact_dependents


@pytest.fixture()
def app(tmp_path):
    class TestConfig:
        SECRET_KEY = "test"
        SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        WTF_CSRF_ENABLED = False
        UPLOAD_FOLDER = str(Path(tmp_path) / "uploads")
        TENANT_BASE_DOMAIN = "volkaportal.com"

    test_app = create_app(TestConfig)
    with test_app.app_context():
        db.create_all()
        yield test_app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


def create_user(username="admin", *, can_manage=False):
    user = User(
        username=username,
        full_name=username.title(),
        password_hash="not-used",
        is_active=True,
    )
    if can_manage:
        user.extra_permissions.append(UserPermission(permission_key="users.manage"))
    db.session.add(user)
    db.session.commit()
    return user


def login(client, user):
    with client.session_transaction() as session:
        session["user_id"] = user.id


def test_organization_page_renders_personnel_selector(app, client):
    user = create_user(can_manage=True)
    db.session.add(
        PersonnelContact(
            full_name="Ayşe Test",
            title="Kalite Personeli",
            is_active=True,
        )
    )
    db.session.commit()

    login(client, user)
    response = client.get("/organization")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "org-personnel-contact" in body
    assert "Ay\\u015fe Test" in body or "Ayşe Test" in body


def test_organization_personnel_link_crud_and_sync(app, client):
    user = create_user(can_manage=True)
    contact = PersonnelContact(
        full_name="Turgut Özal Pekyılmaz",
        title="Genel Müdür",
        is_active=True,
    )
    db.session.add(contact)
    db.session.commit()

    login(client, user)
    create_response = client.post(
        "/orientation/nodes",
        json={
            "node_type": "person",
            "personnel_contact_id": contact.id,
            "x": 120,
            "y": 80,
        },
    )

    assert create_response.status_code == 200
    created_node = create_response.get_json()["node"]
    assert created_node["personnel_contact_id"] == contact.id
    assert created_node["name"] == "Turgut Özal Pekyılmaz"

    update_response = client.post(
        f"/orientation/nodes/{created_node['id']}/update",
        json={
            "node_type": "person",
            "personnel_contact_id": contact.id,
            "name": "Elle Değişmemeli",
            "title": "Elle Değişmemeli",
        },
    )

    assert update_response.status_code == 200
    updated_node = update_response.get_json()["node"]
    assert updated_node["name"] == contact.full_name
    assert updated_node["title"] == contact.title

    contact.full_name = "Turgut Ö. Pekyılmaz"
    contact.title = "Genel Müdür Yardımcısı"
    sync_personnel_contact_dependents(contact)
    db.session.commit()

    linked_node = db.session.get(OrientationNode, created_node["id"])
    assert linked_node.name == "Turgut Ö. Pekyılmaz"
    assert linked_node.title == "Genel Müdür Yardımcısı"

    delete_response = client.post(f"/orientation/nodes/{created_node['id']}/delete")
    assert delete_response.status_code == 200
    assert OrientationNode.query.count() == 0


def test_organization_edit_requires_manage_permission(app, client):
    user = create_user(can_manage=False)
    login(client, user)

    response = client.post("/orientation/nodes", json={"node_type": "person"})

    assert response.status_code == 403


def test_startup_seed_adds_personnel_columns_to_existing_database(tmp_path):
    db_path = Path(tmp_path) / "legacy.db"
    connection = sqlite3.connect(db_path)
    connection.execute(
        """
        CREATE TABLE users (
            id INTEGER NOT NULL PRIMARY KEY,
            company_id INTEGER,
            username VARCHAR(80) NOT NULL,
            full_name VARCHAR(160) NOT NULL,
            title VARCHAR(160),
            email VARCHAR(255),
            password_hash VARCHAR(255) NOT NULL,
            is_active BOOLEAN NOT NULL DEFAULT 1,
            can_create_actions BOOLEAN NOT NULL DEFAULT 0,
            can_edit_actions BOOLEAN NOT NULL DEFAULT 0,
            can_delete_actions BOOLEAN NOT NULL DEFAULT 0,
            can_comment_assigned_actions BOOLEAN NOT NULL DEFAULT 0,
            can_close_assigned_actions BOOLEAN NOT NULL DEFAULT 0,
            can_manage_users BOOLEAN NOT NULL DEFAULT 0,
            created_at DATETIME,
            updated_at DATETIME
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE orientation_nodes (
            id INTEGER NOT NULL PRIMARY KEY,
            company_id INTEGER,
            parent_id INTEGER,
            name VARCHAR(160) NOT NULL,
            title VARCHAR(160),
            node_type VARCHAR(40) NOT NULL DEFAULT 'person',
            color VARCHAR(20) NOT NULL DEFAULT '#198754',
            x INTEGER NOT NULL DEFAULT 120,
            y INTEGER NOT NULL DEFAULT 80,
            created_at DATETIME,
            updated_at DATETIME
        )
        """
    )
    connection.commit()
    connection.close()

    class LegacyConfig:
        SECRET_KEY = "test"
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{db_path.as_posix()}"
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        WTF_CSRF_ENABLED = False
        UPLOAD_FOLDER = str(Path(tmp_path) / "uploads")
        TENANT_BASE_DOMAIN = "volkaportal.com"

    legacy_app = create_app(LegacyConfig)
    with legacy_app.app_context():
        db.create_all()
        from app.seed import ensure_default_users

        ensure_default_users(reset_passwords=False)

        user_columns = {
            row[1]
            for row in db.session.execute(
                text("PRAGMA table_info(users)")
            ).fetchall()
        }
        node_columns = {
            row[1]
            for row in db.session.execute(
                text("PRAGMA table_info(orientation_nodes)")
            ).fetchall()
        }
        assert "personnel_contact_id" in user_columns
        assert "personnel_contact_id" in node_columns
        db.session.remove()
        db.engine.dispose()
