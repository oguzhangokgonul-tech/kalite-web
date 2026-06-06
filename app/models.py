from datetime import date

from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db


DEPARTMENTS = (
    "Üretim",
    "Kalite",
    "Kalite Yönetim",
    "Yönetim",
    "Bakım",
    "Finans",
    "Muhasebe",
    "Satın alma",
    "İnsan Kaynakları",
    "Şantiye",
    "Montaj",
    "Proje",
    "Teklif",
)

ORGANIZATION_NODE_TYPES = ("person", "department")

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
DOF_STATUSES = ("Taslak", "Onay Akışı Bekleniyor", "Tamamlandı")
DOF_APPROVAL_STEPS = (
    "draft",
    "management_representative",
    "general_manager_deputy",
    "completed",
)


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

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


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


class ActionClosureFile(db.Model):
    __tablename__ = "action_closure_files"

    id = db.Column(db.Integer, primary_key=True)
    action_id = db.Column(db.Integer, db.ForeignKey("actions.id"), nullable=False)
    original_name = db.Column(db.String(255), nullable=False)
    stored_name = db.Column(db.String(255), nullable=False)
    mime_type = db.Column(db.String(120), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())

    action = db.relationship("Action", back_populates="closure_files")


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
    message = db.Column(db.Text, nullable=False)
    is_read = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())

    user = db.relationship("User")
    action = db.relationship("Action", back_populates="notifications")


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
