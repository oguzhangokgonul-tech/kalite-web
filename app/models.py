from datetime import date, timedelta

from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db


user_roles = db.Table(
    "user_roles",
    db.Column("user_id", db.Integer, db.ForeignKey("users.id"), primary_key=True),
    db.Column("role_id", db.Integer, db.ForeignKey("roles.id"), primary_key=True),
)


DEPARTMENTS = (
    "Üretim",
    "Kalite",
    "Kalite Yönetim",
    "Kalite Yönetim Departmanı",
    "Yönetim",
    "Bakım",
    "Finans",
    "Muhasebe",
    "Satın alma",
    "Depo",
    "İnsan Kaynakları",
    "Şantiye",
    "Montaj",
    "Proje",
    "Teklif",
)

ORGANIZATION_NODE_TYPES = ("person", "department")
ACTION_SUB_TASK_STATUSES = ("Beklemede", "Devam Ediyor", "Tamamlandı", "İptal Edildi")
ACTION_SUB_TASK_PRIORITIES = ("Düşük", "Orta", "Yüksek", "Kritik")

MAINTENANCE_MACHINE_STATUSES = ("ÇALIŞIYOR", "ARIZALI", "HURDA", "PASİF")
MAINTENANCE_FAULT_STATUSES = ("Açık", "İşlemde", "Tamamlandı", "İptal Edildi")
MAINTENANCE_FAULT_PRIORITIES = ("Düşük", "Orta", "Yüksek", "Kritik")
QUALITY_TEST_STATUSES = ("Kayıtlı", "Devam Ediyor", "Tamamlandı", "İptal Edildi")
QUALITY_TEST_PREFIXES = {
    "beton-deneyi": "BET",
    "metilen-deneyi": "MET",
    "su-emme-deneyi": "SUE",
    "elek-analizi-deneyi": "ELE",
    "demir-cekme-deneyi": "DEM",
}

DOF_PRIORITIES = ("Düşük", "Orta", "Yüksek", "Kritik")
DOF_SOURCES = (
    "İç Denetim",
    "Müşteri Şikayeti",
    "Tedarikçi",
    "Üretim",
    "Kalite Kontrol",
    "Saha",
    "Yönetim Gözden Geçirme",
    "Diğer",
)
DOF_STATUSES = ("Taslak", "Onay Akışı Bekleniyor", "Revizyon Bekleniyor", "Tamamlandı")
DOF_APPROVAL_STEPS = (
    "draft",
    "management_representative",
    "general_manager_deputy",
    "revision_requested",
    "completed",
)

DOCUMENT_STATUSES = (
    "Yayında",
    "Revizyon Bekleyen",
    "Onay Bekleyen",
    "Arşiv",
    "İptal",
)

DOCUMENT_CATEGORY_DEFAULTS = (
    {
        "code": "01",
        "name": "Kalite El Kitabı",
        "slug": "kalite-el-kitabi",
        "sort_order": 1,
        "color": "blue",
        "icon": "folder",
    },
    {
        "code": "02",
        "name": "Prosesler",
        "slug": "prosesler",
        "sort_order": 2,
        "color": "green",
        "icon": "folder",
    },
    {
        "code": "03",
        "name": "Prosedürler",
        "slug": "prosedurler",
        "sort_order": 3,
        "color": "orange",
        "icon": "folder",
    },
    {
        "code": "04",
        "name": "Talimatlar",
        "slug": "talimatlar",
        "sort_order": 4,
        "color": "red",
        "icon": "folder",
    },
    {
        "code": "05",
        "name": "Formlar",
        "slug": "formlar",
        "sort_order": 5,
        "color": "purple",
        "icon": "file-earmark-text",
    },
    {
        "code": "06",
        "name": "Listeler",
        "slug": "listeler",
        "sort_order": 6,
        "color": "cyan",
        "icon": "file-earmark-spreadsheet",
    },
    {
        "code": "07",
        "name": "Planlar",
        "slug": "planlar",
        "sort_order": 7,
        "color": "lime",
        "icon": "calendar-check",
    },
    {
        "code": "08",
        "name": "Görev Tanımları",
        "slug": "gorev-tanimlari",
        "sort_order": 8,
        "color": "amber",
        "icon": "people",
    },
)


class Role(db.Model):
    __tablename__ = "roles"

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(80), nullable=False, unique=True)
    name = db.Column(db.String(160), nullable=False)
    description = db.Column(db.Text, nullable=True)
    hierarchy_level = db.Column(db.Integer, nullable=False, default=100)
    is_system = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        server_default=db.func.now(),
        onupdate=db.func.now(),
    )

    users = db.relationship(
        "User",
        secondary=user_roles,
        back_populates="roles",
        lazy="selectin",
    )
    permissions = db.relationship(
        "RolePermission",
        back_populates="role",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    @property
    def permission_keys(self):
        return {permission.permission_key for permission in self.permissions}


class RolePermission(db.Model):
    __tablename__ = "role_permissions"
    __table_args__ = {"extend_existing": True}

    role_id = db.Column(db.Integer, db.ForeignKey("roles.id"), primary_key=True)
    permission_key = db.Column(db.String(120), primary_key=True)

    role = db.relationship("Role", back_populates="permissions")


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), nullable=False, unique=True)
    full_name = db.Column(db.String(160), nullable=False)
    title = db.Column(db.String(160), nullable=True)
    email = db.Column(db.String(255), nullable=True)
    password_hash = db.Column(db.String(255), nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    can_create_actions = db.Column(db.Boolean, nullable=False, default=False)
    can_edit_actions = db.Column(db.Boolean, nullable=False, default=False)
    can_delete_actions = db.Column(db.Boolean, nullable=False, default=False)
    can_comment_assigned_actions = db.Column(db.Boolean, nullable=False, default=False)
    can_close_assigned_actions = db.Column(db.Boolean, nullable=False, default=False)
    can_manage_users = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        server_default=db.func.now(),
        onupdate=db.func.now(),
    )

    assigned_actions = db.relationship(
        "Action",
        back_populates="responsible_user",
        foreign_keys="Action.responsible_user_id",
    )
    roles = db.relationship(
        "Role",
        secondary=user_roles,
        back_populates="users",
        lazy="selectin",
    )

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def role_keys(self):
        return {role.key for role in self.roles}

    @property
    def role_names(self):
        return [
            role.name
            for role in sorted(self.roles, key=lambda item: item.hierarchy_level)
        ]

    def has_role(self, role_key):
        return role_key in self.role_keys

    def has_permission(self, permission_key):
        if self.has_role("super_admin"):
            return True
        return any(permission_key in role.permission_keys for role in self.roles)


class Action(db.Model):
    __tablename__ = "actions"

    id = db.Column(db.Integer, primary_key=True)
    action_number = db.Column(db.Integer, nullable=True, unique=True)
    title = db.Column(db.String(160), nullable=False)
    responsible_owner = db.Column(db.String(120), nullable=False)
    responsible_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    related_user_1_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    related_user_2_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    department = db.Column(db.String(80), nullable=False, default="Kalite")
    description = db.Column(db.Text, nullable=True)
    termin_date = db.Column(db.Date, nullable=False)
    is_completed = db.Column(db.Boolean, nullable=False, default=False)
    completed_at = db.Column(db.Date, nullable=True)
    delay_days = db.Column(db.Integer, nullable=False, default=0)
    file_original_name = db.Column(db.String(255), nullable=True)
    file_stored_name = db.Column(db.String(255), nullable=True)
    file_mime_type = db.Column(db.String(120), nullable=True)
    closure_approval_requested = db.Column(db.Boolean, nullable=False, default=False)
    closure_requested_at = db.Column(db.DateTime, nullable=True)
    closure_requested_by_user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id"),
        nullable=True,
    )
    closure_evidence_note = db.Column(db.Text, nullable=True)
    closure_file_original_name = db.Column(db.String(255), nullable=True)
    closure_file_stored_name = db.Column(db.String(255), nullable=True)
    closure_file_mime_type = db.Column(db.String(120), nullable=True)
    closure_rejected_at = db.Column(db.DateTime, nullable=True)
    closure_rejected_by_user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id"),
        nullable=True,
    )
    closure_rejection_reason = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        server_default=db.func.now(),
        onupdate=db.func.now(),
    )

    responsible_user = db.relationship(
        "User",
        back_populates="assigned_actions",
        foreign_keys=[responsible_user_id],
    )
    related_user_1 = db.relationship("User", foreign_keys=[related_user_1_id])
    related_user_2 = db.relationship("User", foreign_keys=[related_user_2_id])
    closure_requested_by = db.relationship(
        "User",
        foreign_keys=[closure_requested_by_user_id],
    )
    closure_rejected_by = db.relationship(
        "User",
        foreign_keys=[closure_rejected_by_user_id],
    )
    closure_files = db.relationship(
        "ActionClosureFile",
        back_populates="action",
        cascade="all, delete-orphan",
        order_by="ActionClosureFile.created_at.asc()",
    )
    sub_actions = db.relationship(
        "ActionSubTask",
        back_populates="parent_action",
        cascade="all, delete-orphan",
        order_by="ActionSubTask.created_at.asc()",
    )
    comments = db.relationship(
        "ActionComment",
        back_populates="action",
        cascade="all, delete-orphan",
        order_by="ActionComment.created_at.asc()",
    )
    histories = db.relationship(
        "ActionHistory",
        back_populates="action",
        cascade="all, delete-orphan",
        order_by="ActionHistory.created_at.asc()",
    )
    notifications = db.relationship(
        "Notification",
        back_populates="action",
        cascade="all, delete-orphan",
    )

    def participant_user_ids(self):
        return {
            user_id
            for user_id in (
                self.responsible_user_id,
                self.related_user_1_id,
                self.related_user_2_id,
            )
            if user_id
        }

    @property
    def number_label(self):
        return f"#{self.action_number or self.id}"

    def calculate_delay_days(self, today=None):
        if self.is_completed:
            return 0

        today = today or date.today()
        return max((today - self.termin_date).days, 0)

    def refresh_delay(self, today=None):
        self.delay_days = self.calculate_delay_days(today)

    @property
    def sub_action_total(self):
        return len(self.sub_actions)

    @property
    def sub_action_completed_count(self):
        return sum(1 for item in self.sub_actions if item.status == "Tamamlandı")

    @property
    def sub_action_waiting_count(self):
        return sum(1 for item in self.sub_actions if item.status == "Beklemede")

    @property
    def sub_action_active_count(self):
        return sum(1 for item in self.sub_actions if item.status == "Devam Ediyor")

    @property
    def sub_action_cancelled_count(self):
        return sum(1 for item in self.sub_actions if item.status == "İptal Edildi")

    @property
    def sub_action_progress_percent(self):
        relevant_items = [
            item for item in self.sub_actions if item.status != "İptal Edildi"
        ]
        if not relevant_items:
            return 0
        completed = sum(1 for item in relevant_items if item.status == "Tamamlandı")
        return int(round((completed / len(relevant_items)) * 100))

    @property
    def has_open_sub_actions(self):
        return any(
            item.status not in {"Tamamlandı", "İptal Edildi"}
            for item in self.sub_actions
        )

    def mark_completed(self, today=None):
        self.is_completed = True
        self.completed_at = today or date.today()
        self.delay_days = 0
        self.closure_approval_requested = False
        self.closure_rejected_at = None
        self.closure_rejected_by_user_id = None
        self.closure_rejection_reason = None


class Dof(db.Model):
    __tablename__ = "dofs"

    id = db.Column(db.Integer, primary_key=True)
    dof_no = db.Column(db.String(30), nullable=False, unique=True)
    title = db.Column(db.String(160), nullable=True)
    department = db.Column(db.String(80), nullable=True)
    responsible_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    opening_date = db.Column(db.Date, nullable=True)
    due_date = db.Column(db.Date, nullable=True)
    priority = db.Column(db.String(40), nullable=True)
    source = db.Column(db.String(120), nullable=True)
    nonconformity_description = db.Column(db.Text, nullable=True)
    root_cause_analysis = db.Column(db.Text, nullable=True)
    corrective_action = db.Column(db.Text, nullable=True)
    preventive_action = db.Column(db.Text, nullable=True)
    closing_evidence = db.Column(db.Text, nullable=True)
    evidence_original_name = db.Column(db.String(255), nullable=True)
    evidence_stored_name = db.Column(db.String(255), nullable=True)
    evidence_mime_type = db.Column(db.String(120), nullable=True)
    rejection_reason = db.Column(db.Text, nullable=True)
    rejected_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    rejected_at = db.Column(db.DateTime, nullable=True)
    rejected_step = db.Column(db.String(40), nullable=True)
    status = db.Column(db.String(40), nullable=False, default="Taslak")
    approval_step = db.Column(db.String(40), nullable=False, default="draft")
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    management_approved_by_user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id"),
        nullable=True,
    )
    management_approved_at = db.Column(db.DateTime, nullable=True)
    deputy_approved_by_user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id"),
        nullable=True,
    )
    deputy_approved_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        server_default=db.func.now(),
        onupdate=db.func.now(),
    )

    responsible = db.relationship("User", foreign_keys=[responsible_id])
    created_by = db.relationship("User", foreign_keys=[created_by_user_id])
    management_approved_by = db.relationship(
        "User",
        foreign_keys=[management_approved_by_user_id],
    )
    deputy_approved_by = db.relationship(
        "User",
        foreign_keys=[deputy_approved_by_user_id],
    )
    rejected_by = db.relationship("User", foreign_keys=[rejected_by_user_id])
    notifications = db.relationship(
        "Notification",
        back_populates="dof",
        cascade="all, delete-orphan",
    )
    comments = db.relationship(
        "DofComment",
        back_populates="dof",
        cascade="all, delete-orphan",
        order_by="DofComment.created_at.asc()",
    )
    files = db.relationship(
        "DofFile",
        back_populates="dof",
        cascade="all, delete-orphan",
        order_by="DofFile.created_at.asc()",
    )


class DofFile(db.Model):
    __tablename__ = "dof_files"

    id = db.Column(db.Integer, primary_key=True)
    dof_id = db.Column(db.Integer, db.ForeignKey("dofs.id"), nullable=False)
    original_name = db.Column(db.String(255), nullable=False)
    stored_name = db.Column(db.String(255), nullable=False)
    mime_type = db.Column(db.String(120), nullable=True)
    file_type = db.Column(db.String(40), nullable=False, default="opening")
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())

    dof = db.relationship("Dof", back_populates="files")


class DofComment(db.Model):
    __tablename__ = "dof_comments"

    id = db.Column(db.Integer, primary_key=True)
    dof_id = db.Column(db.Integer, db.ForeignKey("dofs.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    comment = db.Column(db.Text, nullable=False)
    comment_type = db.Column(db.String(40), nullable=False, default="note")
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())

    dof = db.relationship("Dof", back_populates="comments")
    user = db.relationship("User")


class DocumentCategory(db.Model):
    __tablename__ = "document_categories"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(10), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    slug = db.Column(db.String(160), nullable=False, unique=True)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    color = db.Column(db.String(40), nullable=True)
    icon = db.Column(db.String(80), nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        server_default=db.func.now(),
        onupdate=db.func.now(),
    )

    documents = db.relationship(
        "Document",
        back_populates="category",
        cascade="all, delete-orphan",
        order_by="Document.created_at.desc()",
    )

    @property
    def display_name(self):
        return f"{self.code}-) {self.name}"


class Document(db.Model):
    __tablename__ = "documents"

    id = db.Column(db.Integer, primary_key=True)
    category_id = db.Column(
        db.Integer,
        db.ForeignKey("document_categories.id"),
        nullable=False,
    )
    document_code = db.Column(db.String(80), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    revision_no = db.Column(db.String(40), nullable=True)
    publish_date = db.Column(db.Date, nullable=True)
    revision_date = db.Column(db.Date, nullable=True)
    department = db.Column(db.String(80), nullable=True)
    description = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(40), nullable=False, default="Yayında")
    file_name = db.Column(db.String(255), nullable=False)
    original_file_name = db.Column(db.String(255), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    file_type = db.Column(db.String(20), nullable=True)
    file_size = db.Column(db.Integer, nullable=True)
    preview_file_name = db.Column(db.String(255), nullable=True)
    preview_file_path = db.Column(db.String(500), nullable=True)
    preview_status = db.Column(db.String(40), nullable=True)
    preview_error = db.Column(db.Text, nullable=True)
    preview_generated_at = db.Column(db.DateTime, nullable=True)
    uploaded_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        server_default=db.func.now(),
        onupdate=db.func.now(),
    )
    archived_at = db.Column(db.DateTime, nullable=True)

    category = db.relationship("DocumentCategory", back_populates="documents")
    uploader = db.relationship("User", foreign_keys=[uploaded_by])


class MaintenanceMachine(db.Model):
    __tablename__ = "maintenance_machines"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(80), nullable=False, unique=True)
    machine_name = db.Column(db.String(180), nullable=False)
    brand_model = db.Column(db.String(180), nullable=True)
    serial_no = db.Column(db.String(120), nullable=True)
    status = db.Column(db.String(40), nullable=False, default="ÇALIŞIYOR")
    location = db.Column(db.String(160), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        server_default=db.func.now(),
        onupdate=db.func.now(),
    )

    created_by = db.relationship("User", foreign_keys=[created_by_user_id])
    faults = db.relationship(
        "MaintenanceFault",
        back_populates="machine",
        order_by="MaintenanceFault.created_at.desc()",
    )


class MaintenanceFault(db.Model):
    __tablename__ = "maintenance_faults"

    id = db.Column(db.Integer, primary_key=True)
    fault_number = db.Column(db.Integer, nullable=True, unique=True)
    machine_id = db.Column(
        db.Integer,
        db.ForeignKey("maintenance_machines.id"),
        nullable=False,
    )
    title = db.Column(db.String(180), nullable=False)
    description = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(40), nullable=False, default="Açık")
    priority = db.Column(db.String(40), nullable=False, default="Orta")
    reported_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())
    due_date = db.Column(db.Date, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    closing_note = db.Column(db.Text, nullable=True)
    reporting_department = db.Column(db.String(80), nullable=True)
    reported_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    responsible_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        server_default=db.func.now(),
        onupdate=db.func.now(),
    )

    machine = db.relationship("MaintenanceMachine", back_populates="faults")
    reported_by = db.relationship("User", foreign_keys=[reported_by_user_id])
    responsible_user = db.relationship("User", foreign_keys=[responsible_user_id])

    @property
    def number_label(self):
        source_date = self.reported_at or self.created_at
        year = source_date.year if source_date else date.today().year
        return f"BAK-{year}-{(self.fault_number or self.id):04d}"

    @property
    def is_completed(self):
        return self.status == "Tamamlandı"


class QualityTestRecord(db.Model):
    __tablename__ = "quality_test_records"

    id = db.Column(db.Integer, primary_key=True)
    test_type = db.Column(db.String(80), nullable=False)
    record_number = db.Column(db.Integer, nullable=True)
    title = db.Column(db.String(180), nullable=False)
    record_date = db.Column(db.Date, nullable=True)
    customer = db.Column(db.String(180), nullable=True)
    sample_name = db.Column(db.String(180), nullable=True)
    concrete_class = db.Column(db.String(40), nullable=True)
    air_temperature = db.Column(db.Float, nullable=True)
    strength_2_day = db.Column(db.Float, nullable=True)
    strength_2_recorded_at = db.Column(db.DateTime, nullable=True)
    strength_7_day = db.Column(db.Float, nullable=True)
    strength_7_recorded_at = db.Column(db.DateTime, nullable=True)
    strength_28_day = db.Column(db.Float, nullable=True)
    strength_28_recorded_at = db.Column(db.DateTime, nullable=True)
    status = db.Column(db.String(40), nullable=False, default="Kayıtlı")
    description = db.Column(db.Text, nullable=True)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        server_default=db.func.now(),
        onupdate=db.func.now(),
    )

    created_by = db.relationship("User", foreign_keys=[created_by_user_id])

    @property
    def number_label(self):
        source_date = self.record_date or self.created_at
        year = source_date.year if source_date else date.today().year
        prefix = QUALITY_TEST_PREFIXES.get(self.test_type, "DEN")
        return f"{prefix}-{year}-{(self.record_number or self.id):04d}"

    @property
    def measurement_base_date(self):
        if self.record_date:
            return self.record_date
        if self.created_at:
            return self.created_at.date()
        return date.today()

    def measurement_due_date(self, day):
        return self.measurement_base_date + timedelta(days=day)

    @property
    def current_measurement_day(self):
        if self.strength_2_day is None:
            return 2
        if self.strength_7_day is None:
            return 7
        if self.strength_28_day is None:
            return 28
        return None

    @property
    def current_measurement_label(self):
        day = self.current_measurement_day
        return f"{day} Günlük Basınç Dayanımı" if day else "Ölçümler Tamamlandı"

    @property
    def current_measurement_due_date(self):
        day = self.current_measurement_day
        return self.measurement_due_date(day) if day else None

    @property
    def measurement_progress_label(self):
        completed_count = sum(
            value is not None
            for value in (self.strength_2_day, self.strength_7_day, self.strength_28_day)
        )
        return f"{completed_count}/3 ölçüm"

    def measurement_tone(self, today=None):
        today = today or date.today()
        due_date = self.current_measurement_due_date
        if due_date is None:
            return "success"
        if due_date < today:
            return "danger"
        if due_date == today:
            return "warning"
        return "info"

    def measurement_due_label(self, today=None):
        today = today or date.today()
        due_date = self.current_measurement_due_date
        if due_date is None:
            return "Tamamlandı"
        delta = (due_date - today).days
        if delta < 0:
            return f"{abs(delta)} gün gecikti"
        if delta == 0:
            return "Bugün ölçülmeli"
        return f"{delta} gün kaldı"


class InternalAudit(db.Model):
    __tablename__ = "internal_audits"

    id = db.Column(db.Integer, primary_key=True)
    audit_no = db.Column(db.String(30), nullable=False, unique=True)
    title = db.Column(db.String(160), nullable=False, default="İç Denetim")
    auditor_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    evaluated_department = db.Column(db.String(80), nullable=True)
    audited_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    planned_date = db.Column(db.Date, nullable=True)
    status = db.Column(db.String(40), nullable=False, default="Devam Ediyor")
    active_question_order = db.Column(db.Integer, nullable=False, default=1)
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        server_default=db.func.now(),
        onupdate=db.func.now(),
    )

    auditor = db.relationship("User", foreign_keys=[auditor_id])
    audited_user = db.relationship("User", foreign_keys=[audited_user_id])
    questions = db.relationship(
        "InternalAuditQuestion",
        back_populates="audit",
        cascade="all, delete-orphan",
        order_by="InternalAuditQuestion.order_no.asc()",
    )
    answers = db.relationship(
        "InternalAuditAnswer",
        back_populates="audit",
        cascade="all, delete-orphan",
    )


class InternalAuditQuestion(db.Model):
    __tablename__ = "internal_audit_questions"

    id = db.Column(db.Integer, primary_key=True)
    audit_id = db.Column(db.Integer, db.ForeignKey("internal_audits.id"), nullable=False)
    order_no = db.Column(db.Integer, nullable=False)
    standard = db.Column(db.String(160), nullable=False)
    audit_topic = db.Column(db.String(200), nullable=False)
    audit_subject = db.Column(db.Text, nullable=True)
    question_text = db.Column(db.Text, nullable=False)
    evaluated_department = db.Column(db.String(80), nullable=True)
    evaluator_department = db.Column(db.String(80), nullable=True)
    answer_options = db.Column(db.Text, nullable=True)
    expected_answer = db.Column(db.Text, nullable=True)
    is_required = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())

    audit = db.relationship("InternalAudit", back_populates="questions")
    answers = db.relationship(
        "InternalAuditAnswer",
        back_populates="question",
        cascade="all, delete-orphan",
    )


class InternalAuditAnswer(db.Model):
    __tablename__ = "internal_audit_answers"

    id = db.Column(db.Integer, primary_key=True)
    audit_id = db.Column(db.Integer, db.ForeignKey("internal_audits.id"), nullable=False)
    question_id = db.Column(
        db.Integer,
        db.ForeignKey("internal_audit_questions.id"),
        nullable=False,
    )
    standard = db.Column(db.String(160), nullable=False)
    audit_topic = db.Column(db.String(200), nullable=False)
    audit_subject = db.Column(db.Text, nullable=True)
    question_text = db.Column(db.Text, nullable=False)
    evaluated_department = db.Column(db.String(80), nullable=True)
    evaluator_department = db.Column(db.String(80), nullable=True)
    technical_findings = db.Column(db.Text, nullable=True)
    result = db.Column(db.String(40), nullable=True)
    previous_nonconformity_id = db.Column(db.Integer, db.ForeignKey("dofs.id"), nullable=True)
    dof_id = db.Column(db.Integer, db.ForeignKey("dofs.id"), nullable=True)
    answered_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    answered_at = db.Column(db.DateTime, nullable=True)
    is_draft = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        server_default=db.func.now(),
        onupdate=db.func.now(),
    )

    audit = db.relationship("InternalAudit", back_populates="answers")
    question = db.relationship("InternalAuditQuestion", back_populates="answers")
    previous_nonconformity = db.relationship("Dof", foreign_keys=[previous_nonconformity_id])
    dof = db.relationship("Dof", foreign_keys=[dof_id])
    answered_by = db.relationship("User", foreign_keys=[answered_by_user_id])


class ActionClosureFile(db.Model):
    __tablename__ = "action_closure_files"

    id = db.Column(db.Integer, primary_key=True)
    action_id = db.Column(db.Integer, db.ForeignKey("actions.id"), nullable=False)
    original_name = db.Column(db.String(255), nullable=False)
    stored_name = db.Column(db.String(255), nullable=False)
    mime_type = db.Column(db.String(120), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())

    action = db.relationship("Action", back_populates="closure_files")


class ActionSubTask(db.Model):
    __tablename__ = "action_sub_tasks"

    id = db.Column(db.Integer, primary_key=True)
    parent_action_id = db.Column(db.Integer, db.ForeignKey("actions.id"), nullable=False)
    title = db.Column(db.String(160), nullable=False)
    description = db.Column(db.Text, nullable=True)
    responsible_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    related_user_1_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    related_user_2_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    due_date = db.Column(db.Date, nullable=True)
    priority = db.Column(db.String(40), nullable=False, default="Orta")
    status = db.Column(db.String(40), nullable=False, default="Beklemede")
    evidence_required = db.Column(db.Boolean, nullable=False, default=False)
    evidence_original_name = db.Column(db.String(255), nullable=True)
    evidence_stored_name = db.Column(db.String(255), nullable=True)
    evidence_mime_type = db.Column(db.String(120), nullable=True)
    closing_note = db.Column(db.Text, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    completed_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        server_default=db.func.now(),
        onupdate=db.func.now(),
    )

    parent_action = db.relationship("Action", back_populates="sub_actions")
    responsible = db.relationship("User", foreign_keys=[responsible_id])
    related_user_1 = db.relationship("User", foreign_keys=[related_user_1_id])
    related_user_2 = db.relationship("User", foreign_keys=[related_user_2_id])
    completed_by = db.relationship("User", foreign_keys=[completed_by_user_id])
    created_by = db.relationship("User", foreign_keys=[created_by_user_id])

    def participant_user_ids(self):
        return {
            user_id
            for user_id in (
                self.responsible_id,
                self.related_user_1_id,
                self.related_user_2_id,
            )
            if user_id
        }

    @property
    def evidence_uploaded(self):
        return bool(self.evidence_stored_name)


class ActionComment(db.Model):
    __tablename__ = "action_comments"

    id = db.Column(db.Integer, primary_key=True)
    action_id = db.Column(db.Integer, db.ForeignKey("actions.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    comment = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())

    action = db.relationship("Action", back_populates="comments")
    user = db.relationship("User")


class ActionHistory(db.Model):
    __tablename__ = "action_histories"

    id = db.Column(db.Integer, primary_key=True)
    action_id = db.Column(db.Integer, db.ForeignKey("actions.id"), nullable=False)
    actor_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    event_type = db.Column(db.String(40), nullable=False)
    message = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())

    action = db.relationship("Action", back_populates="histories")
    actor = db.relationship("User")


class Notification(db.Model):
    __tablename__ = "notifications"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    action_id = db.Column(db.Integer, db.ForeignKey("actions.id"), nullable=True)
    dof_id = db.Column(db.Integer, db.ForeignKey("dofs.id"), nullable=True)
    message = db.Column(db.Text, nullable=False)
    is_read = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())

    user = db.relationship("User")
    action = db.relationship("Action", back_populates="notifications")
    dof = db.relationship("Dof", back_populates="notifications")


class AppSetting(db.Model):
    __tablename__ = "app_settings"

    key = db.Column(db.String(80), primary_key=True)
    value = db.Column(db.String(255), nullable=False)


class OrientationNode(db.Model):
    __tablename__ = "orientation_nodes"

    id = db.Column(db.Integer, primary_key=True)
    parent_id = db.Column(
        db.Integer,
        db.ForeignKey("orientation_nodes.id"),
        nullable=True,
    )
    name = db.Column(db.String(160), nullable=False)
    title = db.Column(db.String(160), nullable=True)
    node_type = db.Column(db.String(40), nullable=False, default="person")
    color = db.Column(db.String(20), nullable=False, default="#198754")
    x = db.Column(db.Integer, nullable=False, default=120)
    y = db.Column(db.Integer, nullable=False, default=80)
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        server_default=db.func.now(),
        onupdate=db.func.now(),
    )

    parent = db.relationship(
        "OrientationNode",
        remote_side=[id],
        back_populates="children",
    )
    children = db.relationship(
        "OrientationNode",
        back_populates="parent",
        cascade="all, delete-orphan",
    )

    def to_dict(self):
        return {
            "id": self.id,
            "parent_id": self.parent_id,
            "name": self.name,
            "title": self.title or "",
            "node_type": self.node_type or "person",
            "color": self.color or "#198754",
            "x": self.x,
            "y": self.y,
        }
