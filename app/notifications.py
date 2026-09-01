from datetime import datetime

from flask import current_app
from sqlalchemy import inspect, or_, text
from sqlalchemy.exc import OperationalError

from .extensions import db
from .models import Notification, User


LEGACY_PERMISSION_ALIASES = {
    "can_create_actions": "actions.create",
    "can_edit_actions": "actions.edit",
    "can_delete_actions": "actions.delete",
    "can_comment_assigned_actions": "actions.comment_assigned",
    "can_close_assigned_actions": "actions.request_close_assigned",
    "can_manage_users": "users.manage",
}


def ensure_notification_schema():
    if current_app.extensions.get("notification_schema_checked"):
        return

    try:
        inspector = inspect(db.engine)
        tables = set(inspector.get_table_names())
        if "notifications" in tables:
            columns = {column["name"] for column in inspector.get_columns("notifications")}
            column_statements = {
                "dof_id": "ALTER TABLE notifications ADD COLUMN dof_id INTEGER",
                "document_revision_request_id": (
                    "ALTER TABLE notifications ADD COLUMN document_revision_request_id INTEGER"
                ),
                "notification_type": (
                    "ALTER TABLE notifications "
                    "ADD COLUMN notification_type VARCHAR(40) NOT NULL DEFAULT 'info'"
                ),
                "source_key": "ALTER TABLE notifications ADD COLUMN source_key VARCHAR(180)",
                "target_url": "ALTER TABLE notifications ADD COLUMN target_url VARCHAR(500)",
                "due_date": "ALTER TABLE notifications ADD COLUMN due_date DATE",
                "email_sent_at": "ALTER TABLE notifications ADD COLUMN email_sent_at DATETIME",
            }
            with db.engine.begin() as connection:
                for column_name, statement in column_statements.items():
                    if column_name not in columns:
                        connection.execute(text(statement))
                connection.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_notifications_company_id "
                        "ON notifications (company_id)"
                    )
                )
                connection.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_notifications_user_id "
                        "ON notifications (user_id)"
                    )
                )
                connection.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_notifications_source_key "
                        "ON notifications (source_key)"
                    )
                )
                connection.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_notifications_due_date "
                        "ON notifications (due_date)"
                    )
                )
        current_app.extensions["notification_schema_checked"] = True
    except OperationalError as error:
        if "duplicate column name" in str(error).lower():
            current_app.extensions["notification_schema_checked"] = True
            return
        db.session.rollback()
        current_app.logger.exception("Bildirim şeması kontrol edilemedi.")


def safe_notification_target_url(target_url):
    if not target_url:
        return None
    value = str(target_url).strip()
    if not value or not value.startswith("/") or value.startswith("//"):
        return None
    if "\r" in value or "\n" in value:
        return None
    return value[:500]


def unique_users(users):
    unique_by_id = {}
    for user in users:
        if user is not None and getattr(user, "id", None):
            unique_by_id[user.id] = user
    return list(unique_by_id.values())


def user_has_permission(user, permission_key):
    if user is None:
        return False
    if hasattr(user, "has_role") and user.has_role("super_admin"):
        return True
    mapped_key = LEGACY_PERMISSION_ALIASES.get(permission_key, permission_key)
    if hasattr(user, "has_permission") and user.has_permission(mapped_key):
        return True
    return bool(getattr(user, permission_key, False))


def active_company_users(company_id=None):
    query = User.query.filter(User.is_active.is_(True))
    if company_id is None:
        query = query.filter(User.company_id.is_(None))
    else:
        query = query.filter(or_(User.company_id == company_id, User.company_id.is_(None)))
    return query.order_by(User.full_name.asc()).all()


def users_with_permissions(company_id, permission_keys):
    permission_keys = tuple(permission_keys or ())
    if not permission_keys:
        return []
    return unique_users(
        user
        for user in active_company_users(company_id)
        if any(user_has_permission(user, permission_key) for permission_key in permission_keys)
    )


def users_by_ids(user_ids, company_id=None):
    clean_ids = {int(user_id) for user_id in user_ids if user_id}
    if not clean_ids:
        return []
    query = User.query.filter(User.id.in_(clean_ids), User.is_active.is_(True))
    if company_id is None:
        query = query.filter(User.company_id.is_(None))
    else:
        query = query.filter(or_(User.company_id == company_id, User.company_id.is_(None)))
    return query.order_by(User.full_name.asc()).all()


def notification_target_url(action=None, dof=None, document_revision_request=None, target_url=None):
    if target_url:
        return safe_notification_target_url(target_url)
    if action is not None and getattr(action, "id", None):
        return f"/actions/{action.id}"
    if dof is not None and getattr(dof, "id", None):
        return f"/dofs/{dof.id}"
    if document_revision_request is not None and getattr(document_revision_request, "id", None):
        return f"/documents/revision-requests/{document_revision_request.id}"
    return None


def add_user_notification(
    user,
    message,
    *,
    company_id=None,
    action=None,
    dof=None,
    document_revision_request=None,
    notification_type="info",
    source_key=None,
    target_url=None,
    due_date=None,
):
    if user is None or not getattr(user, "is_active", True):
        return None
    if company_id is None:
        company_id = (
            getattr(action, "company_id", None)
            or getattr(dof, "company_id", None)
            or getattr(document_revision_request, "company_id", None)
            or getattr(user, "company_id", None)
        )

    resolved_target_url = notification_target_url(
        action=action,
        dof=dof,
        document_revision_request=document_revision_request,
        target_url=target_url,
    )

    if source_key:
        existing = (
            Notification.query.filter_by(
                company_id=company_id,
                user_id=user.id,
                source_key=source_key,
            )
            .limit(1)
            .first()
        )
        if existing is not None:
            return None

    notification = Notification(
        user_id=user.id,
        company_id=company_id,
        action=action,
        dof=dof,
        document_revision_request=document_revision_request,
        notification_type=notification_type or "info",
        source_key=source_key,
        target_url=resolved_target_url,
        due_date=due_date,
        message=message,
    )
    db.session.add(notification)
    return notification


def add_notifications(users, message, *, exclude_user_id=None, **kwargs):
    created = []
    for user in unique_users(users):
        if exclude_user_id and user.id == exclude_user_id:
            continue
        notification = add_user_notification(user, message, **kwargs)
        if notification is not None:
            created.append(notification)
    return created


def mark_notifications_email_sent(notifications):
    now = datetime.utcnow()
    for notification in notifications:
        notification.email_sent_at = now
