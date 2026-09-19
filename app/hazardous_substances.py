from datetime import UTC, date, datetime, timedelta
from functools import wraps
import hashlib
from pathlib import Path
import re
from uuid import uuid4

from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, send_file, url_for
from sqlalchemy import or_

from .extensions import db
from .models import Action, HazardousSubstance, HazardousSubstanceFile, HazardousSubstanceTransaction, RiskRecord, User
from .notifications import add_user_notification
from .tenant import current_company_id, scoped_query


bp = Blueprint("hazardous_substances", __name__, url_prefix="/tehlikeli-maddeler")

PHYSICAL_STATES = ("Katı", "Sıvı", "Gaz", "Aerosol")
SIGNAL_WORDS = ("Dikkat", "Tehlike")
UNITS = ("kg", "g", "L", "mL", "adet")
STORAGE_GROUPS = ("Yanıcı", "Oksitleyici", "Asit", "Baz", "Toksik", "Su ile Reaktif", "Basınçlı Gaz", "Genel Kimyasal")
GHS_PICTOGRAMS = (
    ("GHS01", "Patlayıcı"), ("GHS02", "Alevlenir"), ("GHS03", "Oksitleyici"),
    ("GHS04", "Basınçlı Gaz"), ("GHS05", "Aşındırıcı"), ("GHS06", "Akut Toksik"),
    ("GHS07", "Zararlı / Tahriş Edici"), ("GHS08", "Ciddi Sağlık Tehlikesi"), ("GHS09", "Çevre İçin Tehlikeli"),
)
HAZARD_CLASSES = (
    "Patlayıcı", "Alevlenir", "Oksitleyici", "Basınçlı gaz", "Aşındırıcı",
    "Akut toksisite", "Tahriş edici", "Kanserojen / mutajen", "Çevre için tehlikeli",
)
STATUSES = ("Taslak", "Revizyon Bekliyor", "Onay Bekliyor", "Aktif", "Karantina", "Reddedildi", "Bertaraf", "Arşiv")
TERMINAL_STATUSES = {"Reddedildi", "Bertaraf", "Arşiv"}
MOVEMENT_TYPES = ("Giriş", "Tüketim", "İade", "Sayım Düzeltme", "Transfer", "Bertaraf")
ALLOWED_EXTENSIONS = {"pdf", "doc", "docx", "xls", "xlsx", "jpg", "jpeg", "png"}
INCOMPATIBLE_STORAGE_PAIRS = {
    frozenset(("Yanıcı", "Oksitleyici")),
    frozenset(("Asit", "Baz")),
    frozenset(("Asit", "Toksik")),
    frozenset(("Su ile Reaktif", "Genel Kimyasal")),
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


def require_company_scope():
    company_id = current_company_id()
    if company_id is None:
        abort(400, "Kayıt işlemi için önce bir şirket bağlamı seçin.")
    return company_id


def substance_query():
    return scoped_query(HazardousSubstance.query, HazardousSubstance)


def active_users():
    return User.query.filter_by(company_id=current_company_id(), is_active=True).order_by(User.full_name).all()


def can_access(row):
    return bool(
        has_permission("hazardous_substances.view_all")
        or has_permission("hazardous_substances.manage")
        or has_permission("hazardous_substances.view")
        or g.current_user.id in {row.responsible_user_id, row.reviewer_user_id, row.created_by_user_id}
    )


def get_substance_or_404(substance_id):
    row = substance_query().filter_by(id=substance_id).first_or_404()
    if not can_access(row):
        abort(404)
    return row


def now_utc():
    return datetime.now(UTC).replace(tzinfo=None)


def parse_date(name, required=False):
    raw = request.form.get(name, "").strip()
    if not raw and not required:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise ValueError("Tarih alanlarından biri geçerli değil.") from None


def parse_float(name, required=False, minimum=None):
    raw = request.form.get(name, "").strip().replace(",", ".")
    if not raw and not required:
        return None
    try:
        value = float(raw)
    except ValueError:
        raise ValueError("Miktar alanlarından biri geçerli değil.") from None
    if minimum is not None and value < minimum:
        raise ValueError(f"{name} değeri {minimum} değerinden küçük olamaz.")
    return value


def parse_user(name):
    try:
        user_id = int(request.form.get(name, ""))
    except (TypeError, ValueError):
        raise ValueError("Sorumlu ve doğrulayan aktif personelden seçilmelidir.") from None
    if not User.query.filter_by(id=user_id, company_id=current_company_id(), is_active=True).first():
        raise ValueError("Seçilen personel bu şirkette aktif değil.")
    return user_id


def parse_scoped_id(name, model):
    raw = request.form.get(name, "").strip()
    if not raw:
        return None
    try:
        record_id = int(raw)
    except ValueError:
        raise ValueError("Bağlantılı kayıt geçerli değil.") from None
    if not scoped_query(model.query, model).filter_by(id=record_id).first():
        raise ValueError("Bağlantılı kayıt bu şirkete ait değil.")
    return record_id


def next_inventory_no():
    prefix = f"KIM-{date.today().year}-"
    numbers = []
    for (value,) in substance_query().with_entities(HazardousSubstance.inventory_no).filter(HazardousSubstance.inventory_no.like(f"{prefix}%")).all():
        try:
            numbers.append(int(value.rsplit("-", 1)[-1]))
        except (TypeError, ValueError):
            pass
    return f"{prefix}{max(numbers, default=0) + 1:04d}"


def notify(user_id, row, message, suffix, due_date=None, notification_type="warning"):
    user = User.query.filter_by(id=user_id, company_id=row.company_id, is_active=True).first()
    if user:
        add_user_notification(
            user,
            f"{row.inventory_no} - {message}",
            company_id=row.company_id,
            source_key=f"hazardous:{suffix}:{row.id}:{user_id}",
            target_url=url_for("hazardous_substances.detail", substance_id=row.id),
            due_date=due_date,
            notification_type=notification_type,
        )


def current_sds(row):
    return next((item for item in row.files if item.file_type == "SDS" and item.is_current), None)


def store_file(upload, row, *, file_type="Diğer", revision_no=None, document_date=None, language=None):
    if not upload or not upload.filename:
        return None
    extension = Path(upload.filename).suffix.lower().lstrip(".")
    if extension not in ALLOWED_EXTENSIONS or (file_type == "SDS" and extension != "pdf"):
        raise ValueError("SDS/GBF yalnızca PDF; diğer ekler PDF, Word, Excel veya görsel olabilir.")
    if file_type == "SDS" and upload.mimetype not in {"application/pdf", "application/x-pdf"}:
        raise ValueError("SDS/GBF dosyası PDF içerik türünde olmalıdır.")
    if file_type == "SDS" and (not revision_no or not document_date or not language):
        raise ValueError("SDS sürüm numarası, belge tarihi ve dili zorunludur.")
    from .routes import assert_company_storage_quota, safe_original_filename, upload_storage_path, uploaded_stream_size
    original = safe_original_filename(upload.filename, "tehlikeli-madde-dosyasi")
    relative, absolute = upload_storage_path(f"{uuid4().hex}.{extension}", "hazardous-substances", row.company_id)
    assert_company_storage_quota(row.company_id, uploaded_stream_size(upload))
    upload.save(absolute)
    if file_type == "SDS":
        for old_file in row.files:
            if old_file.file_type == "SDS" and old_file.is_current:
                old_file.is_current = False
                old_file.archived_at = now_utc()
    db.session.add(HazardousSubstanceFile(
        company_id=row.company_id,
        substance=row,
        file_type=file_type,
        revision_no=revision_no,
        document_date=document_date,
        language=language,
        is_current=file_type == "SDS",
        original_name=original,
        stored_path=str(relative).replace("\\", "/"),
        mime_type=upload.mimetype,
        file_size=absolute.stat().st_size,
        sha256_hash=hashlib.sha256(absolute.read_bytes()).hexdigest(),
        uploaded_by_user_id=g.current_user.id,
    ))
    return absolute


def remove_uncommitted_files(paths):
    for path in paths:
        if path:
            path.unlink(missing_ok=True)


def selected_pictograms():
    valid = {code for code, _ in GHS_PICTOGRAMS}
    return [code for code in request.form.getlist("pictogram_codes") if code in valid]


def selected_hazard_classes():
    return [item for item in request.form.getlist("hazard_classes") if item in HAZARD_CLASSES]


def populate_from_form(row):
    required = {
        "name": "Madde adı", "usage_area": "Kullanım alanı", "storage_location": "Depolama konumu",
        "precautions": "Güvenlik önlemleri", "ppe_requirements": "KKD gereklilikleri",
        "first_aid": "İlk yardım", "spill_response": "Dökülme müdahalesi",
    }
    values = {key: request.form.get(key, "").strip() for key in required}
    missing = [label for key, label in required.items() if not values[key]]
    if missing:
        raise ValueError(f"Zorunlu alanları doldurun: {', '.join(missing)}.")
    physical_state = request.form.get("physical_state", "")
    signal_word = request.form.get("signal_word", "")
    storage_group = request.form.get("storage_group", "")
    unit = request.form.get("unit", "")
    classes = selected_hazard_classes()
    pictograms = selected_pictograms()
    if physical_state not in PHYSICAL_STATES or signal_word not in SIGNAL_WORDS or storage_group not in STORAGE_GROUPS or unit not in UNITS:
        raise ValueError("Sınıflandırma alanlarından biri geçerli değil.")
    if not classes or not pictograms:
        raise ValueError("En az bir tehlike sınıfı ve GHS piktogramı seçin.")
    cas_no = request.form.get("cas_no", "").strip()
    if cas_no and not re.fullmatch(r"\d{2,7}-\d{2}-\d", cas_no):
        raise ValueError("CAS numarası 64-17-5 benzeri geçerli biçimde olmalıdır.")
    responsible_id = parse_user("responsible_user_id")
    reviewer_id = parse_user("reviewer_user_id")
    if reviewer_id == row.created_by_user_id:
        raise ValueError("Kaydı oluşturan kişi kendi kimyasal kartını doğrulayamaz.")
    sds_revision_date = parse_date("sds_revision_date", required=True)
    sds_review_due_date = parse_date("sds_review_due_date", required=True)
    if sds_review_due_date < sds_revision_date:
        raise ValueError("SDS gözden geçirme tarihi revizyon tarihinden önce olamaz.")
    minimum_stock = parse_float("minimum_stock", minimum=0)
    maximum_stock = parse_float("maximum_stock", minimum=0)
    if minimum_stock is not None and maximum_stock is not None and minimum_stock > maximum_stock:
        raise ValueError("Minimum stok, maksimum stoktan büyük olamaz.")
    critical_before = None if not row.id else (
        row.signal_word, row.hazard_classes, row.pictogram_codes, row.storage_group,
        row.storage_location, row.responsible_user_id, row.reviewer_user_id,
        row.expiry_date, row.sds_revision_date, row.sds_review_due_date,
    )
    row.name = values["name"]
    row.product_code = request.form.get("product_code", "").strip() or None
    row.manufacturer = request.form.get("manufacturer", "").strip() or None
    row.supplier = request.form.get("supplier", "").strip() or None
    row.cas_no = cas_no or None
    row.ec_no = request.form.get("ec_no", "").strip() or None
    row.un_no = request.form.get("un_no", "").strip() or None
    row.physical_state = physical_state
    row.signal_word = signal_word
    row.hazard_classes = ", ".join(classes)
    row.pictogram_codes = ",".join(pictograms)
    row.department = request.form.get("department", "").strip() or None
    row.usage_area = values["usage_area"]
    row.storage_location = values["storage_location"]
    row.storage_group = storage_group
    row.incompatible_materials = request.form.get("incompatible_materials", "").strip() or None
    row.precautions = values["precautions"]
    row.ppe_requirements = values["ppe_requirements"]
    row.first_aid = values["first_aid"]
    row.spill_response = values["spill_response"]
    row.unit = unit
    row.minimum_stock = minimum_stock
    row.maximum_stock = maximum_stock
    row.expiry_date = parse_date("expiry_date")
    row.sds_revision_date = sds_revision_date
    row.sds_review_due_date = sds_review_due_date
    row.responsible_user_id = responsible_id
    row.reviewer_user_id = reviewer_id
    row.risk_id = parse_scoped_id("risk_id", RiskRecord)
    row.action_id = parse_scoped_id("action_id", Action)
    critical_after = (
        row.signal_word, row.hazard_classes, row.pictogram_codes, row.storage_group,
        row.storage_location, row.responsible_user_id, row.reviewer_user_id,
        row.expiry_date, row.sds_revision_date, row.sds_review_due_date,
    )
    return bool(critical_before and critical_before != critical_after)


def storage_conflicts(row, location=None):
    target = (location or row.storage_location).strip()
    if not target:
        return []
    others = substance_query().filter(
        HazardousSubstance.id != (row.id or 0),
        HazardousSubstance.status.in_(("Onay Bekliyor", "Aktif", "Karantina")),
        HazardousSubstance.storage_location.ilike(target),
    ).all()
    return [other for other in others if frozenset((row.storage_group, other.storage_group)) in INCOMPATIBLE_STORAGE_PAIRS]


def warning_state(row, today=None):
    today = today or date.today()
    if row.status == "Aktif" and row.expiry_date and row.expiry_date < today:
        return "Son Kullanım Geçti"
    if row.status == "Aktif" and row.sds_review_due_date < today:
        return "SDS Güncelleme Gecikti"
    if row.status == "Aktif" and row.minimum_stock is not None and row.quantity <= row.minimum_stock:
        return "Kritik Stok"
    return row.status


def activation_blockers(row):
    blockers = []
    today = date.today()
    sds = current_sds(row)
    if not sds:
        blockers.append("Güncel SDS/GBF dosyası bulunmuyor.")
    elif sds.document_date != row.sds_revision_date:
        blockers.append("SDS revizyon tarihi değiştiği için yeni PDF sürümü yüklenmelidir.")
    if row.sds_review_due_date < today:
        blockers.append("SDS gözden geçirme tarihi geçmiş.")
    if row.expiry_date and row.expiry_date < today:
        blockers.append("Maddenin son kullanma tarihi geçmiş.")
    if storage_conflicts(row):
        blockers.append("Aynı konumda uyumsuz depolama grubunda madde bulunuyor.")
    return blockers


def form_context(row=None):
    company_id = current_company_id()
    risks = scoped_query(RiskRecord.query, RiskRecord).order_by(RiskRecord.risk_no).all() if company_id else []
    actions = scoped_query(Action.query, Action).filter(Action.is_completed.is_(False)).order_by(Action.id.desc()).all() if company_id else []
    return dict(
        substance=row, values=request.form, users=active_users(), physical_states=PHYSICAL_STATES,
        signal_words=SIGNAL_WORDS, storage_groups=STORAGE_GROUPS, units=UNITS,
        pictograms=GHS_PICTOGRAMS, hazard_classes=HAZARD_CLASSES, risks=risks, actions=actions,
    )


@bp.before_request
def guard():
    checker = getattr(g, "company_module_enabled", None)
    if checker and not checker("hazardous_substances"):
        abort(404)


@bp.get("")
@login_required
def dashboard():
    require_permission("hazardous_substances.view", "hazardous_substances.view_all", "hazardous_substances.manage")
    query = substance_query()
    if not (has_permission("hazardous_substances.view_all") or has_permission("hazardous_substances.manage") or has_permission("hazardous_substances.view")):
        query = query.filter(or_(HazardousSubstance.responsible_user_id == g.current_user.id, HazardousSubstance.reviewer_user_id == g.current_user.id))
    search = request.args.get("q", "").strip()
    status = request.args.get("status", "").strip()
    group = request.args.get("storage_group", "").strip()
    if search:
        term = f"%{search}%"
        query = query.filter(or_(HazardousSubstance.inventory_no.ilike(term), HazardousSubstance.name.ilike(term), HazardousSubstance.cas_no.ilike(term), HazardousSubstance.storage_location.ilike(term)))
    if status in STATUSES:
        query = query.filter_by(status=status)
    else:
        query = query.filter(HazardousSubstance.status != "Arşiv")
    if group in STORAGE_GROUPS:
        query = query.filter_by(storage_group=group)
    rows = query.order_by(HazardousSubstance.name.asc()).all()
    today = date.today()
    return render_template(
        "hazardous_substances/dashboard.html", substances=rows, warning_state=warning_state,
        statuses=STATUSES, storage_groups=STORAGE_GROUPS, search=search, selected_status=status,
        selected_group=group, today=today,
        summary={"total": len(rows), "active": sum(row.status == "Aktif" for row in rows), "warning": sum(warning_state(row, today) != row.status for row in rows), "quarantine": sum(row.status == "Karantina" for row in rows)},
        can_create=has_permission("hazardous_substances.create") or has_permission("hazardous_substances.manage"),
    )


@bp.route("/yeni", methods=["GET", "POST"])
@login_required
def create():
    require_permission("hazardous_substances.create", "hazardous_substances.manage")
    company_id = require_company_scope()
    if request.method == "POST":
        stored = []
        row = HazardousSubstance(company_id=company_id, inventory_no=next_inventory_no(), created_by_user_id=g.current_user.id, quantity=0)
        try:
            populate_from_form(row)
            initial_quantity = parse_float("initial_quantity", required=True, minimum=0)
            if row.maximum_stock is not None and initial_quantity > row.maximum_stock:
                raise ValueError("İlk miktar tanımlı maksimum stok seviyesini aşamaz.")
            sds_upload = request.files.get("sds_file")
            if not sds_upload or not sds_upload.filename:
                raise ValueError("Güncel SDS/GBF PDF dosyası zorunludur.")
            db.session.add(row)
            db.session.flush()
            path = store_file(sds_upload, row, file_type="SDS", revision_no=request.form.get("sds_revision_no", "").strip(), document_date=row.sds_revision_date, language=request.form.get("sds_language", "").strip())
            stored.append(path)
            row.quantity = initial_quantity
            if initial_quantity:
                db.session.add(HazardousSubstanceTransaction(company_id=company_id, substance=row, movement_type="Giriş", quantity=initial_quantity, balance_after=initial_quantity, note="İlk envanter kaydı", performed_by_user_id=g.current_user.id))
            db.session.commit()
            notify(row.responsible_user_id, row, "Kimyasal kartını kontrol edip doğrulamaya hazırlayın.", "created", row.sds_review_due_date)
            db.session.commit()
            flash(f"{row.inventory_no} tehlikeli madde kartı oluşturuldu.", "success")
            return redirect(url_for("hazardous_substances.detail", substance_id=row.id))
        except ValueError as error:
            db.session.rollback()
            remove_uncommitted_files(stored)
            flash(str(error), "danger")
    return render_template("hazardous_substances/form.html", **form_context())


@bp.route("/<int:substance_id>/duzenle", methods=["GET", "POST"])
@login_required
def edit(substance_id):
    require_permission("hazardous_substances.update", "hazardous_substances.manage")
    row = get_substance_or_404(substance_id)
    if row.status in {"Bertaraf", "Arşiv"} or (row.responsible_user_id != g.current_user.id and not has_permission("hazardous_substances.manage")):
        abort(403)
    if request.method == "POST":
        require_company_scope()
        stored = []
        try:
            critical_changed = populate_from_form(row)
            upload = request.files.get("sds_file")
            if upload and upload.filename:
                path = store_file(upload, row, file_type="SDS", revision_no=request.form.get("sds_revision_no", "").strip(), document_date=row.sds_revision_date, language=request.form.get("sds_language", "").strip())
                stored.append(path)
                critical_changed = True
            if critical_changed:
                row.status = "Taslak"
                row.approved_at = None
                row.approved_by_user_id = None
                row.review_note = None
            db.session.commit()
            flash("Kimyasal kartı güncellendi." + (" Kritik değişiklik nedeniyle yeniden doğrulama gerekir." if critical_changed else ""), "success")
            return redirect(url_for("hazardous_substances.detail", substance_id=row.id))
        except ValueError as error:
            db.session.rollback()
            remove_uncommitted_files(stored)
            flash(str(error), "danger")
    return render_template("hazardous_substances/form.html", **form_context(row))


@bp.get("/<int:substance_id>")
@login_required
def detail(substance_id):
    require_permission("hazardous_substances.view", "hazardous_substances.view_all", "hazardous_substances.manage")
    row = get_substance_or_404(substance_id)
    conflicts = storage_conflicts(row)
    blockers = activation_blockers(row)
    return render_template(
        "hazardous_substances/detail.html", substance=row, current_sds=current_sds(row),
        display_status=warning_state(row), conflicts=conflicts, activation_blockers=blockers, movement_types=MOVEMENT_TYPES,
        can_update=(has_permission("hazardous_substances.update") or has_permission("hazardous_substances.manage")) and row.status not in {"Bertaraf", "Arşiv"} and (row.responsible_user_id == g.current_user.id or has_permission("hazardous_substances.manage")),
        can_submit=(has_permission("hazardous_substances.update") or has_permission("hazardous_substances.manage")) and row.responsible_user_id == g.current_user.id and row.status in {"Taslak", "Revizyon Bekliyor"},
        can_review=(has_permission("hazardous_substances.approve") or has_permission("hazardous_substances.manage")) and row.reviewer_user_id == g.current_user.id and row.status == "Onay Bekliyor",
        can_stock=(has_permission("hazardous_substances.stock") or has_permission("hazardous_substances.manage")) and row.status == "Aktif",
        can_quarantine=(has_permission("hazardous_substances.quarantine") or has_permission("hazardous_substances.manage")) and row.status == "Aktif",
        can_dispose=(has_permission("hazardous_substances.dispose") or has_permission("hazardous_substances.manage")) and row.status in {"Aktif", "Karantina"},
        can_archive=(has_permission("hazardous_substances.archive") or has_permission("hazardous_substances.manage")) and row.status in {"Reddedildi", "Bertaraf"},
        can_download=has_permission("hazardous_substances.file_download") or has_permission("hazardous_substances.manage"),
    )


@bp.post("/<int:substance_id>/onaya-gonder")
@login_required
def submit(substance_id):
    require_permission("hazardous_substances.update", "hazardous_substances.manage")
    require_company_scope()
    row = get_substance_or_404(substance_id)
    if row.responsible_user_id != g.current_user.id or row.status not in {"Taslak", "Revizyon Bekliyor"}:
        abort(403)
    blockers = activation_blockers(row)
    if blockers:
        flash(" ".join(blockers), "danger")
        return redirect(url_for("hazardous_substances.detail", substance_id=row.id))
    row.status = "Onay Bekliyor"
    row.submitted_at = now_utc()
    notify(row.reviewer_user_id, row, "Tehlikeli madde kartı doğrulamanızı bekliyor.", f"review-{row.submitted_at.timestamp()}", row.sds_review_due_date)
    db.session.commit()
    flash("Kimyasal kartı doğrulamaya gönderildi.", "success")
    return redirect(url_for("hazardous_substances.detail", substance_id=row.id))


@bp.post("/<int:substance_id>/degerlendir")
@login_required
def review(substance_id):
    require_permission("hazardous_substances.approve", "hazardous_substances.manage")
    require_company_scope()
    row = get_substance_or_404(substance_id)
    if row.reviewer_user_id != g.current_user.id or row.status != "Onay Bekliyor" or row.created_by_user_id == g.current_user.id:
        abort(403)
    decision = request.form.get("decision", "")
    note = request.form.get("note", "").strip()
    if decision == "approve":
        if activation_blockers(row):
            abort(409)
        row.status = "Aktif"
        row.approved_at = now_utc()
        row.approved_by_user_id = g.current_user.id
        row.review_note = note or None
        notify(row.responsible_user_id, row, "Tehlikeli madde kartı doğrulandı ve aktifleştirildi.", f"approved-{row.approved_at.timestamp()}", row.sds_review_due_date, "info")
    elif decision in {"revision", "reject"}:
        if not note:
            flash("Revizyon veya ret gerekçesi zorunludur.", "danger")
            return redirect(url_for("hazardous_substances.detail", substance_id=row.id))
        row.status = "Revizyon Bekliyor" if decision == "revision" else "Reddedildi"
        row.review_note = note
        notify(row.responsible_user_id, row, "Kimyasal kartı revizyona gönderildi." if decision == "revision" else "Kimyasal kartı reddedildi.", f"{decision}-{now_utc().timestamp()}")
    else:
        abort(400)
    db.session.commit()
    flash("Değerlendirme kararı kaydedildi.", "success")
    return redirect(url_for("hazardous_substances.detail", substance_id=row.id))


@bp.post("/<int:substance_id>/stok-hareketi")
@login_required
def stock_movement(substance_id):
    require_permission("hazardous_substances.stock", "hazardous_substances.manage")
    require_company_scope()
    row = get_substance_or_404(substance_id)
    if row.status != "Aktif":
        abort(409)
    movement_type = request.form.get("movement_type", "")
    note = request.form.get("note", "").strip()
    if movement_type not in MOVEMENT_TYPES or movement_type == "Bertaraf" or not note:
        abort(400)
    if movement_type == "Transfer":
        new_location = request.form.get("new_location", "").strip()
        if not new_location:
            flash("Transfer için yeni depolama konumu zorunludur.", "danger")
            return redirect(url_for("hazardous_substances.detail", substance_id=row.id))
        conflicts = storage_conflicts(row, new_location)
        if conflicts:
            flash("Yeni konumda uyumsuz depolama grubunda madde bulunuyor.", "danger")
            return redirect(url_for("hazardous_substances.detail", substance_id=row.id))
        row.storage_location = new_location
        delta = 0.0
    else:
        try:
            amount = parse_float("quantity", required=True, minimum=0.000001)
        except ValueError as error:
            flash(str(error), "danger")
            return redirect(url_for("hazardous_substances.detail", substance_id=row.id))
        if movement_type in {"Tüketim"}:
            delta = -amount
        elif movement_type == "Sayım Düzeltme":
            direction = request.form.get("direction", "increase")
            delta = amount if direction == "increase" else -amount
        else:
            delta = amount
    balance = row.quantity + delta
    if balance < 0:
        flash("Negatif stok oluşturacak hareket kaydedilemez.", "danger")
        return redirect(url_for("hazardous_substances.detail", substance_id=row.id))
    if row.maximum_stock is not None and balance > row.maximum_stock:
        flash("Hareket tanımlı maksimum stok seviyesini aşıyor.", "danger")
        return redirect(url_for("hazardous_substances.detail", substance_id=row.id))
    row.quantity = balance
    db.session.add(HazardousSubstanceTransaction(company_id=row.company_id, substance=row, movement_type=movement_type, quantity=delta, balance_after=balance, note=note, performed_by_user_id=g.current_user.id))
    db.session.commit()
    flash("Stok hareketi kaydedildi.", "success")
    return redirect(url_for("hazardous_substances.detail", substance_id=row.id))


@bp.post("/<int:substance_id>/karantinaya-al")
@login_required
def quarantine(substance_id):
    require_permission("hazardous_substances.quarantine", "hazardous_substances.manage")
    require_company_scope()
    row = get_substance_or_404(substance_id)
    note = request.form.get("note", "").strip()
    if row.status != "Aktif" or not note:
        abort(409)
    row.status = "Karantina"
    row.review_note = note
    row.quarantined_at = now_utc()
    notify(row.reviewer_user_id, row, "Madde karantinaya alındı; inceleme gerekiyor.", f"quarantine-{row.quarantined_at.timestamp()}", notification_type="danger")
    db.session.commit()
    flash("Madde karantinaya alındı; stok çıkışı engellendi.", "success")
    return redirect(url_for("hazardous_substances.detail", substance_id=row.id))


@bp.post("/<int:substance_id>/bertaraf")
@login_required
def dispose(substance_id):
    require_permission("hazardous_substances.dispose", "hazardous_substances.manage")
    require_company_scope()
    row = get_substance_or_404(substance_id)
    note = request.form.get("note", "").strip()
    if row.status not in {"Aktif", "Karantina"} or not note:
        abort(409)
    if row.quantity:
        db.session.add(HazardousSubstanceTransaction(company_id=row.company_id, substance=row, movement_type="Bertaraf", quantity=-row.quantity, balance_after=0, note=note, performed_by_user_id=g.current_user.id))
    row.quantity = 0
    row.status = "Bertaraf"
    row.review_note = note
    row.disposed_at = now_utc()
    db.session.commit()
    flash("Madde bertaraf edildi ve stok sıfırlandı.", "success")
    return redirect(url_for("hazardous_substances.detail", substance_id=row.id))


@bp.post("/<int:substance_id>/arsivle")
@login_required
def archive(substance_id):
    require_permission("hazardous_substances.archive", "hazardous_substances.manage")
    require_company_scope()
    row = get_substance_or_404(substance_id)
    if row.status not in {"Reddedildi", "Bertaraf"}:
        abort(409)
    row.status = "Arşiv"
    row.archived_at = now_utc()
    db.session.commit()
    flash("Tehlikeli madde kartı geçmişi korunarak arşivlendi.", "success")
    return redirect(url_for("hazardous_substances.dashboard", status="Arşiv"))


@bp.get("/dosya/<int:file_id>")
@login_required
def download_file(file_id):
    require_permission("hazardous_substances.file_download", "hazardous_substances.manage")
    file_row = scoped_query(HazardousSubstanceFile.query, HazardousSubstanceFile).filter_by(id=file_id).first_or_404()
    if not can_access(file_row.substance):
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
    query = substance_query().filter(HazardousSubstance.status.notin_(tuple(TERMINAL_STATUSES)))
    user_id = g.current_user.id
    query = query.filter_by(created_by_user_id=user_id) if scope == "created" else query.filter(or_(HazardousSubstance.responsible_user_id == user_id, HazardousSubstance.reviewer_user_id == user_id))
    today = date.today()
    rows = []
    for row in query.all():
        state = warning_state(row, today)
        if scope != "created":
            needs_user = (row.reviewer_user_id == user_id and row.status == "Onay Bekliyor") or (row.responsible_user_id == user_id and (row.status in {"Taslak", "Revizyon Bekliyor", "Karantina"} or state != row.status))
            if not needs_user:
                continue
        due = row.expiry_date if row.expiry_date and row.expiry_date <= row.sds_review_due_date else row.sds_review_due_date
        rows.append(row_builder(
            module_key="hazardous_substance", module_label="Tehlikeli Madde", module_icon="radioactive", module_tone="risk",
            title=row.name, description=f"{row.storage_group} · {row.storage_location}", reference_no=row.inventory_no,
            department=row.department or row.usage_area, due_date=due, status=state,
            status_key="delayed" if state in {"Son Kullanım Geçti", "SDS Güncelleme Gecikti"} else "pending",
            priority="Yüksek" if state != row.status else "Orta", detail_url=url_for("hazardous_substances.detail", substance_id=row.id),
            created_at=row.created_at, sort_id=row.id, date_label="Kontrol Tarihi",
        ))
    return rows
