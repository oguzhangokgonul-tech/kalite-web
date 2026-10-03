"""Company-scoped reminder selection and durable, once-per-day mail batches."""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from datetime import UTC, date, datetime, timedelta, timezone
import hashlib
import json
import smtplib
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import current_app
from sqlalchemy.exc import IntegrityError

from .extensions import db
from .models import AppSetting, Company, CompanyModule, Notification, User, COMPANY_MODULE_CATALOG
from .notification_models import NotificationEmailBatch, NotificationEmailEvent


def _default(label, days=(7, 0), module=None):
    return {"label": label, "days": list(days), "weekly": True, "email": True, "module": module}


POLICY_DEFAULTS = {
    "action": _default("Aksiyon"),
    "sub-action": _default("Alt aksiyon"),
    "action-approval": _default("Aksiyon kapanış onayı"),
    "action-effectiveness": _default("Aksiyon etkinlik kontrolü"),
    "dof": _default("İF / DÖF", module="if_management"),
    "dof-effectiveness": _default("DÖF etkinlik kontrolü", module="if_management"),
    "document-revision": _default("Doküman revizyon onayı", (), "documents"),
    "document-acknowledgement": _default("Doküman okuma-onay", (3, 0), "documents"),
    "internal-audit": _default("İç denetim", (7, 1), "internal_audit"),
    "maintenance": _default("Bakım", module="maintenance"),
    "risk": _default("Risk", module="risk_management"),
    "ohs-risk": _default("İSG riski", module="risk_management"),
    "fmea": _default("FMEA", module="fmea_management"),
    "training": _default("Eğitim", (7, 1), "training"),
    "complaint": _default("Şikayet", (1, 0), "suggestions"),
    "customer-portal": _default("Müşteri geri bildirimi", (1, 0), "customer_feedback_portal"),
    "management-review": _default("Yönetimin gözden geçirmesi", (7, 1), "management_review"),
    "supplier": _default("Tedarikçi değerlendirme", (30, 7, 0), "supplier_management"),
    "calibration": _default("Kalibrasyon", (30, 7, 0), "calibration"),
    "vehicle-insurance": _default("Trafik sigortası", (30, 7, 0), "vehicles"),
    "vehicle-casco": _default("Kasko", (30, 7, 0), "vehicles"),
    "vehicle-inspection": _default("Araç muayenesi", (30, 7, 0), "vehicles"),
    "suggestion-approval": _default("Öneri ön onayı", (), "suggestions"),
    "suggestion-evaluation": _default("Öneri değerlendirmesi", (), "suggestions"),
    "concrete-2": _default("Beton 2 gün ölçümü", (0,), "quality_test_concrete"),
    "concrete-7": _default("Beton 7 gün ölçümü", (0,), "quality_test_concrete"),
    "concrete-28": _default("Beton 28 gün ölçümü", (0,), "quality_test_concrete"),
    "meeting": _default("Toplantı", (1,), "meetings"),
    "meeting-decision": _default("Toplantı kararı", module="meetings"),
    "process-review": _default("Süreç gözden geçirme", (30, 7, 0), "process_management"),
    "quality-objective": _default("Kalite hedefi", (0,), "quality_objectives"),
    "stakeholder-review": _default("İlgili taraflar", (30, 7, 0), "stakeholder_management"),
    "stakeholder-requirement-due": _default("İlgili taraf beklentisi", module="stakeholder_management"),
    "compliance-review": _default("Mevzuat incelemesi", (30, 7, 0), "compliance_management"),
    "compliance-verification": _default("Mevzuat doğrulaması", (), "compliance_management"),
    "hazardous-sds": _default("Güvenlik bilgi formu", (30, 7, 0), "hazardous_substances"),
    "hazardous-expiry": _default("Tehlikeli madde son kullanım", (30, 7, 0), "hazardous_substances"),
    "hazardous-low-stock": _default("Tehlikeli madde stok uyarısı", (), "hazardous_substances"),
    "environmental-aspect": _default("Çevresel boyut", (30, 7, 0), "environmental_management"),
    "environmental-waste": _default("Atık depolama", (30, 7, 0), "environmental_management"),
    "energy-reading": _default("Enerji okuması", (0,), "energy_management"),
    "energy-project": _default("Enerji tasarruf projesi", module="energy_management"),
    "energy-target": _default("Enerji hedefi", (0,), "energy_management"),
    "workflow": _default("İş akışı", (3, 0), "workflow_designer"),
    "dynamic-form": _default("Form ataması", (0,), "dynamic_forms"),
    "change": _default("Değişiklik yönetimi", module="change_management"),
    "deviation": _default("Sapma / uygunsuz ürün", module="deviation_management"),
    "incident": _default("Olay / ramak kala", module="incident_near_miss"),
    "kaizen": _default("Kaizen", module="kaizen_management"),
    "problem-step": _default("A3 / 8D adımı", module="problem_solving"),
    "problem-approval": _default("A3 / 8D onayı", module="problem_solving"),
    "helpdesk": _default("İç talep", (1, 0), "help_desk"),
    "helpdesk-acceptance": _default("İç talep sonuç onayı", (), "help_desk"),
    "work-permit-approval": _default("İş izni onayı", (1, 0), "work_permits"),
}

_collection = ContextVar("reminder_collection", default=None)


def reminder_timezone():
    try:
        return ZoneInfo("Europe/Istanbul")
    except ZoneInfoNotFoundError:
        return timezone(timedelta(hours=3), name="Europe/Istanbul")


def local_now():
    return datetime.now(UTC).astimezone(reminder_timezone())


def _setting(key, fallback):
    item = db.session.get(AppSetting, key)
    if not item:
        return fallback
    try:
        value = json.loads(item.value)
        return value if isinstance(value, dict) else fallback
    except (ValueError, TypeError):
        return fallback


def get_company_policy(company_id):
    policy = {"enabled": True, "weekly_day": 0, "modules": deepcopy(POLICY_DEFAULTS)}
    stored = _setting(f"notification_policy:company:{company_id}", {})
    policy["enabled"] = stored.get("enabled", True) is True
    day = stored.get("weekly_day", 0)
    policy["weekly_day"] = day if type(day) is int and 0 <= day <= 6 else 0
    modules = stored.get("modules", {})
    for kind, values in (modules.items() if isinstance(modules, dict) else ()):
        if kind not in policy["modules"] or not isinstance(values, dict):
            continue
        for flag in ("email", "weekly"):
            if type(values.get(flag)) is bool:
                policy["modules"][kind][flag] = values[flag]
        days = values.get("days")
        if isinstance(days, list) and all(type(n) is int and 0 <= n <= 90 for n in days):
            policy["modules"][kind]["days"] = sorted(set(days), reverse=True)
    return policy


def get_user_preference(company_id, user_id):
    mode = _setting(f"notification_policy:user:{company_id}:{user_id}", {}).get("mode", "important")
    return mode if mode in {"important", "weekly", "site"} else "important"


def module_is_enabled(company_id, kind):
    module = POLICY_DEFAULTS.get(kind, {}).get("module")
    if not module:
        return kind in POLICY_DEFAULTS
    parents = {row["key"]: row.get("parent_key") for row in COMPANY_MODULE_CATALOG}
    keys = []
    while module and module not in keys:
        keys.append(module)
        module = parents.get(module)
    return not CompanyModule.query.filter(
        CompanyModule.company_id == company_id,
        CompanyModule.module_key.in_(keys), CompanyModule.is_enabled.is_(False),
    ).first()


@contextmanager
def reminder_collection(company_id, run_date, *, persist_notifications=True):
    collection = {"company_id": company_id, "run_date": run_date, "items": {},
                  "persist_notifications": persist_notifications}
    token = _collection.set(collection)
    try:
        yield collection
    finally:
        _collection.reset(token)


def collect_reminder(users, *, company_id, kind, record_id, title, message, target_url,
                     due_date=None, notification_type="warning", run_date=None,
                     email_message=None, email_details=None, created_at=None):
    from .notifications import add_user_notification, safe_notification_target_url, unique_users

    collection = _collection.get()
    if not company_id or not module_is_enabled(company_id, kind):
        return 0, 0
    target_url = safe_notification_target_url(target_url)
    if not target_url:
        return 0, 0
    created = 0
    for user in unique_users(users):
        if not user.is_active or user.company_id != company_id:
            continue
        persist = collection is None or collection.get("persist_notifications", True)
        source_key = f"{kind}:{record_id}:{due_date or 'no-date'}:u{user.id}:policy"
        notification = Notification.query.filter_by(
            company_id=company_id, user_id=user.id, source_key=source_key,
        ).first() if persist else None
        if persist and notification is None:
            notification = add_user_notification(
                user, message, company_id=company_id, source_key=source_key,
                target_url=target_url, due_date=due_date, notification_type=notification_type,
            )
            created += int(notification is not None)
        elif notification is not None:
            # Refresh the open task without manufacturing a new unread event each day.
            notification.message = message
            notification.notification_type = notification_type
            notification.target_url = target_url
        if collection is not None and collection["company_id"] == company_id:
            collection["items"][(user.id, kind, record_id)] = {
                "user_id": user.id, "kind": kind, "record_id": record_id,
                "title": title, "message": email_message or message, "target_url": target_url,
                "details": list(email_details or ()),
                "due_date": due_date, "created_at": created_at,
                "notification": notification,
            }
    return created, 0


def _hash(*parts):
    return hashlib.sha256(json.dumps(parts, ensure_ascii=True, default=str).encode()).hexdigest()


def _add_event(company_id, item, phase):
    notification = item.get("notification")
    db.session.flush()
    key = _hash(company_id, item["user_id"], item["kind"], item["record_id"], item["due_date"], phase)
    existing = NotificationEmailEvent.query.filter_by(dedupe_key=key).first()
    if existing is not None:
        return existing
    event = NotificationEmailEvent(
        company_id=company_id, user_id=item["user_id"], dedupe_key=key,
        kind=item["kind"], record_id=item["record_id"], phase=phase,
        due_date=item["due_date"], title=item["title"][:255], message=item["message"],
        target_url=item["target_url"], notification_id=notification.id if notification else None,
        status="pending",
    )
    try:
        with db.session.begin_nested():
            db.session.add(event)
            db.session.flush()
    except IntegrityError:
        return NotificationEmailEvent.query.filter_by(dedupe_key=key).first()
    return event


def queue_notification_event(notification, kind, record_id, event_type):
    if notification is None or event_type not in {"assignment", "approval", "rejected", "rescheduled", "result"}:
        return
    user = db.session.get(User, notification.user_id)
    company_id = notification.company_id
    if not user or not user.is_active or not company_id or user.company_id != company_id:
        return
    due_date = notification.due_date
    if kind in {"action", "dof"} and event_type in {"assignment", "approval", "rescheduled"}:
        from .models import Action, Dof
        record = db.session.get(Action if kind == "action" else Dof, record_id)
        if (record and record.company_id == company_id and record.effectiveness_required
                and record.effectiveness_owner_user_id == user.id
                and not record.effectiveness_checked_at
                and (record.is_completed if kind == "action" else record.approval_step == "effectiveness_review")):
            kind += "-effectiveness"
            due_date = record.effectiveness_due_date
        elif (kind == "action" and record and record.company_id == company_id
              and event_type == "approval" and record.closure_approval_requested):
            kind = "action-approval"
    if not module_is_enabled(company_id, kind):
        return
    db.session.flush()
    _add_event(company_id, {
        "user_id": user.id, "kind": kind, "record_id": record_id,
        "due_date": due_date, "title": POLICY_DEFAULTS[kind]["label"],
        "message": notification.message, "target_url": notification.target_url or "/notifications",
        "notification": notification,
    }, f"event:{event_type}:{notification.id}")


def _phase(item, policy, run_date, mode):
    rule = policy["modules"].get(item["kind"])
    if not rule or not rule["email"] or mode == "site":
        return None
    due_date = item["due_date"]
    delta = (due_date - run_date).days if due_date else None
    if mode == "important":
        if delta is not None and delta in rule["days"]:
            return f"due:{delta}"
        created_at = item.get("created_at")
        if isinstance(created_at, datetime):
            created_at = created_at.date()
        if not due_date and created_at:
            age = (run_date - created_at).days
            ages = (0, 3, 7) if item["kind"] in {"document-revision", "suggestion-approval"} else (0, 7)
            if age in ages:
                return f"age:{age}:{created_at}"
        if item["kind"].startswith("concrete-") and delta == -1:
            return "measurement-overdue:1"
    if rule["weekly"] and run_date.weekday() == policy["weekly_day"]:
        if delta is None or delta <= max(rule["days"] or [7]):
            year, week, _ = run_date.isocalendar()
            return f"weekly:{year}-{week:02d}"
    return None


def _event_current(event, collection, user):
    if not user.is_active or user.company_id != event.company_id:
        return False
    current = collection["items"].get((user.id, event.kind, event.record_id))
    if current is not None and not event.phase.startswith("event:"):
        # Rescheduled tasks must not receive reminders for the old deadline.
        return current["due_date"] == event.due_date
    if not event.phase.startswith("event:"):
        return False
    from .models import Action, ActionSubTask, Dof, DocumentRevisionRequest, ComplaintRecord

    model = {"action": Action, "action-approval": Action, "sub-action": ActionSubTask, "dof": Dof,
             "action-effectiveness": Action, "dof-effectiveness": Dof,
             "document-revision": DocumentRevisionRequest, "customer-portal": ComplaintRecord}.get(event.kind)
    record = db.session.get(model, event.record_id) if model else None
    if record is None or record.company_id != event.company_id:
        return False
    if event.kind in {"action-effectiveness", "dof-effectiveness"}:
        from .models import DOF_EFFECTIVENESS_STATUS
        return bool(record.effectiveness_required and not record.effectiveness_checked_at
                    and record.effectiveness_owner_user_id == user.id
                    and record.effectiveness_result not in {"Etkin", "Etkin Değil"}
                    and record.effectiveness_due_date == event.due_date
                    and (record.is_completed if event.kind == "action-effectiveness" else
                         record.approval_step == "effectiveness_review" and record.status == DOF_EFFECTIVENESS_STATUS))
    if event.kind == "customer-portal":
        from .reminder_sources import customer_portal_recipients
        return any(recipient.id == user.id for recipient in customer_portal_recipients(record))
    if event.kind == "action-approval":
        return bool(not record.is_completed and record.closure_approval_requested
                    and user.has_permission("actions.approve_closure"))
    if event.kind == "sub-action":
        parent = record.parent_action
        from .reminders import _is_completed_text
        return bool(parent and parent.company_id == event.company_id and not parent.is_completed
                    and not _is_completed_text(record.status) and user.id == record.responsible_id
                    and (user.has_permission("actions.request_close_assigned")
                         or user.has_permission("actions.view_all")))
    if event.kind == "action":
        if event.phase.startswith("event:result:"):
            return record.is_completed and user.id in record.participant_user_ids()
        if record.is_completed:
            return False
        if record.closure_approval_requested or event.phase.startswith("event:approval:"):
            return False
        return user.id == record.responsible_user_id and user.has_permission("actions.request_close_assigned")
    if event.kind == "dof":
        if not any(user.has_permission(key) for key in (
            "if.view_all", "if.approve_management", "if.approve_deputy", "actions.request_close_assigned",
        )):
            return False
        if event.phase.startswith("event:result:"):
            return record.approval_step == "completed" and user.id in {record.responsible_id, record.created_by_user_id}
        permissions = {"management_representative": "if.approve_management", "general_manager_deputy": "if.approve_deputy"}
        if record.approval_step in permissions:
            return event.phase.startswith("event:approval:") and user.has_permission(permissions[record.approval_step])
        return (not event.phase.startswith("event:approval:")
                and record.approval_step not in {"draft", "completed", "effectiveness_review"}
                and user.id == record.responsible_id)
    if not record.document or record.document.company_id != event.company_id or record.document.archived_at:
        return False
    if event.phase.startswith("event:result:"):
        return user.id == record.requested_by_user_id and user.has_permission("documents.view")
    return "bekleniyor" in str(record.status).casefold() and user.has_permission("documents.manage")


def _task_identity(event):
    kind = "action" if event.kind == "action-approval" else event.kind
    return kind, event.record_id


def reconcile_interrupted_batches(company_id, run_date):
    # SMTP may have accepted a message before the process stopped. Keep the
    # claim and require operator reconciliation, never blindly replay it.
    batches = NotificationEmailBatch.query.filter(
        NotificationEmailBatch.company_id == company_id,
        NotificationEmailBatch.send_date < run_date,
        NotificationEmailBatch.status.in_(("claimed", "sending")),
    ).all()
    for batch in batches:
        batch.status = "uncertain"
        batch.error_code = "interrupted_delivery"
        batch.finished_at = datetime.now(UTC).replace(tzinfo=None)
        for event in NotificationEmailEvent.query.filter_by(
            company_id=company_id, batch_id=batch.id, status="sending",
        ).all():
            event.status = "uncertain"
        current_app.logger.error("Bildirim teslimi kontrol edilmeli: company=%s batch=%s", company_id, batch.id)
    db.session.commit()


def dispatch_collection(collection, now=None):
    """Persist mail intentions before SMTP. Never equate queueing with delivery."""
    from .mail import _absolute_target_url, _mail_enabled, _mail_settings, send_mail_now

    now = now or local_now()
    if now.tzinfo is None:
        now = now.replace(tzinfo=reminder_timezone())
    now = now.astimezone(reminder_timezone())
    run_date = collection["run_date"]
    if now.date() != run_date or not (now.hour == 8 and 30 <= now.minute < 40):
        return 0
    company_id = collection["company_id"]
    company = db.session.get(Company, company_id) if company_id else None
    if not company or not company.is_active:
        return 0
    reconcile_interrupted_batches(company_id, run_date)
    policy = get_company_policy(company_id)
    if not policy["enabled"]:
        return 0
    settings = _mail_settings()
    if not _mail_enabled(settings) or settings.get("suppress_send"):
        return 0
    if collection.get("refresh_sources"):
        # Rebuild after the originating transaction committed, not from stale task snapshots.
        from .reminders import generate_due_reminders
        db.session.expire_all()
        collection = generate_due_reminders(company_id, run_date)["_collection"]
        db.session.commit()
    for item in collection["items"].values():
        phase = _phase(item, policy, run_date, get_user_preference(company_id, item["user_id"]))
        if phase:
            _add_event(company_id, item, phase)
    db.session.commit()
    pending = NotificationEmailEvent.query.filter(
        NotificationEmailEvent.company_id == company_id,
        NotificationEmailEvent.status.in_(("pending", "failed")),
        NotificationEmailEvent.attempts < 3,
    ).all()
    groups = {}
    for event in pending:
        user = db.session.get(User, event.user_id)
        rule = policy["modules"].get(event.kind, {})
        if (not user or not user.is_active or user.company_id != company_id
                or not module_is_enabled(company_id, event.kind) or not rule.get("email")
                or not _event_current(event, collection, user)):
            event.status = "cancelled"
            continue
        mode = get_user_preference(company_id, user.id)
        if mode == "site":
            event.status = "cancelled"
            continue
        if mode == "weekly" and run_date.weekday() != policy["weekly_day"]:
            continue
        if user.email:
            groups.setdefault(user.id, []).append(event)
    db.session.commit()
    sent = 0
    for user_id, events in groups.items():
        # The unique ledger prevents competing timer/web workers sending the same digest.
        batch = NotificationEmailBatch(company_id=company_id, user_id=user_id, send_date=run_date)
        try:
            db.session.add(batch)
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            continue
        db.session.expire_all()
        user = db.session.get(User, user_id)
        company = db.session.get(Company, company_id)
        policy = get_company_policy(company_id)
        mode = get_user_preference(company_id, user_id)
        if (not user or not user.is_active or user.company_id != company_id
                or not company or not company.is_active or not policy["enabled"]
                or mode == "site" or (mode == "weekly" and run_date.weekday() != policy["weekly_day"])):
            batch.status = "cancelled"
            batch.error_code = "recipient_or_policy_changed"
            db.session.commit()
            continue
        current_collection = collection
        if collection.get("refresh_sources"):
            from .reminders import generate_due_reminders
            current_collection = generate_due_reminders(
                company_id, run_date, kinds={event.kind for event in events}, persist_notifications=False,
            )["_collection"]
        distinct = {}
        for event in events:
            rule = policy["modules"].get(event.kind, {})
            if (not rule.get("email") or not module_is_enabled(company_id, event.kind)
                    or not _event_current(event, current_collection, user)):
                event.status = "cancelled"
                continue
            distinct[_task_identity(event)] = event
        lines = [f"{company.name} | İşleriniz", ""]
        valid = []
        for event in distinct.values():
            link = _absolute_target_url(event.target_url, company_id=company_id)
            if not link:
                continue
            current = current_collection["items"].get((user_id, event.kind, event.record_id))
            title = current["title"] if current else event.title
            message = current["message"] if current else event.message
            lines.extend([title, message[:600]])
            if current:
                lines.extend(f"{label}: {str(value)[:240]}" for label, value in current.get("details", ())
                             if value not in (None, ""))
                if current["due_date"]:
                    lines.append(f"Termin: {current['due_date'].strftime('%d.%m.%Y')}")
            lines.extend([f"Detayları aç: {link}", ""])
            valid.append(event)
        if not valid:
            batch.status = "cancelled"
            batch.error_code = "no_current_items_or_domain"
            db.session.commit()
            continue
        included = {_task_identity(event) for event in valid}
        for event in events:
            if event.status != "cancelled" and _task_identity(event) in included:
                event.status = "sending"
                event.batch_id = batch.id
                event.attempts += 1
        batch.item_count = len(valid)
        batch.status = "sending"
        db.session.commit()
        subject = f"[{company.name}] {len(valid)} işiniz için bildirim özeti"
        try:
            accepted = send_mail_now(settings, [user.email], subject, "\n".join(lines))
            batch.status = "accepted" if accepted else "failed"
        except (smtplib.SMTPAuthenticationError, smtplib.SMTPRecipientsRefused, smtplib.SMTPConnectError) as error:
            batch.status = "failed"
            batch.error_code = type(error).__name__
        except Exception as error:
            # An interrupted SMTP response can mean accepted mail. Do not blindly resend.
            batch.status = "uncertain"
            batch.error_code = type(error).__name__
            current_app.logger.exception("Bildirim özeti teslim sonucu belirsiz: batch=%s", batch.id)
        batch.finished_at = datetime.now(UTC).replace(tzinfo=None)
        for event in events:
            if event.batch_id != batch.id:
                continue
            event.status = batch.status
            if batch.status == "accepted":
                event.accepted_at = batch.finished_at
                if event.notification_id:
                    notification = db.session.get(Notification, event.notification_id)
                    if notification:
                        notification.email_sent_at = batch.finished_at
        from .audit import record_audit_event
        record_audit_event(
            "NotificationDelivery", batch.status, "Bildirim özeti gönderim sonucu kaydedildi.",
            entity_id=batch.id, company_id=company_id,
            details={"item_count": batch.item_count, "error_code": batch.error_code}, commit=False,
        )
        db.session.commit()
        sent += int(batch.status == "accepted")
    return sent
