from datetime import date, datetime, timedelta
import json
import unicodedata

from flask import current_app

from .extensions import db
from .mail import send_generic_notification_email
from .models import (
    Action,
    ActionSubTask,
    AppSetting,
    AuditLog,
    CalibrationRecord,
    ComplaintRecord,
    Company,
    DocumentRevisionRequest,
    Dof,
    InternalAudit,
    MaintenanceFault,
    ManagementReview,
    RiskRecord,
    SupplierRecord,
    TrainingParticipant,
    TrainingRecord,
)
from .notifications import (
    add_user_notification,
    mark_notifications_email_sent,
    unique_users,
    users_by_ids,
    users_with_permissions,
)


ACTION_REMINDER_PERMISSIONS = ("actions.view_all", "actions.approve_closure")
DOF_REMINDER_PERMISSIONS = ("if.view_all", "if.approve_management", "if.approve_deputy")
DOCUMENT_REMINDER_PERMISSIONS = ("documents.manage",)
INTERNAL_AUDIT_REMINDER_PERMISSIONS = ("internal_audit.manage",)
MAINTENANCE_REMINDER_PERMISSIONS = ("maintenance.fault_manage",)
RISK_REMINDER_PERMISSIONS = ("risk.manage",)
TRAINING_REMINDER_PERMISSIONS = ("training.manage",)
COMPLAINT_REMINDER_PERMISSIONS = ("complaints.manage",)
MANAGEMENT_REVIEW_REMINDER_PERMISSIONS = ("management_review.manage",)
SUPPLIER_REMINDER_PERMISSIONS = ("suppliers.manage", "suppliers.evaluate")
CALIBRATION_REMINDER_PERMISSIONS = ("calibration.manage",)


def _status_text(value):
    normalized = unicodedata.normalize("NFKD", (value or "").strip().casefold())
    return "".join(char for char in normalized if not unicodedata.combining(char))


def _is_completed_text(value):
    status = _status_text(value)
    return "tamam" in status or "iptal" in status or "kapand" in status or "arşiv" in status


def _company_query(model, company_id):
    query = model.query
    if not hasattr(model, "company_id"):
        return query
    if company_id is None:
        return query.filter(model.company_id.is_(None))
    return query.filter(model.company_id == company_id)


def _date_in_window(target_date, run_date, days_before):
    if not target_date:
        return False
    return (target_date - run_date).days <= days_before


def _due_state(target_date, run_date):
    days = (target_date - run_date).days
    if days < 0:
        return "danger", f"{abs(days)} gün geçti"
    if days == 0:
        return "warning", "Bugün"
    return "warning", f"{days} gün kaldı"


def _source_key(kind, record_id, target_date, user_id, run_date):
    date_part = target_date.isoformat() if target_date else "no-date"
    return f"{kind}:{record_id}:{date_part}:u{user_id}:{run_date.isoformat()}"


def _send_record_reminders(
    users,
    *,
    company_id,
    kind,
    record_id,
    title,
    message,
    target_url,
    due_date=None,
    notification_type="warning",
    run_date=None,
):
    run_date = run_date or date.today()
    created = []
    emails_sent = 0
    for user in unique_users(users):
        notification = add_user_notification(
            user,
            message,
            company_id=company_id,
            notification_type=notification_type,
            source_key=_source_key(kind, record_id, due_date, user.id, run_date),
            target_url=target_url,
            due_date=due_date,
        )
        if notification is None:
            continue
        created.append(notification)
        if send_generic_notification_email(
            [user],
            message,
            title=title,
            target_url=target_url,
            due_date=due_date,
            source_label=kind,
        ):
            mark_notifications_email_sent([notification])
            emails_sent += 1
    return len(created), emails_sent


def _merge_users(company_id, user_ids=(), permission_keys=()):
    return unique_users(
        [
            *users_by_ids(user_ids, company_id=company_id),
            *users_with_permissions(company_id, permission_keys),
        ]
    )


def _action_reminders(company_id, run_date, days_before):
    stats = {"notifications": 0, "emails": 0}
    limit_date = run_date + timedelta(days=days_before)
    actions = (
        _company_query(Action, company_id)
        .filter(Action.is_completed.is_(False))
        .filter(Action.termin_date <= limit_date)
        .all()
    )
    for action in actions:
        severity, label = _due_state(action.termin_date, run_date)
        users = _merge_users(
            company_id,
            action.participant_user_ids(),
            ACTION_REMINDER_PERMISSIONS if severity == "danger" else (),
        )
        created, emails = _send_record_reminders(
            users,
            company_id=company_id,
            kind="action",
            record_id=action.id,
            title=f"Aksiyon hatırlatması {action.number_label}",
            message=f"{action.number_label} {action.title} için termin durumu: {label}.",
            target_url=f"/actions/{action.id}",
            due_date=action.termin_date,
            notification_type=severity,
            run_date=run_date,
        )
        stats["notifications"] += created
        stats["emails"] += emails
    return stats


def _sub_action_reminders(company_id, run_date, days_before):
    stats = {"notifications": 0, "emails": 0}
    limit_date = run_date + timedelta(days=days_before)
    sub_actions = (
        _company_query(ActionSubTask, company_id)
        .filter(ActionSubTask.due_date.isnot(None))
        .filter(ActionSubTask.due_date <= limit_date)
        .all()
    )
    for sub_action in sub_actions:
        if _is_completed_text(sub_action.status):
            continue
        severity, label = _due_state(sub_action.due_date, run_date)
        parent = sub_action.parent_action
        user_ids = set(sub_action.participant_user_ids())
        if parent and parent.responsible_user_id:
            user_ids.add(parent.responsible_user_id)
        users = _merge_users(
            company_id,
            user_ids,
            ACTION_REMINDER_PERMISSIONS if severity == "danger" else (),
        )
        action_label = parent.number_label if parent else "Aksiyon"
        target_url = f"/actions/{parent.id}" if parent else "/assigned-tasks"
        created, emails = _send_record_reminders(
            users,
            company_id=company_id,
            kind="sub-action",
            record_id=sub_action.id,
            title=f"Alt aksiyon hatırlatması {action_label}",
            message=f"{action_label} alt aksiyonu '{sub_action.title}' için termin durumu: {label}.",
            target_url=target_url,
            due_date=sub_action.due_date,
            notification_type=severity,
            run_date=run_date,
        )
        stats["notifications"] += created
        stats["emails"] += emails
    return stats


def _dof_reminders(company_id, run_date, days_before):
    stats = {"notifications": 0, "emails": 0}
    limit_date = run_date + timedelta(days=days_before)
    dofs = (
        _company_query(Dof, company_id)
        .filter(Dof.due_date.isnot(None))
        .filter(Dof.due_date <= limit_date)
        .all()
    )
    for dof in dofs:
        if _is_completed_text(dof.status) or dof.approval_step == "completed":
            continue
        severity, label = _due_state(dof.due_date, run_date)
        user_ids = [dof.responsible_id, dof.created_by_user_id]
        permission_keys = DOF_REMINDER_PERMISSIONS if severity == "danger" else ()
        if dof.approval_step in {"management_representative", "general_manager_deputy"}:
            permission_keys = DOF_REMINDER_PERMISSIONS
        users = _merge_users(company_id, user_ids, permission_keys)
        created, emails = _send_record_reminders(
            users,
            company_id=company_id,
            kind="dof",
            record_id=dof.id,
            title=f"IF/DÖF hatırlatması {dof.dof_no}",
            message=f"{dof.dof_no} {dof.title or ''} için termin durumu: {label}.",
            target_url=f"/dofs/{dof.id}",
            due_date=dof.due_date,
            notification_type=severity,
            run_date=run_date,
        )
        stats["notifications"] += created
        stats["emails"] += emails
    return stats


def _document_revision_reminders(company_id, run_date):
    stats = {"notifications": 0, "emails": 0}
    requests = _company_query(DocumentRevisionRequest, company_id).all()
    for revision_request in requests:
        if "bekleniyor" not in _status_text(revision_request.status):
            continue
        document = revision_request.document
        users = _merge_users(company_id, (), DOCUMENT_REMINDER_PERMISSIONS)
        document_label = (
            f"{document.document_code} {document.title}" if document else "Doküman"
        )
        created, emails = _send_record_reminders(
            users,
            company_id=company_id,
            kind="document-revision",
            record_id=revision_request.id,
            title="Doküman revizyon onayı",
            message=f"{document_label} için revizyon talebi yönetim onayı bekliyor.",
            target_url=f"/documents/revision-requests/{revision_request.id}",
            due_date=None,
            notification_type="warning",
            run_date=run_date,
        )
        stats["notifications"] += created
        stats["emails"] += emails
    return stats


def _internal_audit_reminders(company_id, run_date, days_before):
    stats = {"notifications": 0, "emails": 0}
    limit_date = run_date + timedelta(days=days_before)
    audits = (
        _company_query(InternalAudit, company_id)
        .filter(InternalAudit.planned_date.isnot(None))
        .filter(InternalAudit.planned_date <= limit_date)
        .all()
    )
    for audit in audits:
        if _is_completed_text(audit.status):
            continue
        severity, label = _due_state(audit.planned_date, run_date)
        users = _merge_users(
            company_id,
            [audit.auditor_id, audit.audited_user_id],
            INTERNAL_AUDIT_REMINDER_PERMISSIONS if severity == "danger" else (),
        )
        created, emails = _send_record_reminders(
            users,
            company_id=company_id,
            kind="internal-audit",
            record_id=audit.id,
            title=f"İç denetim hatırlatması {audit.audit_no}",
            message=f"{audit.audit_no} {audit.title} için plan tarihi durumu: {label}.",
            target_url="/ic-denetim",
            due_date=audit.planned_date,
            notification_type=severity,
            run_date=run_date,
        )
        stats["notifications"] += created
        stats["emails"] += emails
    return stats


def _maintenance_reminders(company_id, run_date, days_before):
    stats = {"notifications": 0, "emails": 0}
    limit_date = run_date + timedelta(days=days_before)
    faults = (
        _company_query(MaintenanceFault, company_id)
        .filter(MaintenanceFault.due_date.isnot(None))
        .filter(MaintenanceFault.due_date <= limit_date)
        .all()
    )
    for fault in faults:
        if getattr(fault, "is_completed", False) or _is_completed_text(fault.status):
            continue
        severity, label = _due_state(fault.due_date, run_date)
        users = _merge_users(
            company_id,
            [fault.responsible_user_id, fault.reported_by_user_id],
            MAINTENANCE_REMINDER_PERMISSIONS if severity == "danger" else (),
        )
        created, emails = _send_record_reminders(
            users,
            company_id=company_id,
            kind="maintenance",
            record_id=fault.id,
            title=f"Bakım arıza hatırlatması {fault.number_label}",
            message=f"{fault.number_label} {fault.title} için termin durumu: {label}.",
            target_url="/bakim/arizalar",
            due_date=fault.due_date,
            notification_type=severity,
            run_date=run_date,
        )
        stats["notifications"] += created
        stats["emails"] += emails
    return stats


def _risk_reminders(company_id, run_date, days_before):
    stats = {"notifications": 0, "emails": 0}
    limit_date = run_date + timedelta(days=days_before)
    risks = (
        _company_query(RiskRecord, company_id)
        .filter(RiskRecord.due_date.isnot(None))
        .filter(RiskRecord.due_date <= limit_date)
        .all()
    )
    for risk in risks:
        if _is_completed_text(risk.status):
            continue
        severity, label = _due_state(risk.due_date, run_date)
        users = _merge_users(
            company_id,
            [risk.owner_user_id, risk.created_by_user_id],
            RISK_REMINDER_PERMISSIONS if severity == "danger" else (),
        )
        created, emails = _send_record_reminders(
            users,
            company_id=company_id,
            kind="risk",
            record_id=risk.id,
            title=f"Risk hatırlatması {risk.risk_no}",
            message=f"{risk.risk_no} {risk.title} için termin durumu: {label}.",
            target_url="/risk-yonetimi",
            due_date=risk.due_date,
            notification_type=severity,
            run_date=run_date,
        )
        stats["notifications"] += created
        stats["emails"] += emails
    return stats


def _training_reminders(company_id, run_date, days_before):
    stats = {"notifications": 0, "emails": 0}
    limit_date = run_date + timedelta(days=days_before)
    trainings = (
        _company_query(TrainingRecord, company_id)
        .filter(TrainingRecord.due_date.isnot(None))
        .filter(TrainingRecord.due_date <= limit_date)
        .all()
    )
    for training in trainings:
        if _is_completed_text(training.status):
            continue
        incomplete_participant_ids = [
            participant.user_id
            for participant in training.participants
            if participant.user_id and not participant.is_completed
        ]
        severity, label = _due_state(training.due_date, run_date)
        users = _merge_users(
            company_id,
            [training.instructor_user_id, *incomplete_participant_ids],
            TRAINING_REMINDER_PERMISSIONS if severity == "danger" else (),
        )
        created, emails = _send_record_reminders(
            users,
            company_id=company_id,
            kind="training",
            record_id=training.id,
            title=f"Eğitim hatırlatması {training.training_no}",
            message=f"{training.training_no} {training.title} için termin durumu: {label}.",
            target_url="/egitim-yeterlilik",
            due_date=training.due_date,
            notification_type=severity,
            run_date=run_date,
        )
        stats["notifications"] += created
        stats["emails"] += emails
    return stats


def _complaint_reminders(company_id, run_date, days_before):
    stats = {"notifications": 0, "emails": 0}
    limit_date = run_date + timedelta(days=days_before)
    complaints = (
        _company_query(ComplaintRecord, company_id)
        .filter(ComplaintRecord.due_date.isnot(None))
        .filter(ComplaintRecord.due_date <= limit_date)
        .all()
    )
    for complaint in complaints:
        if complaint.is_closed or _is_completed_text(complaint.status):
            continue
        severity, label = _due_state(complaint.due_date, run_date)
        users = _merge_users(
            company_id,
            [complaint.responsible_user_id, complaint.created_by_user_id],
            COMPLAINT_REMINDER_PERMISSIONS if severity == "danger" else (),
        )
        created, emails = _send_record_reminders(
            users,
            company_id=company_id,
            kind="complaint",
            record_id=complaint.id,
            title=f"Şikayet hatırlatması {complaint.complaint_no}",
            message=f"{complaint.complaint_no} {complaint.subject} için termin durumu: {label}.",
            target_url="/oneri-sikayet/sikayet",
            due_date=complaint.due_date,
            notification_type=severity,
            run_date=run_date,
        )
        stats["notifications"] += created
        stats["emails"] += emails
    return stats


def _management_review_reminders(company_id, run_date, days_before):
    stats = {"notifications": 0, "emails": 0}
    limit_date = run_date + timedelta(days=days_before)
    reviews = (
        _company_query(ManagementReview, company_id)
        .filter(ManagementReview.meeting_date.isnot(None))
        .filter(ManagementReview.meeting_date <= limit_date)
        .all()
    )
    for review in reviews:
        if review.is_completed or _is_completed_text(review.status):
            continue
        severity, label = _due_state(review.meeting_date, run_date)
        users = _merge_users(
            company_id,
            [review.chair_user_id, review.recorder_user_id, review.created_by_user_id],
            MANAGEMENT_REVIEW_REMINDER_PERMISSIONS if severity == "danger" else (),
        )
        created, emails = _send_record_reminders(
            users,
            company_id=company_id,
            kind="management-review",
            record_id=review.id,
            title=f"YGG hatırlatması {review.review_no}",
            message=f"{review.review_no} {review.title} için toplantı tarihi durumu: {label}.",
            target_url="/yonetimin-gozden-gecirmesi",
            due_date=review.meeting_date,
            notification_type=severity,
            run_date=run_date,
        )
        stats["notifications"] += created
        stats["emails"] += emails
    return stats


def _supplier_reminders(company_id, run_date, days_before):
    stats = {"notifications": 0, "emails": 0}
    limit_date = run_date + timedelta(days=days_before)
    suppliers = (
        _company_query(SupplierRecord, company_id)
        .filter(SupplierRecord.next_evaluation_date.isnot(None))
        .filter(SupplierRecord.next_evaluation_date <= limit_date)
        .all()
    )
    for supplier in suppliers:
        if supplier.is_passive:
            continue
        severity, label = _due_state(supplier.next_evaluation_date, run_date)
        users = _merge_users(
            company_id,
            [supplier.created_by_user_id],
            SUPPLIER_REMINDER_PERMISSIONS,
        )
        created, emails = _send_record_reminders(
            users,
            company_id=company_id,
            kind="supplier",
            record_id=supplier.id,
            title=f"Tedarikçi değerlendirme hatırlatması {supplier.supplier_no}",
            message=f"{supplier.supplier_no} {supplier.name} için değerlendirme tarihi durumu: {label}.",
            target_url="/tedarikci-degerlendirme",
            due_date=supplier.next_evaluation_date,
            notification_type=severity,
            run_date=run_date,
        )
        stats["notifications"] += created
        stats["emails"] += emails
    return stats


def _calibration_reminders(company_id, run_date, days_before):
    stats = {"notifications": 0, "emails": 0}
    limit_date = run_date + timedelta(days=days_before)
    records = (
        _company_query(CalibrationRecord, company_id)
        .filter(CalibrationRecord.is_active.is_(True))
        .filter(CalibrationRecord.next_calibration_date.isnot(None))
        .filter(CalibrationRecord.next_calibration_date <= limit_date)
        .all()
    )
    for record in records:
        severity, label = _due_state(record.next_calibration_date, run_date)
        users = _merge_users(company_id, [record.created_by_user_id], CALIBRATION_REMINDER_PERMISSIONS)
        created, emails = _send_record_reminders(
            users,
            company_id=company_id,
            kind="calibration",
            record_id=record.id,
            title=f"Kalibrasyon hatırlatması {record.device_code}",
            message=f"{record.device_code} {record.device_name} için kalibrasyon durumu: {label}.",
            target_url="/kalibrasyon",
            due_date=record.next_calibration_date,
            notification_type=severity,
            run_date=run_date,
        )
        stats["notifications"] += created
        stats["emails"] += emails
    return stats


def generate_due_reminders(company_id=None, run_date=None):
    run_date = run_date or date.today()
    days_before = int(current_app.config.get("NOTIFICATION_REMINDER_DAYS_BEFORE", 7))
    calibration_days = int(
        current_app.config.get("NOTIFICATION_CALIBRATION_REMINDER_DAYS_BEFORE", 30)
    )
    stats = {"notifications": 0, "emails": 0}
    builders = (
        lambda: _action_reminders(company_id, run_date, days_before),
        lambda: _sub_action_reminders(company_id, run_date, days_before),
        lambda: _dof_reminders(company_id, run_date, days_before),
        lambda: _document_revision_reminders(company_id, run_date),
        lambda: _internal_audit_reminders(company_id, run_date, days_before),
        lambda: _maintenance_reminders(company_id, run_date, days_before),
        lambda: _risk_reminders(company_id, run_date, days_before),
        lambda: _training_reminders(company_id, run_date, days_before),
        lambda: _complaint_reminders(company_id, run_date, days_before),
        lambda: _management_review_reminders(company_id, run_date, days_before),
        lambda: _supplier_reminders(company_id, run_date, calibration_days),
        lambda: _calibration_reminders(company_id, run_date, calibration_days),
    )
    for build_stats in builders:
        item_stats = build_stats()
        stats["notifications"] += item_stats["notifications"]
        stats["emails"] += item_stats["emails"]
    return stats


def _run_key(company_id):
    return f"notifications:due_reminders_last_run:{company_id or 'global'}"


def _company_label(company_id):
    if company_id is None:
        return "Genel"
    company = db.session.get(Company, company_id)
    return company.label if company else str(company_id)


def run_due_reminders_once_for_company(
    company_id=None,
    *,
    actor_user_id=None,
    force=False,
    run_date=None,
):
    run_date = run_date or date.today()
    setting_key = _run_key(company_id)
    setting = db.session.get(AppSetting, setting_key)
    if setting is not None and setting.value == run_date.isoformat() and not force:
        return {"notifications": 0, "emails": 0, "skipped": True}

    stats = generate_due_reminders(company_id=company_id, run_date=run_date)
    if setting is None:
        setting = AppSetting(key=setting_key, value=run_date.isoformat())
        db.session.add(setting)
    else:
        setting.value = run_date.isoformat()

    if stats["notifications"]:
        db.session.add(
            AuditLog(
                company_id=company_id,
                user_id=actor_user_id,
                entity_type="NotificationCenter",
                action="reminders_generated",
                summary=f"{_company_label(company_id)} için günlük hatırlatmalar üretildi",
                new_values=json.dumps(
                    {
                        "company_id": company_id,
                        "run_date": run_date.isoformat(),
                        "notifications": stats["notifications"],
                        "emails": stats["emails"],
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            )
        )
    db.session.commit()
    return {**stats, "skipped": False}


def run_due_reminders_for_all_companies(force=False, run_date=None):
    run_date = run_date or date.today()
    totals = {"companies": 0, "notifications": 0, "emails": 0, "skipped": 0}
    company_ids = [None]
    company_ids.extend(
        company.id for company in Company.query.filter_by(is_active=True).order_by(Company.id.asc()).all()
    )
    for company_id in company_ids:
        stats = run_due_reminders_once_for_company(
            company_id,
            force=force,
            run_date=run_date,
        )
        totals["companies"] += 1
        totals["notifications"] += stats["notifications"]
        totals["emails"] += stats["emails"]
        totals["skipped"] += 1 if stats.get("skipped") else 0
    return totals


def maybe_run_due_reminders_for_request(company_id=None, user=None):
    if not current_app.config.get("NOTIFICATION_AUTO_REMINDERS_ENABLED", True):
        return None
    if company_id is None and user is not None and getattr(user, "has_role", lambda _role: False)("super_admin"):
        return None
    try:
        return run_due_reminders_once_for_company(
            company_id,
            actor_user_id=getattr(user, "id", None),
        )
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Günlük bildirim hatırlatmaları üretilemedi.")
        return None
