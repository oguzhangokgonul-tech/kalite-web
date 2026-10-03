from datetime import date, datetime, timedelta

import pytest

from app import reminder_sources as sources
from app.extensions import db
from app.models import (
    Action, Company, CompanyModule, COMPANY_MODULE_CATALOG, ChangeRequest,
    DeviationRecord, Document, DocumentAcknowledgement, DocumentCategory, Dof,
    DOF_EFFECTIVENESS_STATUS, FmeaRecord, HelpDeskTicket, IncidentReport,
    KaizenProject, MeetingDecision, MeetingDecisionAction, MeetingParticipant,
    MeetingRecord, ProcessRecord, ProblemSolvingCase, ProblemSolvingStep,
    QualityTestRecord, Role, Suggestion, SuggestionEvaluation,
    SuggestionScoreParameter, TrainingParticipant, TrainingRecord, User,
    UserPermission, Vehicle, WorkPermit,
)
from app.seed import PERMISSION_CATALOG


DAY = date(2026, 10, 5)
NOW = datetime(2026, 10, 5, 9)


@pytest.fixture()
def company(app):
    row = Company(code="sources", slug="sources", name="Sources", is_active=True)
    db.session.add(row)
    db.session.flush()
    return row


@pytest.fixture()
def user_factory(company):
    def create(name, *permissions, company_id=None, active=True, role=None):
        user = User(company_id=company.id if company_id is None else company_id,
                    username=name, full_name=name, password_hash="unused", is_active=active)
        user.extra_permissions = [UserPermission(permission_key=key) for key in permissions]
        if role:
            user.roles.append(Role.query.filter_by(key=role).one())
        db.session.add(user)
        db.session.flush()
        return user
    return create


@pytest.fixture()
def captured(monkeypatch, app):
    calls = []

    def collect(users, **kwargs):
        # Assert each generated target really resolves to a GET route.
        app.url_map.bind("localhost").match(kwargs["target_url"], method="GET")
        calls.append(dict(kwargs, user_ids={user.id for user in users}))
        return len(users), 0

    monkeypatch.setattr(sources, "collect_reminder", collect)
    return calls


def persist(row):
    db.session.add(row)
    db.session.flush()
    return row


def action(company, user, **overrides):
    fields = dict(company_id=company.id, title="Action", responsible_owner=user.full_name,
                  responsible_user_id=user.id, termin_date=DAY)
    return persist(Action(**dict(fields, **overrides)))


def vehicle(company, **overrides):
    fields = dict(company_id=company.id, plate="34 TEST", brand="Brand", model="Model",
                  owner="Fleet", traffic_insurance_due_date=DAY,
                  casco_insurance_due_date=DAY, next_inspection_due_date=DAY)
    return persist(Vehicle(**dict(fields, **overrides)))


def test_access_keys_match_real_modules_and_permissions():
    # Suggestion evaluation is an extra permission maintained outside the catalog.
    permissions = {row["key"] for row in PERMISSION_CATALOG} | {"suggestions.evaluate"}
    modules = {row["key"] for row in COMPANY_MODULE_CATALOG}
    for kind, (module, keys) in sources.SOURCE_ACCESS.items():
        assert module is None or module in modules, kind
        assert set(keys) <= permissions, kind


def test_vehicle_explicit_recipients_are_not_replaced(company, user_factory, captured):
    owner = user_factory("owner", "vehicles.view")
    manager = user_factory("manager", "vehicles.manage")
    inactive = user_factory("inactive", "vehicles.view", active=False)
    viewer = user_factory("viewer", "vehicles.view", role="viewer")
    other = persist(Company(code="other", slug="other", name="Other"))
    foreign = user_factory("foreign", "vehicles.view", company_id=other.id)
    row = vehicle(company, reminder_recipients=[owner, inactive, viewer, foreign])
    assert sources.vehicle_reminders(company.id, DAY)["notifications"] == 3
    assert {item["kind"] for item in captured} == {
        "vehicle-insurance", "vehicle-casco", "vehicle-inspection"}
    assert all(item["user_ids"] == {owner.id} for item in captured)
    captured.clear()
    row.reminder_recipients = [inactive, foreign]
    db.session.flush()
    sources.vehicle_reminders(company.id, DAY)
    assert captured == []
    assert manager.id not in {owner.id}


def test_vehicle_unassigned_uses_real_management_permissions(company, user_factory, captured):
    manager = user_factory("inventory", "maintenance.inventory_manage")
    user_factory("reader", "vehicles.view")
    vehicle(company)
    sources.vehicle_reminders(company.id, DAY)
    assert len(captured) == 3
    assert all(item["user_ids"] == {manager.id} for item in captured)


@pytest.mark.parametrize("disable_company", [False, True])
def test_vehicle_disabled_scope(company, user_factory, captured, disable_company):
    user_factory("manager", "vehicles.manage")
    vehicle(company)
    if disable_company:
        company.is_active = False
    else:
        persist(CompanyModule(company_id=company.id, module_key="vehicles", is_enabled=False))
    sources.vehicle_reminders(company.id, DAY)
    assert captured == []


def test_suggestion_approval_and_only_incomplete_evaluations(company, user_factory, captured):
    approver = user_factory("approver", role="management_representative")
    complete = user_factory("complete", "suggestions.evaluate")
    partial = user_factory("partial", "suggestions.evaluate")
    creator = user_factory("creator")
    parameters = [persist(SuggestionScoreParameter(company_id=company.id, name=f"P{i}"))
                  for i in range(2)]
    pending = persist(Suggestion(company_id=company.id, owner_name="Owner", definition="Pending",
                                 status="Y\u00f6netim Temsilcisi Onay\u0131 Bekleniyor",
                                 created_by_user_id=creator.id))
    evaluating = persist(Suggestion(company_id=company.id, owner_name="Owner", definition="Evaluate",
                                    status="De\u011ferlendirmede"))
    persist(Suggestion(company_id=company.id, owner_name="Owner", definition="Done",
                       status="De\u011ferlendirme Tamamland\u0131"))
    for user, ratings in ((complete, (5, 10)), (partial, (5, 0))):
        for parameter, rating in zip(parameters, ratings):
            persist(SuggestionEvaluation(company_id=company.id, suggestion_id=evaluating.id,
                                         parameter_id=parameter.id, parameter_name=parameter.name,
                                         evaluator_department="Quality", evaluator_user_id=user.id,
                                         rating=rating))
    sources.suggestion_reminders(company.id, DAY)
    approvals = [item for item in captured if item["kind"] == "suggestion-approval"]
    evaluations = [item for item in captured if item["kind"] == "suggestion-evaluation"]
    assert len(approvals) == len(evaluations) == 1
    assert approvals[0]["record_id"] == pending.id
    assert approvals[0]["user_ids"] == {approver.id}
    assert evaluations[0]["record_id"] == evaluating.id
    assert partial.id in evaluations[0]["user_ids"]
    assert not evaluations[0]["user_ids"] & {complete.id, creator.id}
    captured.clear()
    for parameter in parameters:
        parameter.is_active = False
    sources.suggestion_reminders(company.id, DAY)
    assert all(item["kind"] == "suggestion-approval" for item in captured)


def reading_training(company, **overrides):
    category = persist(DocumentCategory(company_id=company.id, code="P", name="Procedures", slug="p"))
    document = persist(Document(company_id=company.id, category=category, document_code="P-1",
                                title="Procedure", revision_no="02", file_name="p.pdf",
                                original_file_name="p.pdf", file_path="p.pdf"))
    fields = dict(company_id=company.id, training_no="READ-1", title="Read", document=document,
                  document_revision_no_snapshot="02", training_type="Dok\u00fcman Okuma Onay\u0131",
                  status="Planland\u0131", due_date=DAY)
    return persist(TrainingRecord(**dict(fields, **overrides)))


def test_document_acknowledgement_current_revision_and_pending_participants(company, user_factory, captured):
    row = reading_training(company)
    pending = user_factory("pending", "documents.view")
    acknowledged = user_factory("acknowledged", "documents.view")
    completed = user_factory("completed", "documents.view")
    confirmed = user_factory("confirmed", "documents.view")
    for user in (pending, acknowledged, completed, confirmed):
        persist(TrainingParticipant(company_id=company.id, training=row, user_id=user.id,
                                    status="Okundu" if user == completed else "Atand\u0131",
                                    read_confirmed_at=NOW if user == confirmed else None))
    for user, revision in ((pending, "01"), (acknowledged, "02")):
        persist(DocumentAcknowledgement(company_id=company.id, document=row.document,
                                        user_id=user.id, document_code_snapshot="P-1",
                                        document_title_snapshot="Procedure", revision_no_snapshot=revision))
    sources.document_acknowledgement_reminders(company.id, DAY)
    assert len(captured) == 1
    assert captured[0]["user_ids"] == {pending.id}
    assert captured[0]["target_url"] == f"/documents/{row.document_id}"
    captured.clear()
    row.document.revision_no = "03"
    sources.document_acknowledgement_reminders(company.id, DAY)
    assert captured == []


@pytest.mark.parametrize("reason", ["archived", "closed", "training-disabled", "foreign-document"])
def test_document_acknowledgement_safety(company, user_factory, captured, reason):
    row = reading_training(company)
    user = user_factory("pending", "documents.view")
    persist(TrainingParticipant(company_id=company.id, training=row, user_id=user.id))
    if reason == "archived":
        row.document.archived_at = NOW
    elif reason == "closed":
        row.status = "Tamamland\u0131"
    elif reason == "training-disabled":
        persist(CompanyModule(company_id=company.id, module_key="training", is_enabled=False))
    else:
        other = persist(Company(code="other", slug="other", name="Other"))
        row.document.company_id = other.id
    sources.document_acknowledgement_reminders(company.id, DAY)
    assert captured == []


@pytest.mark.parametrize("changed", ["owner", "date", "both", "completed"])
def test_linked_meeting_decision_always_suppressed(company, user_factory, captured, changed):
    owner = user_factory("owner", "meetings.view", "meetings.decide")
    new_owner = user_factory("new-owner", "meetings.view", "meetings.decide")
    meeting = persist(MeetingRecord(company_id=company.id, title="Meeting", meeting_at=NOW,
                                    status="completed", created_by_user_id=owner.id))
    decision = persist(MeetingDecision(company_id=company.id, meeting=meeting, title="Decision",
                                        owner_user_id=owner.id, due_date=DAY))
    linked = action(company, owner)
    persist(MeetingDecisionAction(company_id=company.id, decision=decision, action=linked,
                                   created_by_user_id=owner.id))
    if changed in {"owner", "both"}:
        linked.responsible_user_id = new_owner.id
    if changed in {"date", "both"}:
        linked.termin_date += timedelta(days=10)
    if changed == "completed":
        linked.is_completed = True
    sources.meeting_reminders(company.id, DAY)
    assert captured == []


def test_meeting_invitation_and_unlinked_decision(company, user_factory, captured):
    owner = user_factory("owner", "meetings.view", "meetings.decide")
    meeting = persist(MeetingRecord(company_id=company.id, title="Meeting", meeting_at=NOW,
                                    status="open", created_by_user_id=owner.id))
    persist(MeetingParticipant(company_id=company.id, meeting=meeting, user_id=owner.id))
    persist(MeetingDecision(company_id=company.id, meeting=meeting, title="Decision",
                            owner_user_id=owner.id, due_date=DAY))
    sources.meeting_reminders(company.id, DAY)
    assert {item["kind"] for item in captured} == {"meeting", "meeting-decision"}
    captured.clear()
    meeting.meeting_at -= timedelta(days=1)
    sources.meeting_reminders(company.id, DAY)
    assert [item["kind"] for item in captured] == ["meeting-decision"]
    captured.clear()
    meeting.status = "archived"
    sources.meeting_reminders(company.id, DAY)
    assert captured == []


def test_concrete_real_fields_next_measurement_and_not_creator_assignment(company, user_factory, captured):
    creator = user_factory("creator")
    worker = user_factory("worker", "quality.create")
    parameters = user_factory("parameters", "quality.parameters_manage")
    row = persist(QualityTestRecord(company_id=company.id, test_type="beton-deneyi", title="Concrete",
                                    record_date=DAY, created_by_user_id=creator.id))
    persist(QualityTestRecord(company_id=company.id, test_type="elek-analizi", title="Other"))
    for day in (2, 7, 28):
        captured.clear()
        sources.concrete_reminders(company.id, DAY)
        assert len(captured) == 1
        assert captured[0]["kind"] == f"concrete-{day}"
        assert captured[0]["user_ids"] == {worker.id, parameters.id}
        assert captured[0]["due_date"] == DAY + timedelta(days=day)
        setattr(row, f"strength_{day}_day", 0)
    captured.clear()
    sources.concrete_reminders(company.id, DAY)
    assert captured == []


def test_concrete_disabled_parent(company, user_factory, captured):
    user_factory("worker", "quality.create")
    persist(QualityTestRecord(company_id=company.id, test_type="beton-deneyi", title="Concrete"))
    persist(CompanyModule(company_id=company.id, module_key="quality_tests", is_enabled=False))
    sources.concrete_reminders(company.id, DAY)
    assert captured == []


def test_effectiveness_uses_assigned_reviewer_and_actual_dof_stage(company, user_factory, captured):
    owner = user_factory("owner")
    creator = user_factory("creator", "actions.edit", "if.view_all")
    shared = dict(effectiveness_required=True, effectiveness_due_date=DAY,
                  effectiveness_owner_user_id=owner.id, effectiveness_result="Bekliyor")
    a = action(company, creator, is_completed=True, **shared)
    d = persist(Dof(company_id=company.id, dof_no="IF-1", title="Dof",
                    status=DOF_EFFECTIVENESS_STATUS, approval_step="effectiveness_review", **shared))
    sources.effectiveness_reminders(company.id, DAY)
    assert {item["kind"] for item in captured} == {"action-effectiveness", "dof-effectiveness"}
    assert all(item["user_ids"] == {owner.id} for item in captured)
    captured.clear()
    a.effectiveness_checked_at = NOW
    d.approval_step = "completed"
    sources.effectiveness_reminders(company.id, DAY)
    assert captured == []


@pytest.mark.parametrize("reason", ["unfinished", "done-result", "inactive-owner", "no-owner", "foreign-owner"])
def test_effectiveness_safety(company, user_factory, captured, reason):
    owner = user_factory("owner", "actions.edit")
    row = action(company, owner, is_completed=True, effectiveness_required=True,
                 effectiveness_due_date=DAY, effectiveness_owner_user_id=owner.id)
    if reason == "unfinished":
        row.is_completed = False
    elif reason == "done-result":
        row.effectiveness_result = "Etkin De\u011fil"
    elif reason == "inactive-owner":
        owner.is_active = False
    elif reason == "no-owner":
        row.effectiveness_owner_user_id = None
    else:
        other = persist(Company(code="other", slug="other", name="Other"))
        owner.company_id = other.id
    sources.effectiveness_reminders(company.id, DAY)
    assert captured == []


def test_additional_due_sources_real_records_and_stage_owners(company, user_factory, captured):
    owner = user_factory("owner", "process.view", "fmea.view", "change_management.view",
                         "deviation.view", "incident.view", "kaizen.update", "kaizen.view")
    reviewer = user_factory("reviewer", "change_management.approve", "deviation.approve", "incident.review")
    persist(ProcessRecord(company_id=company.id, process_no="P-1", title="Process", status="Aktif",
                           next_review_date=DAY, owner_user_id=owner.id))
    persist(FmeaRecord(company_id=company.id, fmea_no="F-1", process_name="Process",
                        failure_mode="Failure", due_date=DAY, responsible_user_id=owner.id))
    change = persist(ChangeRequest(company_id=company.id, change_no="C-1", title="Change",
                                    status="Onayland\u0131", due_date=DAY,
                                    responsible_user_id=owner.id, approver_user_id=reviewer.id))
    persist(DeviationRecord(company_id=company.id, deviation_no="D-1", title="Deviation",
                             status="Karar Bekliyor", due_date=DAY,
                             responsible_user_id=owner.id, approver_user_id=reviewer.id))
    persist(IncidentReport(company_id=company.id, incident_no="I-1", title="Incident",
                            status="Yeni Bildirim", due_date=DAY,
                            responsible_user_id=owner.id, reviewer_user_id=reviewer.id))
    persist(KaizenProject(company_id=company.id, project_no="K-1", title="Kaizen", target_date=DAY,
                           owner_user_id=owner.id, created_by_user_id=reviewer.id, problem_statement="Problem"))
    sources.additional_due_reminders(company.id, DAY)
    assert len(captured) == 6
    for item in captured:
        expected = reviewer if item["kind"] in {"deviation", "incident"} else owner
        assert item["user_ids"] == {expected.id}
    captured.clear()
    change.status = "Onay Bekliyor"
    change.action = action(company, reviewer)
    sources.additional_due_reminders(company.id, DAY)
    assert next(item for item in captured if item["kind"] == "change")["user_ids"] == {reviewer.id}


@pytest.mark.parametrize("reason", ["archived", "closed", "foreign-owner", "inactive-owner", "duplicate"])
def test_additional_due_safety(company, user_factory, captured, reason):
    owner = user_factory("owner", "fmea.view")
    user_factory("manager", "fmea.manage")
    row = persist(FmeaRecord(company_id=company.id, fmea_no="F-1", process_name="Process",
                             failure_mode="Failure", due_date=DAY, responsible_user_id=owner.id))
    if reason == "archived":
        row.archived_at = NOW
    elif reason == "closed":
        row.status = "Kapat\u0131ld\u0131"
    elif reason == "foreign-owner":
        other = persist(Company(code="other", slug="other", name="Other"))
        owner.company_id = other.id
    elif reason == "inactive-owner":
        owner.is_active = False
    else:
        row.action = action(company, owner)
    sources.additional_due_reminders(company.id, DAY)
    assert captured == []


def test_pending_sources_real_records(company, user_factory, captured):
    owner = user_factory("owner", "problem_solving.update", "problem_solving.view", "helpdesk.work", "helpdesk.view")
    reviewer = user_factory("reviewer", "problem_solving.review", "problem_solving.view", "work_permits.approve", "work_permits.view")
    requester = user_factory("requester", "helpdesk.view")
    case = persist(ProblemSolvingCase(company_id=company.id, case_no="PS-1", method="8D", title="Problem",
                                      leader_user_id=owner.id, reviewer_user_id=reviewer.id,
                                      created_by_user_id=requester.id, problem_statement="Problem"))
    step = persist(ProblemSolvingStep(company_id=company.id, case=case, step_order=1, step_key="D1",
                                      title="Team", due_date=DAY, owner_user_id=owner.id))
    ticket = persist(HelpDeskTicket(company_id=company.id, ticket_no="T-1", title="Ticket", description="Issue",
                                    department="Quality", requester_user_id=requester.id,
                                    assignee_user_id=owner.id, sla_due_at=NOW))
    permit = persist(WorkPermit(company_id=company.id, permit_no="WP-1", permit_type="Hot", title="Permit",
                                location="Site", description="Work", hazards="Heat", precautions="Guard",
                                ppe_requirements="Gloves", requester_user_id=requester.id,
                                responsible_user_id=owner.id, approver_user_id=reviewer.id,
                                requested_start_at=NOW, requested_end_at=NOW + timedelta(hours=1),
                                status="Onay Bekliyor", submitted_at=NOW))
    sources.pending_work_reminders(company.id, DAY)
    assert {item["kind"] for item in captured} == {"problem-step", "helpdesk", "work-permit-approval"}
    assert next(item for item in captured if item["kind"] == "problem-step")["user_ids"] == {owner.id}
    captured.clear()
    step.status = "\u0130nceleme Bekliyor"
    ticket.status = "\u00c7\u00f6z\u00fcm Bekliyor"
    permit.archived_at = NOW
    sources.pending_work_reminders(company.id, DAY)
    assert {item["kind"] for item in captured} == {"problem-approval", "helpdesk-acceptance"}
    assert next(item for item in captured if item["kind"] == "problem-approval")["user_ids"] == {reviewer.id}
    assert next(item for item in captured if item["kind"] == "helpdesk-acceptance")["user_ids"] == {requester.id}
    captured.clear()
    step.status = "Onayland\u0131"
    ticket.status = "Kapat\u0131ld\u0131"
    sources.pending_work_reminders(company.id, DAY)
    assert captured == []


@pytest.mark.parametrize("kind,permission", [("kaizen", "kaizen.update"), ("problem-step", "problem_solving.update"),
                                           ("helpdesk", "helpdesk.work"), ("work-permit-approval", "work_permits.approve")])
def test_detail_page_permission_required(company, user_factory, kind, permission):
    user = user_factory("worker", permission)
    assert sources.eligible_recipients([user], company.id, kind) == []


def test_collect_additional_sources_with_real_policy(company, user_factory):
    from app.notification_policy import reminder_collection

    owner = user_factory("owner", "vehicles.view")
    row = vehicle(company, reminder_recipients=[owner], casco_insurance_due_date=None,
                  next_inspection_due_date=None)
    with reminder_collection(company.id, DAY) as collection:
        sources.collect_additional_sources(company.id, DAY)
    assert (owner.id, "vehicle-insurance", row.id) in collection["items"]
