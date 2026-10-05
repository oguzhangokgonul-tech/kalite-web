from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from functools import wraps

from flask import Blueprint, abort, flash, g, redirect, render_template, request, send_file, url_for
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload, selectinload
from sqlalchemy.orm.exc import StaleDataError

from .audit import record_audit_event
from .extensions import db
from .models import Notification, User
from .notifications import add_user_notification
from .project_models import ProjectMilestone, ProjectRecord, ProjectTask
from .project_timeline import axis_ticks, resource_rows, schedule_rows, timeline_window
from .tenant import assign_current_company, current_company_id, scoped_query

bp = Blueprint("projects", __name__, url_prefix="/projeler")
STATUSES = {"draft": "Taslak", "active": "Devam Ediyor", "completed": "Tamamlandı", "archived": "Arşiv"}
TASK_STATUSES = {"pending": "Bekliyor", "in_progress": "Devam Ediyor", "completed": "Tamamlandı", "cancelled": "İptal"}
MILESTONE_STATUSES = {"pending": "Bekliyor", "completed": "Tamamlandı"}
READ_PERMISSIONS = ("projects.view", "projects.view_all", "projects.manage")
EDITABLE = {"draft", "active"}


def has_permission(key):
    user = getattr(g, "current_user", None)
    return bool(user and user.is_active and user.has_permission(key))


def require_permission(*keys):
    if not any(has_permission(key) for key in keys):
        abort(403)


def company_query(model):
    if not current_company_id():
        abort(403, description="Lütfen bir firma seçin.")
    return scoped_query(model.query, model).filter_by(company_id=current_company_id())


@bp.before_request
def guard():
    if getattr(g, "current_user", None) is None:
        return redirect(url_for("main.login", next=request.full_path))
    require_permission(*READ_PERMISSIONS)
    company_query(ProjectRecord)
    checker = getattr(g, "company_module_enabled", None)
    if checker and not checker("projects"):
        abort(404)


def atomic(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        try:
            with db.session.no_autoflush:
                return view(*args, **kwargs)
        except (StaleDataError, IntegrityError):
            db.session.rollback()
            abort(409, description="Kayıt değişti. Sayfayı yenileyip tekrar deneyin.")
        except ValueError as error:
            db.session.rollback()
            abort(400, description=str(error))
        except Exception:
            db.session.rollback()
            raise
    return wrapped


def visible_projects():
    query = company_query(ProjectRecord).options(
        joinedload(ProjectRecord.owner), selectinload(ProjectRecord.tasks).joinedload(ProjectTask.owner),
        selectinload(ProjectRecord.milestones))
    if has_permission("projects.view_all") or has_permission("projects.manage"):
        return query
    user_id = g.current_user.id
    return query.filter(or_(ProjectRecord.created_by_user_id == user_id,
        ProjectRecord.owner_user_id == user_id, ProjectRecord.tasks.any(db.and_(
            ProjectTask.company_id == current_company_id(), ProjectTask.owner_user_id == user_id))))


def get_project(project_id):
    require_permission(*READ_PERMISSIONS)
    return visible_projects().filter_by(id=project_id).first_or_404()


def can_edit(project):
    return bool(project.company_id == current_company_id() and (
        has_permission("projects.manage") or (has_permission("projects.create") and
        g.current_user.id in (project.created_by_user_id, project.owner_user_id))))


def can_update_task(project, task):
    return bool(project.status == "active" and task.project_id == project.id and
        task.company_id == current_company_id() and (can_edit(project) or
        (has_permission("projects.update") and task.owner_user_id == g.current_user.id)))


def check_version(row, field="version_id"):
    try:
        version = int(request.form.get(field, ""))
    except (TypeError, ValueError):
        abort(409)
    if version != row.version_id:
        abort(409, description="Kayıt değişti. Sayfayı yenileyin.")


def touch(project):
    # Parent version serializes task changes against project completion/archive.
    project.version_id += 1
    project.updated_at = datetime.now(UTC).replace(tzinfo=None)
    db.session.flush([project])


def text_field(name, required=False, limit=20000):
    value = request.form.get(name, "").strip()
    if (required and not value) or len(value) > limit:
        raise ValueError("Zorunlu alanları ve metin uzunluklarını kontrol edin.")
    return value


def active_users():
    return company_query(User).filter_by(is_active=True).order_by(User.full_name, User.id).all()


def plan_values(project=None, task=False):
    title = text_field("title", required=True, limit=240)
    try:
        start = date.fromisoformat(request.form.get("start_date", ""))
        due = date.fromisoformat(request.form.get("due_date", ""))
        owner_id = int(request.form.get("owner_user_id", ""))
    except (TypeError, ValueError):
        raise ValueError("Geçerli tarih ve sorumlu seçin.") from None
    owner = company_query(User).filter_by(id=owner_id, is_active=True).first()
    if owner is None or not any(owner.has_permission(key) for key in READ_PERMISSIONS):
        raise ValueError("Bu firmada proje erişimi olan aktif bir sorumlu seçin.")
    if task and not owner.has_permission("projects.update") and not owner.has_permission("projects.manage"):
        raise ValueError("Görev sorumlusunun görev güncelleme yetkisi bulunmalıdır.")
    if not task and not (owner.has_permission("projects.create") or owner.has_permission("projects.manage")):
        raise ValueError("Proje sorumlusunun proje yönetme yetkisi bulunmalıdır.")
    if due < start:
        raise ValueError("Bitiş tarihi başlangıçtan önce olamaz.")
    if task and not (project.start_date <= start <= due <= project.due_date):
        raise ValueError("Görev tarihleri proje tarih aralığında olmalıdır.")
    if project and not task and any(t.start_date < start or t.due_date > due for t in project.tasks if t.status != "cancelled"):
        raise ValueError("Proje tarihleri mevcut görevleri kapsamalıdır.")
    result = dict(title=title, owner_user_id=owner_id, start_date=start, due_date=due)
    if task:
        raw_hours = request.form.get("estimated_hours", "").strip()
        if raw_hours:
            try:
                hours = Decimal(raw_hours)
            except InvalidOperation:
                raise ValueError("Tahmini efor için geçerli bir saat girin.") from None
            if not hours.is_finite() or hours < Decimal("0.1") or hours > Decimal("10000") or hours != hours.quantize(Decimal("0.1")):
                raise ValueError("Tahmini efor 0,1 ile 10000 saat arasında, bir ondalık basamakla girilmelidir.")
            result["estimated_hours"] = hours
        else:
            result["estimated_hours"] = None
    else:
        result["description"] = text_field("description")
        if project and project.status == "active" and not result["description"]:
            raise ValueError("Devam eden projenin amacı boş bırakılamaz.")
    return result


def milestone_values(project):
    title = text_field("title", required=True, limit=240)
    criteria = text_field("acceptance_criteria", required=True)
    try:
        target = date.fromisoformat(request.form.get("target_date", ""))
    except (TypeError, ValueError):
        raise ValueError("Geçerli bir hedef tarihi girin.") from None
    if not project.start_date <= target <= project.due_date:
        raise ValueError("Kilometre taşı hedefi proje tarihleri içinde olmalıdır.")
    return {"title": title, "acceptance_criteria": criteria, "target_date": target}


def snapshot(row):
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


def audit(row, action, old=None):
    record_audit_event(type(row).__name__, action, row.title, entity_id=row.id,
        company_id=row.company_id, old_values=old, new_values=snapshot(row), commit=False)


def notify(project, task=None):
    if project.status != "active":
        return
    row = task or project
    owner = company_query(User).filter_by(id=row.owner_user_id, is_active=True).first()
    if owner:
        add_user_notification(owner, f"{project.project_no} - {row.title}", company_id=project.company_id,
            source_key=f"project:{project.id}:{'task' if task else 'owner'}:{row.id}:{row.version_id}",
            target_url=url_for("projects.detail", project_id=project.id), due_date=row.due_date)


def retire_notices(project, task=None):
    prefix = f"project:{project.id}:"
    if task is not None:
        prefix += f"task:{task.id}:"
    Notification.query.filter_by(company_id=project.company_id).filter(
        Notification.source_key.like(prefix + "%")).delete(synchronize_session=False)


def detail_redirect(project):
    return redirect(url_for("projects.detail", project_id=project.id))


def form_context(project=None):
    values = request.form if request.method == "POST" else (snapshot(project) if project else {})
    users = [u for u in active_users() if any(u.has_permission(k) for k in READ_PERMISSIONS)
             and (u.has_permission("projects.create") or u.has_permission("projects.manage"))]
    return dict(project=project, values=values, users=users)


@bp.get("")
def dashboard():
    query = visible_projects()
    search = request.args.get("q", "").strip()[:240]
    status = request.args.get("status", "")
    if search:
        query = query.filter(ProjectRecord.title.ilike(f"%{search}%"))
    if status in STATUSES:
        query = query.filter_by(status=status)
    else:
        status = ""
    pagination = query.order_by(ProjectRecord.due_date, ProjectRecord.id.desc()).paginate(
        page=request.args.get("page", 1, type=int), per_page=25, error_out=False)
    return render_template("projects/dashboard.html", projects=pagination.items, pagination=pagination,
        search=search, selected_status=status, statuses=STATUSES, today=date.today(),
        can_create=has_permission("projects.create"))


@bp.route("/yeni", methods=["GET", "POST"])
@atomic
def create():
    require_permission("projects.create")
    if request.method == "POST":
        try:
            values = plan_values()
        except ValueError as error:
            flash(str(error), "danger")
            return render_template("projects/form.html", **form_context()), 400
        project = assign_current_company(ProjectRecord(**values, created_by_user_id=g.current_user.id))
        db.session.add(project)
        db.session.flush()
        audit(project, "created")
        db.session.commit()
        return detail_redirect(project)
    return render_template("projects/form.html", **form_context())


@bp.get("/<int:project_id>")
def detail(project_id):
    project = get_project(project_id)
    users = [u for u in active_users() if any(u.has_permission(k) for k in READ_PERMISSIONS)
             and (u.has_permission("projects.update") or u.has_permission("projects.manage"))]
    return render_template("projects/detail.html", project=project, users=users,
        can_edit=can_edit(project), can_update_task=lambda task: can_update_task(project, task),
        can_export=has_permission("projects.export"), statuses=STATUSES, task_statuses=TASK_STATUSES,
        milestone_statuses=MILESTONE_STATUSES, today=date.today())


@bp.get("/<int:project_id>/zaman-cizelgesi")
def timeline(project_id):
    project = get_project(project_id)
    try:
        start, end, year = timeline_window(project, request.args.get("year"))
    except ValueError as error:
        abort(400, description=str(error))
    today = date.today()
    span = (end - start).days + 1
    today_position = 100 * ((today - start).days + 0.5) / span if start <= today <= end else None
    return render_template("projects/timeline.html", project=project,
        rows=schedule_rows(project, start, end), ticks=axis_ticks(start, end),
        resources=resource_rows(project), start=start, end=end, selected_year=year,
        years=range(project.start_date.year, project.due_date.year + 1),
        today_position=today_position, task_statuses=TASK_STATUSES,
        milestone_statuses=MILESTONE_STATUSES, statuses=STATUSES)


@bp.route("/<int:project_id>/duzenle", methods=["GET", "POST"])
@atomic
def edit(project_id):
    project = get_project(project_id)
    if not can_edit(project):
        abort(403)
    if project.status not in EDITABLE:
        abort(409)
    if request.method == "POST":
        check_version(project)
        try:
            values = plan_values(project)
        except ValueError as error:
            flash(str(error), "danger")
            return render_template("projects/form.html", **form_context(project)), 400
        if any(not values["start_date"] <= item.target_date <= values["due_date"] for item in project.milestones):
            raise ValueError("Proje tarihleri kilometre taşlarını da kapsamalıdır.")
        old = snapshot(project)
        for key, value in values.items():
            setattr(project, key, value)
        touch(project)
        audit(project, "updated", old)
        if any(old[key] != getattr(project, key) for key in ("owner_user_id", "due_date")):
            retire_notices(project)
            notify(project)
            for task in project.tasks:
                if task.status in {"pending", "in_progress"}:
                    notify(project, task)
        db.session.commit()
        return detail_redirect(project)
    return render_template("projects/form.html", **form_context(project))


@bp.post("/<int:project_id>/kilometre-tasi")
@atomic
def add_milestone(project_id):
    project = get_project(project_id)
    if not can_edit(project):
        abort(403)
    if project.status not in EDITABLE:
        abort(409)
    check_version(project)
    milestone = assign_current_company(ProjectMilestone(project=project, **milestone_values(project)))
    db.session.add(milestone)
    touch(project)
    db.session.flush()
    audit(milestone, "created")
    db.session.commit()
    return detail_redirect(project)


@bp.post("/<int:project_id>/kilometre-tasi/<int:milestone_id>")
@atomic
def update_milestone(project_id, milestone_id):
    project = get_project(project_id)
    milestone = company_query(ProjectMilestone).filter_by(id=milestone_id, project_id=project.id).first_or_404()
    if not can_edit(project):
        abort(403)
    if project.status not in EDITABLE:
        abort(409)
    check_version(milestone)
    check_version(project, "project_version_id")
    old = snapshot(milestone)
    action = request.form.get("action")
    if action == "edit" and milestone.status == "pending":
        for key, value in milestone_values(project).items():
            setattr(milestone, key, value)
    elif action == "complete" and milestone.status == "pending" and project.status == "active":
        milestone.completion_note = text_field("completion_note", required=True)
        milestone.status = "completed"
        milestone.completed_at = datetime.now(UTC).replace(tzinfo=None)
    elif action == "reopen" and milestone.status == "completed" and project.status == "active":
        reason = text_field("completion_note", required=True)
        record_audit_event("ProjectMilestone", "reopen_reason", milestone.title,
            entity_id=milestone.id, company_id=milestone.company_id,
            details={"reason": reason}, commit=False)
        milestone.status, milestone.completion_note, milestone.completed_at = "pending", None, None
    else:
        abort(409)
    touch(project)
    milestone.version_id += 1
    db.session.flush()
    audit(milestone, action, old)
    db.session.commit()
    return detail_redirect(project)


@bp.post("/<int:project_id>/durum")
@atomic
def transition(project_id):
    project = get_project(project_id)
    if not can_edit(project):
        abort(403)
    check_version(project)
    action = request.form.get("action")
    old = snapshot(project)
    if action == "activate" and project.status == "draft":
        if not project.activation_ready:
            raise ValueError("Projeyi başlatmak için amaç ve en az bir görev gereklidir.")
        assignees = {project.owner_user_id} | {t.owner_user_id for t in project.tasks if t.status != "cancelled"}
        users = {u.id: u for u in active_users()}
        for uid in assignees:
            user = users.get(uid)
            if user is None or not any(user.has_permission(k) for k in READ_PERMISSIONS):
                raise ValueError("Sorumluların aktifliğini ve proje erişimini kontrol edin.")
        if not (users[project.owner_user_id].has_permission("projects.create") or users[project.owner_user_id].has_permission("projects.manage")):
            raise ValueError("Proje sorumlusunun yetkisini kontrol edin.")
        if any(not (users[t.owner_user_id].has_permission("projects.update") or users[t.owner_user_id].has_permission("projects.manage")) for t in project.tasks if t.status != "cancelled"):
            raise ValueError("Görev sorumlularının güncelleme yetkisini kontrol edin.")
        project.status = "active"
    elif action == "complete" and project.status == "active":
        if not project.completion_ready:
            raise ValueError("Projeyi tamamlamak için tüm açık görevleri sonuçlandırın.")
        project.completion_note = text_field("completion_note", required=True)
        project.completed_at = datetime.now(UTC).replace(tzinfo=None)
        project.status = "completed"
        retire_notices(project)
    elif action == "reopen" and project.status == "completed":
        reason = text_field("completion_note", required=True)
        record_audit_event("ProjectRecord", "reopen_reason", project.title, entity_id=project.id,
            company_id=project.company_id, details={"reason": reason}, commit=False)
        project.status, project.completed_at, project.completion_note = "active", None, None
    elif action == "archive" and project.archive_ready:
        note = text_field("completion_note", required=True)
        project.archive_note = note
        project.status = "archived"
        retire_notices(project)
        # Completed evidence is retained; archive reason is separately audited.
        record_audit_event("ProjectRecord", "archive_reason", project.title,
            entity_id=project.id, company_id=project.company_id, details={"reason": note}, commit=False)
    else:
        abort(409)
    touch(project)
    audit(project, action, old)
    if action == "activate":
        notify(project)
        for task in project.tasks:
            if task.status != "cancelled":
                notify(project, task)
    db.session.commit()
    return detail_redirect(project)


@bp.post("/<int:project_id>/gorev")
@atomic
def add_task(project_id):
    project = get_project(project_id)
    if not can_edit(project):
        abort(403)
    if project.status not in EDITABLE:
        abort(409)
    check_version(project)
    task = assign_current_company(ProjectTask(project=project, **plan_values(project, task=True)))
    db.session.add(task)
    touch(project)
    db.session.flush()
    audit(task, "created")
    notify(project, task)
    db.session.commit()
    return detail_redirect(project)


@bp.post("/<int:project_id>/gorev/<int:task_id>")
@atomic
def update_task(project_id, task_id):
    project = get_project(project_id)
    task = company_query(ProjectTask).filter_by(id=task_id, project_id=project.id).first_or_404()
    action = request.form.get("action")
    if action in {"edit", "cancel", "reopen"}:
        if not can_edit(project):
            abort(403)
        if project.status not in EDITABLE:
            abort(409)
    elif not can_update_task(project, task):
        abort(403)
    check_version(task)
    check_version(project, "project_version_id")
    old = snapshot(task)
    if action == "edit" and task.status in {"pending", "in_progress"}:
        for key, value in plan_values(project, task=True).items():
            setattr(task, key, value)
    elif action == "start" and task.status == "pending":
        task.status = "in_progress"
    elif action == "complete" and task.status in {"pending", "in_progress"}:
        task.completion_note = text_field("completion_note", required=True)
        task.status, task.completed_at = "completed", datetime.now(UTC).replace(tzinfo=None)
    elif action == "cancel" and task.status in {"pending", "in_progress"}:
        task.completion_note = text_field("completion_note", required=True)
        task.status = "cancelled"
    elif action == "reopen" and task.status in {"completed", "cancelled"}:
        if not (project.start_date <= task.start_date <= task.due_date <= project.due_date):
            raise ValueError("Görev tarihlerini kapsayacak şekilde proje tarihlerini güncelleyin.")
        owner = company_query(User).filter_by(id=task.owner_user_id, is_active=True).first()
        if owner is None or not any(owner.has_permission(k) for k in READ_PERMISSIONS) or not (owner.has_permission("projects.update") or owner.has_permission("projects.manage")):
            raise ValueError("Görev sorumlusunun aktifliğini ve yetkisini kontrol edin.")
        reason = text_field("completion_note", required=True)
        record_audit_event("ProjectTask", "reopen_reason", task.title, entity_id=task.id,
            company_id=task.company_id, details={"reason": reason}, commit=False)
        task.status, task.completion_note, task.completed_at = "pending", None, None
    else:
        abort(409)
    touch(project)
    task.version_id += 1
    db.session.flush()
    audit(task, action, old)
    if action == "reopen" or (action == "edit" and any(old[key] != getattr(task, key) for key in ("owner_user_id", "due_date"))):
        retire_notices(project, task)
        notify(project, task)
    elif action in {"complete", "cancel"}:
        retire_notices(project, task)
    db.session.commit()
    return detail_redirect(project)


@bp.get("/<int:project_id>/rapor")
@atomic
def export(project_id):
    require_permission("projects.export")
    project = get_project(project_id)
    from .routes import build_simple_xlsx
    rows = [(t.due_date, "Görev", t.title, t.owner.full_name if t.owner else "",
        str(t.start_date), str(t.due_date), TASK_STATUSES[t.status],
        str(t.estimated_hours) if t.estimated_hours is not None else "", "", t.completion_note or "")
        for t in project.tasks]
    rows += [(m.target_date, "Kilometre Taşı", m.title, "", str(m.target_date),
        str(m.target_date), MILESTONE_STATUSES[m.status], "", m.acceptance_criteria,
        m.completion_note or "") for m in project.milestones]
    rows.sort(key=lambda row: (row[0], row[1], row[2]))
    workbook = build_simple_xlsx(
        ("Tür", "Kayıt", "Sorumlu", "Başlangıç", "Termin", "Durum", "Tahmini Efor (saat)", "Kabul Ölçütü", "Sonuç"),
        [row[1:] for row in rows],
        sheet_name="Proje Planı", metadata=[("Proje", project.project_no), ("Başlık", project.title),
            ("Amaç", project.description or ""), ("Durum", STATUSES[project.status]),
            ("İlerleme", f"%{project.progress}"), ("Sonuç", project.completion_note or ""),
            ("Arşiv Gerekçesi", project.archive_note or ""),
            ("Kapanış Türü", "Tamamlanarak arşivlendi" if project.completion_note else "Tamamlanmadan arşivlendi")
            if project.status == "archived" else ("Kapanış Türü", "")])
    audit(project, "exported")
    db.session.commit()
    return send_file(workbook, as_attachment=True, download_name=f"{project.project_no}.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


def report_data():
    require_permission(*READ_PERMISSIONS)
    checker = getattr(g, "company_module_enabled", None)
    if checker and not checker("projects"):
        abort(404)
    rows = visible_projects().order_by(ProjectRecord.due_date, ProjectRecord.id).all() if current_company_id() else []
    return {"headers": ("Proje No", "Başlık", "Sorumlu", "Başlangıç", "Termin", "Durum", "İlerleme (%)", "Görev Sayısı", "Kapanış Türü", "Arşiv Gerekçesi"),
        "rows": [(p.project_no, p.title, p.owner.full_name if p.owner else "", p.start_date.strftime("%d.%m.%Y"), p.due_date.strftime("%d.%m.%Y"), STATUSES[p.status], str(p.progress), str(len(p.tasks)),
            ("Tamamlanarak arşivlendi" if p.completion_note else "Tamamlanmadan arşivlendi") if p.status == "archived" else "", p.archive_note or "") for p in rows],
        "sheet_name": "Projeler", "column_widths": (22, 48, 28, 18, 18, 20, 16, 16, 26, 48)}


def assigned_task_rows(scope, row_builder):
    if not current_company_id() or not (has_permission("projects.update") or has_permission("projects.manage")) or scope == "created":
        return []
    if not any(has_permission(k) for k in READ_PERMISSIONS):
        return []
    checker = getattr(g, "company_module_enabled", None)
    if checker and not checker("projects"):
        return []
    tasks = company_query(ProjectTask).join(ProjectTask.project).filter(
        ProjectRecord.company_id == current_company_id(), ProjectRecord.status == "active",
        ProjectTask.owner_user_id == g.current_user.id, ProjectTask.status.in_(("pending", "in_progress")),
    ).options(joinedload(ProjectTask.project)).order_by(ProjectTask.due_date, ProjectTask.id).all()
    return [row_builder(module_key="projects", module_label="Projeler", module_icon="kanban", module_tone="quality",
        title=t.title, description=t.project.title, reference_no=t.project.project_no, department="",
        due_date=t.due_date, status=TASK_STATUSES[t.status], status_key="delayed" if t.due_date < date.today() else "pending",
        priority="Orta", detail_url=url_for("projects.detail", project_id=t.project_id), created_at=t.project.created_at, sort_id=t.id) for t in tasks]
