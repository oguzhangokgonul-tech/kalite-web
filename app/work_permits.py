from datetime import UTC, datetime
from functools import wraps
import hashlib
from pathlib import Path
from uuid import uuid4

from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, send_file, url_for
from sqlalchemy import or_

from .extensions import db
from .models import User, WorkPermit, WorkPermitControl, WorkPermitFile
from .notifications import add_user_notification
from .tenant import current_company_id, scoped_query


bp = Blueprint("work_permits", __name__, url_prefix="/is-izinleri")

PERMIT_TYPES = (
    "Sıcak Çalışma",
    "Yüksekte Çalışma",
    "Kapalı Alan",
    "Elektrik / LOTO",
    "Kazı",
    "Kaldırma Operasyonu",
)
STATUSES = ("Taslak", "Revizyon Bekliyor", "Onay Bekliyor", "Onaylandı", "Aktif", "Kapatıldı", "Reddedildi", "İptal", "Arşiv")
TERMINAL_STATUSES = {"Kapatıldı", "Reddedildi", "İptal", "Arşiv"}
ALLOWED_EXTENSIONS = {"pdf", "doc", "docx", "xls", "xlsx", "jpg", "jpeg", "png"}

COMMON_CONTROLS = (
    "Çalışma alanı sınırlandırıldı ve uyarı levhaları yerleştirildi.",
    "Çalışanların yetkinliği ve görevlendirmesi doğrulandı.",
    "Gerekli kişisel koruyucu donanımlar hazır ve kullanıma uygun.",
    "Acil durum iletişimi ve müdahale yöntemi ekiple paylaşıldı.",
)
TYPE_CONTROLS = {
    "Sıcak Çalışma": ("Yanıcı malzemeler uzaklaştırıldı.", "Uygun yangın söndürücü ve yangın gözcüsü hazır."),
    "Yüksekte Çalışma": ("İskele/merdiven ve ankraj noktaları kontrol edildi.", "Düşüş durdurucu sistem ve kurtarma planı hazır."),
    "Kapalı Alan": ("Gaz ölçümü yapıldı ve sonuçlar uygun.", "Havalandırma, gözcü ve kurtarma ekipmanı hazır."),
    "Elektrik / LOTO": ("Enerji kaynakları izole edildi ve kilitleme/etiketleme uygulandı.", "Gerilimsizlik kontrolü yetkili kişi tarafından yapıldı."),
    "Kazı": ("Yer altı hatları kontrol edildi ve işaretlendi.", "Şev, iksa ve güvenli giriş/çıkış önlemleri hazır."),
    "Kaldırma Operasyonu": ("Kaldırma ekipmanı ve aksesuarların kontrolleri geçerli.", "Yük güzergahı boşaltıldı ve işaretçi görevlendirildi."),
}


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


def permit_query():
    return scoped_query(WorkPermit.query, WorkPermit)


def active_users():
    return User.query.filter_by(company_id=current_company_id(), is_active=True).order_by(User.full_name).all()


def can_access(row):
    return bool(
        has_permission("work_permits.view_all")
        or has_permission("work_permits.manage")
        or g.current_user.id in {row.requester_user_id, row.responsible_user_id, row.approver_user_id}
    )


def get_permit_or_404(permit_id):
    row = permit_query().filter_by(id=permit_id).first_or_404()
    if not can_access(row):
        abort(404)
    return row


def now_utc():
    return datetime.now(UTC).replace(tzinfo=None)


def parse_datetime(name):
    raw = request.form.get(name, "").strip()
    try:
        return datetime.fromisoformat(raw)
    except (TypeError, ValueError):
        raise ValueError("Başlangıç ve bitiş tarihi geçerli biçimde girilmelidir.") from None


def parse_user(name):
    try:
        user_id = int(request.form.get(name, ""))
    except (TypeError, ValueError):
        raise ValueError("Sorumlu ve onaylayıcı aktif personelden seçilmelidir.") from None
    if not User.query.filter_by(id=user_id, company_id=current_company_id(), is_active=True).first():
        raise ValueError("Seçilen personel bu şirkette aktif değil.")
    return user_id


def next_permit_no():
    prefix = f"IZIN-{now_utc().year}-"
    numbers = []
    for (value,) in permit_query().with_entities(WorkPermit.permit_no).filter(WorkPermit.permit_no.like(f"{prefix}%")).all():
        try:
            numbers.append(int(value.rsplit("-", 1)[-1]))
        except (TypeError, ValueError):
            pass
    return f"{prefix}{max(numbers, default=0) + 1:04d}"


def notify(user_id, row, message, suffix):
    user = User.query.filter_by(id=user_id, company_id=row.company_id, is_active=True).first()
    if user:
        add_user_notification(
            user,
            f"{row.permit_no} - {message}",
            company_id=row.company_id,
            source_key=f"work-permit:{suffix}:{row.id}:{user_id}",
            target_url=url_for("work_permits.detail", permit_id=row.id),
            due_date=row.requested_end_at.date(),
        )


def store_file(upload, row):
    if not upload or not upload.filename:
        return None
    extension = Path(upload.filename).suffix.lower().lstrip(".")
    if extension not in ALLOWED_EXTENSIONS:
        raise ValueError("Yalnızca PDF, Word, Excel veya görsel yükleyin.")
    from .routes import assert_company_storage_quota, safe_original_filename, upload_storage_path, uploaded_stream_size
    original = safe_original_filename(upload.filename, "is-izni-kaniti")
    relative, absolute = upload_storage_path(f"{uuid4().hex}.{extension}", "work-permits", row.company_id)
    assert_company_storage_quota(row.company_id, uploaded_stream_size(upload))
    upload.save(absolute)
    db.session.add(WorkPermitFile(
        company_id=row.company_id,
        permit=row,
        original_name=original,
        stored_path=str(relative).replace("\\", "/"),
        mime_type=upload.mimetype,
        file_size=absolute.stat().st_size,
        sha256_hash=hashlib.sha256(absolute.read_bytes()).hexdigest(),
        uploaded_by_user_id=g.current_user.id,
    ))
    return absolute


def remove_uncommitted_file(path):
    if path:
        path.unlink(missing_ok=True)


def populate_from_form(row):
    permit_type = request.form.get("permit_type", "").strip()
    title = request.form.get("title", "").strip()
    location = request.form.get("location", "").strip()
    description = request.form.get("description", "").strip()
    hazards = request.form.get("hazards", "").strip()
    precautions = request.form.get("precautions", "").strip()
    ppe = request.form.get("ppe_requirements", "").strip()
    if permit_type not in PERMIT_TYPES:
        raise ValueError("Geçerli bir iş izin türü seçin.")
    if not all((title, location, description, hazards, precautions, ppe)):
        raise ValueError("Başlık, konum, iş açıklaması, tehlikeler, önlemler ve KKD alanları zorunludur.")
    start_at = parse_datetime("requested_start_at")
    end_at = parse_datetime("requested_end_at")
    if end_at <= start_at:
        raise ValueError("İzin bitişi başlangıçtan sonra olmalıdır.")
    if end_at <= now_utc():
        raise ValueError("Bitiş tarihi geçmiş bir iş izni oluşturulamaz.")
    responsible_id = parse_user("responsible_user_id")
    approver_id = parse_user("approver_user_id")
    if approver_id == row.requester_user_id:
        raise ValueError("Talep sahibi kendi iş iznini onaylayamaz.")
    type_changed = bool(row.id and row.permit_type != permit_type)
    row.permit_type = permit_type
    row.title = title
    row.location = location
    row.department = request.form.get("department", "").strip() or None
    row.contractor = request.form.get("contractor", "").strip() or None
    row.description = description
    row.hazards = hazards
    row.precautions = precautions
    row.ppe_requirements = ppe
    row.emergency_plan = request.form.get("emergency_plan", "").strip() or None
    row.responsible_user_id = responsible_id
    row.approver_user_id = approver_id
    row.requested_start_at = start_at
    row.requested_end_at = end_at
    if type_changed:
        row.controls.clear()
    if not row.controls:
        for index, title_text in enumerate(COMMON_CONTROLS + TYPE_CONTROLS[permit_type], start=1):
            row.controls.append(WorkPermitControl(company_id=row.company_id, title=title_text, sort_order=index))


def effective_status(row, now=None):
    current = now or now_utc()
    if row.status == "Aktif" and row.requested_end_at < current:
        return "Süresi Geçti"
    return row.status


@bp.before_request
def guard():
    checker = getattr(g, "company_module_enabled", None)
    if checker and not checker("work_permits"):
        abort(404)


@bp.get("")
@login_required
def dashboard():
    require_permission("work_permits.view", "work_permits.view_all", "work_permits.manage")
    query = permit_query()
    if not (has_permission("work_permits.view_all") or has_permission("work_permits.manage")):
        query = query.filter(or_(
            WorkPermit.requester_user_id == g.current_user.id,
            WorkPermit.responsible_user_id == g.current_user.id,
            WorkPermit.approver_user_id == g.current_user.id,
        ))
    search = request.args.get("q", "").strip()
    status = request.args.get("status", "").strip()
    permit_type = request.args.get("type", "").strip()
    if search:
        term = f"%{search}%"
        query = query.filter(or_(WorkPermit.permit_no.ilike(term), WorkPermit.title.ilike(term), WorkPermit.location.ilike(term), WorkPermit.contractor.ilike(term)))
    if status == "Süresi Geçti":
        query = query.filter(WorkPermit.status == "Aktif", WorkPermit.requested_end_at < now_utc())
    elif status in STATUSES:
        query = query.filter_by(status=status)
    else:
        query = query.filter(WorkPermit.status != "Arşiv")
    if permit_type in PERMIT_TYPES:
        query = query.filter_by(permit_type=permit_type)
    rows = query.order_by(WorkPermit.requested_end_at.asc(), WorkPermit.id.desc()).all()
    return render_template("work_permits/dashboard.html", permits=rows, effective_status=effective_status, statuses=STATUSES, permit_types=PERMIT_TYPES, selected_status=status, selected_type=permit_type, search=search, can_create=has_permission("work_permits.create") or has_permission("work_permits.manage"))


@bp.route("/yeni", methods=["GET", "POST"])
@login_required
def create():
    require_permission("work_permits.create", "work_permits.manage")
    if request.method == "POST":
        stored_path = None
        row = WorkPermit(company_id=current_company_id(), permit_no=next_permit_no(), requester_user_id=g.current_user.id)
        try:
            populate_from_form(row)
            db.session.add(row)
            db.session.flush()
            stored_path = store_file(request.files.get("attachment"), row)
            db.session.commit()
            notify(row.responsible_user_id, row, "Saha kontrollerini doğrulamanız bekleniyor.", "control")
            db.session.commit()
            flash(f"{row.permit_no} iş izni taslağı oluşturuldu.", "success")
            return redirect(url_for("work_permits.detail", permit_id=row.id))
        except ValueError as error:
            db.session.rollback()
            remove_uncommitted_file(stored_path)
            flash(str(error), "danger")
    return render_template("work_permits/form.html", permit=None, values=request.form, permit_types=PERMIT_TYPES, users=active_users())


@bp.route("/<int:permit_id>/duzenle", methods=["GET", "POST"])
@login_required
def edit(permit_id):
    require_permission("work_permits.update", "work_permits.manage")
    row = get_permit_or_404(permit_id)
    if row.status not in {"Taslak", "Revizyon Bekliyor"} or (row.requester_user_id != g.current_user.id and not has_permission("work_permits.manage")):
        abort(403)
    if request.method == "POST":
        stored_path = None
        try:
            populate_from_form(row)
            row.status = "Taslak"
            row.review_note = None
            row.approved_at = None
            row.approved_by_user_id = None
            for control in row.controls:
                control.is_confirmed = False
                control.confirmed_by_user_id = None
                control.confirmed_at = None
            stored_path = store_file(request.files.get("attachment"), row)
            db.session.commit()
            notify(row.responsible_user_id, row, "Güncellenen saha kontrollerini doğrulamanız bekleniyor.", f"control-{now_utc().timestamp()}")
            db.session.commit()
            flash("İş izni taslağı güncellendi; önceki saha doğrulamaları sıfırlandı.", "success")
            return redirect(url_for("work_permits.detail", permit_id=row.id))
        except ValueError as error:
            db.session.rollback()
            remove_uncommitted_file(stored_path)
            flash(str(error), "danger")
    return render_template("work_permits/form.html", permit=row, values=request.form, permit_types=PERMIT_TYPES, users=active_users())


@bp.get("/<int:permit_id>")
@login_required
def detail(permit_id):
    require_permission("work_permits.view", "work_permits.view_all", "work_permits.manage")
    row = get_permit_or_404(permit_id)
    current = now_utc()
    all_confirmed = all(not item.is_required or item.is_confirmed for item in row.controls)
    return render_template(
        "work_permits/detail.html",
        permit=row,
        display_status=effective_status(row, current),
        all_confirmed=all_confirmed,
        can_update=(has_permission("work_permits.update") or has_permission("work_permits.manage")) and row.status in {"Taslak", "Revizyon Bekliyor"} and (row.requester_user_id == g.current_user.id or has_permission("work_permits.manage")),
        can_confirm=(has_permission("work_permits.confirm") or has_permission("work_permits.manage")) and row.responsible_user_id == g.current_user.id and row.status in {"Taslak", "Revizyon Bekliyor"},
        can_submit=(has_permission("work_permits.update") or has_permission("work_permits.manage")) and row.requester_user_id == g.current_user.id and row.status in {"Taslak", "Revizyon Bekliyor"} and all_confirmed,
        can_review=(has_permission("work_permits.approve") or has_permission("work_permits.manage")) and row.approver_user_id == g.current_user.id and row.status == "Onay Bekliyor",
        can_activate=(has_permission("work_permits.activate") or has_permission("work_permits.manage")) and row.responsible_user_id == g.current_user.id and row.status == "Onaylandı" and row.requested_start_at <= current <= row.requested_end_at,
        can_close=(has_permission("work_permits.close") or has_permission("work_permits.manage")) and row.responsible_user_id == g.current_user.id and row.status == "Aktif",
        can_cancel=(has_permission("work_permits.manage") or row.requester_user_id == g.current_user.id) and row.status not in TERMINAL_STATUSES,
        can_archive=(has_permission("work_permits.archive") or has_permission("work_permits.manage")) and row.status in {"Kapatıldı", "Reddedildi", "İptal"},
        can_download=has_permission("work_permits.file_download") or has_permission("work_permits.manage"),
        now=current,
    )


@bp.post("/<int:permit_id>/kontroller")
@login_required
def confirm_controls(permit_id):
    require_permission("work_permits.confirm", "work_permits.manage")
    row = get_permit_or_404(permit_id)
    if row.responsible_user_id != g.current_user.id or row.status not in {"Taslak", "Revizyon Bekliyor"}:
        abort(403)
    selected = {int(value) for value in request.form.getlist("control_id") if value.isdigit()}
    current = now_utc()
    for control in row.controls:
        confirmed = control.id in selected
        control.is_confirmed = confirmed
        control.note = request.form.get(f"note_{control.id}", "").strip() or None
        control.confirmed_by_user_id = g.current_user.id if confirmed else None
        control.confirmed_at = current if confirmed else None
    db.session.commit()
    if all(not item.is_required or item.is_confirmed for item in row.controls):
        notify(row.requester_user_id, row, "Saha kontrolleri tamamlandı; izni onaya gönderebilirsiniz.", f"ready-{current.timestamp()}")
        db.session.commit()
    flash("Saha kontrol doğrulamaları kaydedildi.", "success")
    return redirect(url_for("work_permits.detail", permit_id=row.id))


@bp.post("/<int:permit_id>/onaya-gonder")
@login_required
def submit(permit_id):
    require_permission("work_permits.update", "work_permits.manage")
    row = get_permit_or_404(permit_id)
    if row.requester_user_id != g.current_user.id or row.status not in {"Taslak", "Revizyon Bekliyor"}:
        abort(403)
    if not all(not item.is_required or item.is_confirmed for item in row.controls):
        abort(409)
    row.status = "Onay Bekliyor"
    row.submitted_at = now_utc()
    notify(row.approver_user_id, row, "İş izni onayınızı bekliyor.", f"review-{row.submitted_at.timestamp()}")
    db.session.commit()
    flash("İş izni onaya gönderildi.", "success")
    return redirect(url_for("work_permits.detail", permit_id=row.id))


@bp.post("/<int:permit_id>/degerlendir")
@login_required
def review(permit_id):
    require_permission("work_permits.approve", "work_permits.manage")
    row = get_permit_or_404(permit_id)
    if row.approver_user_id != g.current_user.id or row.status != "Onay Bekliyor" or row.requester_user_id == g.current_user.id:
        abort(403)
    decision = request.form.get("decision", "")
    note = request.form.get("note", "").strip()
    if decision == "approve":
        if not all(not item.is_required or item.is_confirmed for item in row.controls):
            abort(409)
        row.status = "Onaylandı"
        row.approved_at = now_utc()
        row.approved_by_user_id = g.current_user.id
        row.review_note = note or None
        notify(row.responsible_user_id, row, "İş izni onaylandı; geçerlilik zamanında etkinleştirebilirsiniz.", f"approved-{row.approved_at.timestamp()}")
    elif decision in {"revision", "reject"}:
        if not note:
            flash("Revizyon veya ret gerekçesi zorunludur.", "danger")
            return redirect(url_for("work_permits.detail", permit_id=row.id))
        row.status = "Revizyon Bekliyor" if decision == "revision" else "Reddedildi"
        row.review_note = note
        notify(row.requester_user_id, row, "İş izni revizyona gönderildi." if decision == "revision" else "İş izni reddedildi.", f"{decision}-{now_utc().timestamp()}")
    else:
        abort(400)
    db.session.commit()
    flash("Değerlendirme kararı kaydedildi.", "success")
    return redirect(url_for("work_permits.detail", permit_id=row.id))


@bp.post("/<int:permit_id>/etkinlestir")
@login_required
def activate(permit_id):
    require_permission("work_permits.activate", "work_permits.manage")
    row = get_permit_or_404(permit_id)
    current = now_utc()
    if row.responsible_user_id != g.current_user.id or row.status != "Onaylandı":
        abort(403)
    if not row.requested_start_at <= current <= row.requested_end_at:
        abort(409)
    row.status = "Aktif"
    row.activated_at = current
    db.session.commit()
    flash("İş izni etkinleştirildi.", "success")
    return redirect(url_for("work_permits.detail", permit_id=row.id))


@bp.post("/<int:permit_id>/kapat")
@login_required
def close(permit_id):
    require_permission("work_permits.close", "work_permits.manage")
    row = get_permit_or_404(permit_id)
    note = request.form.get("closure_note", "").strip()
    if row.responsible_user_id != g.current_user.id or row.status != "Aktif":
        abort(403)
    if not note:
        flash("İşin nasıl tamamlandığını açıklayan kapanış notu zorunludur.", "danger")
        return redirect(url_for("work_permits.detail", permit_id=row.id))
    stored_path = None
    try:
        row.status = "Kapatıldı"
        row.closure_note = note
        row.closed_at = now_utc()
        stored_path = store_file(request.files.get("attachment"), row)
        notify(row.requester_user_id, row, "İş izni kapatıldı.", f"closed-{row.closed_at.timestamp()}")
        db.session.commit()
    except ValueError as error:
        db.session.rollback()
        remove_uncommitted_file(stored_path)
        flash(str(error), "danger")
        return redirect(url_for("work_permits.detail", permit_id=row.id))
    flash("İş izni kapatıldı.", "success")
    return redirect(url_for("work_permits.detail", permit_id=row.id))


@bp.post("/<int:permit_id>/iptal")
@login_required
def cancel(permit_id):
    row = get_permit_or_404(permit_id)
    if row.requester_user_id != g.current_user.id and not has_permission("work_permits.manage"):
        abort(403)
    if row.status in TERMINAL_STATUSES:
        abort(409)
    note = request.form.get("note", "").strip()
    if not note:
        flash("İptal gerekçesi zorunludur.", "danger")
        return redirect(url_for("work_permits.detail", permit_id=row.id))
    row.status = "İptal"
    row.review_note = note
    row.cancelled_at = now_utc()
    notify(row.responsible_user_id, row, "İş izni iptal edildi.", f"cancelled-{row.cancelled_at.timestamp()}")
    db.session.commit()
    flash("İş izni iptal edildi.", "success")
    return redirect(url_for("work_permits.detail", permit_id=row.id))


@bp.post("/<int:permit_id>/arsivle")
@login_required
def archive(permit_id):
    require_permission("work_permits.archive", "work_permits.manage")
    row = get_permit_or_404(permit_id)
    if row.status not in {"Kapatıldı", "Reddedildi", "İptal"}:
        abort(409)
    row.status = "Arşiv"
    row.archived_at = now_utc()
    db.session.commit()
    flash("İş izni arşivlendi.", "success")
    return redirect(url_for("work_permits.dashboard", status="Arşiv"))


@bp.get("/dosya/<int:file_id>")
@login_required
def download_file(file_id):
    require_permission("work_permits.file_download", "work_permits.manage")
    file_row = scoped_query(WorkPermitFile.query, WorkPermitFile).filter_by(id=file_id).first_or_404()
    if not can_access(file_row.permit):
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
    query = permit_query().filter(WorkPermit.status.notin_(tuple(TERMINAL_STATUSES)))
    user_id = g.current_user.id
    if scope == "created":
        query = query.filter_by(requester_user_id=user_id)
    else:
        query = query.filter(or_(WorkPermit.responsible_user_id == user_id, WorkPermit.approver_user_id == user_id))
    current = now_utc()
    rows = []
    for row in query.all():
        display = effective_status(row, current)
        if scope != "created":
            needs_user = (row.approver_user_id == user_id and row.status == "Onay Bekliyor") or (row.responsible_user_id == user_id and row.status in {"Taslak", "Revizyon Bekliyor", "Onaylandı", "Aktif"})
            if not needs_user:
                continue
        rows.append(row_builder(
            module_key="work_permit",
            module_label="İş İzni",
            module_icon="shield-check",
            module_tone="risk",
            title=row.title,
            description=f"{row.permit_type} · {row.location}",
            reference_no=row.permit_no,
            department=row.department or row.location,
            due_date=row.requested_end_at.date(),
            status=display,
            status_key="delayed" if display == "Süresi Geçti" else "pending",
            priority="Yüksek" if display == "Süresi Geçti" else "Orta",
            detail_url=url_for("work_permits.detail", permit_id=row.id),
            created_at=row.created_at,
            sort_id=row.id,
            date_label="İzin Bitişi",
        ))
    return rows
