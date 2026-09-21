from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from functools import wraps
import hashlib
from pathlib import Path
from uuid import uuid4

from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, send_file, url_for
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from .audit import record_audit_event
from .extensions import db
from .models import (
    Action,
    AppSetting,
    CompanyDepartment,
    EnergyMeter,
    EnergyReading,
    EnergySavingProject,
    EnergySavingVerification,
    EnergyTarget,
    QualityObjective,
    User,
)
from .notifications import add_user_notification
from .tenant import current_company_id, scoped_query


bp = Blueprint("energy", __name__, url_prefix="/enerji-yonetimi")

ENERGY_TYPES = ("Elektrik", "Doğal Gaz", "LPG", "Motorin", "Buhar", "Güneş", "Diğer")
UNITS = ("kWh", "MWh", "m³", "kg", "L", "GJ")
ALLOWED_EXTENSIONS = {"pdf", "jpg", "jpeg", "png", "doc", "docx", "xls", "xlsx"}


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


def company_id_required():
    company_id = current_company_id()
    if company_id is None:
        abort(400, "Kayıt işlemi için şirket bağlamı gereklidir.")
    return company_id


def now_utc():
    return datetime.now(UTC).replace(tzinfo=None)


def meter_query():
    return scoped_query(EnergyMeter.query, EnergyMeter)


def reading_query():
    return scoped_query(EnergyReading.query, EnergyReading)


def target_query():
    return scoped_query(EnergyTarget.query, EnergyTarget)


def project_query():
    return scoped_query(EnergySavingProject.query, EnergySavingProject)


def visible_targets(query=None):
    query = query or target_query()
    if has_permission("energy.manage") or has_permission("energy.view_all"):
        return query
    meter_ids = [row.id for row in visible_meters().with_entities(EnergyMeter.id).all()]
    return query.filter(or_(
        EnergyTarget.meter_id.in_(meter_ids),
        EnergyTarget.responsible_user_id == g.current_user.id,
        EnergyTarget.approver_user_id == g.current_user.id,
        EnergyTarget.created_by_user_id == g.current_user.id,
    ))


def visible_projects(query=None):
    query = query or project_query()
    if has_permission("energy.manage") or has_permission("energy.view_all"):
        return query
    meter_ids = [row.id for row in visible_meters().with_entities(EnergyMeter.id).all()]
    return query.filter(or_(
        EnergySavingProject.meter_id.in_(meter_ids),
        EnergySavingProject.responsible_user_id == g.current_user.id,
        EnergySavingProject.approver_user_id == g.current_user.id,
        EnergySavingProject.created_by_user_id == g.current_user.id,
    ))


def parse_decimal(name, *, required=True, minimum=None):
    raw = request.form.get(name, "").strip().replace(",", ".")
    if not raw and not required:
        return None
    try:
        value = Decimal(raw)
    except (InvalidOperation, ValueError):
        raise ValueError("Sayısal alanlardan biri geçerli değil.") from None
    if minimum is not None and value < Decimal(str(minimum)):
        raise ValueError(f"{name} alanı {minimum} değerinden küçük olamaz.")
    return value


def parse_int(name, minimum, maximum):
    try:
        value = int(request.form.get(name, ""))
    except (TypeError, ValueError):
        raise ValueError("Sayısal alanlardan biri geçerli değil.") from None
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} alanı {minimum}-{maximum} aralığında olmalıdır.")
    return value


def parse_date(name, required=True):
    raw = request.form.get(name, "").strip()
    if not raw and not required:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise ValueError("Tarih alanlarından biri geçerli değil.") from None


def parse_record(name, model, required=False):
    raw = request.form.get(name, "").strip()
    if not raw and not required:
        return None
    try:
        row_id = int(raw)
    except (TypeError, ValueError):
        raise ValueError("Bağlantılı kayıt geçerli değil.") from None
    row = scoped_query(model.query, model).filter_by(id=row_id).first()
    if not row:
        raise ValueError("Bağlantılı kayıt bu şirkete ait değil.")
    return row


def active_users(*required_permissions):
    users = User.query.filter_by(company_id=current_company_id(), is_active=True).order_by(User.full_name).all()
    if not required_permissions:
        return users
    return [u for u in users if u.has_permission("energy.manage") or all(u.has_permission(p) for p in required_permissions)]


def department_users(*required_permissions):
    users = active_users(*required_permissions)
    if has_permission("energy.manage") or has_permission("energy.view_all"):
        return users
    allowed = departments()
    if not allowed:
        return []
    from .dynamic_forms import user_matches_department
    return [user for user in users if any(user_matches_department(user, item.name) for item in allowed)]


def parse_user(name, *permissions):
    row = parse_record(name, User, required=True)
    if not row.is_active or (permissions and not (row.has_permission("energy.manage") or all(row.has_permission(p) for p in permissions))):
        raise ValueError("Seçilen personel bu iş akışı için uygun değil.")
    return row


def require_assignable_responsible(user, meter=None):
    if has_permission("energy.manage") or has_permission("energy.view_all"):
        return
    allowed_user_ids = {item.id for item in department_users("energy.view", "energy.project_manage")}
    if user.id not in allowed_user_ids:
        raise ValueError("Sorumlu kişi yetkili olduğunuz departmanda görevli olmalıdır.")
    if meter:
        from .dynamic_forms import user_matches_department
        if not user_matches_department(user, meter.department.name):
            raise ValueError("Sorumlu kişi seçilen sayacın departmanında görevli olmalıdır.")


def departments():
    rows = CompanyDepartment.query.filter_by(company_id=current_company_id(), is_active=True).order_by(CompanyDepartment.sort_order, CompanyDepartment.name).all()
    if has_permission("energy.manage") or has_permission("energy.view_all"):
        return rows
    if g.current_user.has_role("department_manager") or g.current_user.has_role("department_staff"):
        from .dynamic_forms import user_matches_department
        return [row for row in rows if user_matches_department(g.current_user, row.name)]
    return rows


def can_access_department(department):
    if has_permission("energy.manage") or has_permission("energy.view_all"):
        return True
    if g.current_user.has_role("department_manager") or g.current_user.has_role("department_staff"):
        from .dynamic_forms import user_matches_department
        return user_matches_department(g.current_user, department.name)
    return True


def require_department(department):
    if not can_access_department(department):
        abort(403)


def visible_meters(query=None):
    query = query or meter_query()
    if has_permission("energy.manage") or has_permission("energy.view_all"):
        return query
    allowed = [row.id for row in departments()]
    return query.filter(EnergyMeter.department_id.in_(allowed)) if allowed else query.filter(EnergyMeter.id == -1)


def get_meter(meter_id):
    row = meter_query().filter_by(id=meter_id).first_or_404()
    require_department(row.department)
    return row


def get_reading(reading_id):
    row = reading_query().filter_by(id=reading_id).first_or_404()
    require_department(row.meter.department)
    return row


def get_target(target_id):
    row = visible_targets().filter_by(id=target_id).first_or_404()
    if row.meter:
        require_department(row.meter.department)
    return row


def get_project(project_id):
    row = visible_projects().filter_by(id=project_id).first_or_404()
    if row.meter:
        require_department(row.meter.department)
    return row


def next_number(model, field, prefix):
    values = scoped_query(model.query, model).with_entities(getattr(model, field)).filter(getattr(model, field).like(f"{prefix}%")).all()
    numbers = []
    for (value,) in values:
        try:
            numbers.append(int(value.rsplit("-", 1)[-1]))
        except (TypeError, ValueError):
            pass
    return f"{prefix}{max(numbers, default=0) + 1:04d}"


def notify(user_id, reference, message, target_url, due_date=None, kind="warning"):
    user = User.query.filter_by(id=user_id, company_id=current_company_id(), is_active=True).first()
    if user:
        source = hashlib.sha256(f"{reference}:{message}:{now_utc().isoformat()}".encode("utf-8")).hexdigest()[:24]
        add_user_notification(user, f"{reference} - {message}", company_id=current_company_id(), source_key=f"energy:{source}:u{user_id}", target_url=target_url, due_date=due_date, notification_type=kind)


def save_evidence(upload, folder, fallback):
    if not upload or not upload.filename:
        return None
    extension = Path(upload.filename).suffix.lower().lstrip(".")
    if extension not in ALLOWED_EXTENSIONS:
        raise ValueError("Yalnızca PDF, Word, Excel veya görsel dosyası yüklenebilir.")
    from .routes import assert_company_storage_quota, safe_original_filename, upload_storage_path, uploaded_stream_size
    company_id = company_id_required()
    original = safe_original_filename(upload.filename, fallback)
    relative, absolute = upload_storage_path(f"{uuid4().hex}.{extension}", folder, company_id)
    assert_company_storage_quota(company_id, uploaded_stream_size(upload))
    upload.save(absolute)
    return original, str(relative).replace("\\", "/"), hashlib.sha256(absolute.read_bytes()).hexdigest(), absolute


def safe_remove(path):
    if path:
        path.unlink(missing_ok=True)


def settings():
    company_id = company_id_required()
    currency = db.session.get(AppSetting, f"energy:currency:{company_id}")
    return (currency.value if currency else "TRY")


@bp.before_request
def guard():
    checker = getattr(g, "company_module_enabled", None)
    if checker and not checker("energy_management"):
        abort(404)


@bp.get("")
@login_required
def dashboard():
    require_permission("energy.view", "energy.view_all", "energy.manage")
    search = request.args.get("q", "").strip()
    show_archive = request.args.get("archive") == "1" and (has_permission("energy.view_all") or has_permission("energy.manage"))
    meters_q = visible_meters().filter(EnergyMeter.status == ("Arşiv" if show_archive else "Aktif"))
    if search:
        term = f"%{search}%"
        meters_q = meters_q.filter(or_(EnergyMeter.meter_code.ilike(term), EnergyMeter.name.ilike(term), EnergyMeter.location.ilike(term)))
    meters = meters_q.order_by(EnergyMeter.meter_code).all()
    meter_ids = [row.id for row in visible_meters().with_entities(EnergyMeter.id).all()]
    readings = reading_query().filter(EnergyReading.meter_id.in_(meter_ids), EnergyReading.is_current.is_(True)).order_by(EnergyReading.period.desc(), EnergyReading.id.desc()).limit(100).all() if meter_ids else []
    targets = visible_targets().filter(EnergyTarget.status != ("Arşiv" if not show_archive else "__none__")).order_by(EnergyTarget.target_date).all()
    projects = visible_projects().filter(EnergySavingProject.status != ("Arşiv" if not show_archive else "__none__")).order_by(EnergySavingProject.due_date).all()
    if search:
        needle = search.casefold()
        readings = [row for row in readings if needle in f"{row.meter.meter_code} {row.meter.name} {row.period:%m.%Y} {row.status}".casefold()]
        targets = [row for row in targets if needle in f"{row.target_no} {row.title} {row.status}".casefold()]
        projects = [row for row in projects if needle in f"{row.project_no} {row.title} {row.status}".casefold()]
    approved = [row for row in readings if row.status == "Onaylandı"]
    current_period = date.today().replace(day=1)
    previous_year, previous_month = (current_period.year - 1, 12) if current_period.month == 1 else (current_period.year, current_period.month - 1)
    previous_period = date(previous_year, previous_month, 1)
    current_by_unit, previous_by_unit = {}, {}
    for item in approved:
        bucket = current_by_unit if item.period == current_period else previous_by_unit if item.period == previous_period else None
        if bucket is not None:
            bucket[item.meter.unit] = bucket.get(item.meter.unit, Decimal("0")) + item.consumption
    period_changes = {}
    for unit, total in current_by_unit.items():
        previous = previous_by_unit.get(unit)
        period_changes[unit] = ((total - previous) / previous * 100).quantize(Decimal("0.1")) if previous else None
    saving_by_unit = {}
    for item in projects:
        if item.status == "Tamamlandı" and item.actual_saving is not None:
            unit = item.meter.unit if item.meter else "birim"
            saving_by_unit[unit] = saving_by_unit.get(unit, Decimal("0")) + item.actual_saving
    summary = {
        "active_meters": visible_meters().filter_by(status="Aktif").count(),
        "current_by_unit": current_by_unit,
        "period_changes": period_changes,
        "pending_readings": reading_query().filter(EnergyReading.meter_id.in_(meter_ids), EnergyReading.is_current.is_(True), EnergyReading.status == "Onay Bekliyor").count() if meter_ids else 0,
        "overdue_projects": visible_projects().filter(EnergySavingProject.status.in_(("Planlandı", "Devam Ediyor", "Doğrulama Bekliyor")), EnergySavingProject.due_date < date.today()).count(),
        "saving_by_unit": saving_by_unit,
    }
    return render_template("energy/dashboard.html", summary=summary, meters=meters, readings=readings, targets=targets, projects=projects, can_manage=has_permission("energy.manage"), can_meter_manage=has_permission("energy.meter_manage") or has_permission("energy.manage"), can_project_manage=has_permission("energy.project_manage") or has_permission("energy.manage"), can_view_archive=has_permission("energy.view_all") or has_permission("energy.manage"), can_create=has_permission("energy.create") or has_permission("energy.manage"), can_approve=has_permission("energy.approve") or has_permission("energy.manage"), can_export=has_permission("energy.export") or has_permission("energy.manage"), show_archive=show_archive, search=search, today=date.today(), currency=settings())


@bp.route("/parametreler", methods=("GET", "POST"))
@login_required
def parameters():
    require_permission("energy.manage")
    company_id = company_id_required()
    currencies = ("TRY", "EUR", "USD", "GBP")
    if request.method == "POST":
        currency = request.form.get("currency", "")
        if currency not in currencies:
            flash("Para birimi geçerli değil.", "danger")
        else:
            key = f"energy:currency:{company_id}"
            row = db.session.get(AppSetting, key) or AppSetting(key=key)
            row.value = currency; db.session.add(row); db.session.commit()
            record_audit_event("EnergySettings", "updated", "Enerji yönetimi parametreleri güncellendi", details={"currency": currency})
            flash("Enerji parametreleri güncellendi.", "success")
            return redirect(url_for("energy.parameters"))
    return render_template("energy/parameters.html", currency=settings(), currencies=currencies)


@bp.route("/sayac/yeni", methods=("GET", "POST"))
@login_required
def create_meter(meter_id=None):
    require_permission("energy.meter_manage", "energy.manage")
    row = get_meter(meter_id) if meter_id else EnergyMeter(company_id=company_id_required(), created_by_user_id=g.current_user.id)
    if request.method == "POST":
        try:
            department = parse_record("department_id", CompanyDepartment, True); require_department(department)
            responsible = parse_user("responsible_user_id", "energy.view", "energy.create")
            reviewer = parse_user("reviewer_user_id", "energy.view", "energy.approve")
            if reviewer.id in {responsible.id, row.created_by_user_id}:
                raise ValueError("Sorumlu veya kaydı oluşturan kişi kendi enerji kaydını onaylayamaz.")
            if not (has_permission("energy.manage") or has_permission("energy.view_all")):
                from .dynamic_forms import user_matches_department
                if not user_matches_department(responsible, department.name):
                    raise ValueError("Sayaç sorumlusu seçilen departmanda görevli olmalıdır.")
            energy_type = request.form.get("energy_type", "")
            unit = request.form.get("unit", "")
            if energy_type not in ENERGY_TYPES or unit not in UNITS:
                raise ValueError("Enerji türü veya birim geçerli değil.")
            row.meter_code = request.form.get("meter_code", "").strip().upper()
            row.name = request.form.get("name", "").strip()
            row.location = request.form.get("location", "").strip()
            if not row.meter_code or not row.name or not row.location:
                raise ValueError("Sayaç kodu, adı ve konumu zorunludur.")
            row.energy_type, row.unit, row.department_id = energy_type, unit, department.id
            row.serial_no = request.form.get("serial_no", "").strip() or None
            row.multiplier = parse_decimal("multiplier", minimum="0.0001")
            row.emission_factor = parse_decimal("emission_factor", required=False, minimum=0) or Decimal("0")
            row.reading_due_day = parse_int("reading_due_day", 1, 28)
            row.responsible_user_id, row.reviewer_user_id = responsible.id, reviewer.id
            db.session.add(row); db.session.commit()
            flash("Enerji sayacı kaydedildi.", "success")
            return redirect(url_for("energy.meter_detail", meter_id=row.id))
        except (ValueError, IntegrityError) as error:
            db.session.rollback(); flash("Sayaç kaydedilemedi. Kod benzersiz olmalı ve alanlar geçerli olmalıdır." if isinstance(error, IntegrityError) else str(error), "danger")
    return render_template("energy/meter_form.html", meter_record=row if meter_id else None, meter=row if meter_id else None, values=request.form, departments=departments(), users=department_users("energy.view", "energy.create"), approvers=active_users("energy.view", "energy.approve"), energy_types=ENERGY_TYPES, units=UNITS)


@bp.route("/sayac/<int:meter_id>/duzenle", methods=("GET", "POST"), endpoint="edit_meter")
@login_required
def edit_meter(meter_id):
    return create_meter(meter_id)


@bp.get("/sayac/<int:meter_id>")
@login_required
def meter_detail(meter_id):
    require_permission("energy.view", "energy.view_all", "energy.manage")
    row = get_meter(meter_id)
    return render_template("energy/meter_detail.html", meter=row, can_edit=(has_permission("energy.meter_manage") or has_permission("energy.manage")) and row.status == "Aktif", can_create=(has_permission("energy.create") or has_permission("energy.manage")) and row.status == "Aktif", can_archive=(has_permission("energy.archive") or has_permission("energy.manage")) and row.status == "Aktif", can_download=has_permission("energy.file_download") or has_permission("energy.manage"), currency=settings())


@bp.post("/sayac/<int:meter_id>/arsivle")
@login_required
def archive_meter(meter_id):
    require_permission("energy.archive", "energy.manage")
    row = get_meter(meter_id)
    if any(item.status == "Onay Bekliyor" for item in row.readings):
        flash("Onay bekleyen okuması bulunan sayaç arşivlenemez.", "danger")
    else:
        row.status, row.archived_at = "Arşiv", now_utc(); db.session.commit(); flash("Sayaç arşivlendi.", "success")
    return redirect(url_for("energy.dashboard"))


@bp.route("/sayac/<int:meter_id>/okuma/yeni", methods=("GET", "POST"))
@login_required
def create_reading(meter_id):
    require_permission("energy.create", "energy.manage")
    meter = get_meter(meter_id)
    if meter.status != "Aktif":
        abort(409)
    if request.method == "POST":
        evidence_path = None
        try:
            period = parse_date("period").replace(day=1)
            if period > date.today().replace(day=1):
                raise ValueError("Gelecek dönem için tüketim kaydı girilemez.")
            previous = parse_decimal("previous_value", minimum=0)
            current = parse_decimal("current_value", minimum=0)
            if current < previous:
                raise ValueError("Son endeks ilk endeksten küçük olamaz. Sayaç değiştiyse yeni sayaç tanımlayın.")
            multiplier = Decimal(meter.multiplier)
            consumption = (current - previous) * multiplier
            production = parse_decimal("production_quantity", required=False, minimum="0.000001")
            unit_cost = parse_decimal("unit_cost", required=False, minimum=0)
            factor = Decimal(meter.emission_factor)
            previous_version = reading_query().filter_by(meter_id=meter.id, period=period, is_current=True).first()
            if previous_version and previous_version.status != "Reddedildi":
                raise ValueError("Bu sayaç ve dönem için onay süreci devam eden veya onaylanmış kayıt bulunuyor.")
            evidence = save_evidence(request.files.get("evidence_file"), "energy/readings", "enerji-kaniti")
            if previous_version:
                previous_version.is_current = False
            row = EnergyReading(company_id=meter.company_id, meter=meter, period=period, version_no=(previous_version.version_no + 1 if previous_version else 1), supersedes_id=(previous_version.id if previous_version else None), is_current=True, reading_method="Sayaç", previous_value=previous, current_value=current, multiplier_snapshot=multiplier, emission_factor_snapshot=factor, consumption=consumption, production_quantity=production, production_unit=request.form.get("production_unit", "").strip() or None, normalized_consumption=(consumption / production if production else None), unit_cost=unit_cost, total_cost=(consumption * unit_cost if unit_cost is not None else None), emission_kg=consumption * factor, note=request.form.get("note", "").strip() or None, status="Onay Bekliyor", entered_by_user_id=g.current_user.id)
            if evidence:
                row.evidence_name, row.evidence_path, row.evidence_hash, evidence_path = evidence
            db.session.add(row); db.session.commit()
            notify(meter.reviewer_user_id, meter.meter_code, f"{period:%m.%Y} tüketim kaydı onayınızı bekliyor.", url_for("energy.reading_detail", reading_id=row.id))
            flash("Tüketim kaydı onaya gönderildi.", "success")
            return redirect(url_for("energy.reading_detail", reading_id=row.id))
        except (ValueError, IntegrityError) as error:
            db.session.rollback(); safe_remove(evidence_path)
            flash("Bu sayaç ve dönem için çakışan kayıt bulunuyor." if isinstance(error, IntegrityError) else str(error), "danger")
    return render_template("energy/reading_form.html", meter=meter, values=request.form, currency=settings())


@bp.get("/okuma/<int:reading_id>")
@login_required
def reading_detail(reading_id):
    require_permission("energy.view", "energy.view_all", "energy.manage")
    row = get_reading(reading_id)
    can_review = (has_permission("energy.approve") or has_permission("energy.manage")) and row.status == "Onay Bekliyor" and (g.current_user.id == row.meter.reviewer_user_id or has_permission("energy.manage")) and g.current_user.id != row.entered_by_user_id
    return render_template("energy/reading_detail.html", reading=row, can_review=can_review, can_download=(has_permission("energy.file_download") or has_permission("energy.manage")) and bool(row.evidence_path), currency=settings())


@bp.post("/okuma/<int:reading_id>/degerlendir")
@login_required
def review_reading(reading_id):
    require_permission("energy.approve", "energy.manage")
    row = get_reading(reading_id)
    if row.status != "Onay Bekliyor" or (g.current_user.id != row.meter.reviewer_user_id and not has_permission("energy.manage")) or g.current_user.id == row.entered_by_user_id:
        abort(403)
    decision = request.form.get("decision")
    note = request.form.get("review_note", "").strip()
    if decision not in {"approve", "reject"} or (decision == "reject" and not note):
        flash("Ret için açıklama zorunludur.", "danger")
    else:
        row.status = "Onaylandı" if decision == "approve" else "Reddedildi"
        row.reviewed_by_user_id, row.reviewed_at, row.review_note = g.current_user.id, now_utc(), note or None
        db.session.commit(); notify(row.entered_by_user_id, row.meter.meter_code, f"Tüketim kaydı {row.status.lower()}.", url_for("energy.reading_detail", reading_id=row.id), kind="info")
        flash("Değerlendirme kaydedildi.", "success")
    return redirect(url_for("energy.reading_detail", reading_id=row.id))


def target_form_context(row=None):
    return dict(target=row, values=request.form, meters=visible_meters().filter_by(status="Aktif").order_by(EnergyMeter.meter_code).all(), users=department_users("energy.view", "energy.project_manage"), approvers=active_users("energy.view", "energy.approve"), objectives=scoped_query(QualityObjective.query, QualityObjective).order_by(QualityObjective.objective_no).all(), actions=scoped_query(Action.query, Action).filter(Action.is_completed.is_(False)).order_by(Action.id.desc()).all())


@bp.route("/hedef/yeni", methods=("GET", "POST"))
@login_required
def create_target(target_id=None):
    require_permission("energy.project_manage", "energy.manage")
    existing = get_target(target_id) if target_id else None
    if existing and (existing.status != "Taslak" or (existing.responsible_user_id != g.current_user.id and not has_permission("energy.manage"))):
        abort(403)
    if request.method == "POST":
        try:
            meter = parse_record("meter_id", EnergyMeter)
            if meter: require_department(meter.department)
            responsible = parse_user("responsible_user_id", "energy.view", "energy.project_manage")
            require_assignable_responsible(responsible, meter)
            approver = parse_user("approver_user_id", "energy.view", "energy.approve")
            if approver.id in {responsible.id, g.current_user.id}:
                raise ValueError("Sorumlu veya kaydı oluşturan kişi kendi hedefini onaylayamaz.")
            title = request.form.get("title", "").strip()
            if not title: raise ValueError("Hedef adı zorunludur.")
            row = existing or EnergyTarget(company_id=company_id_required(), target_no=next_number(EnergyTarget, "target_no", f"ENH-{date.today().year}-"), created_by_user_id=g.current_user.id)
            row.title=title; row.meter_id=meter.id if meter else None; row.baseline_year=parse_int("baseline_year", 2000, 2100); row.baseline_consumption=parse_decimal("baseline_consumption", minimum="0.001"); row.reduction_percent=parse_decimal("reduction_percent", minimum="0.01"); row.target_date=parse_date("target_date"); row.responsible_user_id=responsible.id; row.approver_user_id=approver.id; row.quality_objective_id=getattr(parse_record("quality_objective_id", QualityObjective), "id", None); row.action_id=getattr(parse_record("action_id", Action), "id", None)
            if row.reduction_percent > 100:
                raise ValueError("Azaltım hedefi yüzde 100'den büyük olamaz.")
            if row.target_date < date.today(): raise ValueError("Hedef tarihi geçmiş olamaz.")
            db.session.add(row); db.session.commit(); flash("Enerji hedefi oluşturuldu.", "success")
            return redirect(url_for("energy.target_detail", target_id=row.id))
        except (ValueError, IntegrityError) as error:
            db.session.rollback(); flash(str(error), "danger")
    return render_template("energy/target_form.html", **target_form_context(existing))


@bp.route("/hedef/<int:target_id>/duzenle", methods=("GET", "POST"), endpoint="edit_target")
@login_required
def edit_target(target_id):
    return create_target(target_id)


@bp.get("/hedef/<int:target_id>")
@login_required
def target_detail(target_id):
    require_permission("energy.view", "energy.view_all", "energy.manage")
    row = get_target(target_id)
    owner = row.responsible_user_id == g.current_user.id or has_permission("energy.manage")
    reviewer = row.approver_user_id == g.current_user.id or has_permission("energy.manage")
    return render_template("energy/target_detail.html", target=row, can_edit=(has_permission("energy.project_manage") or has_permission("energy.manage")) and row.status == "Taslak" and owner, can_submit=(has_permission("energy.project_manage") or has_permission("energy.manage")) and row.status == "Taslak" and owner, can_complete=(has_permission("energy.project_manage") or has_permission("energy.manage")) and row.status == "Aktif" and owner, can_review=(has_permission("energy.approve") or has_permission("energy.manage")) and row.status in {"Onay Bekliyor", "Tamamlama Onayı"} and reviewer and row.created_by_user_id != g.current_user.id, can_archive=(has_permission("energy.archive") or has_permission("energy.manage")) and row.status in {"Aktif", "Tamamlandı", "Reddedildi"})


@bp.post("/hedef/<int:target_id>/onaya-gonder")
@login_required
def submit_target(target_id):
    require_permission("energy.project_manage", "energy.manage")
    row = get_target(target_id)
    if row.status != "Taslak" or (row.responsible_user_id != g.current_user.id and not has_permission("energy.manage")): abort(403)
    row.status = "Onay Bekliyor"; db.session.commit(); notify(row.approver_user_id, row.target_no, "Enerji azaltım hedefi onayınızı bekliyor.", url_for("energy.target_detail", target_id=row.id), row.target_date)
    flash("Hedef onaya gönderildi.", "success"); return redirect(url_for("energy.target_detail", target_id=row.id))


@bp.post("/hedef/<int:target_id>/tamamla")
@login_required
def complete_target(target_id):
    require_permission("energy.project_manage", "energy.manage")
    row = get_target(target_id)
    if row.status != "Aktif" or (row.responsible_user_id != g.current_user.id and not has_permission("energy.manage")):
        abort(403)
    note = request.form.get("completion_note", "").strip()
    try:
        actual = parse_decimal("actual_consumption", minimum=0)
        if not note:
            raise ValueError("Hedef kapanış açıklaması zorunludur.")
        row.actual_consumption, row.completion_note, row.status = actual, note, "Tamamlama Onayı"
        db.session.commit()
        notify(row.approver_user_id, row.target_no, "Enerji hedefi kapanış onayınızı bekliyor.", url_for("energy.target_detail", target_id=row.id), row.target_date)
        flash("Hedef tamamlanma onayına gönderildi.", "success")
    except ValueError as error:
        db.session.rollback(); flash(str(error), "danger")
    return redirect(url_for("energy.target_detail", target_id=row.id))


@bp.post("/hedef/<int:target_id>/degerlendir")
@login_required
def review_target(target_id):
    require_permission("energy.approve", "energy.manage")
    row = get_target(target_id)
    if row.status not in {"Onay Bekliyor", "Tamamlama Onayı"} or (row.approver_user_id != g.current_user.id and not has_permission("energy.manage")) or row.created_by_user_id == g.current_user.id: abort(403)
    closing = row.status == "Tamamlama Onayı"
    decision, note = request.form.get("decision"), request.form.get("review_note", "").strip()
    if decision not in {"approve", "reject"} or (decision == "reject" and not note): flash("Karar ve ret açıklaması kontrol edilmelidir.", "danger")
    else:
        if closing:
            row.status = "Tamamlandı" if decision == "approve" else "Aktif"
            row.completed_at = now_utc() if decision == "approve" else None
            row.completed_by_user_id = g.current_user.id if decision == "approve" else None
        else:
            row.status = "Aktif" if decision == "approve" else "Reddedildi"
            row.approved_at = now_utc() if decision == "approve" else None
        row.review_note = note or None; db.session.commit(); notify(row.responsible_user_id, row.target_no, f"Enerji hedefi {row.status.lower()}.", url_for("energy.target_detail", target_id=row.id), kind="info"); flash("Karar kaydedildi.", "success")
    return redirect(url_for("energy.target_detail", target_id=row.id))


@bp.post("/hedef/<int:target_id>/arsivle")
@login_required
def archive_target(target_id):
    require_permission("energy.archive", "energy.manage")
    row = get_target(target_id)
    if row.status not in {"Aktif", "Tamamlandı", "Reddedildi"}:
        abort(409)
    row.status, row.archived_at = "Arşiv", now_utc(); db.session.commit(); flash("Hedef arşivlendi.", "success"); return redirect(url_for("energy.dashboard"))


def project_form_context(project=None):
    return dict(project=project, values=request.form, meters=visible_meters().filter_by(status="Aktif").order_by(EnergyMeter.meter_code).all(), users=department_users("energy.view", "energy.project_manage"), approvers=active_users("energy.view", "energy.approve"), actions=scoped_query(Action.query, Action).filter(Action.is_completed.is_(False)).order_by(Action.id.desc()).all(), currency=settings())


@bp.route("/tasarruf/yeni", methods=("GET", "POST"))
@login_required
def create_project(project_id=None):
    require_permission("energy.project_manage", "energy.manage")
    existing = get_project(project_id) if project_id else None
    if existing and (existing.status != "Planlandı" or (existing.responsible_user_id != g.current_user.id and not has_permission("energy.manage"))):
        abort(403)
    if request.method == "POST":
        try:
            meter = parse_record("meter_id", EnergyMeter)
            if meter: require_department(meter.department)
            responsible = parse_user("responsible_user_id", "energy.view", "energy.project_manage")
            require_assignable_responsible(responsible, meter)
            approver = parse_user("approver_user_id", "energy.view", "energy.approve")
            if approver.id in {responsible.id, g.current_user.id}: raise ValueError("Proje sorumlusu veya kaydı oluşturan kişi doğrulayıcı olamaz.")
            title, description = request.form.get("title", "").strip(), request.form.get("description", "").strip()
            if not title or not description: raise ValueError("Proje adı ve açıklaması zorunludur.")
            start_date, due_date = parse_date("start_date"), parse_date("due_date")
            if due_date < start_date: raise ValueError("Hedef tarih başlangıç tarihinden önce olamaz.")
            row = existing or EnergySavingProject(company_id=company_id_required(), project_no=next_number(EnergySavingProject, "project_no", f"ENT-{date.today().year}-"), created_by_user_id=g.current_user.id)
            row.title=title; row.description=description; row.meter_id=meter.id if meter else None; row.planned_saving=parse_decimal("planned_saving", minimum="0.001"); row.investment_cost=parse_decimal("investment_cost", required=False, minimum=0); row.start_date=start_date; row.due_date=due_date; row.responsible_user_id=responsible.id; row.approver_user_id=approver.id; row.action_id=getattr(parse_record("action_id", Action), "id", None)
            db.session.add(row); db.session.commit(); notify(responsible.id, row.project_no, "Enerji tasarruf projesi size atandı.", url_for("energy.project_detail", project_id=row.id), due_date); flash("Tasarruf projesi oluşturuldu.", "success"); return redirect(url_for("energy.project_detail", project_id=row.id))
        except (ValueError, IntegrityError) as error:
            db.session.rollback(); flash(str(error), "danger")
    return render_template("energy/project_form.html", **project_form_context(existing))


@bp.route("/tasarruf/<int:project_id>/duzenle", methods=("GET", "POST"), endpoint="edit_project")
@login_required
def edit_project(project_id):
    return create_project(project_id)


@bp.get("/tasarruf/<int:project_id>")
@login_required
def project_detail(project_id):
    require_permission("energy.view", "energy.view_all", "energy.manage")
    row = get_project(project_id)
    owner = row.responsible_user_id == g.current_user.id or has_permission("energy.manage")
    reviewer = row.approver_user_id == g.current_user.id or has_permission("energy.manage")
    return render_template("energy/project_detail.html", project=row, can_edit=(has_permission("energy.project_manage") or has_permission("energy.manage")) and owner and row.status == "Planlandı", can_start=(has_permission("energy.project_manage") or has_permission("energy.manage")) and owner and row.status == "Planlandı", can_complete=(has_permission("energy.project_manage") or has_permission("energy.manage")) and owner and row.status == "Devam Ediyor", can_cancel=(has_permission("energy.project_manage") or has_permission("energy.manage")) and owner and row.status in {"Planlandı", "Devam Ediyor"}, can_verify=(has_permission("energy.approve") or has_permission("energy.manage")) and reviewer and row.status == "Doğrulama Bekliyor" and row.created_by_user_id != g.current_user.id, can_archive=(has_permission("energy.archive") or has_permission("energy.manage")) and row.status in {"Tamamlandı", "İptal"}, can_download=(has_permission("energy.file_download") or has_permission("energy.manage")) and bool(row.evidence_path), currency=settings())


@bp.post("/tasarruf/<int:project_id>/baslat")
@login_required
def start_project(project_id):
    require_permission("energy.project_manage", "energy.manage")
    row = get_project(project_id)
    if row.status != "Planlandı" or (row.responsible_user_id != g.current_user.id and not has_permission("energy.manage")): abort(403)
    row.status = "Devam Ediyor"; db.session.commit(); flash("Proje başlatıldı.", "success"); return redirect(url_for("energy.project_detail", project_id=row.id))


@bp.post("/tasarruf/<int:project_id>/tamamla")
@login_required
def complete_project(project_id):
    require_permission("energy.project_manage", "energy.manage")
    row = get_project(project_id)
    if row.status != "Devam Ediyor" or (row.responsible_user_id != g.current_user.id and not has_permission("energy.manage")): abort(403)
    evidence_path = None
    try:
        note = request.form.get("completion_note", "").strip()
        if not note: raise ValueError("Tamamlama açıklaması zorunludur.")
        row.actual_saving = parse_decimal("actual_saving", minimum=0); row.completion_note = note
        evidence = save_evidence(request.files.get("evidence_file"), "energy/projects", "tasarruf-kaniti")
        if not evidence: raise ValueError("Doğrulama için kanıt dosyası zorunludur.")
        row.evidence_name, row.evidence_path, row.evidence_hash, evidence_path = evidence
        row.status, row.completed_at = "Doğrulama Bekliyor", now_utc(); db.session.commit(); notify(row.approver_user_id, row.project_no, "Tasarruf sonucu doğrulamanızı bekliyor.", url_for("energy.project_detail", project_id=row.id), row.due_date); flash("Proje doğrulamaya gönderildi.", "success")
    except ValueError as error:
        db.session.rollback(); safe_remove(evidence_path); flash(str(error), "danger")
    return redirect(url_for("energy.project_detail", project_id=row.id))


@bp.post("/tasarruf/<int:project_id>/iptal")
@login_required
def cancel_project(project_id):
    require_permission("energy.project_manage", "energy.manage")
    row = get_project(project_id)
    if row.status not in {"Planlandı", "Devam Ediyor"} or (row.responsible_user_id != g.current_user.id and not has_permission("energy.manage")):
        abort(403)
    reason = request.form.get("reason", "").strip()
    if not reason:
        flash("İptal gerekçesi zorunludur.", "danger")
    else:
        row.status = "İptal"; row.completion_note = f"İptal gerekçesi: {reason}"; row.completed_at = now_utc(); db.session.commit(); flash("Proje gerekçesiyle iptal edildi.", "success")
    return redirect(url_for("energy.project_detail", project_id=row.id))


@bp.post("/tasarruf/<int:project_id>/dogrula")
@login_required
def verify_project(project_id):
    require_permission("energy.approve", "energy.manage")
    row = get_project(project_id)
    if row.status != "Doğrulama Bekliyor" or (row.approver_user_id != g.current_user.id and not has_permission("energy.manage")) or row.created_by_user_id == g.current_user.id: abort(403)
    decision, note = request.form.get("decision"), request.form.get("verification_note", "").strip()
    if decision not in {"approve", "reject"} or not note:
        flash("Karar ve doğrulama açıklaması zorunludur.", "danger")
    else:
        verification = EnergySavingVerification(
            company_id=row.company_id, project=row,
            version_no=max((item.version_no for item in row.verifications), default=0) + 1,
            actual_saving=row.actual_saving or 0,
            financial_saving=parse_decimal("financial_saving", required=False, minimum=0),
            decision="Onaylandı" if decision == "approve" else "Reddedildi",
            verification_note=note, evidence_name=row.evidence_name,
            evidence_path=row.evidence_path, evidence_hash=row.evidence_hash,
            verified_by_user_id=g.current_user.id,
        )
        db.session.add(verification)
        if decision == "reject":
            row.status = "Devam Ediyor"; row.completion_note = f"{row.completion_note or ''}\nDoğrulama reddi: {note}".strip()
        else:
            row.status, row.verified_at = "Tamamlandı", now_utc()
        db.session.commit()
        notify(row.responsible_user_id, row.project_no, "Tasarruf sonucu doğrulandı." if decision == "approve" else "Tasarruf doğrulaması revizyon için geri gönderildi.", url_for("energy.project_detail", project_id=row.id), kind="success" if decision == "approve" else "warning")
        flash("Tasarruf doğrulandı." if decision == "approve" else "Proje revizyona gönderildi.", "success")
    return redirect(url_for("energy.project_detail", project_id=row.id))


@bp.post("/tasarruf/<int:project_id>/arsivle")
@login_required
def archive_project(project_id):
    require_permission("energy.archive", "energy.manage")
    row = get_project(project_id)
    if row.status not in {"Tamamlandı", "İptal"}: abort(409)
    row.status, row.archived_at = "Arşiv", now_utc(); db.session.commit(); flash("Proje arşivlendi.", "success"); return redirect(url_for("energy.dashboard"))


@bp.get("/kanit/<kind>/<int:record_id>")
@login_required
def download_evidence(kind, record_id):
    require_permission("energy.file_download", "energy.manage")
    if kind == "reading":
        row = get_reading(record_id)
    elif kind == "project":
        row = get_project(record_id)
    elif kind == "verification":
        row = scoped_query(EnergySavingVerification.query, EnergySavingVerification).filter_by(id=record_id).first_or_404()
        get_project(row.project_id)
    else:
        abort(404)
    stored_path = row.evidence_path
    if not stored_path: abort(404)
    root = Path(current_app.config["UPLOAD_FOLDER"]).resolve(); path = (root / stored_path).resolve()
    try: path.relative_to(root)
    except ValueError: abort(404)
    if not path.is_file(): abort(404)
    record_audit_event(row.__class__.__name__, "downloaded", "Enerji kanıt dosyası indirildi", entity_id=row.id, details={"file_name": row.evidence_name})
    return send_file(path, as_attachment=True, download_name=row.evidence_name)


@bp.get("/rapor.xlsx")
@login_required
def export_excel():
    require_permission("energy.export", "energy.manage")
    from .routes import build_simple_xlsx
    rows = [("Tüketim", row.meter.meter_code, row.meter.name, row.meter.energy_type, row.period.strftime("%m.%Y"), str(row.consumption), row.meter.unit, str(row.normalized_consumption or ""), str(row.total_cost or ""), str(row.emission_kg), row.status) for row in reading_query().join(EnergyMeter).order_by(EnergyReading.period.desc()).all()]
    rows.extend(("Hedef", row.target_no, row.title, row.meter.energy_type if row.meter else "Şirket Geneli", row.target_date.strftime("%d.%m.%Y"), str(row.baseline_consumption), row.meter.unit if row.meter else "", f"%{row.reduction_percent}", "", str(row.actual_consumption or ""), row.status) for row in target_query().order_by(EnergyTarget.target_no).all())
    rows.extend(("Tasarruf Projesi", row.project_no, row.title, row.meter.energy_type if row.meter else "Şirket Geneli", row.due_date.strftime("%d.%m.%Y"), str(row.planned_saving), row.meter.unit if row.meter else "", str(row.actual_saving or ""), str(row.investment_cost or ""), "", row.status) for row in project_query().order_by(EnergySavingProject.project_no).all())
    workbook = build_simple_xlsx(("Kayıt Türü", "Kayıt No", "Ad", "Enerji Türü", "Dönem / Termin", "Tüketim / Plan", "Birim", "Yoğunluk / Gerçekleşen", f"Maliyet / Yatırım ({settings()})", "Emisyon / Sonuç", "Durum"), rows, sheet_name="Enerji Yönetimi")
    record_audit_event("EnergyReport", "exported", "Enerji tüketim raporu indirildi", details={"row_count": len(rows)})
    return send_file(workbook, as_attachment=True, download_name=f"enerji-tuketim-raporu-{date.today():%Y%m%d}.xlsx", mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


def assigned_task_rows(scope, row_builder):
    user_id, today = g.current_user.id, date.today(); results = []
    for row in visible_meters().filter_by(status="Aktif").all():
        if scope == "created" and row.created_by_user_id != user_id: continue
        due = date(today.year, today.month, min(row.reading_due_day, 28))
        exists = reading_query().filter(
            EnergyReading.meter_id == row.id,
            EnergyReading.period == today.replace(day=1),
            EnergyReading.is_current.is_(True),
            EnergyReading.status.in_(("Onay Bekliyor", "Onaylandı")),
        ).first()
        if scope != "created" and row.responsible_user_id == user_id and not exists and due <= today:
            results.append(row_builder(module_key="energy", module_label="Enerji", module_icon="lightning-charge", module_tone="warning", title=f"{row.meter_code} aylık okuma", description=row.name, reference_no=row.meter_code, department=row.department.name, due_date=due, status="Okuma Bekliyor", status_key="delayed" if due < today else "pending", priority="Orta", detail_url=url_for("energy.create_reading", meter_id=row.id), created_at=row.created_at, sort_id=row.id, date_label="Okuma Tarihi"))
    for row in reading_query().filter_by(status="Onay Bekliyor", is_current=True).all():
        if scope == "created" and row.entered_by_user_id != user_id: continue
        if scope != "created" and row.meter.reviewer_user_id != user_id: continue
        results.append(row_builder(module_key="energy", module_label="Enerji", module_icon="lightning-charge", module_tone="warning", title=f"{row.meter.meter_code} tüketim onayı", description=f"{row.period:%m.%Y} · {row.consumption} {row.meter.unit}", reference_no=row.meter.meter_code, department=row.meter.department.name, due_date=None, status=row.status, status_key="pending", priority="Orta", detail_url=url_for("energy.reading_detail", reading_id=row.id), created_at=row.created_at, sort_id=100000 + row.id))
    for row in visible_projects().filter(EnergySavingProject.status.in_(("Planlandı", "Devam Ediyor", "Doğrulama Bekliyor"))).all():
        if scope == "created" and row.created_by_user_id != user_id: continue
        if scope != "created" and user_id not in {row.responsible_user_id, row.approver_user_id}: continue
        results.append(row_builder(module_key="energy", module_label="Enerji", module_icon="lightning-charge", module_tone="success", title=row.title, description=f"Planlanan tasarruf: {row.planned_saving}", reference_no=row.project_no, department=row.meter.department.name if row.meter else "Tüm Şirket", due_date=row.due_date, status=row.status, status_key="delayed" if row.due_date < today else "pending", priority="Yüksek" if row.due_date < today else "Orta", detail_url=url_for("energy.project_detail", project_id=row.id), created_at=row.created_at, sort_id=200000 + row.id, date_label="Hedef Tarih"))
    for row in visible_targets().filter(EnergyTarget.status.in_(("Taslak", "Onay Bekliyor", "Aktif", "Tamamlama Onayı"))).all():
        if scope == "created" and row.created_by_user_id != user_id: continue
        if scope != "created" and user_id not in {row.responsible_user_id, row.approver_user_id}: continue
        results.append(row_builder(module_key="energy", module_label="Enerji", module_icon="bullseye", module_tone="success", title=row.title, description=f"Azaltım hedefi: %{row.reduction_percent}", reference_no=row.target_no, department=row.meter.department.name if row.meter else "Tüm Şirket", due_date=row.target_date, status=row.status, status_key="delayed" if row.target_date < today and row.status == "Aktif" else "pending", priority="Yüksek" if row.target_date < today else "Orta", detail_url=url_for("energy.target_detail", target_id=row.id), created_at=row.created_at, sort_id=300000 + row.id, date_label="Hedef Tarih"))
    return results
