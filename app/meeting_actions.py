"""Transactional links between meeting decisions and the existing Action workflow."""

from datetime import UTC, datetime

from flask import abort, g, url_for
from sqlalchemy.orm.exc import StaleDataError

from .extensions import db
from .meeting_models import MeetingDecisionAction
from .tenant import current_company_id


def can_generate(meeting):
    from .meetings import can_edit
    from .routes import current_user_can

    return can_edit(meeting) and current_user_can("can_create_actions")


def link_for_action(action):
    return MeetingDecisionAction.query.filter_by(
        action_id=action.id, company_id=action.company_id,
    ).first()


def action_info(decision):
    from .routes import can_view_action

    link = decision.action_link
    if not link or link.company_id != decision.company_id or decision.company_id != current_company_id():
        return None
    action = link.action
    # Meeting access alone must never grant access to the Action's contents.
    if not action or not can_view_action(action):
        return {"restricted": True}
    if action.is_completed:
        status = "Etkinlik Kontrolü Bekliyor" if action.effectiveness_required and action.effectiveness_result != "Etkin" else "Tamamlandı"
    else:
        status = "Kapanış Onayı Bekliyor" if action.closure_approval_requested else "Açık"
    return {"restricted": False, "number": action.number_label, "status": status,
            "url": url_for("main.action_detail", action_id=action.id),
            "owner": action.responsible_owner, "due_date": action.termin_date}


def visible_source(action):
    from .meetings import READ_PERMISSIONS, has_permission, visible_meetings

    checker = getattr(g, "company_module_enabled", None)
    if (action.company_id != current_company_id()
            or not any(has_permission(key) for key in READ_PERMISSIONS)
            or (checker and not checker("meetings"))):
        return None
    link = link_for_action(action)
    if not link:
        return None
    meeting = visible_meetings().filter_by(id=link.decision.meeting_id).first()
    return meeting


def sync_decision(action):
    """Called inside Action mutations, before notifications/commit, not during reads."""
    from .meetings import audit, snapshot, touch
    from .routes import action_is_finally_completed

    with db.session.no_autoflush:
        link = link_for_action(action)
        if not link:
            return
        decision = link.decision
        meeting = decision.meeting
        if decision.company_id != action.company_id or meeting.company_id != action.company_id:
            abort(409)
        completed = action_is_finally_completed(action)
        target = "completed" if completed else "open"
        if decision.status == target:
            return
        old, meeting_old = snapshot(decision), snapshot(meeting)
        if not completed and meeting.status == "archived":
            meeting.status = "completed"
        try:
            touch(meeting)
            decision.status = target
            decision.completed_at = datetime.now(UTC).replace(tzinfo=None) if completed else None
            decision.completion_note = "Bağlı aksiyonun kapanış süreci tamamlandı." if completed else None
            decision.version_id += 1
            db.session.flush()
        except StaleDataError:
            db.session.rollback()
            abort(409, description="Toplantı kaydı değişti; sayfayı yenileyin.")
        audit(decision, "action_completed" if completed else "action_reopened", old)
        if meeting_old["status"] != meeting.status:
            audit(meeting, "action_reopened", meeting_old)


def require_unlinked_for_delete(action):
    if link_for_action(action):
        abort(409, description="Toplantı kararına bağlı aksiyon silinemez; karar ve işlem geçmişi korunur.")
