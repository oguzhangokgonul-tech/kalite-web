from .extensions import db
from .models import User


DEFAULT_USERS = (
    {
        "username": "oguzhan",
        "full_name": "Oğuzhan Gökgönül",
        "title": "Yönetici Asistanı",
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
)


def ensure_default_users(reset_passwords=True):
    for item in DEFAULT_USERS:
        user = User.query.filter_by(username=item["username"]).first()
        if user is None:
            user = User(username=item["username"])
            db.session.add(user)

        user.full_name = item["full_name"]
        user.title = item["title"]
        user.is_active = True

        for permission, value in item["permissions"].items():
            setattr(user, permission, value)

        if reset_passwords or not user.password_hash:
            user.set_password(item["password"])

    db.session.commit()
