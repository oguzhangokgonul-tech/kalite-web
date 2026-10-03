"""Current, actionable reminder sources; delivery schedules belong to policy."""

import unicodedata

from .extensions import db
from .models import (
    Action, COMPANY_MODULE_CATALOG, Company, CompanyModule, Dof,
    DocumentAcknowledgement, FmeaRecord, ProcessRecord, ChangeRequest,
    DeviationRecord, IncidentReport, KaizenProject, ProblemSolvingCase,
    HelpDeskTicket, WorkPermit, MeetingRecord, MeetingDecision, ComplaintRecord,
    QualityTestRecord, Suggestion, SuggestionScoreParameter, TrainingRecord,
    User, Vehicle, DOF_EFFECTIVENESS_STATUS, CHANGE_REQUEST_STATUS_PENDING,
    DEVIATION_STATUS_DECISION_PENDING, INCIDENT_STATUS_NEW, INCIDENT_STATUS_REVIEW,
)
from .notification_policy import collect_reminder
from .notifications import unique_users, user_has_permission


# Read access is sufficient only for an explicitly assigned task. Permission
# fallback is separately restricted to the managers who can perform the work.
SOURCE_ACCESS = {
    "action": (None, ("actions.comment_assigned", "actions.view_all", "actions.edit", "actions.request_close_assigned")),
    "action-approval": (None, ("actions.approve_closure",)),
    "sub-action": (None, ("actions.comment_assigned", "actions.view_all", "actions.edit", "actions.request_close_assigned")),
    "dof": ("if_management", ("if.view_all", "if.approve_management", "if.approve_deputy", "actions.request_close_assigned")),
    "document-revision": ("documents", ("documents.manage",)),
    "document-acknowledgement": ("documents", ("documents.view", "documents.manage")),
    "internal-audit": ("internal_audit", ("internal_audit.manage",)),
    "maintenance": ("maintenance", ("maintenance.fault_manage",)),
    "risk": ("risk_management", ("risk.view", "risk.manage")),
    "ohs-risk": ("risk_management", ("risk.ohs_view", "risk.ohs_manage", "risk.ohs_approve")),
    "training": ("training", ("training.view", "training.manage")),
    "complaint": ("suggestions", ("complaints.view", "complaints.manage")),
    "customer-portal": ("customer_feedback_portal", ("customer_portal.view",)),
    "management-review": ("management_review", ("management_review.view", "management_review.manage")),
    "supplier": ("supplier_management", ("suppliers.evaluate", "suppliers.manage")),
    "calibration": ("calibration", ("calibration.manage",)),
    "quality-objective": ("quality_objectives", ("quality_objective.view", "quality_objective.manage", "quality_objective.measure")),
    "stakeholder-review": ("stakeholder_management", ("stakeholder.view", "stakeholder.manage", "stakeholder.review")),
    "stakeholder-requirement-due": ("stakeholder_management", ("stakeholder.view", "stakeholder.manage", "stakeholder.review")),
    "compliance-review": ("compliance_management", ("compliance.view", "compliance.manage")),
    "compliance-verification": ("compliance_management", ("compliance.verify",)),
    "hazardous-sds": ("hazardous_substances", ("hazardous_substances.view", "hazardous_substances.manage")),
    "hazardous-expiry": ("hazardous_substances", ("hazardous_substances.view", "hazardous_substances.manage")),
    "hazardous-low-stock": ("hazardous_substances", ("hazardous_substances.view", "hazardous_substances.manage")),
    "environmental-aspect": ("environmental_management", ("environmental.view", "environmental.manage")),
    "environmental-waste": ("environmental_management", ("environmental.view", "environmental.manage")),
    "energy-reading": ("energy_management", ("energy.create", "energy.manage")),
    "energy-project": ("energy_management", ("energy.project_manage", "energy.approve", "energy.manage")),
    "energy-target": ("energy_management", ("energy.project_manage", "energy.approve", "energy.manage")),
    "workflow": ("workflow_designer", ("workflow.act", "workflow.manage_all")),
    "dynamic-form": ("dynamic_forms", ("dynamic_forms.respond", "dynamic_forms.manage")),
    "vehicle-insurance": ("vehicles", ("vehicles.view", "vehicles.manage", "maintenance.fault_manage", "maintenance.inventory_manage")),
    "vehicle-casco": ("vehicles", ("vehicles.view", "vehicles.manage", "maintenance.fault_manage", "maintenance.inventory_manage")),
    "vehicle-inspection": ("vehicles", ("vehicles.view", "vehicles.manage", "maintenance.fault_manage", "maintenance.inventory_manage")),
    "suggestion-approval": ("suggestions", ()),
    # This extra permission is assigned by the suggestion evaluator screen.
    "suggestion-evaluation": ("suggestions", ("suggestions.evaluate",)),
    "meeting": ("meetings", ("meetings.view", "meetings.view_all", "meetings.manage")),
    "meeting-decision": ("meetings", ("meetings.decide", "meetings.manage")),
    "concrete-2": ("quality_test_concrete", ("quality.create", "quality.parameters_manage")),
    "concrete-7": ("quality_test_concrete", ("quality.create", "quality.parameters_manage")),
    "concrete-28": ("quality_test_concrete", ("quality.create", "quality.parameters_manage")),
    "action-effectiveness": (None, ("actions.request_close_assigned", "actions.view_all", "actions.edit")),
    "dof-effectiveness": ("if_management", ("if.view_all", "if.approve_management", "actions.request_close_assigned")),
    "process-review": ("process_management", ("process.view", "process.manage")),
    "fmea": ("fmea_management", ("fmea.view", "fmea.manage", "fmea.close")),
    "change": ("change_management", ("change_management.view", "change_management.manage", "change_management.approve")),
    "deviation": ("deviation_management", ("deviation.view", "deviation.manage", "deviation.approve")),
    "incident": ("incident_near_miss", ("incident.view", "incident.manage", "incident.review")),
    "kaizen": ("kaizen_management", ("kaizen.update", "kaizen.manage")),
    "problem-step": ("problem_solving", ("problem_solving.update", "problem_solving.manage")),
    "problem-approval": ("problem_solving", ("problem_solving.review", "problem_solving.manage")),
    "helpdesk": ("help_desk", ("helpdesk.work", "helpdesk.manage", "helpdesk.assign")),
    "helpdesk-acceptance": ("help_desk", ("helpdesk.view", "helpdesk.manage")),
    "work-permit-approval": ("work_permits", ("work_permits.approve", "work_permits.manage")),
}


def company_query(model, company_id):
    return model.query.filter(model.company_id == company_id)


def source_module_enabled(company_id, kind):
    if kind not in SOURCE_ACCESS:
        return False
    if company_id is not None:
        company = db.session.get(Company, company_id)
        if company is None or not company.is_active:
            return False
    module_key = SOURCE_ACCESS[kind][0]
    parents = {row["key"]: row.get("parent_key") for row in COMPANY_MODULE_CATALOG}
    while module_key:
        setting = company_query(CompanyModule, company_id).filter_by(module_key=module_key).first()
        if setting is not None and not setting.is_enabled:
            return False
        module_key = parents.get(module_key)
    return True


def strict_recipients(company_id, user_ids=(), permission_keys=()):
    ids = {user_id for user_id in user_ids if user_id}
    query = company_query(User, company_id).filter(User.is_active.is_(True))
    if ids:
        return query.filter(User.id.in_(ids)).all()
    if not permission_keys:
        return []
    return [user for user in query.all()
            if any(user_has_permission(user, key) for key in permission_keys)]


def eligible_recipients(users, company_id, kind):
    if not source_module_enabled(company_id, kind):
        return []
    permissions = SOURCE_ACCESS[kind][1]
    result = []
    for user in unique_users(users):
        if not user.is_active or user.company_id != company_id:
            continue
        if user.has_role("viewer") and user.role_keys <= {"viewer"}:
            continue
        if kind == "suggestion-approval":
            allowed = user.has_role("management_representative") or user.has_role("super_admin")
        elif kind in {"action-effectiveness", "dof-effectiveness"}:
            # These builders select only the explicitly assigned reviewer;
            # the review routes authorize that assignment directly.
            allowed = True
        else:
            allowed = any(user_has_permission(user, key) for key in permissions)
        # These blueprints separately require read access to the linked detail page.
        detail_prefix = {
            "kaizen": "kaizen", "problem-step": "problem_solving",
            "problem-approval": "problem_solving", "helpdesk": "helpdesk",
            "helpdesk-acceptance": "helpdesk", "work-permit-approval": "work_permits",
        }.get(kind)
        if detail_prefix:
            allowed = allowed and any(user_has_permission(user, f"{detail_prefix}.{suffix}")
                                      for suffix in ("view", "view_all", "manage"))
        if allowed:
            result.append(user)
    return result


def linked_action_duplicates(action, company_id, owner_id, due_date):
    return bool(action and action.company_id == company_id
                and action.responsible_user_id == owner_id and action.termin_date == due_date)


def _closed(row):
    if getattr(row, "archived_at", None) or getattr(row, "is_closed", False):
        return True
    status = unicodedata.normalize("NFKD", (getattr(row, "status", None) or "").casefold())
    status = "".join(char for char in status if not unicodedata.combining(char))
    if "onay" in status or "bekli" in status:
        return False
    return any(word in status for word in (
        "tamam", "iptal", "arsiv", "kapand", "kapat", "redded", "sonucland",
        "completed", "cancelled", "archived", "closed", "rejected", "taslak", "draft",
    ))


def _collect(stats, users, *, company_id, run_date, kind, row, title,
             target_url, due_date=None, record_id=None, created_at=None):
    users = eligible_recipients(users, company_id, kind)
    if not users:
        return
    created, _ = collect_reminder(
        users, company_id=company_id, kind=kind,
        record_id=row.id if record_id is None else record_id,
        title=title, message=title, target_url=target_url, due_date=due_date,
        notification_type="danger" if due_date and due_date < run_date else "warning",
        run_date=run_date, created_at=created_at or getattr(row, "created_at", None),
    )
    stats["notifications"] += created


def vehicle_reminders(company_id, run_date):
    stats = {"notifications": 0, "emails": 0}
    if not source_module_enabled(company_id, "vehicle-insurance"):
        return stats
    for row in company_query(Vehicle, company_id).all():
        users = strict_recipients(company_id, [user.id for user in row.reminder_recipients],
                                  ("vehicles.manage", "maintenance.inventory_manage"))
        for kind, label, due in (
            ("vehicle-insurance", "Trafik sigortasi", row.traffic_insurance_due_date),
            ("vehicle-casco", "Kasko", row.casco_insurance_due_date),
            ("vehicle-inspection", "Muayene", row.next_inspection_due_date),
        ):
            if due:
                _collect(stats, users, company_id=company_id, run_date=run_date, kind=kind,
                         row=row, title=f"{row.plate}: {label}", target_url="/arac-yonetimi", due_date=due)
    return stats


def suggestion_reminders(company_id, run_date):
    stats = {"notifications": 0, "emails": 0}
    if not source_module_enabled(company_id, "suggestion-approval"):
        return stats
    users = company_query(User, company_id).filter(User.is_active.is_(True)).all()
    approvers = eligible_recipients(users, company_id, "suggestion-approval")
    evaluators = eligible_recipients(users, company_id, "suggestion-evaluation")
    required = {row.id for row in company_query(SuggestionScoreParameter, company_id).filter_by(is_active=True).all()}
    for row in company_query(Suggestion, company_id).all():
        if row.status == "Y\u00f6netim Temsilcisi Onay\u0131 Bekleniyor":
            kind, recipients = "suggestion-approval", approvers
        elif row.status == "De\u011ferlendirmede" and required:
            kind = "suggestion-evaluation"
            recipients = []
            for user in evaluators:
                rated = {item.parameter_id for item in row.evaluations
                         if item.company_id == company_id and item.evaluator_user_id == user.id
                         and 1 <= item.rating <= 10}
                if not required.issubset(rated):
                    recipients.append(user)
        else:
            continue
        _collect(stats, recipients, company_id=company_id, run_date=run_date, kind=kind, row=row,
                 title=f"{row.number_label}: {'Onay' if kind == 'suggestion-approval' else 'Degerlendirme'} bekliyor",
                 target_url=f"/oneri-sikayet/oneri/{row.id}")
    return stats


def document_acknowledgement_reminders(company_id, run_date):
    stats = {"notifications": 0, "emails": 0}
    if not source_module_enabled(company_id, "document-acknowledgement") or not source_module_enabled(company_id, "training"):
        return stats
    for row in company_query(TrainingRecord, company_id).filter_by(training_type="Dok\u00fcman Okuma Onay\u0131").all():
        document = row.document
        if _closed(row) or not document or document.company_id != company_id or _closed(document):
            continue
        revision = (document.revision_no or "").strip()
        if (row.document_revision_no_snapshot or "").strip() != revision:
            continue
        acknowledged = {item.user_id for item in company_query(DocumentAcknowledgement, company_id).filter_by(
            document_id=document.id, revision_no_snapshot=revision,
        ).all()}
        pending = [item.user_id for item in row.participants
                   if item.company_id == company_id and not item.is_completed
                   and not item.read_confirmed_at and item.user_id not in acknowledged]
        _collect(stats, strict_recipients(company_id, pending), company_id=company_id, run_date=run_date,
                 kind="document-acknowledgement", row=row,
                 title=f"{document.document_code}: Okuma onayi bekliyor",
                 target_url=f"/documents/{document.id}", due_date=row.due_date)
    return stats


def meeting_reminders(company_id, run_date):
    stats = {"notifications": 0, "emails": 0}
    if not source_module_enabled(company_id, "meeting"):
        return stats
    for row in company_query(MeetingRecord, company_id).filter_by(status="open").all():
        due = row.meeting_at.date()
        if due < run_date:
            continue
        users = strict_recipients(company_id, [item.user_id for item in row.participants if item.company_id == company_id])
        _collect(stats, users, company_id=company_id, run_date=run_date, kind="meeting", row=row,
                 title=f"Toplanti daveti: {row.title}", target_url=f"/toplantilar/{row.id}", due_date=due)
    for row in company_query(MeetingDecision, company_id).filter_by(status="open").all():
        if not row.meeting or row.meeting.company_id != company_id or row.meeting.status not in {"open", "completed"}:
            continue
        if (row.action_link and row.action_link.company_id == company_id
                and row.action_link.action is not None):
            continue
        _collect(stats, strict_recipients(company_id, [row.owner_user_id]), company_id=company_id,
                 run_date=run_date, kind="meeting-decision", row=row, title=f"Toplanti karari: {row.title}",
                 target_url=f"/toplantilar/{row.meeting_id}", due_date=row.due_date,
                 created_at=row.meeting.created_at)
    return stats


def concrete_reminders(company_id, run_date):
    stats = {"notifications": 0, "emails": 0}
    if not source_module_enabled(company_id, "concrete-2"):
        return stats
    for row in company_query(QualityTestRecord, company_id).filter_by(test_type="beton-deneyi").all():
        if _closed(row):
            continue
        # The model has no assigned measurement owner; creation is not assignment.
        users = strict_recipients(company_id, permission_keys=("quality.create", "quality.parameters_manage"))
        day = row.current_measurement_day
        if day is not None:
            _collect(stats, users, company_id=company_id, run_date=run_date, kind=f"concrete-{day}", row=row,
                     title=f"{row.number_label}: {day} gunluk olcum bekliyor",
                     target_url=f"/kalite-deneyleri/beton-deneyi/{row.id}/olcum", due_date=row.measurement_due_date(day))
    return stats


def effectiveness_reminders(company_id, run_date):
    stats = {"notifications": 0, "emails": 0}
    for model, kind, path in ((Action, "action-effectiveness", "actions"), (Dof, "dof-effectiveness", "dofs")):
        if not source_module_enabled(company_id, kind):
            continue
        rows = company_query(model, company_id).filter(
            model.effectiveness_required.is_(True), model.effectiveness_checked_at.is_(None),
            model.effectiveness_due_date.isnot(None),
        ).all()
        for row in rows:
            if model is Action and not row.is_completed:
                continue
            if row.effectiveness_result in {"Etkin", "Etkin De\u011fil"}:
                continue
            if model is Dof and (row.approval_step != "effectiveness_review"
                                 or row.status != DOF_EFFECTIVENESS_STATUS):
                continue
            _collect(stats, strict_recipients(company_id, [row.effectiveness_owner_user_id]),
                     company_id=company_id, run_date=run_date, kind=kind, row=row,
                     title=f"Etkinlik kontrolu: {row.title}", target_url=f"/{path}/{row.id}",
                     due_date=row.effectiveness_due_date)
    return stats


def additional_due_reminders(company_id, run_date):
    stats = {"notifications": 0, "emails": 0}
    sources = (
        (ProcessRecord, "process-review", "next_review_date", "owner_user_id", "process.manage", "/surec-yonetimi/{id}", "title"),
        (FmeaRecord, "fmea", "due_date", "responsible_user_id", "fmea.manage", "/fmea/{id}", "failure_mode"),
        (ChangeRequest, "change", "due_date", "responsible_user_id", "change_management.manage", "/degisiklik-yonetimi/{id}", "title"),
        (DeviationRecord, "deviation", "due_date", "responsible_user_id", "deviation.manage", "/sapma-uygunsuz-urun/{id}", "title"),
        (IncidentReport, "incident", "due_date", "responsible_user_id", "incident.manage", "/olay-ramak-kala/{id}", "title"),
        (KaizenProject, "kaizen", "target_date", "owner_user_id", "kaizen.manage", "/kaizen/{id}", "title"),
    )
    for model, kind, date_field, owner_field, fallback, path, title_field in sources:
        if not source_module_enabled(company_id, kind):
            continue
        for row in company_query(model, company_id).all():
            if _closed(row):
                continue
            due = getattr(row, date_field)
            if kind == "process-review" and due is None:
                continue
            owner_id = getattr(row, owner_field)
            permission = fallback
            if ((kind == "change" and row.status == CHANGE_REQUEST_STATUS_PENDING)
                    or (kind == "deviation" and row.status == DEVIATION_STATUS_DECISION_PENDING)):
                owner_id = row.approver_user_id
                permission = "change_management.approve" if kind == "change" else "deviation.approve"
            elif kind == "incident" and row.status in {INCIDENT_STATUS_NEW, INCIDENT_STATUS_REVIEW}:
                owner_id = row.reviewer_user_id
                permission = "incident.review"
            if (kind != "process-review" and permission == fallback
                    and linked_action_duplicates(row.action, company_id, owner_id, due)):
                continue
            users = strict_recipients(company_id, [owner_id], (permission,))
            if permission != fallback:
                users = [user for user in users if user_has_permission(user, permission)]
            _collect(stats, users, company_id=company_id,
                     run_date=run_date, kind=kind, row=row, title=f"Bekleyen is: {getattr(row, title_field)}",
                     target_url=path.format(id=row.id), due_date=due)
    return stats


def pending_work_reminders(company_id, run_date):
    stats = {"notifications": 0, "emails": 0}
    if source_module_enabled(company_id, "problem-step"):
        for row in company_query(ProblemSolvingCase, company_id).all():
            if _closed(row):
                continue
            step = next((item for item in row.steps if item.step_order == row.current_step and item.company_id == company_id), None)
            if not step or step.status == "Onayland\u0131":
                continue
            approval = step.status == "\u0130nceleme Bekliyor"
            owner_id = row.reviewer_user_id if approval else step.owner_user_id or row.leader_user_id
            if not approval and linked_action_duplicates(row.action, company_id, owner_id, step.due_date):
                continue
            _collect(stats, strict_recipients(company_id, [owner_id]), company_id=company_id,
                     run_date=run_date, kind="problem-approval" if approval else "problem-step", row=step,
                     title=f"{row.case_no}: {step.title}", target_url=f"/problem-cozme/{row.id}",
                     due_date=step.due_date, created_at=step.submitted_at if approval else step.created_at)
    if source_module_enabled(company_id, "helpdesk"):
        for row in company_query(HelpDeskTicket, company_id).all():
            if _closed(row):
                continue
            acceptance = row.status == "\u00c7\u00f6z\u00fcm Bekliyor"
            owner_id = row.requester_user_id if acceptance else row.assignee_user_id
            _collect(stats, strict_recipients(company_id, [owner_id], ("helpdesk.assign", "helpdesk.manage")),
                     company_id=company_id, run_date=run_date, kind="helpdesk-acceptance" if acceptance else "helpdesk",
                     row=row, title=f"{row.ticket_no}: {row.title}", target_url=f"/ic-talepler/{row.id}",
                     due_date=row.sla_due_at.date())
    if source_module_enabled(company_id, "work-permit-approval"):
        for row in company_query(WorkPermit, company_id).filter_by(status="Onay Bekliyor").all():
            if _closed(row):
                continue
            _collect(stats, strict_recipients(company_id, [row.approver_user_id]), company_id=company_id,
                     run_date=run_date, kind="work-permit-approval", row=row,
                     title=f"{row.permit_no}: Onay bekliyor", target_url=f"/is-izinleri/{row.id}",
                     due_date=row.requested_start_at.date(), created_at=row.submitted_at)
    return stats


def collect_additional_sources(company_id, run_date, *, kinds=None):
    stats = {"notifications": 0, "emails": 0}
    builders = (
        ({"vehicle-insurance", "vehicle-casco", "vehicle-inspection"}, vehicle_reminders),
        ({"suggestion-approval", "suggestion-evaluation"}, suggestion_reminders),
        ({"document-acknowledgement"}, document_acknowledgement_reminders),
        ({"meeting", "meeting-decision"}, meeting_reminders),
        ({"concrete-2", "concrete-7", "concrete-28"}, concrete_reminders),
        ({"action-effectiveness", "dof-effectiveness"}, effectiveness_reminders),
        ({"process-review", "fmea", "change", "deviation", "incident", "kaizen"}, additional_due_reminders),
        ({"problem-step", "problem-approval", "helpdesk", "helpdesk-acceptance", "work-permit-approval"}, pending_work_reminders),
        ({"customer-portal"}, customer_portal_reminders),
    )
    for source_kinds, builder in builders:
        if kinds is not None and source_kinds.isdisjoint(kinds):
            continue
        stats["notifications"] += builder(company_id, run_date)["notifications"]
    return stats


def customer_portal_recipients(record):
    if (record.source != "Müşteri Portalı" or not record.email_verified_at
            or record.is_archived or _closed(record)):
        return []
    if record.responsible_user_id:
        users = strict_recipients(record.company_id, [record.responsible_user_id])
    else:
        users = strict_recipients(record.company_id, permission_keys=(
            "customer_portal.assign", "customer_portal.triage",
        ))
        # Department triage alone does not grant access to every portal record.
        from .customer_portal import _user_matches_department
        users = [user for user in users if user.has_permission("customer_portal.assign")
                 or not user.has_role("department_manager")
                 or _user_matches_department(user, record.department)]
    return eligible_recipients(users, record.company_id, "customer-portal")


def customer_portal_reminders(company_id, run_date):
    stats = {"notifications": 0, "emails": 0}
    if not source_module_enabled(company_id, "customer-portal"):
        return stats
    for row in company_query(ComplaintRecord, company_id).filter_by(source="Müşteri Portalı").all():
        users = customer_portal_recipients(row)
        if not users:
            continue
        deadline = row.first_response_due_at if not row.first_response_at else row.resolution_due_at
        due = deadline.date() if deadline else row.due_date
        _collect(stats, users, company_id=company_id, run_date=run_date, kind="customer-portal",
                 row=row, title=f"{row.complaint_no}: Müşteri geri bildirimi işlem bekliyor",
                 target_url=f"/musteri-geri-bildirimleri/{row.id}", due_date=due,
                 created_at=row.email_verified_at)
    return stats
