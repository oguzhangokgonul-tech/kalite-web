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

USER_EMAILS = {
    "oguzhan": "oguzhangokgonul@erprefabrik.com.tr",
    "seyma": "seymainci@erprefabrik.com.tr",
    "turgut": "turgutpekyilmaz@erprefabrik.com.tr",
}


def ensure_runtime_schema():
    inspector = inspect(db.engine)
    if "users" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("users")}
    if "email" not in columns:
        db.session.execute(text("ALTER TABLE users ADD COLUMN email VARCHAR(255)"))
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

        if reset_passwords or not user.password_hash:
            user.set_password(item["password"])

    for username, email in USER_EMAILS.items():
        user = User.query.filter_by(username=username).first()
        if user is not None:
            user.email = email

    db.session.commit()
