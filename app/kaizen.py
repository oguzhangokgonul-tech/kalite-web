from datetime import UTC, date, datetime, timedelta
from functools import wraps
import hashlib
from pathlib import Path
from uuid import uuid4

from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, send_file, url_for
from sqlalchemy import or_

from .extensions import db
from .models import Action, KaizenProject, KaizenProjectFile, KaizenProjectUpdate, KaizenTeamMember, QualityObjective, Suggestion, User
from .notifications import add_user_notification
from .tenant import current_company_id, scoped_query


bp = Blueprint("kaizen", __name__, url_prefix="/kaizen")
STAGES = ("Fikir", "Analiz", "Uygulama", "Doğrulama", "Standartlaştırma", "Tamamlandı")
STATUSES = ("Açık", "Devam Ediyor", "Onay Bekliyor", "Tamamlandı", "İptal")
PRIORITIES = ("Düşük", "Orta", "Yüksek", "Kritik")
ALLOWED_EXTENSIONS = {"pdf", "doc", "docx", "xls", "xlsx", "csv", "txt", "jpg", "jpeg", "png"}


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if getattr(g, "current_user", None) is None:
            return redirect(url_for("main.login", next=request.full_path))
        return view(*args, **kwargs)
    return wrapped


def has_permission(key):
    user = getattr(g, "current_user", None)
    return bool(user and user.has_permission(key))


def require_permission(*keys):
    if not any(has_permission(key) for key in keys):
        abort(403)


def module_enabled():
    checker = getattr(g, "company_module_enabled", None)
    return checker("kaizen_management") if checker else True


def project_query():
    return scoped_query(KaizenProject.query, KaizenProject)


def can_access(project):
    user_id = g.current_user.id
    return bool(
        has_permission("kaizen.view_all") or has_permission("kaizen.manage")
        or project.created_by_user_id == user_id or project.owner_user_id == user_id
        or any(member.user_id == user_id for member in project.team_members)
    )


def get_project_or_404(project_id):
    project = project_query().filter_by(id=project_id).first_or_404()
    if not can_access(project):
        abort(404)
    return project


def parse_date(name, required=False):
    raw = request.form.get(name, "").strip()
    if not raw:
        if required:
            raise ValueError("Tarih alanı zorunludur.")
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise ValueError("Tarih bilgisini kontrol edin.") from None


def parse_float(name):
    raw = request.form.get(name, "").strip().replace(",", ".")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        raise ValueError("Sayısal değerleri kontrol edin.") from None


def active_users():
    return User.query.filter_by(company_id=current_company_id(), is_active=True).order_by(User.full_name.asc()).all()


def scoped_choices(model, label):
    return scoped_query(model.query, model).order_by(model.id.desc()).all(), label


def optional_scoped_id(name, model):
    raw = request.form.get(name, "").strip()
    if not raw:
        return None
    try:
        row_id = int(raw)
    except ValueError:
        raise ValueError("Bağlantılı kayıt geçersiz.") from None
    if not scoped_query(model.query, model).filter_by(id=row_id).first():
        raise ValueError("Bağlantılı kayıt bu şirkete ait değil.")
    return row_id


def selected_team_ids():
    valid = {user.id for user in active_users()}
    try:
        selected = {int(value) for value in request.form.getlist("team_user_ids")}
    except ValueError:
        raise ValueError("Ekip seçimini kontrol edin.") from None
    if not selected.issubset(valid):
        raise ValueError("Ekipte yalnızca aktif şirket personeli seçilebilir.")
    return selected


def parse_form():
    users = {user.id for user in active_users()}
    try:
        owner_id = int(request.form.get("owner_user_id", ""))
    except ValueError:
        raise ValueError("Proje sorumlusu zorunludur.") from None
    if owner_id not in users:
        raise ValueError("Proje sorumlusu bu şirkette aktif değil.")
    stage = request.form.get("stage", "Fikir").strip()
    status = request.form.get("status", "Açık").strip()
    priority = request.form.get("priority", "Orta").strip()
    title = request.form.get("title", "").strip()
    problem = request.form.get("problem_statement", "").strip()
    if not title or not problem:
        raise ValueError("Proje adı ve problem tanımı zorunludur.")
    if stage not in STAGES or status not in STATUSES or priority not in PRIORITIES:
        raise ValueError("Aşama, durum veya öncelik geçersiz.")
    return {
        "title": title, "department": request.form.get("department", "").strip() or None,
        "owner_user_id": owner_id, "stage": stage, "status": status, "priority": priority,
        "start_date": parse_date("start_date", True), "target_date": parse_date("target_date"),
        "problem_statement": problem,
        "current_state": request.form.get("current_state", "").strip() or None,
        "target_state": request.form.get("target_state", "").strip() or None,
        "root_cause": request.form.get("root_cause", "").strip() or None,
        "solution": request.form.get("solution", "").strip() or None,
        "verification_method": request.form.get("verification_method", "").strip() or None,
        "standardization_plan": request.form.get("standardization_plan", "").strip() or None,
        "metric_name": request.form.get("metric_name", "").strip() or None,
        "baseline_value": parse_float("baseline_value"), "target_value": parse_float("target_value"),
        "estimated_cost": parse_float("estimated_cost"), "estimated_benefit": parse_float("estimated_benefit"),
        "suggestion_id": optional_scoped_id("suggestion_id", Suggestion),
        "action_id": optional_scoped_id("action_id", Action),
        "quality_objective_id": optional_scoped_id("quality_objective_id", QualityObjective),
    }


def next_project_no():
    prefix = f"KZN-{date.today().year}-"
    values = []
    for (number,) in project_query().with_entities(KaizenProject.project_no).filter(KaizenProject.project_no.like(f"{prefix}%")).all():
        try:
            values.append(int(number.rsplit("-", 1)[-1]))
        except (TypeError, ValueError):
            pass
    return f"{prefix}{max(values, default=0) + 1:04d}"


def sync_team(project, user_ids):
    existing = {member.user_id: member for member in project.team_members}
    for user_id in set(existing) - user_ids:
        db.session.delete(existing[user_id])
    for user_id in user_ids - set(existing):
        db.session.add(KaizenTeamMember(company_id=project.company_id, project=project, user_id=user_id))


def store_file(upload, project):
    if not upload or not upload.filename:
        return
    extension = Path(upload.filename).suffix.lower().lstrip(".")
    if extension not in ALLOWED_EXTENSIONS:
        raise ValueError("Yalnızca PDF, Word, Excel, CSV, metin veya görsel yükleyin.")
    from .routes import assert_company_storage_quota, safe_original_filename, upload_storage_path, uploaded_stream_size
    original = safe_original_filename(upload.filename, "kaizen-kanit")
    relative, absolute = upload_storage_path(f"{uuid4().hex}.{extension}", "kaizen", project.company_id)
    assert_company_storage_quota(project.company_id, uploaded_stream_size(upload))
    upload.save(absolute)
    db.session.add(KaizenProjectFile(
        company_id=project.company_id, project=project, original_name=original,
        stored_path=str(relative).replace("\\", "/"), mime_type=upload.mimetype,
        file_size=absolute.stat().st_size, sha256_hash=hashlib.sha256(absolute.read_bytes()).hexdigest(),
        uploaded_by_user_id=g.current_user.id,
    ))


def form_context(project=None):
    return {
        "project": project, "values": request.form, "users": active_users(), "stages": STAGES,
        "statuses": STATUSES, "priorities": PRIORITIES, "today": date.today().isoformat(),
        "suggestions": scoped_query(Suggestion.query, Suggestion).order_by(Suggestion.id.desc()).all(),
        "actions": scoped_query(Action.query, Action).order_by(Action.id.desc()).all(),
        "objectives": scoped_query(QualityObjective.query, QualityObjective).order_by(QualityObjective.id.desc()).all(),
        "selected_team": {int(v) for v in request.form.getlist("team_user_ids") if v.isdigit()} if request.form else ({m.user_id for m in project.team_members} if project else set()),
    }


@bp.before_request
def guard_module():
    if not module_enabled():
        abort(404)


@bp.get("")
@login_required
def dashboard():
    require_permission("kaizen.view", "kaizen.view_all", "kaizen.manage")
    query = project_query()
    if not (has_permission("kaizen.view_all") or has_permission("kaizen.manage")):
        member_ids = db.session.query(KaizenTeamMember.project_id).filter_by(company_id=current_company_id(), user_id=g.current_user.id)
        query = query.filter(or_(KaizenProject.created_by_user_id == g.current_user.id, KaizenProject.owner_user_id == g.current_user.id, KaizenProject.id.in_(member_ids)))
    search, stage, status = (request.args.get(key, "").strip() for key in ("q", "stage", "status"))
    archived = request.args.get("archived", "active") == "archived"
    query = query.filter(KaizenProject.archived_at.is_not(None) if archived else KaizenProject.archived_at.is_(None))
    if search:
        term = f"%{search}%"
        query = query.filter(or_(KaizenProject.project_no.ilike(term), KaizenProject.title.ilike(term), KaizenProject.department.ilike(term)))
    if stage in STAGES:
        query = query.filter_by(stage=stage)
    if status in STATUSES:
        query = query.filter_by(status=status)
    projects = query.order_by(KaizenProject.target_date.asc(), KaizenProject.project_no.asc()).all()
    return render_template("kaizen/dashboard.html", projects=projects, stages=STAGES, statuses=STATUSES, search=search, selected_stage=stage, selected_status=status, archived=archived, today=date.today(), can_create=has_permission("kaizen.create") or has_permission("kaizen.manage"), can_manage=has_permission("kaizen.manage"))


@bp.route("/yeni", methods=["GET", "POST"])
@login_required
def create():
    require_permission("kaizen.create", "kaizen.manage")
    if request.method == "POST":
        try:
            values, team_ids = parse_form(), selected_team_ids()
            project = KaizenProject(company_id=current_company_id(), project_no=next_project_no(), created_by_user_id=g.current_user.id, **values)
            db.session.add(project); db.session.flush()
            sync_team(project, team_ids)
            db.session.add(KaizenProjectUpdate(company_id=project.company_id, project=project, stage=project.stage, status=project.status, note="Kaizen projesi oluşturuldu.", created_by_user_id=g.current_user.id))
            store_file(request.files.get("attachment"), project)
            recipients = {project.owner_user_id, *team_ids} - {g.current_user.id}
            for user in User.query.filter(User.id.in_(recipients), User.company_id == project.company_id).all() if recipients else []:
                add_user_notification(user, f"{project.project_no} Kaizen projesinde görevlendirildiniz: {project.title}", company_id=project.company_id, source_key=f"kaizen-assignment:{project.id}:{user.id}", target_url=url_for("kaizen.detail", project_id=project.id))
            db.session.commit()
            flash(f"{project.project_no} Kaizen projesi oluşturuldu.", "success")
            return redirect(url_for("kaizen.detail", project_id=project.id))
        except ValueError as error:
            db.session.rollback(); flash(str(error), "danger")
    return render_template("kaizen/form.html", **form_context())


@bp.route("/<int:project_id>/duzenle", methods=["GET", "POST"])
@login_required
def edit(project_id):
    require_permission("kaizen.manage")
    project = get_project_or_404(project_id)
    if project.archived_at:
        abort(409)
    if request.method == "POST":
        try:
            values, team_ids = parse_form(), selected_team_ids()
            for key, value in values.items(): setattr(project, key, value)
            sync_team(project, team_ids); store_file(request.files.get("attachment"), project)
            db.session.commit(); flash("Kaizen projesi güncellendi.", "success")
            return redirect(url_for("kaizen.detail", project_id=project.id))
        except ValueError as error:
            db.session.rollback(); flash(str(error), "danger")
    return render_template("kaizen/form.html", **form_context(project))


@bp.get("/<int:project_id>")
@login_required
def detail(project_id):
    require_permission("kaizen.view", "kaizen.view_all", "kaizen.manage")
    project = get_project_or_404(project_id)
    return render_template("kaizen/detail.html", project=project, stages=STAGES, statuses=STATUSES, can_manage=has_permission("kaizen.manage"), can_update=has_permission("kaizen.update") or has_permission("kaizen.manage"), can_archive=has_permission("kaizen.archive") or has_permission("kaizen.manage"), can_download=has_permission("kaizen.file_download") or has_permission("kaizen.manage"))


@bp.post("/<int:project_id>/ilerleme")
@login_required
def add_update(project_id):
    require_permission("kaizen.update", "kaizen.manage")
    project = get_project_or_404(project_id)
    if project.archived_at:
        abort(409)
    stage, status, note = request.form.get("stage", "").strip(), request.form.get("status", "").strip(), request.form.get("note", "").strip()
    if stage not in STAGES or status not in STATUSES or not note:
        flash("Aşama, durum ve ilerleme notu zorunludur.", "danger"); return redirect(url_for("kaizen.detail", project_id=project.id))
    try:
        project.stage, project.status = stage, status
        project.actual_value, project.realized_cost, project.realized_benefit = parse_float("actual_value"), parse_float("realized_cost"), parse_float("realized_benefit")
        project.completed_at = datetime.now(UTC).replace(tzinfo=None) if status == "Tamamlandı" else None
        db.session.add(KaizenProjectUpdate(company_id=project.company_id, project=project, stage=stage, status=status, note=note, actual_value=project.actual_value, realized_cost=project.realized_cost, realized_benefit=project.realized_benefit, created_by_user_id=g.current_user.id))
        store_file(request.files.get("attachment"), project); db.session.commit(); flash("İlerleme kaydedildi.", "success")
    except ValueError as error:
        db.session.rollback(); flash(str(error), "danger")
    return redirect(url_for("kaizen.detail", project_id=project.id))


@bp.post("/<int:project_id>/arsivle")
@login_required
def archive(project_id):
    require_permission("kaizen.archive", "kaizen.manage")
    project = get_project_or_404(project_id)
    if project.status not in {"Tamamlandı", "İptal"}:
        flash("Yalnızca tamamlanan veya iptal edilen proje arşivlenebilir.", "danger"); return redirect(url_for("kaizen.detail", project_id=project.id))
    project.archived_at = datetime.now(UTC).replace(tzinfo=None); db.session.commit()
    flash("Kaizen projesi denetim izi korunarak arşivlendi.", "success")
    return redirect(url_for("kaizen.dashboard", archived="archived"))


@bp.get("/dosya/<int:file_id>")
@login_required
def download_file(file_id):
    require_permission("kaizen.file_download", "kaizen.manage")
    row = scoped_query(KaizenProjectFile.query, KaizenProjectFile).filter_by(id=file_id).first_or_404()
    if not can_access(row.project): abort(404)
    root = Path(current_app.config["UPLOAD_FOLDER"]).resolve(); path = (root / row.stored_path).resolve()
    try: path.relative_to(root)
    except ValueError: abort(404)
    if not path.is_file(): abort(404)
    return send_file(path, as_attachment=True, download_name=row.original_name)


def assigned_task_rows(scope, row_builder):
    if not module_enabled(): return []
    query = project_query().filter(KaizenProject.archived_at.is_(None), ~KaizenProject.status.in_(("Tamamlandı", "İptal")))
    if scope == "created": query = query.filter_by(created_by_user_id=g.current_user.id)
    else:
        memberships = db.session.query(KaizenTeamMember.project_id).filter_by(company_id=current_company_id(), user_id=g.current_user.id)
        query = query.filter(or_(KaizenProject.owner_user_id == g.current_user.id, KaizenProject.id.in_(memberships)))
    today, rows = date.today(), []
    for project in query.all():
        delayed = bool(project.target_date and project.target_date < today)
        rows.append(row_builder(module_key="kaizen", module_label="Kaizen", module_icon="arrow-up-right-circle", module_tone="quality", title=project.title, description=project.problem_statement, reference_no=project.project_no, department=project.department or "Kaizen", due_date=project.target_date or project.start_date, status="Termin Geçti" if delayed else project.stage, status_key="delayed" if delayed else "pending", priority="Yüksek" if delayed else project.priority, detail_url=url_for("kaizen.detail", project_id=project.id), created_at=project.created_at, sort_id=project.id, date_label="Hedef"))
    return rows
