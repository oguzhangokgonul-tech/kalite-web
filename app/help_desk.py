from datetime import UTC, date, datetime, timedelta
from functools import wraps
import hashlib
from pathlib import Path
from uuid import uuid4

from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, send_file, url_for
from sqlalchemy import or_

from .extensions import db
from .models import HelpDeskComment, HelpDeskFile, HelpDeskTicket, User
from .notifications import add_user_notification
from .tenant import current_company_id, scoped_query

bp = Blueprint("help_desk", __name__, url_prefix="/ic-talepler")
CATEGORIES = ("Bilgi Teknolojileri", "İnsan Kaynakları", "Kalite", "Bakım", "Satın Alma", "İdari İşler", "Diğer")
PRIORITIES = ("Düşük", "Orta", "Yüksek", "Kritik")
STATUSES = ("Yeni", "Atandı", "İşlemde", "Çözüm Bekliyor", "Yeniden Açıldı", "Kapatıldı", "Arşiv")
SLA_HOURS = {"Düşük": 72, "Orta": 24, "Yüksek": 8, "Kritik": 4}
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


def ticket_query():
    return scoped_query(HelpDeskTicket.query, HelpDeskTicket)


def active_users():
    return User.query.filter_by(company_id=current_company_id(), is_active=True).order_by(User.full_name).all()


def can_access(row):
    return bool(has_permission("helpdesk.view_all") or has_permission("helpdesk.manage") or row.requester_user_id == g.current_user.id or row.assignee_user_id == g.current_user.id)


def get_ticket_or_404(ticket_id):
    row = ticket_query().filter_by(id=ticket_id).first_or_404()
    if not can_access(row):
        abort(404)
    return row


def parse_user(name, required=False):
    raw = request.form.get(name, "").strip()
    if not raw and not required:
        return None
    try:
        user_id = int(raw)
    except ValueError:
        raise ValueError("Aktif bir personel seçin.") from None
    if not User.query.filter_by(id=user_id, company_id=current_company_id(), is_active=True).first():
        raise ValueError("Seçilen personel bu şirkette aktif değil.")
    return user_id


def next_ticket_no():
    prefix = f"TLP-{date.today().year}-"
    numbers = []
    for (value,) in ticket_query().with_entities(HelpDeskTicket.ticket_no).filter(HelpDeskTicket.ticket_no.like(f"{prefix}%")).all():
        try:
            numbers.append(int(value.rsplit("-", 1)[-1]))
        except (TypeError, ValueError):
            pass
    return f"{prefix}{max(numbers, default=0) + 1:04d}"


def notify(user_id, row, message, suffix):
    user = User.query.filter_by(id=user_id, company_id=row.company_id, is_active=True).first()
    if user:
        add_user_notification(user, f"{row.ticket_no} - {message}", company_id=row.company_id, source_key=f"helpdesk:{suffix}:{row.id}:{user_id}", target_url=url_for("help_desk.detail", ticket_id=row.id), due_date=row.sla_due_at.date())


def store_file(upload, row, comment=None):
    if not upload or not upload.filename:
        return
    extension = Path(upload.filename).suffix.lower().lstrip(".")
    if extension not in ALLOWED_EXTENSIONS:
        raise ValueError("Yalnızca PDF, Word, Excel, CSV, metin veya görsel yükleyin.")
    from .routes import assert_company_storage_quota, safe_original_filename, upload_storage_path, uploaded_stream_size
    original = safe_original_filename(upload.filename, "ic-talep-dosyasi")
    relative, absolute = upload_storage_path(f"{uuid4().hex}.{extension}", "help-desk", row.company_id)
    assert_company_storage_quota(row.company_id, uploaded_stream_size(upload))
    upload.save(absolute)
    db.session.add(HelpDeskFile(company_id=row.company_id, ticket=row, comment=comment, original_name=original, stored_path=str(relative).replace("\\", "/"), mime_type=upload.mimetype, file_size=absolute.stat().st_size, sha256_hash=hashlib.sha256(absolute.read_bytes()).hexdigest(), uploaded_by_user_id=g.current_user.id))


@bp.before_request
def guard():
    checker = getattr(g, "company_module_enabled", None)
    if checker and not checker("help_desk"):
        abort(404)


@bp.get("")
@login_required
def dashboard():
    require_permission("helpdesk.view", "helpdesk.view_all", "helpdesk.manage")
    query = ticket_query()
    if not (has_permission("helpdesk.view_all") or has_permission("helpdesk.manage")):
        query = query.filter(or_(HelpDeskTicket.requester_user_id == g.current_user.id, HelpDeskTicket.assignee_user_id == g.current_user.id))
    search = request.args.get("q", "").strip()
    status = request.args.get("status", "").strip()
    priority = request.args.get("priority", "").strip()
    if search:
        term = f"%{search}%"
        query = query.filter(or_(HelpDeskTicket.ticket_no.ilike(term), HelpDeskTicket.title.ilike(term), HelpDeskTicket.description.ilike(term), HelpDeskTicket.department.ilike(term)))
    if status in STATUSES:
        query = query.filter_by(status=status)
    else:
        query = query.filter(HelpDeskTicket.status != "Arşiv")
    if priority in PRIORITIES:
        query = query.filter_by(priority=priority)
    return render_template("help_desk/dashboard.html", tickets=query.order_by(HelpDeskTicket.sla_due_at.asc(), HelpDeskTicket.id.desc()).all(), statuses=STATUSES, priorities=PRIORITIES, search=search, selected_status=status, selected_priority=priority, now=datetime.now(UTC).replace(tzinfo=None), can_create=has_permission("helpdesk.create") or has_permission("helpdesk.manage"))


@bp.route("/yeni", methods=["GET", "POST"])
@login_required
def create():
    require_permission("helpdesk.create", "helpdesk.manage")
    if request.method == "POST":
        try:
            title = request.form.get("title", "").strip()
            description = request.form.get("description", "").strip()
            department = request.form.get("department", "").strip()
            priority = request.form.get("priority", "Orta").strip()
            category = request.form.get("category", "Diğer").strip()
            if not all((title, description, department)):
                raise ValueError("Başlık, açıklama ve ilgili departman zorunludur.")
            if priority not in PRIORITIES or category not in CATEGORIES:
                raise ValueError("Kategori veya öncelik geçersiz.")
            assignee_id = parse_user("assignee_user_id") if has_permission("helpdesk.manage") else None
            now = datetime.now(UTC).replace(tzinfo=None)
            row = HelpDeskTicket(company_id=current_company_id(), ticket_no=next_ticket_no(), title=title, description=description, category=category, department=department, priority=priority, status="Atandı" if assignee_id else "Yeni", requester_user_id=g.current_user.id, assignee_user_id=assignee_id, sla_due_at=now + timedelta(hours=SLA_HOURS[priority]))
            db.session.add(row)
            db.session.flush()
            store_file(request.files.get("attachment"), row)
            if assignee_id:
                notify(assignee_id, row, "Yeni iç talep size atandı.", "assigned")
            db.session.commit()
            flash(f"{row.ticket_no} iç talebi oluşturuldu.", "success")
            return redirect(url_for("help_desk.detail", ticket_id=row.id))
        except ValueError as error:
            db.session.rollback()
            flash(str(error), "danger")
    return render_template("help_desk/form.html", values=request.form, categories=CATEGORIES, priorities=PRIORITIES, users=active_users(), can_assign=has_permission("helpdesk.manage"))


@bp.get("/<int:ticket_id>")
@login_required
def detail(ticket_id):
    require_permission("helpdesk.view", "helpdesk.view_all", "helpdesk.manage")
    row = get_ticket_or_404(ticket_id)
    return render_template("help_desk/detail.html", ticket=row, users=active_users(), can_assign=has_permission("helpdesk.assign") or has_permission("helpdesk.manage"), can_work=(row.assignee_user_id == g.current_user.id and has_permission("helpdesk.work")) or has_permission("helpdesk.manage"), can_comment=has_permission("helpdesk.comment") or has_permission("helpdesk.manage"), can_accept=row.requester_user_id == g.current_user.id and row.status == "Çözüm Bekliyor", can_archive=(has_permission("helpdesk.archive") or has_permission("helpdesk.manage")) and row.status == "Kapatıldı", can_download=has_permission("helpdesk.file_download") or has_permission("helpdesk.manage"), now=datetime.now(UTC).replace(tzinfo=None))


@bp.post("/<int:ticket_id>/ata")
@login_required
def assign(ticket_id):
    require_permission("helpdesk.assign", "helpdesk.manage")
    row = get_ticket_or_404(ticket_id)
    if row.status in {"Kapatıldı", "Arşiv"}:
        abort(409)
    try:
        row.assignee_user_id = parse_user("assignee_user_id", required=True)
    except ValueError as error:
        flash(str(error), "danger")
        return redirect(url_for("help_desk.detail", ticket_id=row.id))
    row.status = "Atandı"
    notify(row.assignee_user_id, row, "İç talep size atandı.", f"assigned-{datetime.now(UTC).timestamp()}")
    db.session.commit()
    flash("Talep sorumlusu güncellendi.", "success")
    return redirect(url_for("help_desk.detail", ticket_id=row.id))


@bp.post("/<int:ticket_id>/isleme-al")
@login_required
def start(ticket_id):
    require_permission("helpdesk.work", "helpdesk.manage")
    row = get_ticket_or_404(ticket_id)
    if row.assignee_user_id != g.current_user.id and not has_permission("helpdesk.manage"):
        abort(403)
    if row.status not in {"Atandı", "Yeniden Açıldı"}:
        abort(409)
    row.status = "İşlemde"
    db.session.commit()
    flash("Talep işleme alındı.", "success")
    return redirect(url_for("help_desk.detail", ticket_id=row.id))


@bp.post("/<int:ticket_id>/cozumle")
@login_required
def resolve(ticket_id):
    require_permission("helpdesk.work", "helpdesk.manage")
    row = get_ticket_or_404(ticket_id)
    if row.assignee_user_id != g.current_user.id and not has_permission("helpdesk.manage"):
        abort(403)
    resolution = request.form.get("resolution", "").strip()
    if row.status != "İşlemde" or not resolution:
        flash("Talep işlemde olmalı ve çözüm açıklaması girilmelidir.", "danger")
        return redirect(url_for("help_desk.detail", ticket_id=row.id))
    row.resolution = resolution
    row.status = "Çözüm Bekliyor"
    row.resolved_at = datetime.now(UTC).replace(tzinfo=None)
    store_file(request.files.get("attachment"), row)
    notify(row.requester_user_id, row, "Çözüm onayınızı bekliyor.", "resolution")
    db.session.commit()
    flash("Çözüm talep sahibinin onayına gönderildi.", "success")
    return redirect(url_for("help_desk.detail", ticket_id=row.id))


@bp.post("/<int:ticket_id>/sonuclandir")
@login_required
def finish(ticket_id):
    require_permission("helpdesk.view", "helpdesk.manage")
    row = get_ticket_or_404(ticket_id)
    if row.requester_user_id != g.current_user.id or row.status != "Çözüm Bekliyor":
        abort(403)
    decision = request.form.get("decision")
    note = request.form.get("note", "").strip()
    if decision == "accept":
        row.status = "Kapatıldı"
        row.closed_at = datetime.now(UTC).replace(tzinfo=None)
    elif decision == "reopen":
        if not note:
            flash("Yeniden açma gerekçesi zorunludur.", "danger")
            return redirect(url_for("help_desk.detail", ticket_id=row.id))
        row.status = "Yeniden Açıldı"
        row.reopened_at = datetime.now(UTC).replace(tzinfo=None)
        comment = HelpDeskComment(company_id=row.company_id, ticket=row, user_id=g.current_user.id, body=f"Yeniden açma gerekçesi: {note}")
        db.session.add(comment)
        if row.assignee_user_id:
            notify(row.assignee_user_id, row, "Talep sahibi kaydı yeniden açtı.", f"reopened-{row.reopened_at.timestamp()}")
    else:
        abort(400)
    db.session.commit()
    flash("Talep kararı kaydedildi.", "success")
    return redirect(url_for("help_desk.detail", ticket_id=row.id))


@bp.post("/<int:ticket_id>/yorum")
@login_required
def comment(ticket_id):
    require_permission("helpdesk.comment", "helpdesk.manage")
    row = get_ticket_or_404(ticket_id)
    if row.status == "Arşiv":
        abort(409)
    body = request.form.get("body", "").strip()
    if not body:
        flash("Yorum boş bırakılamaz.", "danger")
        return redirect(url_for("help_desk.detail", ticket_id=row.id))
    comment_row = HelpDeskComment(company_id=row.company_id, ticket=row, user_id=g.current_user.id, body=body)
    db.session.add(comment_row)
    db.session.flush()
    store_file(request.files.get("attachment"), row, comment_row)
    recipients = {row.requester_user_id, row.assignee_user_id} - {None, g.current_user.id}
    for user_id in recipients:
        notify(user_id, row, "İç talebe yeni yorum eklendi.", f"comment-{comment_row.id}")
    db.session.commit()
    flash("Yorum eklendi.", "success")
    return redirect(url_for("help_desk.detail", ticket_id=row.id))


@bp.post("/<int:ticket_id>/arsivle")
@login_required
def archive(ticket_id):
    require_permission("helpdesk.archive", "helpdesk.manage")
    row = get_ticket_or_404(ticket_id)
    if row.status != "Kapatıldı":
        abort(409)
    row.status = "Arşiv"
    row.archived_at = datetime.now(UTC).replace(tzinfo=None)
    db.session.commit()
    flash("Talep arşivlendi.", "success")
    return redirect(url_for("help_desk.dashboard", status="Arşiv"))


@bp.get("/dosya/<int:file_id>")
@login_required
def download_file(file_id):
    require_permission("helpdesk.file_download", "helpdesk.manage")
    file_row = scoped_query(HelpDeskFile.query, HelpDeskFile).filter_by(id=file_id).first_or_404()
    if not can_access(file_row.ticket):
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
    query = ticket_query().filter(HelpDeskTicket.status.notin_(("Kapatıldı", "Arşiv")))
    query = query.filter_by(requester_user_id=g.current_user.id) if scope == "created" else query.filter_by(assignee_user_id=g.current_user.id)
    rows = []
    now = datetime.now(UTC).replace(tzinfo=None)
    for row in query.all():
        delayed = row.sla_due_at < now
        rows.append(row_builder(module_key="helpdesk", module_label="İç Talep", module_icon="headset", module_tone="operations", title=row.title, description=row.description, reference_no=row.ticket_no, department=row.department, due_date=row.sla_due_at.date(), status="SLA Geçti" if delayed else row.status, status_key="delayed" if delayed else "pending", priority=row.priority, detail_url=url_for("help_desk.detail", ticket_id=row.id), created_at=row.created_at, sort_id=row.id, date_label="SLA"))
    return rows
