from .extensions import db


class NotificationEmailBatch(db.Model):
    __tablename__ = "notification_email_batches"
    __table_args__ = (
        db.UniqueConstraint("company_id", "user_id", "send_date", name="uq_notification_batch_day"),
    )

    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey("companies.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    send_date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="claimed")
    item_count = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())
    finished_at = db.Column(db.DateTime)
    error_code = db.Column(db.String(80))


class NotificationEmailEvent(db.Model):
    __tablename__ = "notification_email_events"

    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey("companies.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    dedupe_key = db.Column(db.String(64), nullable=False, unique=True)
    kind = db.Column(db.String(80), nullable=False)
    record_id = db.Column(db.Integer, nullable=False)
    phase = db.Column(db.String(100), nullable=False)
    due_date = db.Column(db.Date)
    notification_id = db.Column(db.Integer, db.ForeignKey("notifications.id", ondelete="SET NULL"))
    title = db.Column(db.String(255), nullable=False)
    message = db.Column(db.Text, nullable=False)
    target_url = db.Column(db.String(500), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="pending", index=True)
    batch_id = db.Column(db.Integer, db.ForeignKey("notification_email_batches.id"))
    attempts = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())
    accepted_at = db.Column(db.DateTime)
