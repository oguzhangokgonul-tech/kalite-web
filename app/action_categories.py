"""Availability of action categories, shared by UI and background jobs."""

from sqlalchemy import String, cast, or_

from .models import Action, ActionSubTask, CompanyModule, Notification


def action_module_available(action):
    if action.action_category != "ohs":
        return True
    if not action.company_id:
        return False
    setting = CompanyModule.query.filter_by(
        company_id=action.company_id, module_key="ohs_actions"
    ).first()
    return setting is None or setting.is_enabled


def available_actions_clause():
    disabled = CompanyModule.query.with_entities(CompanyModule.company_id).filter(
        CompanyModule.module_key == "ohs_actions", CompanyModule.is_enabled.is_(False)
    )
    return or_(
        Action.action_category == "general",
        (Action.action_category == "ohs")
        & Action.company_id.isnot(None)
        & ~Action.company_id.in_(disabled),
    )


def available_notifications_clause():
    # Reminder notifications may reference an action URL without an action_id.
    target = "/actions/" + cast(Action.id, String)
    unavailable = Action.query.filter(~available_actions_clause()).filter(
        or_(
            Notification.action_id == Action.id,
            Notification.target_url == target,
            Notification.target_url.like(target + "/%"),
            Notification.target_url.like(target + "?%"),
            Notification.target_url.like(target + "#%"),
        )
    ).exists()
    sub_target = "/sub-actions/" + cast(ActionSubTask.id, String)
    unavailable_sub = ActionSubTask.query.join(Action).filter(
        ~available_actions_clause(),
        or_(
            Notification.target_url == sub_target,
            Notification.target_url.like(sub_target + "/%"),
            Notification.target_url.like(sub_target + "?%"),
            Notification.target_url.like(sub_target + "#%"),
        ),
    ).exists()
    return ~unavailable & ~unavailable_sub
