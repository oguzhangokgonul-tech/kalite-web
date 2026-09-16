from datetime import UTC, date, datetime
from functools import wraps
import hashlib
from pathlib import Path
from uuid import uuid4

from flask import (
    Blueprint, abort, current_app, flash, g, redirect, render_template,
    request, send_file, url_for,
)
from sqlalchemy import or_

from .extensions import db
from .models import (
    OfficialCorrespondence,
    OfficialCorrespondenceDistribution,
    OfficialCorrespondenceFile,
    User,
)
from .notifications import add_user_notification
from .tenant import current_company_id, scoped_query


bp = Blueprint("ebys", __name__, url_prefix="/resmi-yazismalar")

DIRECTIONS = {"incoming": "Gelen Yazı", "outgoing": "Giden Yazı"}
STATUSES = ("Kayıtlı", "Dağıtıldı", "İşlemde", "Sonuçlandırıldı")
SECURITY_LEVELS = ("Normal", "Hizmete Özel", "Gizli")
ALLOWED_EXTENSIONS = {
    "pdf", "doc", "docx", "xls", "xlsx", "csv", "txt", "jpg", "jpeg", "png"
}


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
    return checker("ebys") if checker else True


def correspondence_query():
    return scoped_query(OfficialCorrespondence.query, OfficialCorrespondence)


def distribution_query():
    return scoped_query(
        OfficialCorrespondenceDistribution.query, OfficialCorrespondenceDistribution
    )


def file_query():
    return scoped_query(OfficialCorrespondenceFile.query, OfficialCorrespondenceFile)


def can_access(record):
    user = g.current_user
    if record.security_level == "Gizli" and not (
        has_permission("ebys.confidential")
        or record.created_by_user_id == user.id
        or any(row.user_id == user.id for row in record.distributions)
    ):
        return False
    if has_permission("ebys.view_all") or has_permission("ebys.manage"):
        return True
    return record.created_by_user_id == user.id or any(
        row.user_id == user.id for row in record.distributions
    )


def get_record_or_404(record_id):
    record = correspondence_query().filter_by(id=record_id).first_or_404()
    if not can_access(record):
        abort(404)
    return record


def parse_date(name, required=False):
    raw = request.form.get(name, "").strip()
    if not raw:
        if required:
            raise ValueError(f"{name}_required")
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise ValueError(f"{name}_invalid") from None


def next_registration_no():
    year = date.today().year
    prefix = f"EBYS-{year}-"
    rows = (
        correspondence_query()
        .filter(OfficialCorrespondence.registration_no.like(f"{prefix}%"))
        .with_entities(OfficialCorrespondence.registration_no)
        .all()
    )
    numbers = []
    for (value,) in rows:
        try:
            numbers.append(int(value.rsplit("-", 1)[-1]))
        except (TypeError, ValueError):
            continue
    return f"{prefix}{max(numbers, default=0) + 1:04d}"


def active_company_users():
    company_id = current_company_id()
    query = User.query.filter_by(is_active=True)
    if company_id is not None:
        query = query.filter(User.company_id == company_id)
    return query.order_by(User.full_name.asc()).all()


def selected_user_ids():
    values = set()
    for raw in request.form.getlist("assigned_user_ids"):
        try:
            values.add(int(raw))
        except (TypeError, ValueError):
            continue
    allowed = {user.id for user in active_company_users()}
    if not values <= allowed:
        raise ValueError("invalid_assignee")
    return values


def parse_form():
    direction = request.form.get("direction", "").strip()
    security_level = request.form.get("security_level", "Normal").strip()
    status = request.form.get("status", "Kayıtlı").strip()
    values = {
        "direction": direction,
        "document_date": parse_date("document_date", required=True),
        "external_reference_no": request.form.get("external_reference_no", "").strip() or None,
        "subject": request.form.get("subject", "").strip(),
        "sender": request.form.get("sender", "").strip(),
        "recipient": request.form.get("recipient", "").strip(),
        "department": request.form.get("department", "").strip() or None,
        "security_level": security_level,
        "status": status,
        "due_date": parse_date("due_date"),
        "notes": request.form.get("notes", "").strip() or None,
    }
    if direction not in DIRECTIONS:
        raise ValueError("invalid_direction")
    if security_level not in SECURITY_LEVELS:
        raise ValueError("invalid_security")
    if status not in STATUSES:
        raise ValueError("invalid_status")
    if not values["subject"] or not values["sender"] or not values["recipient"]:
        raise ValueError("required_fields")
    return values


def form_error(key):
    messages = {
        "document_date_required": "Evrak tarihi zorunludur.",
        "document_date_invalid": "Geçerli bir evrak tarihi girin.",
        "due_date_invalid": "Geçerli bir termin tarihi girin.",
        "invalid_direction": "Gelen veya giden yazı türünü seçin.",
        "invalid_security": "Geçerli bir gizlilik seviyesi seçin.",
        "invalid_status": "Geçerli bir durum seçin.",
        "invalid_assignee": "Yalnızca şirketinizdeki aktif kullanıcıları seçebilirsiniz.",
        "required_fields": "Konu, gönderen ve alıcı alanları zorunludur.",
    }
    return messages.get(key, key if " " in key else "Resmî yazışma kaydedilemedi.")


def utcnow():
    return datetime.now(UTC).replace(tzinfo=None)


def store_file(uploaded_file, record):
    if not uploaded_file or not uploaded_file.filename:
        return None
    extension = Path(uploaded_file.filename).suffix.lower().lstrip(".")
    if extension not in ALLOWED_EXTENSIONS:
        raise ValueError("Yalnızca PDF, Word, Excel, CSV, metin veya görsel yükleyin.")
    from .routes import (
        assert_company_storage_quota, safe_original_filename,
        upload_storage_path, uploaded_stream_size,
    )
    original_name = safe_original_filename(uploaded_file.filename, "resmi-yazi")
    stored_name = f"{uuid4().hex}.{extension}"
    relative_path, absolute_path = upload_storage_path(
        stored_name, "ebys", record.company_id
    )
    assert_company_storage_quota(record.company_id, uploaded_stream_size(uploaded_file))
    uploaded_file.save(absolute_path)
    size = absolute_path.stat().st_size
    digest = hashlib.sha256(absolute_path.read_bytes()).hexdigest()
    row = OfficialCorrespondenceFile(
        company_id=record.company_id,
        correspondence=record,
        original_name=original_name,
        stored_path=str(relative_path).replace("\\", "/"),
        mime_type=uploaded_file.mimetype,
        file_size=size,
        sha256_hash=digest,
        uploaded_by_user_id=g.current_user.id,
    )
    db.session.add(row)
    return row


def sync_distributions(record, user_ids):
    existing = {row.user_id: row for row in record.distributions}
    for user_id, row in list(existing.items()):
        if user_id not in user_ids and row.status == "Bekliyor":
            db.session.delete(row)
    for user_id in user_ids:
        if user_id in existing:
            continue
        row = OfficialCorrespondenceDistribution(
            company_id=record.company_id,
            correspondence=record,
            user_id=user_id,
            status="Bekliyor",
        )
        db.session.add(row)
        user = db.session.get(User, user_id)
        add_user_notification(
            user,
            f"{record.registration_no} numaralı resmî yazı size dağıtıldı: {record.subject}",
            company_id=record.company_id,
            notification_type="warning",
            source_key=f"ebys-distribution:{record.id}:{user_id}",
            target_url=url_for("ebys.detail", record_id=record.id),
            due_date=record.due_date,
        )
    if user_ids and record.status == "Kayıtlı":
        record.status = "Dağıtıldı"


@bp.before_request
def guard_module():
    if not module_enabled():
        abort(404)


@bp.get("")
@login_required
def dashboard():
    require_permission("ebys.view", "ebys.view_all", "ebys.manage")
    query = correspondence_query()
    if not (has_permission("ebys.view_all") or has_permission("ebys.manage")):
        query = query.filter(
            or_(
                OfficialCorrespondence.created_by_user_id == g.current_user.id,
                OfficialCorrespondence.distributions.any(
                    OfficialCorrespondenceDistribution.user_id == g.current_user.id
                ),
            )
        )
    if not has_permission("ebys.confidential"):
        query = query.filter(
            or_(
                OfficialCorrespondence.security_level != "Gizli",
                OfficialCorrespondence.created_by_user_id == g.current_user.id,
                OfficialCorrespondence.distributions.any(
                    OfficialCorrespondenceDistribution.user_id == g.current_user.id
                ),
            )
        )
    search = request.args.get("q", "").strip()
    direction = request.args.get("direction", "").strip()
    status = request.args.get("status", "").strip()
    archived = request.args.get("archived", "active") == "archived"
    query = query.filter(
        OfficialCorrespondence.archived_at.is_not(None)
        if archived else OfficialCorrespondence.archived_at.is_(None)
    )
    if search:
        term = f"%{search}%"
        query = query.filter(or_(
            OfficialCorrespondence.registration_no.ilike(term),
            OfficialCorrespondence.external_reference_no.ilike(term),
            OfficialCorrespondence.subject.ilike(term),
            OfficialCorrespondence.sender.ilike(term),
            OfficialCorrespondence.recipient.ilike(term),
        ))
    if direction in DIRECTIONS:
        query = query.filter_by(direction=direction)
    if status in STATUSES:
        query = query.filter_by(status=status)
    records = query.order_by(
        OfficialCorrespondence.document_date.desc(), OfficialCorrespondence.id.desc()
    ).all()
    today = date.today()
    return render_template(
        "ebys/dashboard.html", records=records, directions=DIRECTIONS,
        statuses=STATUSES, search=search, selected_direction=direction,
        selected_status=status, archived=archived, today=today,
        can_create=has_permission("ebys.create") or has_permission("ebys.manage"),
        can_manage=has_permission("ebys.manage"),
    )


@bp.route("/yeni", methods=["GET", "POST"])
@login_required
def create():
    require_permission("ebys.create", "ebys.manage")
    if request.method == "POST":
        try:
            values = parse_form()
            user_ids = selected_user_ids()
            record = OfficialCorrespondence(
                company_id=current_company_id(),
                registration_no=next_registration_no(),
                created_by_user_id=g.current_user.id,
                **values,
            )
            db.session.add(record)
            db.session.flush()
            sync_distributions(record, user_ids)
            store_file(request.files.get("attachment"), record)
            db.session.commit()
            flash(f"{record.registration_no} resmî yazışma kaydı oluşturuldu.", "success")
            return redirect(url_for("ebys.detail", record_id=record.id))
        except ValueError as error:
            db.session.rollback()
            flash(form_error(str(error)), "danger")
    return render_template(
        "ebys/form.html", record=None, values=request.form, directions=DIRECTIONS,
        statuses=STATUSES, security_levels=SECURITY_LEVELS,
        users=active_company_users(), selected_users=set(request.form.getlist("assigned_user_ids")),
        today=date.today().isoformat(),
    )


@bp.route("/<int:record_id>/duzenle", methods=["GET", "POST"])
@login_required
def edit(record_id):
    require_permission("ebys.manage")
    record = get_record_or_404(record_id)
    if record.archived_at:
        abort(409)
    if request.method == "POST":
        try:
            values = parse_form()
            user_ids = selected_user_ids()
            for key, value in values.items():
                setattr(record, key, value)
            sync_distributions(record, user_ids)
            store_file(request.files.get("attachment"), record)
            db.session.commit()
            flash("Resmî yazışma güncellendi.", "success")
            return redirect(url_for("ebys.detail", record_id=record.id))
        except ValueError as error:
            db.session.rollback()
            flash(form_error(str(error)), "danger")
    selected = {row.user_id for row in record.distributions}
    return render_template(
        "ebys/form.html", record=record, values=request.form, directions=DIRECTIONS,
        statuses=STATUSES, security_levels=SECURITY_LEVELS,
        users=active_company_users(), selected_users=selected,
        today=date.today().isoformat(),
    )


@bp.get("/<int:record_id>")
@login_required
def detail(record_id):
    require_permission("ebys.view", "ebys.view_all", "ebys.manage")
    record = get_record_or_404(record_id)
    own_distribution = next(
        (row for row in record.distributions if row.user_id == g.current_user.id), None
    )
    return render_template(
        "ebys/detail.html", record=record, directions=DIRECTIONS,
        own_distribution=own_distribution,
        can_manage=has_permission("ebys.manage"),
        can_archive=has_permission("ebys.archive") or has_permission("ebys.manage"),
        can_download=has_permission("ebys.file_download") or has_permission("ebys.manage"),
    )


@bp.post("/<int:record_id>/teslim-al")
@login_required
def accept_distribution(record_id):
    record = get_record_or_404(record_id)
    row = distribution_query().filter_by(
        correspondence_id=record.id, user_id=g.current_user.id
    ).first_or_404()
    if row.status == "Bekliyor":
        row.status = "Okundu"
        row.read_at = utcnow()
        if record.status == "Dağıtıldı":
            record.status = "İşlemde"
        db.session.commit()
        flash("Yazı teslim alındı ve okundu olarak kaydedildi.", "success")
    return redirect(url_for("ebys.detail", record_id=record.id))


@bp.post("/<int:record_id>/tamamla")
@login_required
def complete_distribution(record_id):
    record = get_record_or_404(record_id)
    row = distribution_query().filter_by(
        correspondence_id=record.id, user_id=g.current_user.id
    ).first_or_404()
    row.status = "Tamamlandı"
    row.read_at = row.read_at or utcnow()
    row.completed_at = utcnow()
    if all(item.status == "Tamamlandı" for item in record.distributions):
        record.status = "Sonuçlandırıldı"
    db.session.commit()
    flash("Dağıtım görevi tamamlandı.", "success")
    return redirect(url_for("ebys.detail", record_id=record.id))


@bp.post("/<int:record_id>/arsivle")
@login_required
def archive(record_id):
    require_permission("ebys.archive", "ebys.manage")
    record = get_record_or_404(record_id)
    if record.status != "Sonuçlandırıldı":
        flash("Yalnızca sonuçlandırılmış yazılar arşivlenebilir.", "danger")
        return redirect(url_for("ebys.detail", record_id=record.id))
    record.archived_at = utcnow()
    record.archived_by_user_id = g.current_user.id
    db.session.commit()
    flash("Resmî yazı denetim izi korunarak arşivlendi.", "success")
    return redirect(url_for("ebys.dashboard", archived="archived"))


@bp.get("/dosya/<int:file_id>")
@login_required
def download_file(file_id):
    require_permission("ebys.file_download", "ebys.manage")
    row = file_query().filter_by(id=file_id).first_or_404()
    if not can_access(row.correspondence):
        abort(404)
    root = Path(current_app.config["UPLOAD_FOLDER"]).resolve()
    path = (root / row.stored_path).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        abort(404)
    if not path.is_file():
        abort(404)
    return send_file(path, as_attachment=True, download_name=row.original_name)


@bp.get("/rapor/excel")
@login_required
def export_excel():
    require_permission("ebys.export", "ebys.manage")
    records = [
        row for row in correspondence_query().order_by(
            OfficialCorrespondence.document_date.desc(),
            OfficialCorrespondence.id.desc(),
        ).all()
        if can_access(row)
    ]
    from .routes import build_simple_xlsx
    workbook = build_simple_xlsx(
        (
            "Kayıt No", "Tür", "Evrak Tarihi", "Harici Evrak No", "Konu",
            "Gönderen", "Alıcı", "Departman", "Gizlilik", "Termin",
            "Durum", "Arşiv",
        ),
        [
            (
                row.registration_no,
                DIRECTIONS.get(row.direction, row.direction),
                row.document_date.strftime("%d.%m.%Y"),
                row.external_reference_no or "",
                row.subject,
                row.sender,
                row.recipient,
                row.department or "",
                row.security_level,
                row.due_date.strftime("%d.%m.%Y") if row.due_date else "",
                row.status,
                "Evet" if row.archived_at else "Hayır",
            )
            for row in records
        ],
        sheet_name="Resmi Yazisma Sicili",
        column_widths=(20, 16, 15, 20, 38, 28, 28, 22, 16, 15, 18, 12),
    )
    return send_file(
        workbook,
        as_attachment=True,
        download_name=f"resmi-yazisma-sicili-{date.today():%Y%m%d}.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def assigned_task_rows(scope, row_builder):
    if not module_enabled():
        return []
    user_id = g.current_user.id
    if scope == "created":
        records = correspondence_query().filter_by(
            created_by_user_id=user_id, archived_at=None
        ).all()
        return [
            row_builder(
                module_key="ebys", module_label="Resmî Yazışma",
                module_icon="envelope-paper", module_tone="document",
                title=row.subject, description=f"{DIRECTIONS.get(row.direction, row.direction)} · {row.recipient}",
                reference_no=row.registration_no, department=row.department or "EBYS",
                due_date=row.due_date or row.document_date, status=row.status,
                status_key="completed" if row.status == "Sonuçlandırıldı" else "pending",
                priority="Orta", detail_url=url_for("ebys.detail", record_id=row.id),
                created_at=row.created_at, sort_id=row.id, date_label="Termin",
            )
            for row in records
        ]
    distributions = distribution_query().filter(
        OfficialCorrespondenceDistribution.user_id == user_id,
        OfficialCorrespondenceDistribution.status != "Tamamlandı",
    ).all()
    today = date.today()
    rows = []
    for item in distributions:
        record = item.correspondence
        if record.archived_at:
            continue
        delayed = bool(record.due_date and record.due_date < today)
        rows.append(row_builder(
            module_key="ebys", module_label="Resmî Yazışma",
            module_icon="envelope-paper", module_tone="document",
            title=record.subject, description=f"{DIRECTIONS.get(record.direction, record.direction)} · {record.sender}",
            reference_no=record.registration_no, department=record.department or "EBYS",
            due_date=record.due_date or record.document_date,
            status="Termin Geçti" if delayed else item.status,
            status_key="delayed" if delayed else "pending",
            priority="Yüksek" if delayed else "Orta",
            detail_url=url_for("ebys.detail", record_id=record.id),
            created_at=item.assigned_at, sort_id=item.id, date_label="Termin",
        ))
    return rows
