from sqlalchemy import inspect, text

from .extensions import db
from .models import User


DEFAULT_USERS = (
    {
        "username": "oguzhan",
        "full_name": "Oğuzhan Gökgönül",
        "title": "Yönetici Asistanı",
        "email": "oguzhangokgonul@erprefabrik.com.tr",
        "password": "kysoguzhan",
        "permissions": {
            "can_create_actions": True,
            "can_edit_actions": True,
            "can_delete_actions": True,
            "can_comment_assigned_actions": True,
            "can_close_assigned_actions": True,
            "can_manage_users": True,
        },
    },
    {
        "username": "ufuk",
        "full_name": "Ufuk Yaşayan",
        "title": "Prefabrik Proje Müdürü",
        "email": "",
        "password": "kysufuk",
        "permissions": {
            "can_create_actions": False,
            "can_edit_actions": False,
            "can_delete_actions": False,
            "can_comment_assigned_actions": True,
            "can_close_assigned_actions": True,
            "can_manage_users": False,
        },
    },
    {
        "username": "seyma",
        "full_name": "Şeyma İnci Göçmen",
        "title": "Proje Sorumlusu",
        "email": "seymainci@erprefabrik.com.tr",
        "password": "kysseyma",
        "permissions": {
            "can_create_actions": False,
            "can_edit_actions": False,
            "can_delete_actions": False,
            "can_comment_assigned_actions": True,
            "can_close_assigned_actions": True,
            "can_manage_users": False,
        },
    },
    {
        "username": "turgut",
        "full_name": "Turgut Özal Pekyılmaz",
        "title": "Şantiye Peygamberi",
        "email": "turgutpekyilmaz@erprefabrik.com.tr",
        "password": "kysturgut",
        "permissions": {
            "can_create_actions": False,
            "can_edit_actions": False,
            "can_delete_actions": False,
            "can_comment_assigned_actions": True,
            "can_close_assigned_actions": True,
            "can_manage_users": False,
        },
    },
)

ADMIN_USERNAMES = {"oguzhan"}


def ensure_runtime_schema():
    inspector = inspect(db.engine)
    tables = set(inspector.get_table_names())
    changed = False

    if "users" in tables:
        columns = {column["name"] for column in inspector.get_columns("users")}
        if "email" not in columns:
            db.session.execute(text("ALTER TABLE users ADD COLUMN email VARCHAR(255)"))
            changed = True

    if "actions" in tables:
        columns = {column["name"] for column in inspector.get_columns("actions")}
        if "action_number" not in columns:
            db.session.execute(text("ALTER TABLE actions ADD COLUMN action_number INTEGER"))
            changed = True
        if "related_user_1_id" not in columns:
            db.session.execute(
                text("ALTER TABLE actions ADD COLUMN related_user_1_id INTEGER")
            )
            changed = True
        if "related_user_2_id" not in columns:
            db.session.execute(
                text("ALTER TABLE actions ADD COLUMN related_user_2_id INTEGER")
            )
            changed = True

    if "orientation_nodes" in tables:
        columns = {
            column["name"] for column in inspector.get_columns("orientation_nodes")
        }
        if "node_type" not in columns:
            db.session.execute(
                text(
                    "ALTER TABLE orientation_nodes "
                    "ADD COLUMN node_type VARCHAR(40) NOT NULL DEFAULT 'person'"
                )
            )
            changed = True
        if "color" not in columns:
            db.session.execute(
                text(
                    "ALTER TABLE orientation_nodes "
                    "ADD COLUMN color VARCHAR(20) NOT NULL DEFAULT '#198754'"
                )
            )
            changed = True

    if changed:
        db.session.commit()

    tables = set(inspect(db.engine).get_table_names())
    if "orientation_nodes" in tables:
        columns = {
            column["name"] for column in inspect(db.engine).get_columns("orientation_nodes")
        }
        if "node_type" in columns:
            db.session.execute(
                text(
                    "UPDATE orientation_nodes SET node_type = 'person' "
                    "WHERE node_type IS NULL OR node_type = ''"
                )
            )
            db.session.commit()
        if "color" in columns:
            db.session.execute(
                text(
                    "UPDATE orientation_nodes SET color = '#198754' "
                    "WHERE color IS NULL OR color = ''"
                )
            )
            db.session.commit()

    tables = set(inspect(db.engine).get_table_names())
    if "actions" in tables:
        columns = {
            column["name"] for column in inspect(db.engine).get_columns("actions")
        }
        if "action_number" in columns:
            db.session.execute(
                text("UPDATE actions SET action_number = id WHERE action_number IS NULL")
            )
            db.session.commit()

    tables = set(inspect(db.engine).get_table_names())
    if "actions" in tables and "app_settings" in tables:
        max_number = db.session.execute(
            text("SELECT COALESCE(MAX(COALESCE(action_number, id)), 0) FROM actions")
        ).scalar()
        next_number = max_number + 1
        current_value = db.session.execute(
            text("SELECT value FROM app_settings WHERE key = 'next_action_number'")
        ).scalar()
        if current_value is None:
            db.session.execute(
                text(
                    "INSERT INTO app_settings (key, value) "
                    "VALUES ('next_action_number', :value)"
                ),
                {"value": str(next_number)},
            )
            db.session.commit()
        elif int(current_value) <= max_number:
            db.session.execute(
                text(
                    "UPDATE app_settings SET value = :value "
                    "WHERE key = 'next_action_number'"
                ),
                {"value": str(next_number)},
            )
            db.session.commit()


def ensure_default_users(reset_passwords=True):
    ensure_runtime_schema()

    for item in DEFAULT_USERS:
        user = User.query.filter_by(username=item["username"]).first()
        if user is None:
            user = User(username=item["username"])
            db.session.add(user)
            user.full_name = item["full_name"]
            user.title = item["title"]
            user.email = item["email"]
            user.is_active = True

            for permission, value in item["permissions"].items():
                setattr(user, permission, value)

            user.set_password(item["password"])
            continue

        if user.username in ADMIN_USERNAMES:
            user.is_active = True
            for permission, value in item["permissions"].items():
                if value:
                    setattr(user, permission, True)

        if reset_passwords and not user.password_hash:
            user.set_password(item["password"])

    db.session.commit()
