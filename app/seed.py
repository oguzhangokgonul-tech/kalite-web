from sqlalchemy import inspect, text

from .extensions import db
from .models import AppSetting, Company, MaintenanceMachine, Role, RolePermission, User
from .maintenance_seed import MAINTENANCE_MACHINE_DEFAULTS


PERMISSION_CATALOG = (
    {
        "key": "roles.manage",
        "label": "Rol ve yetki yönetimi",
        "group": "Sistem",
        "description": "Rol hiyerarşisini, rol izinlerini ve kullanıcı rol atamalarını yönetir.",
    },
    {
        "key": "users.manage",
        "label": "Kullanıcı yönetimi",
        "group": "Sistem",
        "description": "Kullanıcı hesaplarını oluşturur ve düzenler.",
        "legacy_field": "can_manage_users",
    },
    {
        "key": "users.delete",
        "label": "Kullanıcı silme",
        "group": "Sistem",
        "description": "Kullanıcılar sayfasından personel kayıtlarını sistemden kaldırır.",
    },
    {
        "key": "actions.create",
        "label": "Aksiyon açma",
        "group": "Aksiyon",
        "description": "Yeni aksiyon kaydı oluşturur.",
        "legacy_field": "can_create_actions",
    },
    {
        "key": "actions.edit",
        "label": "Aksiyon düzenleme",
        "group": "Aksiyon",
        "description": "Yetkili olduğu aksiyon kayıtlarını düzenler.",
        "legacy_field": "can_edit_actions",
    },
    {
        "key": "actions.delete",
        "label": "Aksiyon silme",
        "group": "Aksiyon",
        "description": "Aksiyon kayıtlarını silebilir.",
        "legacy_field": "can_delete_actions",
    },
    {
        "key": "actions.comment_assigned",
        "label": "Atanan aksiyona yorum",
        "group": "Aksiyon",
        "description": "Kendisine atanan veya ilgili olduğu aksiyonlara yorum yapar.",
        "legacy_field": "can_comment_assigned_actions",
    },
    {
        "key": "actions.request_close_assigned",
        "label": "Atanan aksiyonu kapanışa gönderme",
        "group": "Aksiyon",
        "description": "Kendisine atanan aksiyon için kapanış onayı ister.",
        "legacy_field": "can_close_assigned_actions",
    },
    {
        "key": "actions.approve_closure",
        "label": "Aksiyon kapanış onayı",
        "group": "Aksiyon",
        "description": "Kapanış talebi gönderilen aksiyonu onaylar veya reddeder.",
    },
    {
        "key": "actions.view_all",
        "label": "Tüm aksiyonları görme",
        "group": "Aksiyon",
        "description": "Atama kısıtı olmadan tüm aksiyonları görebilir.",
    },
    {
        "key": "if.view_all",
        "label": "Tüm IF kayıtlarını görme",
        "group": "IF Yönetimi",
        "description": "Tüm IF kayıtlarını görüntüler.",
    },
    {
        "key": "if.delete",
        "label": "IF silme",
        "group": "IF Yönetimi",
        "description": "IF kayıtlarını silebilir.",
    },
    {
        "key": "if.approve_management",
        "label": "Yönetim Temsilcisi IF onayı",
        "group": "IF Yönetimi",
        "description": "IF yönetim temsilcisi onay adımını onaylar veya reddeder.",
    },
    {
        "key": "if.approve_deputy",
        "label": "Genel Müdür Yardımcısı IF onayı",
        "group": "IF Yönetimi",
        "description": "IF final onay adımını onaylar veya reddeder.",
    },
    {
        "key": "if.reject",
        "label": "IF reddetme",
        "group": "IF Yönetimi",
        "description": "Yetkili olduğu IF onay adımında ret sebebi girer.",
    },
    {
        "key": "risk.view",
        "label": "Riskleri görüntüleme",
        "group": "Risk Yönetimi",
        "description": "Risk yönetimi kayıtlarını ve RPN özetlerini görüntüler.",
    },
    {
        "key": "risk.manage",
        "label": "Risk yönetimi",
        "group": "Risk Yönetimi",
        "description": "Risk kaydı oluşturur, düzenler ve aksiyon/IF bağlantısı kurar.",
    },
    {
        "key": "risk.delete",
        "label": "Risk silme",
        "group": "Risk Yönetimi",
        "description": "Risk kayıtlarını silebilir.",
    },
    {
        "key": "training.view",
        "label": "Eğitimleri görüntüleme",
        "group": "Eğitim / Yeterlilik",
        "description": "Atanan eğitimleri, doküman okuma onaylarını ve yeterlilik özetlerini görüntüler.",
    },
    {
        "key": "training.manage",
        "label": "Eğitim yönetimi",
        "group": "Eğitim / Yeterlilik",
        "description": "Eğitim kaydı oluşturur, katılımcı atar ve sonuçları günceller.",
    },
    {
        "key": "training.delete",
        "label": "Eğitim silme",
        "group": "Eğitim / Yeterlilik",
        "description": "Eğitim ve yeterlilik kayıtlarını silebilir.",
    },
    {
        "key": "complaints.view",
        "label": "Şikayetleri görüntüleme",
        "group": "Öneri & Şikayet",
        "description": "Müşteri şikayet kayıtlarını, terminleri ve bağlantılı aksiyon/IF kayıtlarını görüntüler.",
    },
    {
        "key": "complaints.manage",
        "label": "Şikayet yönetimi",
        "group": "Öneri & Şikayet",
        "description": "Şikayet kaydı oluşturur, düzenler, kök neden ve düzeltici faaliyetleri yönetir.",
    },
    {
        "key": "complaints.delete",
        "label": "Şikayet silme",
        "group": "Öneri & Şikayet",
        "description": "Şikayet kayıtlarını silebilir.",
    },
    {
        "key": "internal_audit.manage",
        "label": "İç denetim yönetimi",
        "group": "İç Denetim",
        "description": "İç denetim oluşturur, düzenler, kopyalar, siler ve cevaplar.",
    },
    {
        "key": "documents.view",
        "label": "Doküman görüntüleme",
        "group": "Doküman",
        "description": "Doküman listelerini, detaylarını, indirme ve önizleme alanlarını sadece görüntüler.",
    },
    {
        "key": "documents.manage",
        "label": "Doküman yönetimi",
        "group": "Doküman",
        "description": "Doküman yükler, düzenler, arşivler ve önizleme üretir.",
    },
    {
        "key": "documents.delete",
        "label": "Doküman silme",
        "group": "Doküman",
        "description": "Doküman kayıtlarını silebilir.",
    },
    {
        "key": "maintenance.inventory_manage",
        "label": "Bakım envanteri yönetimi",
        "group": "Bakım",
        "description": "Makine envanterini oluşturur, düzenler ve arşivler.",
    },
    {
        "key": "maintenance.fault_manage",
        "label": "Bakım arıza yönetimi",
        "group": "Bakım",
        "description": "Bakım arızalarını açar, düzenler, kapatır ve takip eder.",
    },
    {
        "key": "vehicles.view",
        "label": "Araçları görüntüleme",
        "group": "Araç Yönetimi",
        "description": "Araç envanterini, sigorta/muayene takiplerini ve işlem kayıtlarını görüntüler.",
    },
    {
        "key": "vehicles.manage",
        "label": "Araç yönetimi",
        "group": "Araç Yönetimi",
        "description": "Araç ekler, düzenler, siler; işlem ve akaryakıt kayıtlarını yönetir.",
    },
    {
        "key": "calibration.manage",
        "label": "Kalibrasyon planı yönetimi",
        "group": "Kalibrasyon Planı",
        "description": "Kalibrasyon kayıtlarını ekler, düzenler ve siler.",
    },
    {
        "key": "quality.create",
        "label": "Kalite deneyi açabilme",
        "group": "Kalite Deneyleri",
        "description": "Kalite deneyleri ekranında yeni deney kaydı oluşturur.",
    },
    {
        "key": "quality.parameters_manage",
        "label": "Kalite deney parametreleri",
        "group": "Kalite Deneyleri",
        "description": "Beton deney parametrelerini ve kabul aralıklarını yönetir.",
    },
    {
        "key": "organization.manage",
        "label": "Organizasyon şeması yönetimi",
        "group": "Organizasyon",
        "description": "Organizasyon şeması kişi/departman kutularını yönetir.",
    },
)

DEFAULT_COMPANIES = (
    {
        "code": "000",
        "name": "Deneme Hesabı",
    },
    {
        "code": "001",
        "name": "Er Prefabrik",
    },
)
PRIMARY_COMPANY_CODE = "001"

ROLE_DEFINITIONS = (
    {
        "key": "super_admin",
        "name": "Süper Admin",
        "hierarchy_level": 1,
        "description": "Sistemin en yüksek rolüdür. Tüm izinlere sahiptir ve rol ataması yapabilir.",
        "permissions": [item["key"] for item in PERMISSION_CATALOG],
    },
    {
        "key": "management_representative",
        "name": "Yönetim Temsilcisi",
        "hierarchy_level": 10,
        "description": "Kalite sistemi süreçlerini, aksiyon kapanışlarını, IF yönetim onaylarını ve denetimleri yönetir.",
        "permissions": [
            "users.manage",
            "actions.create",
            "actions.edit",
            "actions.delete",
            "actions.comment_assigned",
            "actions.request_close_assigned",
            "actions.approve_closure",
            "actions.view_all",
            "if.view_all",
            "if.delete",
            "if.approve_management",
            "if.reject",
            "risk.view",
            "risk.manage",
            "risk.delete",
            "training.view",
            "training.manage",
            "training.delete",
            "complaints.view",
            "complaints.manage",
            "complaints.delete",
            "internal_audit.manage",
            "documents.manage",
            "documents.delete",
            "maintenance.inventory_manage",
            "maintenance.fault_manage",
            "vehicles.view",
            "vehicles.manage",
            "calibration.manage",
            "quality.parameters_manage",
            "organization.manage",
        ],
    },
    {
        "key": "management",
        "name": "Yönetim",
        "hierarchy_level": 20,
        "description": "Yönetim seviyesinde aksiyonları ve IF kayıtlarını görüntüler, yetkili onayları verir.",
        "permissions": [
            "if.view_all",
            "if.approve_deputy",
            "if.reject",
            "actions.view_all",
            "documents.view",
            "risk.view",
            "training.view",
            "complaints.view",
            "vehicles.view",
        ],
    },
    {
        "key": "department_manager",
        "name": "Departman Yöneticisi",
        "hierarchy_level": 30,
        "description": "Kendi departmanı ve sorumluluğundaki işler için aksiyon ve görev takibi yapar.",
        "permissions": [
            "actions.create",
            "actions.comment_assigned",
            "actions.request_close_assigned",
            "maintenance.fault_manage",
            "documents.view",
            "risk.view",
            "training.view",
            "complaints.view",
            "complaints.manage",
            "quality.create",
            "vehicles.view",
            "vehicles.manage",
        ],
    },
    {
        "key": "department_staff",
        "name": "Departman Personeli",
        "hierarchy_level": 40,
        "description": "Kendisine atanan aksiyon ve görevlerde yorum, kanıt ve kapanış talebi işlemleri yapar.",
        "permissions": [
            "actions.comment_assigned",
            "actions.request_close_assigned",
            "documents.view",
            "training.view",
            "complaints.view",
            "vehicles.view",
        ],
    },
    {
        "key": "viewer",
        "name": "Sadece Görüntüleyici",
        "hierarchy_level": 50,
        "description": "Yetkili olduğu sayfaları sadece görüntüler.",
        "permissions": [
            "documents.view",
            "training.view",
            "complaints.view",
            "vehicles.view",
        ],
    },
)

REMOVED_ROLE_MAPPINGS = {
    "executive_approver": "management",
    "module_responsible": "department_staff",
    "task_responsible": "department_staff",
    "audited_viewer": "department_staff",
}


DEFAULT_USERS = (
    {
        "username": "superadmin",
        "full_name": "Süper Admin",
        "title": "Sistem Sahibi",
        "email": "",
        "password": "0408169635",
        "roles": ("super_admin",),
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
        "username": "oguzhan",
        "full_name": "Oğuzhan Gökgönül",
        "title": "Yönetim Temsilcisi",
        "email": "oguzhangokgonul@erprefabrik.com.tr",
        "password": "kysoguzhan",
        "roles": ("management_representative",),
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
        "roles": ("department_staff",),
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
        "roles": ("department_staff",),
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
        "roles": ("department_staff",),
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

ADMIN_USERNAMES = {"superadmin"}
DEFAULT_ROLE_ASSIGNMENT_MARKER = "default_role_assignments_initialized"
LEGACY_PERMISSION_FIELD_MAP = {
    "can_create_actions": "actions.create",
    "can_edit_actions": "actions.edit",
    "can_delete_actions": "actions.delete",
    "can_comment_assigned_actions": "actions.comment_assigned",
    "can_close_assigned_actions": "actions.request_close_assigned",
    "can_manage_users": "users.manage",
}


def sync_seed_legacy_permissions(user):
    permission_keys = {
        permission.permission_key
        for role in user.roles
        for permission in role.permissions
    }
    if any(role.key == "super_admin" for role in user.roles):
        permission_keys.update(item["key"] for item in PERMISSION_CATALOG)
    for field, permission_key in LEGACY_PERMISSION_FIELD_MAP.items():
        setattr(user, field, permission_key in permission_keys)


def ensure_runtime_schema():
    inspector = inspect(db.engine)
    tables = set(inspector.get_table_names())
    changed = False

    if "users" in tables:
        columns = {column["name"] for column in inspector.get_columns("users")}
        if "email" not in columns:
            db.session.execute(text("ALTER TABLE users ADD COLUMN email VARCHAR(255)"))
            changed = True
        if "personnel_contact_id" not in columns:
            db.session.execute(
                text("ALTER TABLE users ADD COLUMN personnel_contact_id INTEGER")
            )
            changed = True
        db.session.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_users_personnel_contact_id "
                "ON users (personnel_contact_id)"
            )
        )

    if "app_settings" not in tables:
        db.session.execute(
            text(
                """
                CREATE TABLE app_settings (
                    key VARCHAR(80) NOT NULL PRIMARY KEY,
                    value VARCHAR(255) NOT NULL
                )
                """
            )
        )
        changed = True
        tables.add("app_settings")

    if "audit_logs" not in tables:
        db.session.execute(
            text(
                """
                CREATE TABLE audit_logs (
                    id INTEGER NOT NULL PRIMARY KEY,
                    company_id INTEGER,
                    user_id INTEGER,
                    entity_type VARCHAR(120) NOT NULL,
                    entity_id VARCHAR(80),
                    action VARCHAR(40) NOT NULL,
                    summary VARCHAR(255),
                    old_values TEXT,
                    new_values TEXT,
                    ip_address VARCHAR(80),
                    user_agent VARCHAR(255),
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(company_id) REFERENCES companies (id),
                    FOREIGN KEY(user_id) REFERENCES users (id)
                )
                """
            )
        )
        changed = True
        tables.add("audit_logs")

    if "audit_logs" in tables:
        for index_name, column_name in (
            ("ix_audit_logs_company_id", "company_id"),
            ("ix_audit_logs_user_id", "user_id"),
            ("ix_audit_logs_entity_type", "entity_type"),
            ("ix_audit_logs_entity_id", "entity_id"),
            ("ix_audit_logs_action", "action"),
            ("ix_audit_logs_created_at", "created_at"),
        ):
            db.session.execute(
                text(
                    f"CREATE INDEX IF NOT EXISTS {index_name} "
                    f"ON audit_logs ({column_name})"
                )
            )

    if "risk_records" not in tables:
        db.session.execute(
            text(
                """
                CREATE TABLE risk_records (
                    id INTEGER NOT NULL PRIMARY KEY,
                    company_id INTEGER,
                    risk_no VARCHAR(30) NOT NULL,
                    title VARCHAR(180) NOT NULL,
                    department VARCHAR(80),
                    process VARCHAR(160),
                    description TEXT,
                    cause TEXT,
                    consequence TEXT,
                    likelihood INTEGER NOT NULL DEFAULT 1,
                    severity INTEGER NOT NULL DEFAULT 1,
                    status VARCHAR(40) NOT NULL DEFAULT 'Açık',
                    due_date DATE,
                    owner_user_id INTEGER,
                    action_id INTEGER,
                    dof_id INTEGER,
                    created_by_user_id INTEGER,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(company_id) REFERENCES companies (id),
                    FOREIGN KEY(owner_user_id) REFERENCES users (id),
                    FOREIGN KEY(action_id) REFERENCES actions (id),
                    FOREIGN KEY(dof_id) REFERENCES dofs (id),
                    FOREIGN KEY(created_by_user_id) REFERENCES users (id)
                )
                """
            )
        )
        changed = True
        tables.add("risk_records")

    if "risk_records" in tables:
        for index_name, column_name in (
            ("ix_risk_records_company_id", "company_id"),
            ("ix_risk_records_owner_user_id", "owner_user_id"),
            ("ix_risk_records_action_id", "action_id"),
            ("ix_risk_records_dof_id", "dof_id"),
        ):
            db.session.execute(
                text(
                    f"CREATE INDEX IF NOT EXISTS {index_name} "
                    f"ON risk_records ({column_name})"
                )
            )
        db.session.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_risk_records_company_risk_no "
                "ON risk_records (company_id, risk_no)"
            )
        )

    if "training_records" not in tables:
        db.session.execute(
            text(
                """
                CREATE TABLE training_records (
                    id INTEGER NOT NULL PRIMARY KEY,
                    company_id INTEGER,
                    training_no VARCHAR(30) NOT NULL,
                    title VARCHAR(180) NOT NULL,
                    training_type VARCHAR(60) NOT NULL DEFAULT 'Eğitim',
                    description TEXT,
                    document_id INTEGER,
                    planned_date DATE,
                    due_date DATE,
                    instructor_user_id INTEGER,
                    status VARCHAR(40) NOT NULL DEFAULT 'Planlandı',
                    created_by_user_id INTEGER,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(company_id) REFERENCES companies (id),
                    FOREIGN KEY(document_id) REFERENCES documents (id),
                    FOREIGN KEY(instructor_user_id) REFERENCES users (id),
                    FOREIGN KEY(created_by_user_id) REFERENCES users (id)
                )
                """
            )
        )
        changed = True
        tables.add("training_records")

    if "training_records" in tables:
        for index_name, column_name in (
            ("ix_training_records_company_id", "company_id"),
            ("ix_training_records_document_id", "document_id"),
            ("ix_training_records_instructor_user_id", "instructor_user_id"),
        ):
            db.session.execute(
                text(
                    f"CREATE INDEX IF NOT EXISTS {index_name} "
                    f"ON training_records ({column_name})"
                )
            )
        db.session.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_training_records_company_training_no "
                "ON training_records (company_id, training_no)"
            )
        )

    if "training_participants" not in tables:
        db.session.execute(
            text(
                """
                CREATE TABLE training_participants (
                    id INTEGER NOT NULL PRIMARY KEY,
                    company_id INTEGER,
                    training_id INTEGER NOT NULL,
                    user_id INTEGER,
                    personnel_contact_id INTEGER,
                    status VARCHAR(40) NOT NULL DEFAULT 'Atandı',
                    read_confirmed_at DATETIME,
                    attended_at DATETIME,
                    score NUMERIC(5, 2),
                    notes TEXT,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(company_id) REFERENCES companies (id),
                    FOREIGN KEY(training_id) REFERENCES training_records (id),
                    FOREIGN KEY(user_id) REFERENCES users (id),
                    FOREIGN KEY(personnel_contact_id) REFERENCES personnel_contacts (id)
                )
                """
            )
        )
        changed = True
        tables.add("training_participants")

    if "training_participants" in tables:
        for index_name, column_name in (
            ("ix_training_participants_company_id", "company_id"),
            ("ix_training_participants_training_id", "training_id"),
            ("ix_training_participants_user_id", "user_id"),
            ("ix_training_participants_personnel_contact_id", "personnel_contact_id"),
        ):
            db.session.execute(
                text(
                    f"CREATE INDEX IF NOT EXISTS {index_name} "
                    f"ON training_participants ({column_name})"
                )
            )

    if "complaint_records" not in tables:
        db.session.execute(
            text(
                """
                CREATE TABLE complaint_records (
                    id INTEGER NOT NULL PRIMARY KEY,
                    company_id INTEGER,
                    complaint_no VARCHAR(30) NOT NULL,
                    customer_name VARCHAR(180) NOT NULL,
                    contact_name VARCHAR(160),
                    contact_phone VARCHAR(80),
                    department VARCHAR(80),
                    subject VARCHAR(180) NOT NULL,
                    description TEXT,
                    root_cause TEXT,
                    corrective_action TEXT,
                    closing_note TEXT,
                    received_date DATE,
                    due_date DATE,
                    closed_at DATETIME,
                    status VARCHAR(40) NOT NULL DEFAULT 'Açık',
                    priority VARCHAR(40) NOT NULL DEFAULT 'Orta',
                    responsible_user_id INTEGER,
                    action_id INTEGER,
                    dof_id INTEGER,
                    created_by_user_id INTEGER,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(company_id) REFERENCES companies (id),
                    FOREIGN KEY(responsible_user_id) REFERENCES users (id),
                    FOREIGN KEY(action_id) REFERENCES actions (id),
                    FOREIGN KEY(dof_id) REFERENCES dofs (id),
                    FOREIGN KEY(created_by_user_id) REFERENCES users (id)
                )
                """
            )
        )
        changed = True
        tables.add("complaint_records")

    if "complaint_records" in tables:
        for index_name, column_name in (
            ("ix_complaint_records_company_id", "company_id"),
            ("ix_complaint_records_responsible_user_id", "responsible_user_id"),
            ("ix_complaint_records_action_id", "action_id"),
            ("ix_complaint_records_dof_id", "dof_id"),
            ("ix_complaint_records_status", "status"),
            ("ix_complaint_records_due_date", "due_date"),
        ):
            db.session.execute(
                text(
                    f"CREATE INDEX IF NOT EXISTS {index_name} "
                    f"ON complaint_records ({column_name})"
                )
            )
        db.session.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_complaint_records_company_complaint_no "
                "ON complaint_records (company_id, complaint_no)"
            )
        )

    if "roles" not in tables:
        db.session.execute(
            text(
                """
                CREATE TABLE roles (
                    id INTEGER NOT NULL PRIMARY KEY,
                    key VARCHAR(80) NOT NULL UNIQUE,
                    name VARCHAR(160) NOT NULL,
                    description TEXT,
                    hierarchy_level INTEGER NOT NULL DEFAULT 100,
                    is_system BOOLEAN NOT NULL DEFAULT 1,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
        changed = True

    if "role_permissions" not in tables:
        db.session.execute(
            text(
                """
                CREATE TABLE role_permissions (
                    role_id INTEGER NOT NULL,
                    permission_key VARCHAR(120) NOT NULL,
                    PRIMARY KEY (role_id, permission_key),
                    FOREIGN KEY(role_id) REFERENCES roles (id)
                )
                """
            )
        )
        changed = True

    if "user_roles" not in tables:
        db.session.execute(
            text(
                """
                CREATE TABLE user_roles (
                    user_id INTEGER NOT NULL,
                    role_id INTEGER NOT NULL,
                    PRIMARY KEY (user_id, role_id),
                    FOREIGN KEY(user_id) REFERENCES users (id),
                    FOREIGN KEY(role_id) REFERENCES roles (id)
                )
                """
            )
        )
        changed = True

    if "user_permissions" not in tables:
        db.session.execute(
            text(
                """
                CREATE TABLE user_permissions (
                    user_id INTEGER NOT NULL,
                    permission_key VARCHAR(120) NOT NULL,
                    PRIMARY KEY (user_id, permission_key),
                    FOREIGN KEY(user_id) REFERENCES users (id)
                )
                """
            )
        )
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
        if "personnel_contact_id" not in columns:
            db.session.execute(
                text(
                    "ALTER TABLE orientation_nodes "
                    "ADD COLUMN personnel_contact_id INTEGER"
                )
            )
            changed = True
        db.session.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_orientation_nodes_personnel_contact_id "
                "ON orientation_nodes (personnel_contact_id)"
            )
        )

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

    tables = set(inspect(db.engine).get_table_names())
    if "app_settings" in tables:
        for readiness_key in (
            "sales_readiness:audit_log",
            "sales_readiness:iso_dashboard",
            "sales_readiness:risk_module",
            "sales_readiness:training_module",
            "sales_readiness:complaint_module",
            "sales_readiness:month3_complaints",
        ):
            db.session.execute(
                text(
                    "INSERT OR IGNORE INTO app_settings (key, value) "
                    "VALUES (:key, '1')"
                ),
                {"key": readiness_key},
            )
        db.session.commit()


def ensure_default_companies():
    for item in DEFAULT_COMPANIES:
        company = Company.query.filter_by(code=item["code"]).first()
        if company is None:
            company = Company(code=item["code"])
            db.session.add(company)
        company.name = item["name"]
        company.is_active = True
    db.session.flush()


def ensure_default_users(reset_passwords=True):
    ensure_runtime_schema()
    ensure_default_companies()
    primary_company = Company.query.filter_by(code=PRIMARY_COMPANY_CODE).first()
    from .company_onboarding import initialize_company_workspace

    for company in Company.query.filter_by(is_active=True).all():
        initialize_company_workspace(company)
    db.session.flush()

    user_columns = {
        column["name"] for column in inspect(db.engine).get_columns("users")
    }
    users_have_company_id = "company_id" in user_columns
    role_by_key = ensure_default_roles()
    role_assignments_initialized = (
        db.session.get(AppSetting, DEFAULT_ROLE_ASSIGNMENT_MARKER) is not None
    )

    for item in DEFAULT_USERS:
        user_query = User.query.filter_by(username=item["username"])
        if users_have_company_id:
            if item["username"] in ADMIN_USERNAMES:
                user_query = user_query.filter(User.company_id.is_(None))
            elif primary_company is not None:
                user_query = user_query.filter_by(company_id=primary_company.id)
        user = user_query.first()
        is_new_user = user is None
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
        elif user.username == "oguzhan":
            user.title = item["title"]

        if user.username in ADMIN_USERNAMES:
            if users_have_company_id:
                user.company_id = None
            user.is_active = True
            for permission, value in item["permissions"].items():
                if value:
                    setattr(user, permission, True)
        elif (
            users_have_company_id
            and primary_company is not None
            and user.company_id is None
        ):
            user.company_id = primary_company.id

        item_roles = item.get("roles") or ()
        should_apply_default_roles = (
            is_new_user
            or user.username in ADMIN_USERNAMES
            or (not role_assignments_initialized and not user.roles)
        )
        if should_apply_default_roles:
            for role_key in item_roles:
                role = role_by_key.get(role_key)
                if role and role not in user.roles:
                    user.roles.append(role)
            sync_seed_legacy_permissions(user)

        if reset_passwords and not user.password_hash:
            user.set_password(item["password"])

    if not role_assignments_initialized:
        db.session.add(AppSetting(key=DEFAULT_ROLE_ASSIGNMENT_MARKER, value="1"))

    db.session.commit()


def ensure_default_roles():
    role_by_key = {}
    active_role_keys = {definition["key"] for definition in ROLE_DEFINITIONS}
    for definition in ROLE_DEFINITIONS:
        role = Role.query.filter_by(key=definition["key"]).first()
        is_new_role = role is None
        if role is None:
            role = Role(key=definition["key"])
            db.session.add(role)
        role.name = definition["name"]
        role.description = definition.get("description")
        role.hierarchy_level = definition["hierarchy_level"]
        role.is_system = True

        existing_permissions = {item.permission_key: item for item in role.permissions}
        desired_permissions = set(definition.get("permissions") or ())
        if is_new_role or role.key == "super_admin":
            for permission_key in desired_permissions:
                if permission_key not in existing_permissions:
                    role.permissions.append(RolePermission(permission_key=permission_key))
            for permission in list(role.permissions):
                if permission.permission_key not in desired_permissions:
                    role.permissions.remove(permission)
        role_by_key[role.key] = role

    db.session.flush()
    for old_role_key, new_role_key in REMOVED_ROLE_MAPPINGS.items():
        old_role = Role.query.filter_by(key=old_role_key).first()
        new_role = role_by_key.get(new_role_key)
        if old_role is None:
            continue
        if new_role is not None:
            for user in list(old_role.users):
                if new_role not in user.roles:
                    user.roles.append(new_role)
                if old_role in user.roles:
                    user.roles.remove(old_role)
        old_role.is_system = False

    for role in Role.query.all():
        if role.key not in active_role_keys and role.key not in REMOVED_ROLE_MAPPINGS:
            role.is_system = False

    db.session.flush()
    return role_by_key


def ensure_default_maintenance_machines():
    from .routes import ensure_maintenance_schema

    ensure_maintenance_schema()
    changed = False
    for item in MAINTENANCE_MACHINE_DEFAULTS:
        code = item["code"]
        machine = MaintenanceMachine.query.filter_by(code=code).first()
        if machine is None:
            machine = MaintenanceMachine(
                code=code,
                machine_name=item["machine_name"],
                brand_model=item.get("brand_model") or None,
                serial_no=item.get("serial_no") or None,
                status=item.get("status") or "ÇALIŞIYOR",
                location=item.get("location") or None,
                is_active=True,
            )
            db.session.add(machine)
            changed = True
            continue

        for key in ("machine_name", "brand_model", "serial_no", "status", "location"):
            if getattr(machine, key):
                continue
            value = item.get(key) or None
            if key == "status":
                value = item.get(key) or "ÇALIŞIYOR"
            if value:
                setattr(machine, key, value)
                changed = True

    if changed:
        db.session.commit()
