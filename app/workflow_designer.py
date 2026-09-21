from datetime import UTC, date, datetime, timedelta
from functools import wraps
import re

from flask import Blueprint, abort, flash, g, redirect, render_template, request, send_file, url_for
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from .audit import record_audit_event
from .extensions import db
from .models import (
    CompanyDepartment,
    Role,
    User,
    WorkflowEvent,
    WorkflowInstance,
    WorkflowInstanceStep,
    WorkflowStep,
    WorkflowStepRecipient,
    WorkflowTemplate,
    WorkflowVersion,
)
from .notifications import add_user_notification
from .tenant import assign_current_company, current_company_id, scoped_query


bp = Blueprint("workflows", __name__, url_prefix="/is-akislari")
STEP_TYPES = {"approval", "task", "notification"}
ASSIGNMENT_TYPES = {"user", "role", "department_manager"}
APPROVAL_POLICIES = {"any", "all"}
REJECTION_ACTIONS = {"return", "reject"}


def now_utc():
    return datetime.now(UTC).replace(tzinfo=None)


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if getattr(g, "current_user", None) is None:
            return redirect(url_for("main.login", next=request.full_path))
        if current_company_id() is None:
            abort(400, "İş akışları için şirket bağlamı gereklidir.")
        checker = getattr(g, "company_module_enabled", None)
        if checker and not checker("workflow_designer"):
            abort(404)
        return view(*args, **kwargs)

    return wrapped


def has_permission(key):
    return bool(g.current_user and g.current_user.has_permission(key))


def require(*keys):
    if not any(has_permission(key) for key in keys):
        abort(403)


def can_manage_all():
    return has_permission("workflow.manage_all")


def template_query():
    return scoped_query(WorkflowTemplate.query, WorkflowTemplate)


def version_query():
    return scoped_query(WorkflowVersion.query, WorkflowVersion)


def instance_query():
    return scoped_query(WorkflowInstance.query, WorkflowInstance)


def visible_instances():
    query = instance_query()
    if can_manage_all():
        return query
    recipient_exists = db.session.query(WorkflowStepRecipient.id).join(
        WorkflowInstanceStep,
        WorkflowStepRecipient.instance_step_id == WorkflowInstanceStep.id,
    ).filter(
        WorkflowInstanceStep.instance_id == WorkflowInstance.id,
        WorkflowStepRecipient.company_id == current_company_id(),
        WorkflowStepRecipient.user_id == g.current_user.id,
    ).exists()
    return query.filter(or_(WorkflowInstance.requester_user_id == g.current_user.id, recipient_exists))


def get_template(template_id):
    return template_query().filter_by(id=template_id).first_or_404()


def get_version(version_id):
    return version_query().filter_by(id=version_id).first_or_404()


def get_instance(instance_id):
    return visible_instances().filter_by(id=instance_id).first_or_404()


def active_users():
    return User.query.filter_by(company_id=current_company_id(), is_active=True).order_by(User.full_name, User.id).all()


def active_departments():
    return CompanyDepartment.query.filter_by(company_id=current_company_id(), is_active=True).order_by(CompanyDepartment.sort_order, CompanyDepartment.name).all()


def available_roles():
    role_ids = {role.id for user in active_users() for role in user.roles if role.key != "super_admin"}
    return Role.query.filter(Role.id.in_(role_ids)).order_by(Role.hierarchy_level, Role.name).all() if role_ids else []


def next_code():
    numbers = []
    for (value,) in template_query().with_entities(WorkflowTemplate.code).all():
        match = re.search(r"(\d+)$", value or "")
        if match:
            numbers.append(int(match.group(1)))
    return f"WF-{max(numbers, default=0) + 1:04d}"


def next_instance_no():
    prefix = f"WF-{date.today().year}-"
    numbers = []
    for (value,) in instance_query().with_entities(WorkflowInstance.instance_no).filter(WorkflowInstance.instance_no.like(f"{prefix}%")).all():
        try:
            numbers.append(int(value.rsplit("-", 1)[-1]))
        except (TypeError, ValueError):
            pass
    return f"{prefix}{max(numbers, default=0) + 1:04d}"


def parse_int(value, *, minimum=0, maximum=365, default=None):
    if value in (None, ""):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise ValueError("Sayısal alanlardan biri geçerli değil.") from None
    if not minimum <= parsed <= maximum:
        raise ValueError(f"Değer {minimum}-{maximum} aralığında olmalıdır.")
    return parsed


def parse_steps():
    names = request.form.getlist("step_name")
    types = request.form.getlist("step_type")
    assignments = request.form.getlist("assignment_mode")
    user_ids = request.form.getlist("assigned_user_id")
    role_keys = request.form.getlist("assigned_role_key")
    due_days = request.form.getlist("due_days")
    policies = request.form.getlist("approval_policy")
    rejection_actions = request.form.getlist("rejection_mode")
    instructions = request.form.getlist("instructions")
    users_by_id = {user.id: user for user in active_users()}
    roles_by_key = {role.key: role for role in available_roles()}
    rows = []
    for index, raw_name in enumerate(names):
        name = raw_name.strip()[:180]
        if not name:
            raise ValueError("Her adımın bir adı olmalıdır.")
        step_type = types[index] if index < len(types) else "approval"
        assignment_type = assignments[index] if index < len(assignments) else "user"
        policy = policies[index] if index < len(policies) else "any"
        rejection_action = rejection_actions[index] if index < len(rejection_actions) else "return"
        if step_type not in STEP_TYPES or assignment_type not in ASSIGNMENT_TYPES:
            raise ValueError("Adım türü veya atama yöntemi geçerli değil.")
        if policy not in APPROVAL_POLICIES or rejection_action not in REJECTION_ACTIONS:
            raise ValueError("Adım karar ayarı geçerli değil.")
        assigned_user = None
        assigned_role = None
        if assignment_type == "user":
            user_id = parse_int(user_ids[index] if index < len(user_ids) else "", minimum=1, maximum=2_147_483_647)
            assigned_user = users_by_id.get(user_id)
            if assigned_user is None:
                raise ValueError(f"{name} adımı için aktif bir kullanıcı seçin.")
        elif assignment_type == "role":
            role_key = role_keys[index] if index < len(role_keys) else ""
            assigned_role = roles_by_key.get(role_key)
            if assigned_role is None:
                raise ValueError(f"{name} adımı için aktif bir rol seçin.")
        elif not any(user.has_role("department_manager") for user in active_users()):
            raise ValueError("Departman yöneticisi ataması için aktif bir departman yöneticisi bulunmalıdır.")
        rows.append({
            "step_key": f"step_{index + 1}",
            "name": name,
            "instructions": (instructions[index].strip()[:2000] if index < len(instructions) else "") or None,
            "step_type": step_type,
            "assignment_type": assignment_type,
            "assigned_user_id": assigned_user.id if assigned_user else None,
            "assigned_role_id": assigned_role.id if assigned_role else None,
            "sort_order": index + 1,
            "approval_policy": policy,
            "rejection_action": rejection_action,
            "due_days": parse_int(due_days[index] if index < len(due_days) else "3", default=3),
            "requires_comment": False,
        })
    if not rows:
        raise ValueError("Akışta en az bir adım bulunmalıdır.")
    return rows


def save_version(version):
    if version.status != "draft":
        abort(409)
    name = request.form.get("name", "").strip()[:180]
    if not name:
        raise ValueError("Akış adı zorunludur.")
    rows = parse_steps()
    version.name_snapshot = name
    version.description_snapshot = request.form.get("description", "").strip() or None
    version.template.name = name
    version.template.description = version.description_snapshot
    for step in list(version.steps):
        db.session.delete(step)
    db.session.flush()
    for values in rows:
        step = WorkflowStep(version=version, **values)
        assign_current_company(step)
        db.session.add(step)


def copy_steps(source, target):
    for source_step in source.steps:
        step = WorkflowStep(
            version=target,
            step_key=source_step.step_key,
            name=source_step.name,
            instructions=source_step.instructions,
            step_type=source_step.step_type,
            assignment_type=source_step.assignment_type,
            assigned_user_id=source_step.assigned_user_id,
            assigned_role_id=source_step.assigned_role_id,
            sort_order=source_step.sort_order,
            approval_policy=source_step.approval_policy,
            rejection_action=source_step.rejection_action,
            due_days=source_step.due_days,
            requires_comment=source_step.requires_comment,
        )
        assign_current_company(step)
        db.session.add(step)


def event(instance, event_type, message, step=None, data=None):
    row = WorkflowEvent(
        instance=instance,
        instance_step=step,
        actor_user_id=getattr(g.current_user, "id", None),
        event_type=event_type,
        message=message,
        event_data_json=None if not data else __import__("json").dumps(data, ensure_ascii=False, sort_keys=True),
    )
    assign_current_company(row)
    db.session.add(row)


def resolve_recipients(step, instance):
    users = active_users()
    if step.assignment_type_snapshot == "user":
        resolved = [user for user in users if user.id == step.assigned_user_id_snapshot]
    elif step.assignment_type_snapshot == "role":
        resolved = [user for user in users if any(role.id == step.assigned_role_id_snapshot for role in user.roles)]
    else:
        from .dynamic_forms import user_matches_department
        resolved = [
            user for user in users
            if user.has_role("department_manager")
            and instance.department is not None
            and user_matches_department(user, instance.department.name)
        ]
    if step.step_type_snapshot == "approval":
        resolved = [user for user in resolved if user.id != instance.requester_user_id]
    return {user.id: user for user in resolved}.values()


def notify_recipients(step):
    target_url = url_for("workflows.instance_detail", instance_id=step.instance_id)
    for recipient in step.recipients:
        add_user_notification(
            recipient.user,
            f"{step.instance.instance_no} için {step.name_snapshot} adımı sizi bekliyor.",
            company_id=step.company_id,
            notification_type="warning",
            source_key=f"workflow:{step.id}:u{recipient.user_id}",
            target_url=target_url,
            due_date=step.due_date,
        )


def activate_step(step):
    step.status = "active"
    step.activated_at = now_utc()
    step.due_date = date.today() + timedelta(days=step.due_days_snapshot)
    recipients = list(resolve_recipients(step, step.instance))
    if not recipients:
        raise ValueError(f"{step.name_snapshot} adımı için uygun ve aktif bir sorumlu bulunamadı.")
    for user in recipients:
        recipient = WorkflowStepRecipient(
            instance_step=step,
            user_id=user.id,
            recipient_name_snapshot=user.full_name,
            recipient_email_snapshot=user.email,
            status="pending",
        )
        assign_current_company(recipient)
        db.session.add(recipient)
    db.session.flush()
    step.instance.current_step_order = step.sort_order
    event(step.instance, "step_activated", f"{step.name_snapshot} adımı başlatıldı.", step)
    if step.step_type_snapshot == "notification":
        for recipient in step.recipients:
            recipient.status = "acted"
            recipient.decision = "acknowledge"
            recipient.decided_at = now_utc()
        step.status = "completed"
        step.completed_at = now_utc()
        event(step.instance, "notification_sent", f"{step.name_snapshot} bilgilendirmesi gönderildi.", step)
        activate_next_step(step.instance, step.sort_order)
    else:
        notify_recipients(step)


def activate_next_step(instance, completed_order):
    next_step = next((step for step in instance.instance_steps if step.status == "pending" and step.sort_order > completed_order), None)
    if next_step is None:
        instance.status = "completed"
        instance.current_step_order = None
        instance.completed_at = now_utc()
        event(instance, "completed", "İş akışı tamamlandı.")
        return
    activate_step(next_step)


def create_instance_steps(instance, version):
    for source in version.steps:
        assignment_label = source.assigned_user.full_name if source.assigned_user else (source.assigned_role.name if source.assigned_role else "Departman Yöneticisi")
        step = WorkflowInstanceStep(
            instance=instance,
            source_step_id=source.id,
            step_key_snapshot=source.step_key,
            name_snapshot=source.name,
            instructions_snapshot=source.instructions,
            step_type_snapshot=source.step_type,
            assignment_type_snapshot=source.assignment_type,
            assigned_user_id_snapshot=source.assigned_user_id,
            assigned_role_id_snapshot=source.assigned_role_id,
            assignment_label_snapshot=assignment_label,
            sort_order=source.sort_order,
            round_number=1,
            approval_policy_snapshot=source.approval_policy,
            rejection_action_snapshot=source.rejection_action,
            due_days_snapshot=source.due_days,
            requires_comment_snapshot=source.requires_comment,
            status="pending",
        )
        assign_current_company(step)
        db.session.add(step)
    db.session.flush()


@bp.get("")
@login_required
def dashboard():
    require("workflow.view", "workflow.start", "workflow.act", "workflow.design")
    templates_query = template_query().filter(WorkflowTemplate.status != "archived")
    if not has_permission("workflow.design"):
        templates_query = templates_query.filter(WorkflowTemplate.status == "published")
    templates = templates_query.order_by(WorkflowTemplate.name, WorkflowTemplate.id).all()
    visible_query = visible_instances()
    instances = visible_query.order_by(WorkflowInstance.created_at.desc(), WorkflowInstance.id.desc()).limit(100).all()
    today = date.today()
    visible_instance_ids = visible_query.with_entities(WorkflowInstance.id)
    active_steps = scoped_query(WorkflowInstanceStep.query, WorkflowInstanceStep).filter(
        WorkflowInstanceStep.status == "active",
        WorkflowInstanceStep.instance_id.in_(visible_instance_ids),
    ).all()
    metrics = (
        ("Yayınlanan Akış", sum(1 for row in templates if row.published_version is not None), "bi-broadcast", "primary"),
        ("Devam Eden", sum(1 for row in instances if row.status == "in_progress"), "bi-arrow-repeat", "info"),
        ("Bana Atanan", sum(1 for row in active_steps for recipient in row.recipients if recipient.user_id == g.current_user.id and recipient.status == "pending"), "bi-person-check", "success"),
        ("Geciken Adım", sum(1 for row in active_steps if row.due_date and row.due_date < today), "bi-clock-history", "danger"),
    )
    return render_template(
        "workflows/dashboard.html", templates=templates, instances=instances, metrics=metrics,
        can_design=has_permission("workflow.design"), can_start=has_permission("workflow.start"),
        can_export=has_permission("workflow.export") or can_manage_all(),
    )


@bp.route("/sablon/yeni", methods=("GET", "POST"))
@login_required
def create_template():
    require("workflow.design")
    if request.method == "POST":
        name = request.form.get("name", "").strip()[:180]
        if not name:
            flash("Akış adı zorunludur.", "danger")
        else:
            template = WorkflowTemplate(code=next_code(), name=name, description=None, status="draft", current_version_number=1, created_by_user_id=g.current_user.id)
            assign_current_company(template)
            version = WorkflowVersion(template=template, version_number=1, status="draft", name_snapshot=name, created_by_user_id=g.current_user.id)
            assign_current_company(version)
            db.session.add_all((template, version))
            db.session.commit()
            return redirect(url_for("workflows.edit_version", version_id=version.id))
    return render_template("workflows/create.html")


@bp.route("/surum/<int:version_id>/tasarla", methods=("GET", "POST"))
@login_required
def edit_version(version_id):
    require("workflow.design")
    version = get_version(version_id)
    if version.status != "draft":
        abort(409)
    if request.method == "POST":
        try:
            save_version(version)
            db.session.commit()
        except (ValueError, IntegrityError) as error:
            db.session.rollback()
            flash(str(error) if isinstance(error, ValueError) else "Adım sırası kaydedilemedi.", "danger")
        else:
            flash("İş akışı taslağı kaydedildi.", "success")
            return redirect(url_for("workflows.edit_version", version_id=version.id))
    return render_template(
        "workflows/designer.html", version=version, users=active_users(), roles=available_roles(),
        empty_step={"step_type": "approval", "assignment_mode": "user", "due_days": 3, "approval_policy": "any", "rejection_mode": "return"},
    )


@bp.post("/surum/<int:version_id>/yayinla")
@login_required
def publish_version(version_id):
    require("workflow.publish")
    version = get_version(version_id)
    if version.status != "draft" or not version.steps:
        abort(409)
    departments = active_departments()
    for step in version.steps:
        snapshot = type("Snapshot", (), {
            "assignment_type_snapshot": step.assignment_type,
            "assigned_user_id_snapshot": step.assigned_user_id,
            "assigned_role_id_snapshot": step.assigned_role_id,
            "step_type_snapshot": "task",
        })()
        target_departments = departments if step.assignment_type == "department_manager" else [departments[0] if departments else None]
        for department in target_departments:
            probe = WorkflowInstance(requester_user_id=-1, department=department)
            probe.company_id = current_company_id()
            if not list(resolve_recipients(snapshot, probe)):
                department_note = f" ({department.name})" if department is not None else ""
                flash(f"{step.name} adımı için aktif sorumlu bulunamadı{department_note}.", "danger")
                return redirect(url_for("workflows.edit_version", version_id=version.id))
    previous = version.template.published_version
    if previous and previous.id != version.id:
        previous.status = "archived"
    version.status = "published"
    version.published_by_user_id = g.current_user.id
    version.published_at = now_utc()
    version.template.status = "published"
    version.template.published_version_number = version.version_number
    record_audit_event("WorkflowVersion", "published", f"{version.name_snapshot} v{version.version_number} yayınlandı", entity_id=version.id, commit=False)
    db.session.commit()
    flash("İş akışı yayınlandı ve değişikliğe kapatıldı.", "success")
    return redirect(url_for("workflows.dashboard"))


@bp.post("/sablon/<int:template_id>/yeni-surum")
@login_required
def create_new_version(template_id):
    require("workflow.design")
    template = get_template(template_id)
    existing_draft = next((version for version in template.versions if version.status == "draft"), None)
    if existing_draft:
        return redirect(url_for("workflows.edit_version", version_id=existing_draft.id))
    source = template.published_version
    if source is None:
        abort(409)
    number = max(version.version_number for version in template.versions) + 1
    version = WorkflowVersion(template=template, source_version_id=source.id, version_number=number, status="draft", name_snapshot=source.name_snapshot, description_snapshot=source.description_snapshot, created_by_user_id=g.current_user.id)
    assign_current_company(version)
    db.session.add(version)
    db.session.flush()
    copy_steps(source, version)
    template.current_version_number = number
    db.session.commit()
    return redirect(url_for("workflows.edit_version", version_id=version.id))


@bp.route("/sablon/<int:template_id>/baslat", methods=("GET", "POST"))
@login_required
def launch_instance(template_id):
    require("workflow.start")
    template = get_template(template_id)
    version = template.published_version
    if version is None or not version.steps:
        abort(409)
    departments = active_departments()
    if request.method == "POST":
        title = request.form.get("title", "").strip()[:240]
        description = request.form.get("description", "").strip()[:5000]
        department_id = parse_int(request.form.get("department_id"), minimum=1, maximum=2_147_483_647)
        department = next((row for row in departments if row.id == department_id), None)
        if not title or not description or department is None:
            flash("Başlık, açıklama ve geçerli departman zorunludur.", "danger")
        else:
            instance = WorkflowInstance(
                instance_no=next_instance_no(), version=version, department=department,
                requester_user_id=g.current_user.id, title=title, description=description,
                workflow_code_snapshot=template.code, workflow_name_snapshot=version.name_snapshot,
                version_number_snapshot=version.version_number, status="in_progress", submitted_at=now_utc(),
            )
            assign_current_company(instance)
            db.session.add(instance)
            try:
                db.session.flush()
                create_instance_steps(instance, version)
                event(instance, "started", "İş akışı başlatıldı.")
                activate_step(instance.instance_steps[0])
                record_audit_event("WorkflowInstance", "started", f"{instance.instance_no} başlatıldı", entity_id=instance.id, commit=False)
                db.session.commit()
            except (ValueError, IntegrityError) as error:
                db.session.rollback()
                flash(str(error) if isinstance(error, ValueError) else "Süreç başlatılamadı.", "danger")
            else:
                flash("Süreç başlatıldı ve ilk adım sorumlusuna atandı.", "success")
                return redirect(url_for("workflows.instance_detail", instance_id=instance.id))
    return render_template("workflows/launch.html", template=template, version=version, departments=departments)


@bp.get("/kayit/<int:instance_id>")
@login_required
def instance_detail(instance_id):
    require("workflow.view", "workflow.start", "workflow.act", "workflow.manage_all")
    instance = get_instance(instance_id)
    active_recipient = None
    if instance.active_step:
        active_recipient = next((recipient for recipient in instance.active_step.recipients if recipient.user_id == g.current_user.id and recipient.status == "pending"), None)
    return render_template("workflows/instance_detail.html", instance=instance, active_recipient=active_recipient, can_archive=has_permission("workflow.archive") or can_manage_all())


def transition_active_step(step, status):
    updated = scoped_query(WorkflowInstanceStep.query, WorkflowInstanceStep).filter_by(
        id=step.id,
        status="active",
    ).update({WorkflowInstanceStep.status: status}, synchronize_session="fetch")
    if updated != 1:
        db.session.rollback()
        abort(409)


def record_recipient_decision(recipient, decision, note):
    decided_at = now_utc()
    updated = scoped_query(WorkflowStepRecipient.query, WorkflowStepRecipient).filter_by(
        id=recipient.id,
        status="pending",
    ).update(
        {
            WorkflowStepRecipient.status: "acted",
            WorkflowStepRecipient.decision: decision,
            WorkflowStepRecipient.decision_note: note or None,
            WorkflowStepRecipient.decided_at: decided_at,
        },
        synchronize_session="fetch",
    )
    if updated != 1:
        db.session.rollback()
        abort(409)


def cancel_pending_recipients(step_id, *, except_recipient_id=None):
    query = scoped_query(WorkflowStepRecipient.query, WorkflowStepRecipient).filter_by(
        instance_step_id=step_id,
        status="pending",
    )
    if except_recipient_id is not None:
        query = query.filter(WorkflowStepRecipient.id != except_recipient_id)
    query.update({WorkflowStepRecipient.status: "cancelled"}, synchronize_session="fetch")


@bp.post("/adim/<int:step_id>/karar")
@login_required
def decide_step(step_id):
    require("workflow.act", "workflow.manage_all")
    step = scoped_query(WorkflowInstanceStep.query, WorkflowInstanceStep).filter_by(id=step_id).with_for_update().first_or_404()
    get_instance(step.instance_id)
    if step.status != "active":
        abort(409)
    recipient = scoped_query(WorkflowStepRecipient.query, WorkflowStepRecipient).filter_by(instance_step_id=step.id, user_id=g.current_user.id, status="pending").first()
    if recipient is None:
        abort(403)
    decision = request.form.get("decision", "").strip()
    note = request.form.get("note", "").strip()[:2000]
    allowed = {"approve"} if step.step_type_snapshot == "task" else {"approve", "return", "reject"}
    if decision not in allowed:
        abort(400)
    if decision in {"return", "reject"} and not note:
        flash("Ret veya revizyon için işlem notu zorunludur.", "danger")
        return redirect(url_for("workflows.instance_detail", instance_id=step.instance_id))
    recorded_decision = "complete" if step.step_type_snapshot == "task" else decision
    if decision == "return":
        transition_active_step(step, "returned")
        record_recipient_decision(recipient, recorded_decision, note)
        step.completion_note = note
        step.completed_at = now_utc()
        step.instance.status = "revision_requested"
        cancel_pending_recipients(step.id)
        event(step.instance, "revision_requested", f"{g.current_user.full_name} revizyon istedi.", step)
    elif decision == "reject":
        action = step.rejection_action_snapshot
        target_status = "returned" if action == "return" else "rejected"
        transition_active_step(step, target_status)
        record_recipient_decision(recipient, recorded_decision, note)
        if action == "return":
            step.instance.status = "revision_requested"
            event(step.instance, "revision_requested", f"{g.current_user.full_name} revizyon istedi.", step)
        else:
            step.instance.status = "rejected"
            step.instance.rejected_at = now_utc()
            event(step.instance, "rejected", f"{g.current_user.full_name} akışı reddetti.", step)
        step.completion_note = note
        step.completed_at = now_utc()
        cancel_pending_recipients(step.id)
    else:
        if step.approval_policy_snapshot != "all":
            transition_active_step(step, "completed")
        record_recipient_decision(recipient, recorded_decision, note)
        pending_count = scoped_query(WorkflowStepRecipient.query, WorkflowStepRecipient).filter_by(
            instance_step_id=step.id,
            status="pending",
        ).count()
        if step.approval_policy_snapshot == "all" and pending_count:
            event(step.instance, "decision_recorded", f"{g.current_user.full_name} adımı onayladı; diğer kararlar bekleniyor.", step)
        else:
            if step.approval_policy_snapshot == "all":
                transition_active_step(step, "completed")
            else:
                cancel_pending_recipients(step.id)
            step.completed_at = now_utc()
            step.completion_note = note or None
            event(step.instance, "step_completed", f"{step.name_snapshot} adımı tamamlandı.", step)
            activate_next_step(step.instance, step.sort_order)
    record_audit_event("WorkflowInstanceStep", "decision", f"{step.instance.instance_no} adım kararı: {decision}", entity_id=step.id, details={"decision": decision}, commit=False)
    db.session.commit()
    flash("İşleminiz kaydedildi.", "success")
    return redirect(url_for("workflows.instance_detail", instance_id=step.instance_id))


@bp.post("/kayit/<int:instance_id>/yeniden-gonder")
@login_required
def resubmit_instance(instance_id):
    instance = get_instance(instance_id)
    if instance.requester_user_id != g.current_user.id or instance.status != "revision_requested":
        abort(403)
    description = request.form.get("description", "").strip()[:5000]
    if not description:
        flash("Güncel açıklama zorunludur.", "danger")
        return redirect(url_for("workflows.instance_detail", instance_id=instance.id))
    returned = max((step for step in instance.instance_steps if step.status == "returned"), key=lambda row: (row.sort_order, row.round_number), default=None)
    if returned is None:
        abort(409)
    instance.description = description
    instance.status = "in_progress"
    round_number = max(step.round_number for step in instance.instance_steps if step.source_step_id == returned.source_step_id) + 1
    retry = WorkflowInstanceStep(
        instance=instance, source_step_id=returned.source_step_id, step_key_snapshot=returned.step_key_snapshot,
        name_snapshot=returned.name_snapshot, instructions_snapshot=returned.instructions_snapshot,
        step_type_snapshot=returned.step_type_snapshot, assignment_type_snapshot=returned.assignment_type_snapshot,
        assigned_user_id_snapshot=returned.assigned_user_id_snapshot, assigned_role_id_snapshot=returned.assigned_role_id_snapshot,
        assignment_label_snapshot=returned.assignment_label_snapshot, sort_order=returned.sort_order, round_number=round_number,
        approval_policy_snapshot=returned.approval_policy_snapshot, rejection_action_snapshot=returned.rejection_action_snapshot,
        due_days_snapshot=returned.due_days_snapshot, requires_comment_snapshot=returned.requires_comment_snapshot, status="pending",
    )
    assign_current_company(retry)
    db.session.add(retry)
    db.session.flush()
    event(instance, "resubmitted", "Talep sahibi süreci yeniden gönderdi.", retry)
    try:
        activate_step(retry)
        db.session.commit()
    except ValueError as error:
        db.session.rollback()
        flash(str(error), "danger")
    else:
        flash("Süreç yeniden gönderildi.", "success")
    return redirect(url_for("workflows.instance_detail", instance_id=instance.id))


@bp.post("/kayit/<int:instance_id>/arsivle")
@login_required
def archive_instance(instance_id):
    require("workflow.archive", "workflow.manage_all")
    instance = get_instance(instance_id)
    if instance.status not in {"completed", "rejected"}:
        abort(409)
    instance.status = "archived"
    instance.archived_at = now_utc()
    event(instance, "archived", "İş akışı arşivlendi.")
    db.session.commit()
    flash("Süreç arşivlendi.", "success")
    return redirect(url_for("workflows.dashboard"))


@bp.get("/rapor.xlsx")
@login_required
def export_excel():
    require("workflow.export", "workflow.manage_all")
    from .routes import build_simple_xlsx
    rows = [(
        item.instance_no, item.workflow_name_snapshot, item.version_number_snapshot, item.title,
        item.department.name if item.department else "-", item.requester.full_name,
        item.active_step.name_snapshot if item.active_step else "-",
        item.active_step.due_date.strftime("%d.%m.%Y") if item.active_step and item.active_step.due_date else "-",
        item.status_label, item.created_at.strftime("%d.%m.%Y %H:%M"),
    ) for item in visible_instances().order_by(WorkflowInstance.created_at.desc()).all()]
    workbook = build_simple_xlsx(("Kayıt No", "Akış", "Sürüm", "Başlık", "Departman", "Talep Sahibi", "Aktif Adım", "Termin", "Durum", "Başlatma"), rows, sheet_name="İş Akışları")
    record_audit_event("WorkflowReport", "exported", "İş akışları raporu indirildi", details={"row_count": len(rows)})
    return send_file(workbook, as_attachment=True, download_name=f"is-akislari-{date.today():%Y%m%d}.xlsx", mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


def assigned_task_rows(scope, row_builder):
    query = scoped_query(WorkflowStepRecipient.query, WorkflowStepRecipient).join(WorkflowInstanceStep).join(WorkflowInstance)
    if scope == "created":
        query = query.filter(WorkflowInstance.requester_user_id == g.current_user.id, WorkflowStepRecipient.status == "pending")
    else:
        query = query.filter(WorkflowStepRecipient.user_id == g.current_user.id, WorkflowStepRecipient.status == "pending")
    today = date.today()
    rows = []
    seen = set()
    for recipient in query.all():
        step = recipient.instance_step
        if step.id in seen or step.status != "active":
            continue
        seen.add(step.id)
        rows.append(row_builder(
            module_key="workflow", module_label="İş Akışı", module_icon="bezier2", module_tone="quality",
            title=f"{step.instance.instance_no} - {step.name_snapshot}", description=step.instance.title,
            reference_no=step.instance.instance_no, department=step.instance.department.name if step.instance.department else "-",
            due_date=step.due_date, status=step.status_label, status_key="delayed" if step.due_date and step.due_date < today else "pending",
            priority="Orta", detail_url=url_for("workflows.instance_detail", instance_id=step.instance_id),
            created_at=step.created_at, sort_id=700000 + step.id, date_label="Adım Termini",
        ))
    return rows


def report_data():
    rows = [(
        item.instance_no, item.workflow_name_snapshot, item.version_number_snapshot, item.title,
        item.department.name if item.department else "-", item.requester.full_name,
        item.active_step.name_snapshot if item.active_step else "-", item.status_label,
    ) for item in visible_instances().order_by(WorkflowInstance.created_at.desc()).all()]
    return {"title": "İş Akışları Raporu", "headers": ("Kayıt No", "Akış", "Sürüm", "Başlık", "Departman", "Talep Sahibi", "Aktif Adım", "Durum"), "rows": rows, "sheet_name": "İş Akışları"}


def reminder_rows(company_id, run_date, days_before):
    steps = WorkflowInstanceStep.query.filter_by(company_id=company_id, status="active").filter(WorkflowInstanceStep.due_date <= run_date + timedelta(days=days_before)).all()
    rows = []
    for step in steps:
        for recipient in step.recipients:
            if recipient.status == "pending":
                rows.append({"user": recipient.user, "message": f"{step.instance.instance_no} - {step.name_snapshot} adımı", "source_key": f"workflow-reminder:{run_date.isoformat()}:{step.id}:u{recipient.user_id}", "target_url": f"/is-akislari/kayit/{step.instance_id}", "due_date": step.due_date})
    return rows
