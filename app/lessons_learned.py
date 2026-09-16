from datetime import UTC, date, datetime
from functools import wraps
import hashlib
from pathlib import Path
from uuid import uuid4

from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, send_file, url_for
from sqlalchemy import or_

from .extensions import db
from .models import Action, Dof, KaizenProject, LessonLearned, LessonLearnedFile, ProblemSolvingCase, RiskRecord, User
from .notifications import add_user_notification
from .tenant import current_company_id, scoped_query

bp = Blueprint("lessons_learned", __name__, url_prefix="/alinan-dersler")
CATEGORIES = ("Kalite", "Üretim", "İSG", "Çevre", "Müşteri", "Tedarikçi", "Bakım", "Genel")
STATUSES = ("Taslak", "İnceleme Bekliyor", "Revizyon Bekliyor", "Yayınlandı", "Arşiv")
ALLOWED_EXTENSIONS = {"pdf", "doc", "docx", "xls", "xlsx", "csv", "txt", "jpg", "jpeg", "png"}


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if getattr(g, "current_user", None) is None:
            return redirect(url_for("main.login", next=request.full_path))
        return view(*args, **kwargs)
    return wrapped


def has_permission(key):
    return bool(getattr(g, "current_user", None) and g.current_user.has_permission(key))


def require_permission(*keys):
    if not any(has_permission(key) for key in keys):
        abort(403)


def lesson_query():
    return scoped_query(LessonLearned.query, LessonLearned)


def active_users():
    return User.query.filter_by(company_id=current_company_id(), is_active=True).order_by(User.full_name).all()


def can_access(row):
    if row.status == "Yayınlandı":
        return has_permission("lessons.view") or has_permission("lessons.view_all") or has_permission("lessons.manage")
    return bool(has_permission("lessons.view_all") or has_permission("lessons.manage") or row.owner_user_id == g.current_user.id or row.reviewer_user_id == g.current_user.id or row.created_by_user_id == g.current_user.id)


def get_lesson_or_404(lesson_id):
    row = lesson_query().filter_by(id=lesson_id).first_or_404()
    if not can_access(row):
        abort(404)
    return row


def parse_user(name):
    try:
        user_id = int(request.form.get(name, ""))
    except ValueError:
        raise ValueError("Aktif bir personel seçin.") from None
    if not User.query.filter_by(id=user_id, company_id=current_company_id(), is_active=True).first():
        raise ValueError("Seçilen personel bu şirkette aktif değil.")
    return user_id


def optional_id(name, model):
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


def next_lesson_no():
    prefix = f"DERS-{date.today().year}-"
    numbers = []
    for (value,) in lesson_query().with_entities(LessonLearned.lesson_no).filter(LessonLearned.lesson_no.like(f"{prefix}%")).all():
        try:
            numbers.append(int(value.rsplit("-", 1)[-1]))
        except (TypeError, ValueError):
            pass
    return f"{prefix}{max(numbers, default=0) + 1:04d}"


def store_file(upload, row):
    if not upload or not upload.filename:
        return
    extension = Path(upload.filename).suffix.lower().lstrip(".")
    if extension not in ALLOWED_EXTENSIONS:
        raise ValueError("Yalnızca PDF, Word, Excel, CSV, metin veya görsel yükleyin.")
    from .routes import assert_company_storage_quota, safe_original_filename, upload_storage_path, uploaded_stream_size
    original = safe_original_filename(upload.filename, "alinan-ders-kaniti")
    relative, absolute = upload_storage_path(f"{uuid4().hex}.{extension}", "lessons-learned", row.company_id)
    assert_company_storage_quota(row.company_id, uploaded_stream_size(upload))
    upload.save(absolute)
    db.session.add(LessonLearnedFile(company_id=row.company_id, lesson_record=row, original_name=original, stored_path=str(relative).replace("\\", "/"), mime_type=upload.mimetype, file_size=absolute.stat().st_size, sha256_hash=hashlib.sha256(absolute.read_bytes()).hexdigest(), uploaded_by_user_id=g.current_user.id))


def notify(user_id, row, message, suffix):
    user = User.query.filter_by(id=user_id, company_id=row.company_id, is_active=True).first()
    if user:
        add_user_notification(user, f"{row.lesson_no} - {message}", company_id=row.company_id, source_key=f"lesson:{suffix}:{row.id}:{user_id}", target_url=url_for("lessons_learned.detail", lesson_id=row.id))


def form_context():
    return {
        "users": active_users(), "categories": CATEGORIES, "values": request.form,
        "problem_cases": scoped_query(ProblemSolvingCase.query, ProblemSolvingCase).filter_by(status="Tamamlandı").order_by(ProblemSolvingCase.id.desc()).all(),
        "dofs": scoped_query(Dof.query, Dof).order_by(Dof.id.desc()).all(),
        "actions": scoped_query(Action.query, Action).order_by(Action.id.desc()).all(),
        "risks": scoped_query(RiskRecord.query, RiskRecord).order_by(RiskRecord.id.desc()).all(),
        "kaizens": scoped_query(KaizenProject.query, KaizenProject).order_by(KaizenProject.id.desc()).all(),
    }


@bp.before_request
def guard():
    checker = getattr(g, "company_module_enabled", None)
    if checker and not checker("lessons_learned"):
        abort(404)


@bp.get("")
@login_required
def dashboard():
    require_permission("lessons.view", "lessons.view_all", "lessons.manage")
    query = lesson_query()
    if not (has_permission("lessons.view_all") or has_permission("lessons.manage")):
        query = query.filter(or_(LessonLearned.status == "Yayınlandı", LessonLearned.owner_user_id == g.current_user.id, LessonLearned.reviewer_user_id == g.current_user.id, LessonLearned.created_by_user_id == g.current_user.id))
    search = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()
    status = request.args.get("status", "").strip()
    if search:
        term = f"%{search}%"
        query = query.filter(or_(LessonLearned.lesson_no.ilike(term), LessonLearned.title.ilike(term), LessonLearned.tags.ilike(term), LessonLearned.lesson.ilike(term), LessonLearned.recommendation.ilike(term)))
    if category in CATEGORIES:
        query = query.filter_by(category=category)
    if status in STATUSES:
        query = query.filter_by(status=status)
    else:
        query = query.filter(LessonLearned.status != "Arşiv")
    return render_template("lessons_learned/dashboard.html", lessons=query.order_by(LessonLearned.published_at.desc(), LessonLearned.id.desc()).all(), categories=CATEGORIES, statuses=STATUSES, search=search, selected_category=category, selected_status=status, can_create=has_permission("lessons.create") or has_permission("lessons.manage"))


@bp.route("/yeni", methods=["GET", "POST"])
@login_required
def create():
    require_permission("lessons.create", "lessons.manage")
    if request.method == "POST":
        try:
            title = request.form.get("title", "").strip()
            situation = request.form.get("situation", "").strip()
            lesson_text = request.form.get("lesson", "").strip()
            recommendation = request.form.get("recommendation", "").strip()
            owner_id = parse_user("owner_user_id")
            reviewer_id = parse_user("reviewer_user_id")
            if not all((title, situation, lesson_text, recommendation)):
                raise ValueError("Başlık, olay, alınan ders ve önerilen uygulama zorunludur.")
            if owner_id == reviewer_id:
                raise ValueError("Kayıt sahibi ve inceleyen farklı kişiler olmalıdır.")
            category = request.form.get("category", "Genel").strip()
            if category not in CATEGORIES:
                raise ValueError("Kategori geçersiz.")
            row = LessonLearned(company_id=current_company_id(), lesson_no=next_lesson_no(), title=title, department=request.form.get("department", "").strip() or None, category=category, tags=request.form.get("tags", "").strip() or None, situation=situation, lesson=lesson_text, recommendation=recommendation, applicability=request.form.get("applicability", "").strip() or None, owner_user_id=owner_id, reviewer_user_id=reviewer_id, created_by_user_id=g.current_user.id, problem_solving_case_id=optional_id("problem_solving_case_id", ProblemSolvingCase), dof_id=optional_id("dof_id", Dof), action_id=optional_id("action_id", Action), risk_id=optional_id("risk_id", RiskRecord), kaizen_project_id=optional_id("kaizen_project_id", KaizenProject))
            db.session.add(row)
            db.session.flush()
            store_file(request.files.get("attachment"), row)
            db.session.commit()
            flash(f"{row.lesson_no} taslak olarak oluşturuldu.", "success")
            return redirect(url_for("lessons_learned.detail", lesson_id=row.id))
        except ValueError as error:
            db.session.rollback()
            flash(str(error), "danger")
    return render_template("lessons_learned/form.html", **form_context())


@bp.get("/<int:lesson_id>")
@login_required
def detail(lesson_id):
    require_permission("lessons.view", "lessons.view_all", "lessons.manage")
    row = get_lesson_or_404(lesson_id)
    can_edit = (has_permission("lessons.manage") or row.owner_user_id == g.current_user.id) and row.status in {"Taslak", "Revizyon Bekliyor"}
    can_review = (has_permission("lessons.review") or has_permission("lessons.manage")) and (row.reviewer_user_id == g.current_user.id or has_permission("lessons.manage")) and row.status == "İnceleme Bekliyor"
    return render_template("lessons_learned/detail.html", lesson_record=row, can_edit=can_edit, can_review=can_review, can_archive=(has_permission("lessons.archive") or has_permission("lessons.manage")) and row.status == "Yayınlandı", can_download=has_permission("lessons.file_download") or has_permission("lessons.manage"))


@bp.post("/<int:lesson_id>/guncelle")
@login_required
def update(lesson_id):
    require_permission("lessons.update", "lessons.manage")
    row = get_lesson_or_404(lesson_id)
    if row.owner_user_id != g.current_user.id and not has_permission("lessons.manage"):
        abort(403)
    if row.status not in {"Taslak", "Revizyon Bekliyor"}:
        abort(409)
    for name in ("title", "situation", "lesson", "recommendation"):
        value = request.form.get(name, "").strip()
        if not value:
            flash("Zorunlu alanları doldurun.", "danger")
            return redirect(url_for("lessons_learned.detail", lesson_id=row.id))
        setattr(row, name, value)
    row.department = request.form.get("department", "").strip() or None
    row.tags = request.form.get("tags", "").strip() or None
    row.applicability = request.form.get("applicability", "").strip() or None
    store_file(request.files.get("attachment"), row)
    db.session.commit()
    flash("Taslak güncellendi.", "success")
    return redirect(url_for("lessons_learned.detail", lesson_id=row.id))


@bp.post("/<int:lesson_id>/incelemeye-gonder")
@login_required
def submit(lesson_id):
    require_permission("lessons.update", "lessons.manage")
    row = get_lesson_or_404(lesson_id)
    if row.owner_user_id != g.current_user.id and not has_permission("lessons.manage"):
        abort(403)
    if row.status not in {"Taslak", "Revizyon Bekliyor"}:
        abort(409)
    row.status = "İnceleme Bekliyor"
    row.submitted_at = datetime.now(UTC).replace(tzinfo=None)
    notify(row.reviewer_user_id, row, "Alınan ders kaydı incelemenizi bekliyor.", f"review-{row.submitted_at.timestamp()}")
    db.session.commit()
    flash("Kayıt incelemeye gönderildi.", "success")
    return redirect(url_for("lessons_learned.detail", lesson_id=row.id))


@bp.post("/<int:lesson_id>/incele")
@login_required
def review(lesson_id):
    require_permission("lessons.review", "lessons.manage")
    row = get_lesson_or_404(lesson_id)
    if row.reviewer_user_id != g.current_user.id and not has_permission("lessons.manage"):
        abort(403)
    if row.status != "İnceleme Bekliyor":
        abort(409)
    decision = request.form.get("decision")
    note = request.form.get("review_note", "").strip()
    if decision == "return":
        if not note:
            flash("Revizyon gerekçesi zorunludur.", "danger")
            return redirect(url_for("lessons_learned.detail", lesson_id=row.id))
        row.status = "Revizyon Bekliyor"
        row.review_note = note
        notify(row.owner_user_id, row, "Kayıt revizyona gönderildi.", f"returned-{datetime.now(UTC).timestamp()}")
    elif decision == "publish":
        row.status = "Yayınlandı"
        row.review_note = note or None
        row.published_at = datetime.now(UTC).replace(tzinfo=None)
        row.published_by_user_id = g.current_user.id
        notify(row.owner_user_id, row, "Kayıt doğrulandı ve yayınlandı.", "published")
    else:
        abort(400)
    db.session.commit()
    flash("İnceleme kararı kaydedildi.", "success")
    return redirect(url_for("lessons_learned.detail", lesson_id=row.id))


@bp.post("/<int:lesson_id>/yeniden-kullan")
@login_required
def reuse(lesson_id):
    require_permission("lessons.view", "lessons.view_all", "lessons.manage")
    row = get_lesson_or_404(lesson_id)
    if row.status != "Yayınlandı":
        abort(409)
    row.reuse_count += 1
    db.session.commit()
    flash("Bu dersin yeniden kullanımı kaydedildi.", "success")
    return redirect(url_for("lessons_learned.detail", lesson_id=row.id))


@bp.post("/<int:lesson_id>/arsivle")
@login_required
def archive(lesson_id):
    require_permission("lessons.archive", "lessons.manage")
    row = get_lesson_or_404(lesson_id)
    if row.status != "Yayınlandı":
        abort(409)
    row.status = "Arşiv"
    row.archived_at = datetime.now(UTC).replace(tzinfo=None)
    db.session.commit()
    flash("Kayıt arşivlendi.", "success")
    return redirect(url_for("lessons_learned.dashboard", status="Arşiv"))


@bp.get("/dosya/<int:file_id>")
@login_required
def download_file(file_id):
    require_permission("lessons.file_download", "lessons.manage")
    file_row = scoped_query(LessonLearnedFile.query, LessonLearnedFile).filter_by(id=file_id).first_or_404()
    if not can_access(file_row.lesson_record):
        abort(404)
    root = Path(current_app.config["UPLOAD_FOLDER"]).resolve()
    path = (root / file_row.stored_path).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        abort(404)
    if not path.is_file():
        abort(404)
    return send_file(path, as_attachment=True, download_name=file_row.original_name)


def assigned_task_rows(scope, row_builder):
    query = lesson_query().filter_by(status="İnceleme Bekliyor", reviewer_user_id=g.current_user.id)
    if scope == "created":
        query = lesson_query().filter(LessonLearned.status.in_(("Taslak", "Revizyon Bekliyor")), LessonLearned.created_by_user_id == g.current_user.id)
    return [row_builder(module_key="lessons", module_label="Alınan Dersler", module_icon="journal-check", module_tone="quality", title=row.title, description=row.lesson, reference_no=row.lesson_no, department=row.department or row.category, due_date=row.created_at.date(), status=row.status, status_key="pending", priority="Orta", detail_url=url_for("lessons_learned.detail", lesson_id=row.id), created_at=row.created_at, sort_id=row.id, date_label="Kayıt") for row in query.all()]
