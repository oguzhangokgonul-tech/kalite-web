from sqlalchemy import inspect, text

from .extensions import db
from .models import MaintenanceMachine, User
from .maintenance_seed import MAINTENANCE_MACHINE_DEFAULTS


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
        if "closure_approval_requested" not in columns:
            db.session.execute(
                text(
                    "ALTER TABLE actions ADD COLUMN "
                    "closure_approval_requested BOOLEAN NOT NULL DEFAULT 0"
                )
            )
            changed = True
        if "closure_requested_at" not in columns:
            db.session.execute(text("ALTER TABLE actions ADD COLUMN closure_requested_at DATETIME"))
            changed = True
        if "closure_requested_by_user_id" not in columns:
            db.session.execute(
                text("ALTER TABLE actions ADD COLUMN closure_requested_by_user_id INTEGER")
            )
            changed = True
        if "closure_evidence_note" not in columns:
            db.session.execute(text("ALTER TABLE actions ADD COLUMN closure_evidence_note TEXT"))
            changed = True
        if "closure_file_original_name" not in columns:
            db.session.execute(
                text("ALTER TABLE actions ADD COLUMN closure_file_original_name VARCHAR(255)")
            )
            changed = True
        if "closure_file_stored_name" not in columns:
            db.session.execute(
                text("ALTER TABLE actions ADD COLUMN closure_file_stored_name VARCHAR(255)")
            )
            changed = True
        if "closure_file_mime_type" not in columns:
            db.session.execute(
                text("ALTER TABLE actions ADD COLUMN closure_file_mime_type VARCHAR(120)")
            )
            changed = True
        if "closure_rejected_at" not in columns:
            db.session.execute(text("ALTER TABLE actions ADD COLUMN closure_rejected_at DATETIME"))
            changed = True
        if "closure_rejected_by_user_id" not in columns:
            db.session.execute(
                text("ALTER TABLE actions ADD COLUMN closure_rejected_by_user_id INTEGER")
            )
            changed = True
        if "closure_rejection_reason" not in columns:
            db.session.execute(text("ALTER TABLE actions ADD COLUMN closure_rejection_reason TEXT"))
            changed = True

    if "action_closure_files" not in tables:
        db.session.execute(
            text(
                """
                CREATE TABLE action_closure_files (
                    id INTEGER NOT NULL PRIMARY KEY,
                    action_id INTEGER NOT NULL,
                    original_name VARCHAR(255) NOT NULL,
                    stored_name VARCHAR(255) NOT NULL,
                    mime_type VARCHAR(120),
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(action_id) REFERENCES actions (id)
                )
                """
            )
        )
        changed = True

    if "action_sub_tasks" not in tables:
        db.session.execute(
            text(
                """
                CREATE TABLE action_sub_tasks (
                    id INTEGER NOT NULL PRIMARY KEY,
                    parent_action_id INTEGER NOT NULL,
                    title VARCHAR(160) NOT NULL,
                    description TEXT,
                    responsible_id INTEGER,
                    related_user_1_id INTEGER,
                    related_user_2_id INTEGER,
                    due_date DATE,
                    priority VARCHAR(40) NOT NULL DEFAULT 'Orta',
                    status VARCHAR(40) NOT NULL DEFAULT 'Beklemede',
                    evidence_required BOOLEAN NOT NULL DEFAULT 0,
                    evidence_original_name VARCHAR(255),
                    evidence_stored_name VARCHAR(255),
                    evidence_mime_type VARCHAR(120),
                    closing_note TEXT,
                    completed_at DATETIME,
                    completed_by_user_id INTEGER,
                    created_by_user_id INTEGER,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(parent_action_id) REFERENCES actions (id),
                    FOREIGN KEY(responsible_id) REFERENCES users (id),
                    FOREIGN KEY(related_user_1_id) REFERENCES users (id),
                    FOREIGN KEY(related_user_2_id) REFERENCES users (id),
                    FOREIGN KEY(completed_by_user_id) REFERENCES users (id),
                    FOREIGN KEY(created_by_user_id) REFERENCES users (id)
                )
                """
            )
        )
        changed = True
    else:
        columns = {
            column["name"] for column in inspector.get_columns("action_sub_tasks")
        }
        action_sub_task_columns = {
            "related_user_1_id": (
                "ALTER TABLE action_sub_tasks "
                "ADD COLUMN related_user_1_id INTEGER"
            ),
            "related_user_2_id": (
                "ALTER TABLE action_sub_tasks "
                "ADD COLUMN related_user_2_id INTEGER"
            ),
        }
        for column_name, statement in action_sub_task_columns.items():
            if column_name not in columns:
                db.session.execute(text(statement))
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

    if "dofs" in tables:
        columns = {column["name"] for column in inspector.get_columns("dofs")}
        if "approval_step" not in columns:
            db.session.execute(
                text(
                    "ALTER TABLE dofs "
                    "ADD COLUMN approval_step VARCHAR(40) NOT NULL DEFAULT 'draft'"
                )
            )
            changed = True
        if "management_approved_by_user_id" not in columns:
            db.session.execute(
                text("ALTER TABLE dofs ADD COLUMN management_approved_by_user_id INTEGER")
            )
            changed = True
        if "management_approved_at" not in columns:
            db.session.execute(text("ALTER TABLE dofs ADD COLUMN management_approved_at DATETIME"))
            changed = True
        if "deputy_approved_by_user_id" not in columns:
            db.session.execute(
                text("ALTER TABLE dofs ADD COLUMN deputy_approved_by_user_id INTEGER")
            )
            changed = True
        if "deputy_approved_at" not in columns:
            db.session.execute(text("ALTER TABLE dofs ADD COLUMN deputy_approved_at DATETIME"))
            changed = True
        if "completed_at" not in columns:
            db.session.execute(text("ALTER TABLE dofs ADD COLUMN completed_at DATETIME"))
            changed = True

    if changed:
        db.session.commit()

    tables = set(inspect(db.engine).get_table_names())
    if "actions" in tables and "action_closure_files" in tables:
        columns = {
            column["name"] for column in inspect(db.engine).get_columns("actions")
        }
        if {
            "closure_file_original_name",
            "closure_file_stored_name",
            "closure_file_mime_type",
        }.issubset(columns):
            db.session.execute(
                text(
                    """
                    INSERT INTO action_closure_files
                        (action_id, original_name, stored_name, mime_type, created_at)
                    SELECT
                        id,
                        closure_file_original_name,
                        closure_file_stored_name,
                        closure_file_mime_type,
                        CURRENT_TIMESTAMP
                    FROM actions
                    WHERE closure_file_stored_name IS NOT NULL
                      AND closure_file_original_name IS NOT NULL
                      AND NOT EXISTS (
                          SELECT 1
                          FROM action_closure_files
                          WHERE action_closure_files.action_id = actions.id
                            AND action_closure_files.stored_name = actions.closure_file_stored_name
                      )
                    """
                )
            )
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

    tables = set(inspect(db.engine).get_table_names())
    if "dofs" in tables:
        columns = {
            column["name"] for column in inspect(db.engine).get_columns("dofs")
        }
        if {"approval_step", "status"}.issubset(columns):
            db.session.execute(
                text(
                    """
                    UPDATE dofs
                    SET approval_step = 'management_representative',
                        status = 'Onay Akışı Bekleniyor'
                    WHERE status IS NOT NULL
                      AND status != 'Taslak'
                      AND (approval_step IS NULL OR approval_step = 'draft')
                    """
                )
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


def ensure_default_maintenance_machines():
    from .routes import ensure_maintenance_schema

    ensure_maintenance_schema()
    changed = False
    for item in MAINTENANCE_MACHINE_DEFAULTS:
        code = item["code"]
        machine = MaintenanceMachine.query.filter_by(code=code).first()
        if machine is None:
            machine = MaintenanceMachine(code=code)
            db.session.add(machine)
            changed = True

        for key in ("machine_name", "brand_model", "serial_no", "status", "location"):
            value = item.get(key) or None
            if key == "status":
                value = item.get(key) or "ÇALIŞIYOR"
            if getattr(machine, key) != value:
                setattr(machine, key, value)
                changed = True
        if not machine.is_active:
            machine.is_active = True
            changed = True

    if changed:
        db.session.commit()
