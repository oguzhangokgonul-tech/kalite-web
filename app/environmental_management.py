from datetime import UTC, date, datetime, timedelta
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
    ComplianceObligation,
    EnvironmentalAspect,
    EnvironmentalAspectAssessment,
    EnvironmentalAspectFile,
    QualityObjective,
    RiskRecord,
    User,
    WasteBatch,
    WasteMovement,
    WasteMovementFile,
    WasteStream,
)
from .notifications import add_user_notification
from .tenant import current_company_id, scoped_query


bp = Blueprint("environmental", __name__, url_prefix="/cevre-yonetimi")

LIFECYCLE_STAGES = ("Hammadde", "Tasarım", "Üretim", "Depolama", "Sevkiyat", "Kullanım", "Ömür Sonu")
OPERATING_CONDITIONS = ("Normal", "Anormal", "Acil Durum")
INFLUENCE_TYPES = ("Doğrudan Kontrol", "Dolaylı Etki")
ASPECT_STATUSES = ("Taslak", "Revizyon Bekliyor", "Onay Bekliyor", "Aktif", "Arşiv")
WASTE_UNITS = ("kg", "L", "adet")
WASTE_BATCH_STATUSES = (
    "Geçici Depoda", "Sevk Bekliyor", "Taşıyıcıya Teslim", "Mutabakat Bekliyor",
    "Tamamlandı", "İptal", "Arşiv",
)
ALLOWED_EXTENSIONS = {"pdf", "doc", "docx", "xls", "xlsx", "jpg", "jpeg", "png"}
ALLOWED_MIME_PREFIXES = ("application/pdf", "application/msword", "application/vnd.", "image/")


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


def now_utc():
    return datetime.now(UTC).replace(tzinfo=None)


def matrix_settings():
    company_id = require_company_scope()
    version_row = db.session.get(AppSetting, f"environmental:matrix_version:{company_id}")
    threshold_row = db.session.get(AppSetting, f"environmental:significance_threshold:{company_id}")
    version = (version_row.value if version_row else "V1").strip() or "V1"
    try:
        threshold = int(threshold_row.value) if threshold_row else 40
    except (TypeError, ValueError):
        threshold = 40
    return version[:30], min(625, max(1, threshold))


def form_error_message(error):
    if isinstance(error, IntegrityError):
        return "Aynı kayıt numarası veya referans eşzamanlı olarak kullanıldı. Sayfayı yenileyip tekrar deneyin."
    return str(error)


def aspect_query():
    return scoped_query(EnvironmentalAspect.query, EnvironmentalAspect)


def stream_query():
    return scoped_query(WasteStream.query, WasteStream)


def batch_query():
    return scoped_query(WasteBatch.query, WasteBatch)


def active_users():
    return User.query.filter_by(company_id=current_company_id(), is_active=True).order_by(User.full_name).all()


def users_with_permissions(*permission_keys):
    return [
        user
        for user in active_users()
        if user.has_permission("environmental.manage")
        or all(user.has_permission(key) for key in permission_keys)
    ]


def active_departments():
    rows = CompanyDepartment.query.filter_by(company_id=current_company_id(), is_active=True).order_by(CompanyDepartment.sort_order, CompanyDepartment.name).all()
    user = getattr(g, "current_user", None)
    if user and not has_permission("environmental.manage") and (
        user.has_role("department_manager") or user.has_role("department_staff")
    ):
        from .dynamic_forms import user_matches_department

        return [row for row in rows if user_matches_department(user, row.name)]
    return rows


def parse_date(name, required=False):
    raw = request.form.get(name, "").strip()
    if not raw and not required:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise ValueError("Tarih alanlarından biri geçerli değil.") from None


def parse_int(name, *, minimum=None, maximum=None, required=True):
    raw = request.form.get(name, "").strip()
    if not raw and not required:
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ValueError("Sayısal alanlardan biri geçerli değil.") from None
    if minimum is not None and value < minimum or maximum is not None and value > maximum:
        raise ValueError(f"{name} alanı {minimum}-{maximum} aralığında olmalıdır.")
    return value


def parse_decimal(name, *, required=True, minimum=None):
    raw = request.form.get(name, "").strip().replace(",", ".")
    if not raw and not required:
        return None
    try:
        value = Decimal(raw).quantize(Decimal("0.001"))
    except (InvalidOperation, ValueError):
        raise ValueError("Miktar alanlarından biri geçerli değil.") from None
    if minimum is not None and value < Decimal(str(minimum)):
        raise ValueError(f"{name} alanı {minimum} değerinden küçük olamaz.")
    return value


def parse_company_record(name, model, required=False):
    raw = request.form.get(name, "").strip()
    if not raw and not required:
        return None
    try:
        record_id = int(raw)
    except (TypeError, ValueError):
        raise ValueError("Bağlantılı kayıt geçerli değil.") from None
    row = scoped_query(model.query, model).filter_by(id=record_id).first()
    if not row:
        raise ValueError("Bağlantılı kayıt bu şirkete ait değil.")
    return row


def parse_user(name, *required_permissions):
    row = parse_company_record(name, User, required=True)
    if not row.is_active:
        raise ValueError("Seçilen personel aktif değil.")
    if required_permissions and not (
        row.has_permission("environmental.manage")
        or all(row.has_permission(key) for key in required_permissions)
    ):
        raise ValueError("Seçilen personel bu iş akışı için gerekli yetkilere sahip değil.")
    return row


def require_department_scope(department):
    if not can_access_department(department):
        abort(403)


def can_access_department(department):
    user = getattr(g, "current_user", None)
    return user_can_access_department(user, department)


def user_can_access_department(user, department):
    if not user or user.has_permission("environmental.manage"):
        return True
    if user.has_role("department_manager") or user.has_role("department_staff"):
        from .dynamic_forms import user_matches_department

        return user_matches_department(user, department.name)
    return True


def next_number(model, field_name, prefix):
    values = scoped_query(model.query, model).with_entities(getattr(model, field_name)).filter(getattr(model, field_name).like(f"{prefix}%")).all()
    numbers = []
    for (value,) in values:
        try:
            numbers.append(int(value.rsplit("-", 1)[-1]))
        except (TypeError, ValueError):
            pass
    return f"{prefix}{max(numbers, default=0) + 1:04d}"


def next_aspect_no():
    return next_number(EnvironmentalAspect, "aspect_no", f"CEV-{date.today().year}-")


def next_batch_no():
    return next_number(WasteBatch, "batch_no", f"ATK-{date.today().year}-")


def notify(user_id, *, company_id, reference, message, source, target_url, due_date=None, kind="warning"):
    user = User.query.filter_by(id=user_id, company_id=company_id, is_active=True).first()
    if user:
        add_user_notification(
            user, f"{reference} - {message}", company_id=company_id,
            source_key=f"environmental:{source}:{user_id}", target_url=target_url,
            due_date=due_date, notification_type=kind,
        )


def calculate_scores(severity, frequency, legal_score, stakeholder_score, control_effectiveness):
    inherent = severity * frequency * max(legal_score, stakeholder_score)
    residual = round(inherent * (6 - control_effectiveness) / 5)
    return inherent, residual


def add_assessment(row):
    scores = [parse_int(name, minimum=1, maximum=5) for name in (
        "severity", "frequency", "legal_score", "stakeholder_score", "control_effectiveness"
    )]
    rationale = request.form.get("assessment_rationale", "").strip()
    if not rationale:
        raise ValueError("Değerlendirme gerekçesi zorunludur.")
    inherent, residual = calculate_scores(*scores)
    assessment = EnvironmentalAspectAssessment(
        company_id=row.company_id, aspect_record=row,
        version_no=max((item.version_no for item in row.assessments), default=0) + 1,
        matrix_version=row.matrix_version, significance_threshold=row.significance_threshold,
        lifecycle_stage=row.lifecycle_stage, operating_condition=row.operating_condition,
        influence_type=row.influence_type, controls_snapshot=row.existing_controls,
        severity=scores[0], frequency=scores[1],
        legal_score=scores[2], stakeholder_score=scores[3], control_effectiveness=scores[4],
        inherent_score=inherent, residual_score=residual,
        is_significant=residual >= row.significance_threshold,
        rationale=rationale, assessed_by_user_id=g.current_user.id,
    )
    db.session.add(assessment)
    return assessment


def aspect_activation_blockers(row):
    blockers = []
    assessment = row.current_assessment
    if not assessment:
        blockers.append("Etki değerlendirmesi bulunmuyor.")
        return blockers
    if assessment.is_significant and not (row.risk_id or row.action_id):
        blockers.append("Önemli çevresel boyut için bağlı risk veya aksiyon zorunludur.")
    if assessment.legal_score >= 4 and not row.compliance_obligation_id:
        blockers.append("Mevzuat puanı yüksek kayıt için yasal yükümlülük bağlantısı zorunludur.")
    if row.review_due_date < date.today():
        blockers.append("Gözden geçirme tarihi geçmiş bir değerlendirme aktifleştirilemez.")
    return blockers


def store_upload(upload, folder, *, model_factory):
    if not upload or not upload.filename:
        raise ValueError("Kanıt dosyası zorunludur.")
    extension = Path(upload.filename).suffix.lower().lstrip(".")
    if extension not in ALLOWED_EXTENSIONS or not any((upload.mimetype or "").startswith(prefix) for prefix in ALLOWED_MIME_PREFIXES):
        raise ValueError("Yalnızca PDF, Word, Excel veya görsel dosyası yüklenebilir.")
    from .routes import assert_company_storage_quota, safe_original_filename, upload_storage_path, uploaded_stream_size
    company_id = require_company_scope()
    original = safe_original_filename(upload.filename, "cevre-kaniti")
    relative, absolute = upload_storage_path(f"{uuid4().hex}.{extension}", folder, company_id)
    assert_company_storage_quota(company_id, uploaded_stream_size(upload))
    upload.save(absolute)
    row = model_factory(
        company_id=company_id, original_name=original,
        stored_path=str(relative).replace("\\", "/"), mime_type=upload.mimetype,
        file_size=absolute.stat().st_size, sha256_hash=hashlib.sha256(absolute.read_bytes()).hexdigest(),
        uploaded_by_user_id=g.current_user.id,
    )
    db.session.add(row)
    return absolute


def safe_remove(paths):
    for path in paths:
        if path:
            path.unlink(missing_ok=True)


def can_view_aspect(row):
    return row.status == "Aktif" or has_permission("environmental.view_all") or has_permission("environmental.manage") or g.current_user.id in {row.responsible_user_id, row.reviewer_user_id, row.created_by_user_id}


def get_aspect(aspect_id):
    row = aspect_query().filter_by(id=aspect_id).first_or_404()
    if not can_view_aspect(row):
        abort(404)
    return row


def get_stream(stream_id):
    row = stream_query().filter_by(id=stream_id).first_or_404()
    require_department_scope(row.department)
    return row


def get_batch(batch_id):
    row = batch_query().filter_by(id=batch_id).first_or_404()
    require_department_scope(row.stream.department)
    return row


def aspect_form_context(row=None):
    company_id = current_company_id()
    matrix_version, significance_threshold = matrix_settings()
    return dict(
        aspect_record=row, values=request.form,
        responsible_users=users_with_permissions("environmental.view", "environmental.update", "environmental.assess"),
        reviewer_users=users_with_permissions("environmental.view", "environmental.approve"),
        departments=active_departments(),
        lifecycle_stages=LIFECYCLE_STAGES, operating_conditions=OPERATING_CONDITIONS,
        influence_types=INFLUENCE_TYPES,
        matrix_version=matrix_version, significance_threshold=significance_threshold,
        risks=scoped_query(RiskRecord.query, RiskRecord).order_by(RiskRecord.risk_no).all() if company_id else [],
        actions=scoped_query(Action.query, Action).filter(Action.is_completed.is_(False)).order_by(Action.id.desc()).all() if company_id else [],
        obligations=scoped_query(ComplianceObligation.query, ComplianceObligation).order_by(ComplianceObligation.obligation_no).all() if company_id else [],
        objectives=scoped_query(QualityObjective.query, QualityObjective).order_by(QualityObjective.objective_no).all() if company_id else [],
    )


def populate_aspect(row):
    required = {"process": "Süreç", "activity": "Faaliyet", "aspect": "Çevresel boyut", "impact": "Çevresel etki", "existing_controls": "Mevcut kontroller"}
    values = {key: request.form.get(key, "").strip() for key in required}
    missing = [label for key, label in required.items() if not values[key]]
    if missing:
        raise ValueError(f"Zorunlu alanları doldurun: {', '.join(missing)}.")
    department = parse_company_record("department_id", CompanyDepartment, required=True)
    require_department_scope(department)
    responsible = parse_user("responsible_user_id", "environmental.view", "environmental.update", "environmental.assess")
    reviewer = parse_user("reviewer_user_id", "environmental.view", "environmental.approve")
    if reviewer.id in {row.created_by_user_id, responsible.id}:
        raise ValueError("Kaydı hazırlayan veya sorumlu kişi kendi değerlendirmesini onaylayamaz.")
    lifecycle = request.form.get("lifecycle_stage", "")
    condition = request.form.get("operating_condition", "")
    influence = request.form.get("influence_type", "")
    if lifecycle not in LIFECYCLE_STAGES or condition not in OPERATING_CONDITIONS or influence not in INFLUENCE_TYPES:
        raise ValueError("Çevresel sınıflandırma alanlarından biri geçerli değil.")
    row.department_id = department.id
    row.process, row.activity, row.aspect, row.impact = values["process"], values["activity"], values["aspect"], values["impact"]
    row.existing_controls = values["existing_controls"]
    row.emergency_response = request.form.get("emergency_response", "").strip() or None
    row.lifecycle_stage, row.operating_condition, row.influence_type = lifecycle, condition, influence
    row.matrix_version, row.significance_threshold = matrix_settings()
    row.responsible_user_id, row.reviewer_user_id = responsible.id, reviewer.id
    row.review_due_date = parse_date("review_due_date", required=True)
    row.risk_id = getattr(parse_company_record("risk_id", RiskRecord), "id", None)
    row.action_id = getattr(parse_company_record("action_id", Action), "id", None)
    row.compliance_obligation_id = getattr(parse_company_record("compliance_obligation_id", ComplianceObligation), "id", None)
    row.quality_objective_id = getattr(parse_company_record("quality_objective_id", QualityObjective), "id", None)


@bp.before_request
def guard():
    checker = getattr(g, "company_module_enabled", None)
    if checker and not checker("environmental_management"):
        abort(404)


@bp.get("")
@login_required
def dashboard():
    require_permission("environmental.view", "environmental.view_all", "environmental.manage")
    search = request.args.get("q", "").strip()
    can_view_archive = has_permission("environmental.view_all") or has_permission("environmental.manage")
    show_archive = can_view_archive and request.args.get("archive") == "1"
    aspect_rows = aspect_query()
    waste_rows = batch_query()
    stream_rows = stream_query()
    if not show_archive:
        aspect_rows = aspect_rows.filter(EnvironmentalAspect.status != "Arşiv")
        waste_rows = waste_rows.filter(WasteBatch.status != "Arşiv")
        stream_rows = stream_rows.filter(WasteStream.status != "Arşiv")
    if search:
        term = f"%{search}%"
        aspect_rows = aspect_rows.filter(or_(EnvironmentalAspect.aspect_no.ilike(term), EnvironmentalAspect.aspect.ilike(term), EnvironmentalAspect.impact.ilike(term)))
        waste_rows = waste_rows.join(WasteStream).filter(or_(WasteBatch.batch_no.ilike(term), WasteStream.waste_code.ilike(term), WasteStream.name.ilike(term)))
        stream_rows = stream_rows.filter(or_(WasteStream.waste_code.ilike(term), WasteStream.name.ilike(term), WasteStream.source_process.ilike(term)))
    aspects = [row for row in aspect_rows.order_by(EnvironmentalAspect.review_due_date).all() if can_view_aspect(row)]
    batches = [row for row in waste_rows.order_by(WasteBatch.storage_due_date).all() if can_access_department(row.stream.department)]
    streams = [row for row in stream_rows.order_by(WasteStream.waste_code).all() if can_access_department(row.department)]
    today = date.today()
    return render_template(
        "environmental/dashboard.html", aspects=aspects, batches=batches, streams=streams,
        stream_open_counts={row.id: sum(batch.status not in {"Tamamlandı", "İptal", "Arşiv"} for batch in row.batches) for row in streams},
        search=search, today=today, show_archive=show_archive, can_view_archive=can_view_archive,
        summary={
            "significant": sum(bool(row.current_assessment and row.current_assessment.is_significant) for row in aspects),
            "overdue_reviews": sum(row.status == "Aktif" and row.review_due_date < today for row in aspects),
            "stored_waste": sum(row.status in {"Geçici Depoda", "Sevk Bekliyor"} for row in batches),
            "overdue_waste": sum(row.status not in {"Tamamlandı", "İptal", "Arşiv"} and row.storage_due_date < today for row in batches),
        },
        can_create=has_permission("environmental.create") or has_permission("environmental.manage"),
        can_manage_waste=has_permission("environmental.waste_manage") or has_permission("environmental.manage"),
        can_export=has_permission("environmental.export") or has_permission("environmental.manage"),
        can_manage=has_permission("environmental.manage"),
    )


@bp.route("/parametreler", methods=["GET", "POST"])
@login_required
def parameters():
    require_permission("environmental.manage")
    company_id = require_company_scope()
    if request.method == "POST":
        version = request.form.get("matrix_version", "").strip()
        if not version or len(version) > 30:
            flash("Matris sürümü 1-30 karakter olmalıdır.", "danger")
            return redirect(url_for("environmental.parameters"))
        try:
            threshold = parse_int("significance_threshold", minimum=1, maximum=625)
        except ValueError as error:
            flash(str(error), "danger")
            return redirect(url_for("environmental.parameters"))
        values = {
            f"environmental:matrix_version:{company_id}": version,
            f"environmental:significance_threshold:{company_id}": str(threshold),
        }
        for key, value in values.items():
            row = db.session.get(AppSetting, key)
            if row is None:
                db.session.add(AppSetting(key=key, value=value))
            else:
                row.value = value
        db.session.commit()
        flash("Şirket çevre puanlama parametreleri güncellendi.", "success")
        return redirect(url_for("environmental.parameters"))
    version, threshold = matrix_settings()
    return render_template("environmental/parameters.html", matrix_version=version, significance_threshold=threshold)


@bp.route("/boyut/yeni", methods=["GET", "POST"])
@login_required
def create_aspect():
    require_permission("environmental.create", "environmental.manage")
    company_id = require_company_scope()
    if request.method == "POST":
        stored = []
        row = EnvironmentalAspect(company_id=company_id, aspect_no=next_aspect_no(), created_by_user_id=g.current_user.id)
        try:
            populate_aspect(row)
            db.session.add(row)
            db.session.flush()
            add_assessment(row)
            upload = request.files.get("evidence_file")
            if upload and upload.filename:
                stored.append(store_upload(upload, "environmental/aspects", model_factory=lambda **kwargs: EnvironmentalAspectFile(aspect_record=row, **kwargs)))
            db.session.commit()
            notify(row.responsible_user_id, company_id=company_id, reference=row.aspect_no, message="Çevresel boyut kaydını incelemeye hazırlayın.", source=f"aspect-created:{row.id}", target_url=url_for("environmental.aspect_detail", aspect_id=row.id), due_date=row.review_due_date)
            db.session.commit()
            flash(f"{row.aspect_no} çevresel boyut kaydı oluşturuldu.", "success")
            return redirect(url_for("environmental.aspect_detail", aspect_id=row.id))
        except (ValueError, IntegrityError) as error:
            db.session.rollback(); safe_remove(stored); flash(form_error_message(error), "danger")
    return render_template("environmental/aspect_form.html", **aspect_form_context())


@bp.route("/boyut/<int:aspect_id>/duzenle", methods=["GET", "POST"])
@login_required
def edit_aspect(aspect_id):
    require_permission("environmental.update", "environmental.manage")
    row = get_aspect(aspect_id)
    if row.status not in {"Taslak", "Revizyon Bekliyor"} or (row.responsible_user_id != g.current_user.id and not has_permission("environmental.manage")):
        abort(403)
    if request.method == "POST":
        stored = []
        try:
            populate_aspect(row)
            add_assessment(row)
            upload = request.files.get("evidence_file")
            if upload and upload.filename:
                stored.append(store_upload(upload, "environmental/aspects", model_factory=lambda **kwargs: EnvironmentalAspectFile(aspect_record=row, **kwargs)))
            db.session.commit(); flash("Çevresel boyut kaydı güncellendi.", "success")
            return redirect(url_for("environmental.aspect_detail", aspect_id=row.id))
        except (ValueError, IntegrityError) as error:
            db.session.rollback(); safe_remove(stored); flash(form_error_message(error), "danger")
    return render_template("environmental/aspect_form.html", **aspect_form_context(row))


@bp.get("/boyut/<int:aspect_id>")
@login_required
def aspect_detail(aspect_id):
    require_permission("environmental.view", "environmental.view_all", "environmental.manage")
    row = get_aspect(aspect_id)
    return render_template(
        "environmental/aspect_detail.html", aspect_record=row,
        today=date.today(),
        activation_blockers=aspect_activation_blockers(row),
        can_edit=(has_permission("environmental.update") or has_permission("environmental.manage")) and row.status in {"Taslak", "Revizyon Bekliyor"} and (row.responsible_user_id == g.current_user.id or has_permission("environmental.manage")),
        can_submit=(has_permission("environmental.update") or has_permission("environmental.manage")) and row.status in {"Taslak", "Revizyon Bekliyor"} and (row.responsible_user_id == g.current_user.id or has_permission("environmental.manage")),
        can_assess=(has_permission("environmental.assess") or has_permission("environmental.manage")) and row.status == "Aktif" and (row.responsible_user_id == g.current_user.id or has_permission("environmental.manage")),
        can_review=(has_permission("environmental.approve") or has_permission("environmental.manage")) and row.status == "Onay Bekliyor" and (row.reviewer_user_id == g.current_user.id or has_permission("environmental.manage")) and row.created_by_user_id != g.current_user.id,
        can_archive=(has_permission("environmental.archive") or has_permission("environmental.manage")) and row.status == "Aktif",
        can_download=has_permission("environmental.file_download") or has_permission("environmental.manage"),
    )


@bp.post("/boyut/<int:aspect_id>/onaya-gonder")
@login_required
def submit_aspect(aspect_id):
    require_permission("environmental.update", "environmental.manage")
    row = get_aspect(aspect_id); require_company_scope()
    if (row.responsible_user_id != g.current_user.id and not has_permission("environmental.manage")) or row.status not in {"Taslak", "Revizyon Bekliyor"}:
        abort(403)
    blockers = aspect_activation_blockers(row)
    if blockers:
        flash(" ".join(blockers), "danger")
        return redirect(url_for("environmental.aspect_detail", aspect_id=row.id))
    row.status, row.submitted_at = "Onay Bekliyor", now_utc()
    notify(row.reviewer_user_id, company_id=row.company_id, reference=row.aspect_no, message="Çevresel boyut değerlendirmesi onayınızı bekliyor.", source=f"aspect-review:{row.id}:{row.submitted_at.timestamp()}", target_url=url_for("environmental.aspect_detail", aspect_id=row.id), due_date=row.review_due_date)
    db.session.commit(); flash("Değerlendirme onaya gönderildi.", "success")
    return redirect(url_for("environmental.aspect_detail", aspect_id=row.id))


@bp.post("/boyut/<int:aspect_id>/yeniden-degerlendir")
@login_required
def reassess_aspect(aspect_id):
    require_permission("environmental.assess", "environmental.manage")
    row = get_aspect(aspect_id); require_company_scope()
    if row.status != "Aktif" or (row.responsible_user_id != g.current_user.id and not has_permission("environmental.manage")):
        abort(403)
    try:
        row.matrix_version, row.significance_threshold = matrix_settings()
        add_assessment(row)
        row.status, row.submitted_at = "Onay Bekliyor", now_utc()
        row.review_due_date = parse_date("review_due_date", required=True)
        notify(row.reviewer_user_id, company_id=row.company_id, reference=row.aspect_no, message="Yeni çevresel etki değerlendirmesi onayınızı bekliyor.", source=f"aspect-reassessment:{row.id}:{row.submitted_at.timestamp()}", target_url=url_for("environmental.aspect_detail", aspect_id=row.id), due_date=row.review_due_date)
        db.session.commit(); flash("Yeni değerlendirme sürümü onaya gönderildi.", "success")
    except (ValueError, IntegrityError) as error:
        db.session.rollback(); flash(form_error_message(error), "danger")
    return redirect(url_for("environmental.aspect_detail", aspect_id=row.id))


@bp.post("/boyut/<int:aspect_id>/degerlendir")
@login_required
def review_aspect(aspect_id):
    require_permission("environmental.approve", "environmental.manage")
    row = get_aspect(aspect_id); require_company_scope()
    if row.status != "Onay Bekliyor" or (row.reviewer_user_id != g.current_user.id and not has_permission("environmental.manage")) or row.created_by_user_id == g.current_user.id:
        abort(403)
    decision, note = request.form.get("decision", ""), request.form.get("note", "").strip()
    assessment = row.current_assessment
    if decision == "approve":
        blockers = aspect_activation_blockers(row)
        if blockers:
            flash(" ".join(blockers), "danger")
            return redirect(url_for("environmental.aspect_detail", aspect_id=row.id))
        row.status, row.approved_at, row.approved_by_user_id = "Aktif", now_utc(), g.current_user.id
        row.review_note = note or None
        assessment.review_status, assessment.reviewed_by_user_id = "Onaylandı", g.current_user.id
        assessment.reviewed_at, assessment.review_note = row.approved_at, note or None
    elif decision == "revision" and note:
        row.status, row.review_note = "Revizyon Bekliyor", note
        assessment.review_status, assessment.reviewed_by_user_id = "Revizyon", g.current_user.id
        assessment.reviewed_at, assessment.review_note = now_utc(), note
    else:
        flash("Revizyon gerekçesi zorunludur.", "danger")
        return redirect(url_for("environmental.aspect_detail", aspect_id=row.id))
    notify(row.responsible_user_id, company_id=row.company_id, reference=row.aspect_no, message="Çevresel boyut değerlendirme kararı kaydedildi.", source=f"aspect-decision:{row.id}:{now_utc().timestamp()}", target_url=url_for("environmental.aspect_detail", aspect_id=row.id), due_date=row.review_due_date, kind="info")
    db.session.commit(); flash("Değerlendirme kararı kaydedildi.", "success")
    return redirect(url_for("environmental.aspect_detail", aspect_id=row.id))


@bp.post("/boyut/<int:aspect_id>/arsivle")
@login_required
def archive_aspect(aspect_id):
    require_permission("environmental.archive", "environmental.manage")
    row = get_aspect(aspect_id); require_company_scope()
    if row.status != "Aktif" or any(stream.status == "Aktif" for stream in row.waste_streams):
        abort(409)
    row.status, row.archived_at = "Arşiv", now_utc(); db.session.commit()
    flash("Çevresel boyut geçmişi korunarak arşivlendi.", "success")
    return redirect(url_for("environmental.dashboard"))


@bp.route("/atik-akisi/yeni", methods=["GET", "POST"])
@login_required
def create_stream():
    require_permission("environmental.waste_manage", "environmental.manage")
    company_id = require_company_scope()
    if request.method == "POST":
        try:
            code, name = request.form.get("waste_code", "").strip(), request.form.get("name", "").strip()
            if not code or not name or stream_query().filter_by(waste_code=code).first():
                raise ValueError("Atık kodu ve adı zorunlu; kod şirket içinde benzersiz olmalıdır.")
            department = parse_company_record("department_id", CompanyDepartment, required=True)
            require_department_scope(department)
            responsible = parse_user("responsible_user_id", "environmental.view", "environmental.waste_manage")
            if not user_can_access_department(responsible, department):
                raise ValueError("Atık sorumlusu seçilen departmanda işlem yapabilmelidir.")
            unit = request.form.get("unit", "")
            if unit not in WASTE_UNITS:
                raise ValueError("Atık birimi geçerli değil.")
            source, location = request.form.get("source_process", "").strip(), request.form.get("storage_location", "").strip()
            if not source or not location:
                raise ValueError("Kaynak süreç ve geçici depolama alanı zorunludur.")
            row = WasteStream(
                company_id=company_id, waste_code=code, name=name,
                is_hazardous=request.form.get("is_hazardous") == "1", department_id=department.id,
                source_process=source, storage_location=location, unit=unit,
                maximum_capacity=parse_decimal("maximum_capacity", required=False, minimum=0),
                maximum_storage_days=parse_int("maximum_storage_days", minimum=1, maximum=3650),
                responsible_user_id=responsible.id, created_by_user_id=g.current_user.id,
                aspect_id=getattr(parse_company_record("aspect_id", EnvironmentalAspect), "id", None),
                compliance_obligation_id=getattr(parse_company_record("compliance_obligation_id", ComplianceObligation), "id", None),
            )
            db.session.add(row); db.session.commit(); flash("Atık akışı tanımlandı.", "success")
            return redirect(url_for("environmental.stream_detail", stream_id=row.id))
        except (ValueError, IntegrityError) as error:
            db.session.rollback(); flash(form_error_message(error), "danger")
    return render_template("environmental/stream_form.html", values=request.form, departments=active_departments(), users=users_with_permissions("environmental.view", "environmental.waste_manage"), units=WASTE_UNITS, aspects=aspect_query().filter_by(status="Aktif").all(), obligations=scoped_query(ComplianceObligation.query, ComplianceObligation).all())


@bp.get("/atik-akisi/<int:stream_id>")
@login_required
def stream_detail(stream_id):
    require_permission("environmental.view", "environmental.view_all", "environmental.manage")
    row = get_stream(stream_id)
    require_department_scope(row.department)
    open_total = sum((batch.remaining_quantity for batch in row.batches if batch.status not in {"Tamamlandı", "İptal", "Arşiv"}), Decimal("0"))
    return render_template(
        "environmental/stream_detail.html", stream=row, open_total=open_total,
        can_create_batch=(has_permission("environmental.create") or has_permission("environmental.waste_manage") or has_permission("environmental.manage")) and row.status == "Aktif",
        can_archive=(has_permission("environmental.archive") or has_permission("environmental.manage")) and row.status == "Aktif" and not any(batch.status not in {"Tamamlandı", "İptal", "Arşiv"} for batch in row.batches),
        users=users_with_permissions("environmental.view", "environmental.approve"), today=date.today(),
    )


@bp.post("/atik-akisi/<int:stream_id>/parti")
@login_required
def create_batch(stream_id):
    require_permission("environmental.create", "environmental.waste_manage", "environmental.manage")
    row = get_stream(stream_id); company_id = require_company_scope()
    require_department_scope(row.department)
    if row.status != "Aktif":
        abort(409)
    try:
        generated = parse_date("generated_date", required=True)
        if generated > date.today():
            raise ValueError("Atık oluşum tarihi gelecekte olamaz.")
        quantity = parse_decimal("quantity", minimum=Decimal("0.001"))
        container_count = parse_int("container_count", minimum=1, maximum=100000, required=False)
        reviewer = parse_user("reviewer_user_id", "environmental.view", "environmental.approve")
        if reviewer.id == g.current_user.id:
            raise ValueError("Atık kaydını oluşturan kişi nihai kabul doğrulamasını yapamaz.")
        current_total = sum((batch.remaining_quantity for batch in row.batches if batch.status not in {"Tamamlandı", "İptal", "Arşiv"}), Decimal("0"))
        if row.maximum_capacity is not None and current_total + quantity > row.maximum_capacity:
            raise ValueError("Bu kayıt geçici depo kapasitesini aşıyor.")
        batch = WasteBatch(
            company_id=company_id, batch_no=next_batch_no(), stream=row, generated_date=generated,
            storage_due_date=generated + timedelta(days=row.maximum_storage_days),
            initial_quantity=quantity, remaining_quantity=quantity, container_count=container_count,
            storage_location=row.storage_location, responsible_user_id=row.responsible_user_id,
            reviewer_user_id=reviewer.id, created_by_user_id=g.current_user.id,
        )
        db.session.add(batch); db.session.flush()
        db.session.add(WasteMovement(company_id=company_id, batch=batch, movement_type="Oluşum", quantity=quantity, balance_after=quantity, location=batch.storage_location, note=request.form.get("note", "").strip() or "İlk atık oluşum kaydı", performed_by_user_id=g.current_user.id))
        db.session.commit(); flash(f"{batch.batch_no} atık partisi oluşturuldu.", "success")
        return redirect(url_for("environmental.batch_detail", batch_id=batch.id))
    except (ValueError, IntegrityError) as error:
        db.session.rollback(); flash(form_error_message(error), "danger")
        return redirect(url_for("environmental.stream_detail", stream_id=row.id))


@bp.get("/atik/<int:batch_id>")
@login_required
def batch_detail(batch_id):
    require_permission("environmental.view", "environmental.view_all", "environmental.manage")
    row = get_batch(batch_id)
    can_move = has_permission("environmental.waste_manage") or has_permission("environmental.shipment") or has_permission("environmental.manage")
    return render_template(
        "environmental/batch_detail.html", batch=row, today=date.today(),
        can_move=can_move and row.status in {"Geçici Depoda", "Sevk Bekliyor"},
        can_ship=can_move and row.status == "Sevk Bekliyor",
        can_accept=(has_permission("environmental.approve") or has_permission("environmental.manage")) and row.status == "Taşıyıcıya Teslim" and (row.reviewer_user_id == g.current_user.id or has_permission("environmental.manage")) and row.created_by_user_id != g.current_user.id,
        can_reconcile=(has_permission("environmental.approve") or has_permission("environmental.manage")) and row.status == "Mutabakat Bekliyor" and (row.reviewer_user_id == g.current_user.id or has_permission("environmental.manage")) and row.created_by_user_id != g.current_user.id,
        can_cancel=(has_permission("environmental.archive") or has_permission("environmental.manage")) and row.status in {"Geçici Depoda", "Sevk Bekliyor"},
        can_archive=(has_permission("environmental.archive") or has_permission("environmental.manage")) and row.status in {"Tamamlandı", "İptal"},
        can_download=has_permission("environmental.file_download") or has_permission("environmental.manage"),
    )


@bp.post("/atik/<int:batch_id>/transfer")
@login_required
def transfer_batch(batch_id):
    require_permission("environmental.waste_manage", "environmental.shipment", "environmental.manage")
    row = get_batch(batch_id); require_company_scope()
    location, note = request.form.get("location", "").strip(), request.form.get("note", "").strip()
    if row.status != "Geçici Depoda" or not location or not note:
        abort(409)
    row.storage_location = location
    db.session.add(WasteMovement(company_id=row.company_id, batch=row, movement_type="Depo Transferi", quantity=0, balance_after=row.remaining_quantity, location=location, note=note, performed_by_user_id=g.current_user.id))
    db.session.commit(); flash("Depo transferi kaydedildi.", "success")
    return redirect(url_for("environmental.batch_detail", batch_id=row.id))


@bp.post("/atik/<int:batch_id>/sevke-hazirla")
@login_required
def prepare_shipment(batch_id):
    require_permission("environmental.waste_manage", "environmental.shipment", "environmental.manage")
    row = get_batch(batch_id); require_company_scope()
    if row.status != "Geçici Depoda" or row.remaining_quantity <= 0:
        abort(409)
    row.status = "Sevk Bekliyor"
    db.session.add(WasteMovement(company_id=row.company_id, batch=row, movement_type="Sevke Hazır", quantity=0, balance_after=row.remaining_quantity, location=row.storage_location, note=request.form.get("note", "").strip() or "Sevk hazırlığı tamamlandı", performed_by_user_id=g.current_user.id))
    db.session.commit(); flash("Atık partisi sevke hazırlandı.", "success")
    return redirect(url_for("environmental.batch_detail", batch_id=row.id))


@bp.post("/atik/<int:batch_id>/teslim")
@login_required
def ship_batch(batch_id):
    require_permission("environmental.shipment", "environmental.manage")
    row = get_batch(batch_id); require_company_scope(); stored = []
    if row.status != "Sevk Bekliyor":
        abort(409)
    try:
        required = {key: request.form.get(key, "").strip() for key in ("carrier_name", "carrier_license_no", "receiving_facility", "facility_license_no", "motat_reference")}
        if any(not value for value in required.values()):
            raise ValueError("Taşıyıcı, lisanslı tesis ve MOTAT referans bilgileri zorunludur.")
        if batch_query().filter(WasteBatch.id != row.id, WasteBatch.motat_reference == required["motat_reference"]).first():
            raise ValueError("Bu MOTAT referansı başka bir atık partisinde kullanılıyor.")
        quantity = parse_decimal("quantity", minimum=Decimal("0.001"))
        if quantity != row.remaining_quantity:
            raise ValueError("Parti izlenebilirliği için sevk miktarı kalan miktara eşit olmalıdır.")
        movement = WasteMovement(company_id=row.company_id, batch=row, movement_type="Taşıyıcıya Teslim", quantity=-quantity, balance_after=0, location=required["receiving_facility"], note=request.form.get("note", "").strip() or "Lisanslı taşıyıcıya teslim", performed_by_user_id=g.current_user.id)
        db.session.add(movement); db.session.flush()
        stored.append(store_upload(request.files.get("evidence_file"), "environmental/waste", model_factory=lambda **kwargs: WasteMovementFile(movement=movement, document_type="Taşıma / Teslim", **kwargs)))
        row.carrier_name, row.carrier_license_no = required["carrier_name"], required["carrier_license_no"]
        row.receiving_facility, row.facility_license_no = required["receiving_facility"], required["facility_license_no"]
        row.motat_reference, row.abs_declaration_no = required["motat_reference"], request.form.get("abs_declaration_no", "").strip() or None
        row.shipped_quantity, row.remaining_quantity, row.status = quantity, Decimal("0"), "Taşıyıcıya Teslim"
        notify(row.reviewer_user_id, company_id=row.company_id, reference=row.batch_no, message="Tesis kabulü ve tartım doğrulaması bekliyor.", source=f"waste-accept:{row.id}", target_url=url_for("environmental.batch_detail", batch_id=row.id), due_date=row.storage_due_date)
        db.session.commit(); flash("Taşıma ve teslim kaydı oluşturuldu.", "success")
    except (ValueError, IntegrityError) as error:
        db.session.rollback(); safe_remove(stored); flash(form_error_message(error), "danger")
    return redirect(url_for("environmental.batch_detail", batch_id=row.id))


@bp.post("/atik/<int:batch_id>/tesis-kabulu")
@login_required
def accept_batch(batch_id):
    require_permission("environmental.approve", "environmental.manage")
    row = get_batch(batch_id); require_company_scope(); stored = []
    if row.status != "Taşıyıcıya Teslim" or (row.reviewer_user_id != g.current_user.id and not has_permission("environmental.manage")) or row.created_by_user_id == g.current_user.id:
        abort(403)
    try:
        accepted = parse_decimal("accepted_quantity", minimum=Decimal("0.001"))
        movement = WasteMovement(company_id=row.company_id, batch=row, movement_type="Tesiste Kabul", quantity=0, balance_after=0, measured_quantity=accepted, location=row.receiving_facility, note=request.form.get("note", "").strip() or "Tesis tartım ve kabul kaydı", performed_by_user_id=g.current_user.id)
        db.session.add(movement); db.session.flush()
        stored.append(store_upload(request.files.get("evidence_file"), "environmental/waste", model_factory=lambda **kwargs: WasteMovementFile(movement=movement, document_type="Tesis Kabul / Tartım", **kwargs)))
        row.accepted_quantity = accepted
        if abs(accepted - row.shipped_quantity) > Decimal("0.001"):
            row.status = "Mutabakat Bekliyor"
            row.review_note = "Sevk ve tesis kabul miktarı arasında fark var."
        else:
            row.status, row.completed_at = "Tamamlandı", now_utc()
        db.session.commit(); flash("Tesis kabulü kaydedildi." if row.status == "Tamamlandı" else "Miktar farkı nedeniyle mutabakat gerekiyor.", "success" if row.status == "Tamamlandı" else "warning")
    except ValueError as error:
        db.session.rollback(); safe_remove(stored); flash(str(error), "danger")
    return redirect(url_for("environmental.batch_detail", batch_id=row.id))


@bp.post("/atik/<int:batch_id>/mutabakat")
@login_required
def reconcile_batch(batch_id):
    require_permission("environmental.approve", "environmental.manage")
    row = get_batch(batch_id); require_company_scope(); stored = []
    if row.status != "Mutabakat Bekliyor" or (row.reviewer_user_id != g.current_user.id and not has_permission("environmental.manage")) or row.created_by_user_id == g.current_user.id:
        abort(403)
    note = request.form.get("note", "").strip()
    if not note:
        flash("Miktar farkı açıklaması zorunludur.", "danger")
        return redirect(url_for("environmental.batch_detail", batch_id=row.id))
    try:
        movement = WasteMovement(company_id=row.company_id, batch=row, movement_type="Miktar Mutabakatı", quantity=0, balance_after=0, measured_quantity=row.accepted_quantity, location=row.receiving_facility, note=note, performed_by_user_id=g.current_user.id)
        db.session.add(movement); db.session.flush()
        stored.append(store_upload(request.files.get("evidence_file"), "environmental/waste", model_factory=lambda **kwargs: WasteMovementFile(movement=movement, document_type="Mutabakat", **kwargs)))
        row.status, row.review_note, row.completed_at = "Tamamlandı", note, now_utc()
        db.session.commit(); flash("Miktar farkı mutabakatla kapatıldı.", "success")
    except ValueError as error:
        db.session.rollback(); safe_remove(stored); flash(str(error), "danger")
    return redirect(url_for("environmental.batch_detail", batch_id=row.id))


@bp.post("/atik/<int:batch_id>/iptal")
@login_required
def cancel_batch(batch_id):
    require_permission("environmental.archive", "environmental.manage")
    row = get_batch(batch_id); require_company_scope()
    if row.status not in {"Geçici Depoda", "Sevk Bekliyor"}:
        abort(409)
    reason = request.form.get("reason", "").strip()
    if not reason:
        flash("İptal gerekçesi zorunludur.", "danger")
        return redirect(url_for("environmental.batch_detail", batch_id=row.id))
    row.status, row.review_note, row.completed_at = "İptal", reason, now_utc()
    db.session.add(WasteMovement(
        company_id=row.company_id, batch=row, movement_type="İptal",
        quantity=0, balance_after=row.remaining_quantity, location=row.storage_location,
        note=reason, performed_by_user_id=g.current_user.id,
    ))
    db.session.commit()
    flash("Atık partisi gerekçesi ve miktar izi korunarak iptal edildi.", "success")
    return redirect(url_for("environmental.batch_detail", batch_id=row.id))


@bp.post("/atik/<int:batch_id>/arsivle")
@login_required
def archive_batch(batch_id):
    require_permission("environmental.archive", "environmental.manage")
    row = get_batch(batch_id); require_company_scope()
    if row.status not in {"Tamamlandı", "İptal"}:
        abort(409)
    row.status, row.archived_at = "Arşiv", now_utc(); db.session.commit()
    flash("Atık partisi geçmişi korunarak arşivlendi.", "success")
    return redirect(url_for("environmental.dashboard"))


@bp.post("/atik-akisi/<int:stream_id>/arsivle")
@login_required
def archive_stream(stream_id):
    require_permission("environmental.archive", "environmental.manage")
    row = get_stream(stream_id); require_company_scope()
    if any(batch.status not in {"Tamamlandı", "İptal", "Arşiv"} for batch in row.batches):
        abort(409)
    row.status, row.archived_at = "Arşiv", now_utc(); db.session.commit()
    flash("Atık akışı arşivlendi.", "success")
    return redirect(url_for("environmental.dashboard"))


@bp.get("/boyut-dosya/<int:file_id>")
@bp.get("/atik-dosya/<int:waste_file_id>")
@login_required
def download_file(file_id=None, waste_file_id=None):
    require_permission("environmental.file_download", "environmental.manage")
    if file_id is not None:
        file_row = scoped_query(EnvironmentalAspectFile.query, EnvironmentalAspectFile).filter_by(id=file_id).first_or_404()
        if not can_view_aspect(file_row.aspect_record):
            abort(404)
        reference = file_row.aspect_record.aspect_no
    else:
        file_row = scoped_query(WasteMovementFile.query, WasteMovementFile).filter_by(id=waste_file_id).first_or_404()
        require_department_scope(file_row.movement.batch.stream.department)
        reference = file_row.movement.batch.batch_no
    root = Path(current_app.config["UPLOAD_FOLDER"]).resolve()
    path = (root / file_row.stored_path).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        abort(404)
    if not path.is_file():
        abort(404)
    record_audit_event(
        file_row.__class__.__name__, "downloaded", f"{reference} kanıtı indirildi",
        entity_id=file_row.id, details={"reference": reference, "file_name": file_row.original_name},
    )
    return send_file(path, as_attachment=True, download_name=file_row.original_name)


@bp.get("/rapor.xlsx")
@login_required
def export_excel():
    require_permission("environmental.export", "environmental.manage")
    from .routes import build_simple_xlsx
    rows = []
    for row in aspect_query().order_by(EnvironmentalAspect.aspect_no).all():
        assessment = row.current_assessment
        rows.append(("Çevresel Boyut", row.aspect_no, row.aspect, row.impact, row.department.name, row.status, assessment.residual_score if assessment else "", "puan", row.review_due_date.strftime("%d.%m.%Y")))
    for row in batch_query().join(WasteStream).order_by(WasteBatch.batch_no).all():
        rows.append(("Atık Partisi", row.batch_no, row.stream.waste_code, row.stream.name, row.stream.department.name, row.status, str(row.initial_quantity), row.stream.unit, row.storage_due_date.strftime("%d.%m.%Y")))
    workbook = build_simple_xlsx(("Kayıt Türü", "Kayıt No", "Kod / Boyut", "Etki / Atık", "Departman", "Durum", "Değer", "Birim", "Termin"), rows, sheet_name="Çevre ve Atık")
    record_audit_event("EnvironmentalReport", "exported", "Çevre ve atık Excel raporu indirildi", details={"row_count": len(rows)})
    return send_file(workbook, as_attachment=True, download_name=f"cevre-atik-raporu-{date.today():%Y%m%d}.xlsx", mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


def assigned_task_rows(scope, row_builder):
    user_id, today = g.current_user.id, date.today()
    results = []
    aspects = aspect_query().filter(EnvironmentalAspect.status.notin_(("Arşiv",))).all()
    for row in aspects:
        if scope == "created" and row.created_by_user_id != user_id:
            continue
        if scope != "created":
            pending = row.reviewer_user_id == user_id and row.status == "Onay Bekliyor"
            owner_due = row.responsible_user_id == user_id and (row.status in {"Taslak", "Revizyon Bekliyor"} or row.review_due_date <= today)
            if not (pending or owner_due):
                continue
        results.append(row_builder(module_key="environmental", module_label="Çevre ve Atık", module_icon="recycle", module_tone="success", title=row.aspect, description=row.impact, reference_no=row.aspect_no, department=row.department.name, due_date=row.review_due_date, status=row.status, status_key="delayed" if row.review_due_date < today else "pending", priority="Yüksek" if row.current_assessment and row.current_assessment.is_significant else "Orta", detail_url=url_for("environmental.aspect_detail", aspect_id=row.id), created_at=row.created_at, sort_id=row.id, date_label="Gözden Geçirme"))
    batches = batch_query().filter(WasteBatch.status.notin_(("Tamamlandı", "İptal", "Arşiv"))).all()
    for row in batches:
        if scope == "created" and row.created_by_user_id != user_id:
            continue
        if scope != "created" and user_id not in {row.responsible_user_id, row.reviewer_user_id}:
            continue
        results.append(row_builder(module_key="environmental", module_label="Çevre ve Atık", module_icon="recycle", module_tone="warning", title=row.stream.name, description=f"{row.stream.waste_code} · {row.remaining_quantity} {row.stream.unit}", reference_no=row.batch_no, department=row.stream.department.name, due_date=row.storage_due_date, status=row.status, status_key="delayed" if row.storage_due_date < today else "pending", priority="Yüksek" if row.stream.is_hazardous else "Orta", detail_url=url_for("environmental.batch_detail", batch_id=row.id), created_at=row.created_at, sort_id=100000 + row.id, date_label="Azami Depolama"))
    return results
