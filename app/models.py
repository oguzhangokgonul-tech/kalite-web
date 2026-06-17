from datetime import date

from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db


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
