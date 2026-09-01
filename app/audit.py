from datetime import date, datetime
from decimal import Decimal
import json

from flask import g, has_request_context, request
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Session
from sqlalchemy import event

from .models import AuditLog


TRACKED_MODEL_NAMES = {
    "Action",
    "ActionSubTask",
    "CalibrationRecord",
    "ComplaintRecord",
    "Company",
    "CompanyModule",
    "Dof",
    "Document",
    "DocumentCategory",
    "DocumentRevisionRequest",
    "InternalAudit",
    "InternalAuditAnswer",
    "InternalAuditQuestion",
    "MaintenanceFault",
    "MaintenanceMachine",
    "ManagementReview",
    "OrientationNode",
    "PersonnelContact",
    "QualityTestRecord",
    "RiskRecord",
    "Role",
    "RolePermission",
    "Suggestion",
    "SuggestionEvaluation",
    "SuggestionScoreParameter",
    "SupplierEvaluation",
    "SupplierRecord",
    "TrainingParticipant",
    "TrainingRecord",
    "User",
    "UserPermission",
    "Vehicle",
    "VehicleFuelEntry",
    "VehicleOperation",
}

SENSITIVE_FIELD_NAMES = {
    "password",
    "password_hash",
    "token",
    "remember_token",
    "csrf_token",
}

NOISY_FIELD_NAMES = {"updated_at"}

_REGISTERED = False


def register_audit_listeners():
    global _REGISTERED
    if _REGISTERED:
        return
    event.listen(Session, "before_flush", queue_audit_logs)
    event.listen(Session, "after_flush_postexec", write_queued_audit_logs)
    _REGISTERED = True


def queue_audit_logs(session, flush_context, instances):
    entries = []
    for obj in list(session.new):
        entry = build_audit_entry(obj, "created")
        if entry is not None:
            entries.append((obj, entry))

    for obj in list(session.dirty):
        if not session.is_modified(obj, include_collections=False):
            continue
        entry = build_audit_entry(obj, "updated")
        if entry is not None:
            entries.append((obj, entry))

    for obj in list(session.deleted):
        entry = build_audit_entry(obj, "deleted")
        if entry is not None:
            entries.append((obj, entry))

    if entries:
        session.info.setdefault("audit_log_entries", []).extend(entries)


def write_queued_audit_logs(session, flush_context):
    entries = session.info.pop("audit_log_entries", [])
    for obj, entry in entries:
        if not entry.entity_id:
            entry.entity_id = audit_entity_id(obj)
        session.add(entry)


def build_audit_entry(obj, action):
    model_name = obj.__class__.__name__
    if model_name == "AuditLog" or model_name not in TRACKED_MODEL_NAMES:
        return None

    old_values, new_values = audit_value_changes(obj, action)
    if action == "updated" and not old_values and not new_values:
        return None

    user_id, company_id, ip_address, user_agent = audit_request_context(obj)
    return AuditLog(
        company_id=company_id,
        user_id=user_id,
        entity_type=model_name,
        entity_id=audit_entity_id(obj),
        action=action,
        summary=audit_summary(obj),
        old_values=json.dumps(old_values, ensure_ascii=False, sort_keys=True)
        if old_values
        else None,
        new_values=json.dumps(new_values, ensure_ascii=False, sort_keys=True)
        if new_values
        else None,
        ip_address=ip_address,
        user_agent=user_agent,
    )


def audit_value_changes(obj, action):
    mapper = sa_inspect(obj.__class__)
    if action == "created":
        return None, audit_column_values(obj, mapper)
    if action == "deleted":
        return audit_column_values(obj, mapper), None

    old_values = {}
    new_values = {}
    state = sa_inspect(obj)
    for column in mapper.columns:
        key = column.key
        if skip_audit_field(key):
            continue
        history = state.attrs[key].history
        if not history.has_changes():
            continue
        old_values[key] = audit_scalar(history.deleted[0] if history.deleted else None)
        new_values[key] = audit_scalar(history.added[0] if history.added else getattr(obj, key))
    return old_values, new_values


def audit_column_values(obj, mapper):
    values = {}
    for column in mapper.columns:
        key = column.key
        if skip_audit_field(key):
            continue
        values[key] = audit_scalar(getattr(obj, key))
    return values


def skip_audit_field(key):
    normalized = key.lower()
    if normalized in NOISY_FIELD_NAMES:
        return True
    return any(marker in normalized for marker in SENSITIVE_FIELD_NAMES)


def audit_scalar(value):
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, bytes):
        return "<binary>"
    return value


def audit_request_context(obj):
    user_id = None
    company_id = getattr(obj, "company_id", None)
    ip_address = None
    user_agent = None

    if not has_request_context():
        return user_id, company_id, ip_address, user_agent

    current_user = getattr(g, "current_user", None)
    current_company = getattr(g, "current_company", None)
    if current_user is not None:
        user_id = current_user.id
    if current_company is not None:
        company_id = current_company.id
    if company_id is None and current_user is not None:
        company_id = current_user.company_id

    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        ip_address = forwarded_for.split(",", 1)[0].strip()[:80]
    elif request.remote_addr:
        ip_address = request.remote_addr[:80]
    if request.user_agent and request.user_agent.string:
        user_agent = request.user_agent.string[:255]
    return user_id, company_id, ip_address, user_agent


def audit_entity_id(obj):
    identity = sa_inspect(obj).identity
    if identity:
        return ":".join(str(part) for part in identity)
    value = getattr(obj, "id", None)
    return str(value) if value is not None else None


def audit_summary(obj):
    for key in (
        "action_no",
        "action_number",
        "dof_no",
        "document_code",
        "code",
        "complaint_no",
        "record_no",
        "risk_no",
        "review_no",
        "supplier_no",
        "training_no",
        "test_no",
        "title",
        "name",
        "full_name",
        "username",
        "machine_name",
        "vehicle_name",
        "plate",
    ):
        value = getattr(obj, key, None)
        if value:
            return str(value)[:255]
    return obj.__class__.__name__
