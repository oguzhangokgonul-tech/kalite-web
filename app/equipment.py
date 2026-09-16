from datetime import UTC, date, datetime, timedelta
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
    CalibrationRecord, EquipmentAsset, EquipmentAssetFile,
    EquipmentLifecycleEvent, MaintenanceMachine, User,
)
from .notifications import add_user_notification
from .tenant import current_company_id, scoped_query


bp = Blueprint("equipment", __name__, url_prefix="/ekipman-yasam-dongusu")

STATUSES = ("Kabul Bekliyor", "Aktif", "Bakımda", "Kalibrasyonda", "Kullanım Dışı", "Hurda")
CRITICALITIES = ("Düşük", "Orta", "Yüksek", "Kritik")
EVENT_TYPES = (
    "Satın Alma", "Kabul", "Devreye Alma", "Zimmet", "Transfer",
    "Bakım", "Kalibrasyon", "Kontrol", "Durum Değişikliği", "Kullanım Dışı", "Hurda",
)
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
    return checker("equipment_lifecycle") if checker else True


def asset_query():
    return scoped_query(EquipmentAsset.query, EquipmentAsset)


def event_query():
    return scoped_query(EquipmentLifecycleEvent.query, EquipmentLifecycleEvent)


def file_query():
    return scoped_query(EquipmentAssetFile.query, EquipmentAssetFile)


def can_access(asset):
    return bool(
        has_permission("equipment.view_all")
        or has_permission("equipment.manage")
        or asset.created_by_user_id == g.current_user.id
        or asset.custodian_user_id == g.current_user.id
    )


def get_asset_or_404(asset_id):
    asset = asset_query().filter_by(id=asset_id).first_or_404()
    if not can_access(asset):
        abort(404)
    return asset


def parse_date(name):
    raw = request.form.get(name, "").strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise ValueError("invalid_date") from None


def active_users():
    return User.query.filter_by(
        company_id=current_company_id(), is_active=True
    ).order_by(User.full_name.asc()).all()


def linked_choices(model, label_attr):
    return [
        (row.id, getattr(row, label_attr))
        for row in scoped_query(model.query, model).order_by(getattr(model, label_attr).asc()).all()
    ]


def optional_choice(name, allowed_ids):
    raw = request.form.get(name, "").strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        raise ValueError("invalid_relation") from None
    if value not in allowed_ids:
        raise ValueError("invalid_relation")
    return value


def parse_form():
    status = request.form.get("status", "Aktif").strip()
    criticality = request.form.get("criticality", "Orta").strip()
    users = {row.id for row in active_users()}
    machines = {row[0] for row in linked_choices(MaintenanceMachine, "machine_name")}
    calibrations = {row[0] for row in linked_choices(CalibrationRecord, "device_name")}
    custodian_id = optional_choice("custodian_user_id", users)
    values = {
        "name": request.form.get("name", "").strip(),
        "category": request.form.get("category", "").strip() or None,
        "manufacturer": request.form.get("manufacturer", "").strip() or None,
        "brand_model": request.form.get("brand_model", "").strip() or None,
        "serial_no": request.form.get("serial_no", "").strip() or None,
        "purchase_date": parse_date("purchase_date"),
        "commissioning_date": parse_date("commissioning_date"),
        "warranty_end_date": parse_date("warranty_end_date"),
        "location": request.form.get("location", "").strip() or None,
        "department": request.form.get("department", "").strip() or None,
        "custodian_user_id": custodian_id,
        "maintenance_machine_id": optional_choice("maintenance_machine_id", machines),
        "calibration_record_id": optional_choice("calibration_record_id", calibrations),
        "next_maintenance_date": parse_date("next_maintenance_date"),
        "next_inspection_date": parse_date("next_inspection_date"),
        "criticality": criticality,
        "status": status,
        "notes": request.form.get("notes", "").strip() or None,
    }
    if not values["name"]:
        raise ValueError("name_required")
    if status not in STATUSES or criticality not in CRITICALITIES:
        raise ValueError("invalid_choice")
    return values


def next_asset_code():
    year = date.today().year
    prefix = f"EKP-{year}-"
    numbers = []
    for (value,) in asset_query().filter(
        EquipmentAsset.asset_code.like(f"{prefix}%")
    ).with_entities(EquipmentAsset.asset_code).all():
        try:
            numbers.append(int(value.rsplit("-", 1)[-1]))
        except (TypeError, ValueError):
            continue
    return f"{prefix}{max(numbers, default=0) + 1:04d}"


def add_event(asset, event_type, description, *, old_status=None, new_status=None,
              old_location=None, new_location=None, event_date=None):
    row = EquipmentLifecycleEvent(
        company_id=asset.company_id,
        asset=asset,
        event_type=event_type,
        event_date=event_date or date.today(),
        description=description,
        old_status=old_status,
        new_status=new_status,
        old_location=old_location,
        new_location=new_location,
        performed_by_user_id=g.current_user.id,
    )
    db.session.add(row)
    return row


def store_file(uploaded_file, asset):
    if not uploaded_file or not uploaded_file.filename:
        return
    extension = Path(uploaded_file.filename).suffix.lower().lstrip(".")
    if extension not in ALLOWED_EXTENSIONS:
        raise ValueError("Yalnızca PDF, Word, Excel, CSV, metin veya görsel yükleyin.")
    from .routes import assert_company_storage_quota, safe_original_filename, upload_storage_path, uploaded_stream_size
    original_name = safe_original_filename(uploaded_file.filename, "ekipman-teknik-dosya")
    relative, absolute = upload_storage_path(
        f"{uuid4().hex}.{extension}", "equipment", asset.company_id
    )
    assert_company_storage_quota(asset.company_id, uploaded_stream_size(uploaded_file))
    uploaded_file.save(absolute)
    row = EquipmentAssetFile(
        company_id=asset.company_id,
        asset=asset,
        original_name=original_name,
        stored_path=str(relative).replace("\\", "/"),
        mime_type=uploaded_file.mimetype,
        file_size=absolute.stat().st_size,
        sha256_hash=hashlib.sha256(absolute.read_bytes()).hexdigest(),
        uploaded_by_user_id=g.current_user.id,
    )
    db.session.add(row)


def form_context(asset=None):
    return {
        "asset": asset,
        "values": request.form,
        "statuses": STATUSES,
        "criticalities": CRITICALITIES,
        "users": active_users(),
        "machines": linked_choices(MaintenanceMachine, "machine_name"),
        "calibrations": linked_choices(CalibrationRecord, "device_name"),
        "today": date.today().isoformat(),
    }


@bp.before_request
def guard_module():
    if not module_enabled():
        abort(404)


@bp.get("")
@login_required
def dashboard():
    require_permission("equipment.view", "equipment.view_all", "equipment.manage")
    query = asset_query()
    if not (has_permission("equipment.view_all") or has_permission("equipment.manage")):
        query = query.filter(or_(
            EquipmentAsset.created_by_user_id == g.current_user.id,
            EquipmentAsset.custodian_user_id == g.current_user.id,
        ))
    search = request.args.get("q", "").strip()
    status = request.args.get("status", "").strip()
    archived = request.args.get("archived", "active") == "archived"
    query = query.filter(EquipmentAsset.archived_at.is_not(None) if archived else EquipmentAsset.archived_at.is_(None))
    if search:
        term = f"%{search}%"
        query = query.filter(or_(
            EquipmentAsset.asset_code.ilike(term), EquipmentAsset.name.ilike(term),
            EquipmentAsset.serial_no.ilike(term), EquipmentAsset.location.ilike(term),
        ))
    if status in STATUSES:
        query = query.filter_by(status=status)
    assets = query.order_by(EquipmentAsset.asset_code.asc()).all()
    today = date.today()
    return render_template(
        "equipment/dashboard.html", assets=assets, statuses=STATUSES,
        search=search, selected_status=status, archived=archived, today=today,
        can_create=has_permission("equipment.create") or has_permission("equipment.manage"),
        can_manage=has_permission("equipment.manage"),
    )


@bp.route("/yeni", methods=["GET", "POST"])
@login_required
def create():
    require_permission("equipment.create", "equipment.manage")
    if request.method == "POST":
        try:
            values = parse_form()
            asset = EquipmentAsset(
                company_id=current_company_id(), asset_code=next_asset_code(),
                created_by_user_id=g.current_user.id, **values,
            )
            db.session.add(asset)
            db.session.flush()
            add_event(asset, "Kabul", "Ekipman yaşam döngüsü kaydı oluşturuldu.", new_status=asset.status)
            store_file(request.files.get("attachment"), asset)
            if asset.custodian:
                add_user_notification(
                    asset.custodian,
                    f"{asset.asset_code} ekipmanı size zimmetlendi: {asset.name}",
                    company_id=asset.company_id,
                    source_key=f"equipment-custodian:{asset.id}:{asset.custodian_user_id}",
                    target_url=url_for("equipment.detail", asset_id=asset.id),
                    notification_type="info",
                )
            db.session.commit()
            flash(f"{asset.asset_code} ekipman kartı oluşturuldu.", "success")
            return redirect(url_for("equipment.detail", asset_id=asset.id))
        except ValueError as error:
            db.session.rollback()
            flash(str(error) if " " in str(error) else "Ekipman bilgilerini kontrol edin.", "danger")
    return render_template("equipment/form.html", **form_context())


@bp.route("/<int:asset_id>/duzenle", methods=["GET", "POST"])
@login_required
def edit(asset_id):
    require_permission("equipment.manage")
    asset = get_asset_or_404(asset_id)
    if asset.archived_at:
        abort(409)
    if request.method == "POST":
        try:
            values = parse_form()
            old_status, old_location, old_custodian = asset.status, asset.location, asset.custodian_user_id
            for key, value in values.items():
                setattr(asset, key, value)
            if old_status != asset.status or old_location != asset.location:
                add_event(
                    asset, "Durum Değişikliği",
                    "Ekipman durumu veya lokasyonu güncellendi.",
                    old_status=old_status, new_status=asset.status,
                    old_location=old_location, new_location=asset.location,
                )
            if old_custodian != asset.custodian_user_id:
                add_event(asset, "Zimmet", "Ekipman zimmet sorumlusu değiştirildi.")
            store_file(request.files.get("attachment"), asset)
            db.session.commit()
            flash("Ekipman kartı güncellendi.", "success")
            return redirect(url_for("equipment.detail", asset_id=asset.id))
        except ValueError as error:
            db.session.rollback()
            flash(str(error) if " " in str(error) else "Ekipman bilgilerini kontrol edin.", "danger")
    return render_template("equipment/form.html", **form_context(asset))


@bp.get("/<int:asset_id>")
@login_required
def detail(asset_id):
    require_permission("equipment.view", "equipment.view_all", "equipment.manage")
    asset = get_asset_or_404(asset_id)
    return render_template(
        "equipment/detail.html", asset=asset, event_types=EVENT_TYPES, statuses=STATUSES,
        can_manage=has_permission("equipment.manage"),
        can_record=has_permission("equipment.event") or has_permission("equipment.manage"),
        can_archive=has_permission("equipment.archive") or has_permission("equipment.manage"),
        can_download=has_permission("equipment.file_download") or has_permission("equipment.manage"),
    )


@bp.post("/<int:asset_id>/olay")
@login_required
def add_lifecycle_event(asset_id):
    require_permission("equipment.event", "equipment.manage")
    asset = get_asset_or_404(asset_id)
    if asset.archived_at:
        abort(409)
    event_type = request.form.get("event_type", "").strip()
    description = request.form.get("description", "").strip()
    new_status = request.form.get("new_status", "").strip() or None
    new_location = request.form.get("new_location", "").strip() or None
    if event_type not in EVENT_TYPES or not description:
        flash("Olay türü ve açıklama zorunludur.", "danger")
        return redirect(url_for("equipment.detail", asset_id=asset.id))
    if new_status and new_status not in STATUSES:
        abort(400)
    try:
        old_status, old_location = asset.status, asset.location
        if new_status:
            asset.status = new_status
        if new_location:
            asset.location = new_location
        add_event(
            asset, event_type, description, old_status=old_status,
            new_status=asset.status if new_status else None,
            old_location=old_location, new_location=asset.location if new_location else None,
            event_date=parse_date("event_date") or date.today(),
        )
        store_file(request.files.get("attachment"), asset)
        db.session.commit()
    except ValueError as error:
        db.session.rollback()
        flash(
            str(error) if " " in str(error) else "Olay tarihi veya dosya bilgisini kontrol edin.",
            "danger",
        )
        return redirect(url_for("equipment.detail", asset_id=asset.id))
    flash("Yaşam döngüsü olayı kaydedildi.", "success")
    return redirect(url_for("equipment.detail", asset_id=asset.id))


@bp.post("/<int:asset_id>/arsivle")
@login_required
def archive(asset_id):
    require_permission("equipment.archive", "equipment.manage")
    asset = get_asset_or_404(asset_id)
    if asset.status not in {"Kullanım Dışı", "Hurda"}:
        flash("Arşiv için cihazı önce Kullanım Dışı veya Hurda durumuna alın.", "danger")
        return redirect(url_for("equipment.detail", asset_id=asset.id))
    asset.archived_at = datetime.now(UTC).replace(tzinfo=None)
    add_event(asset, "Hurda" if asset.status == "Hurda" else "Kullanım Dışı", "Ekipman yaşam döngüsü arşivlendi.")
    db.session.commit()
    flash("Ekipman denetim izi korunarak arşivlendi.", "success")
    return redirect(url_for("equipment.dashboard", archived="archived"))


@bp.get("/dosya/<int:file_id>")
@login_required
def download_file(file_id):
    require_permission("equipment.file_download", "equipment.manage")
    row = file_query().filter_by(id=file_id).first_or_404()
    if not can_access(row.asset):
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


def assigned_task_rows(scope, row_builder):
    if not module_enabled():
        return []
    user_id = g.current_user.id
    query = asset_query().filter(EquipmentAsset.archived_at.is_(None))
    query = query.filter_by(created_by_user_id=user_id) if scope == "created" else query.filter_by(custodian_user_id=user_id)
    today = date.today()
    rows = []
    for asset in query.all():
        due_candidates = [value for value in (asset.next_maintenance_date, asset.next_inspection_date, asset.warranty_end_date) if value]
        due_date = min(due_candidates) if due_candidates else None
        if scope != "created" and (not due_date or due_date > today + timedelta(days=30)):
            continue
        delayed = bool(due_date and due_date < today)
        rows.append(row_builder(
            module_key="equipment", module_label="Ekipman",
            module_icon="pc-display-horizontal", module_tone="maintenance",
            title=asset.name, description=f"{asset.category or 'Ekipman'} · {asset.location or '-'}",
            reference_no=asset.asset_code, department=asset.department or "Ekipman",
            due_date=due_date or asset.commissioning_date or date.today(),
            status="Termin Geçti" if delayed else asset.status,
            status_key="delayed" if delayed else "pending",
            priority="Yüksek" if delayed or asset.criticality in {"Yüksek", "Kritik"} else "Orta",
            detail_url=url_for("equipment.detail", asset_id=asset.id),
            created_at=asset.created_at, sort_id=asset.id, date_label="Termin",
        ))
    return rows
