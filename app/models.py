from datetime import date

from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db


DEPARTMENTS = (
    "Üretim",
    "Kalite",
    "İnsan Kaynakları",
    "Şantiye",
    "Montaj",
    "Proje",
    "Teklif",
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
