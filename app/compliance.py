from datetime import date, datetime
from functools import wraps
import hashlib
from pathlib import Path
import re
from uuid import uuid4

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    g,
    redirect,
    render_template,
    request,
    send_file,
    send_from_directory,
    url_for,
)
from sqlalchemy import event, inspect as sa_inspect, or_
from sqlalchemy.exc import IntegrityError

from .audit import record_audit_event
from .extensions import db
from .models import (
    Action,
    AppSetting,
    CompanyDepartment,
    ComplianceEvaluation,
    ComplianceFile,
    ComplianceObligation,
    ComplianceRevision,
    COMPLIANCE_EVALUATION_OUTCOMES,
    COMPLIANCE_OBLIGATION_STATUSES,
    COMPLIANCE_REVISION_STATUSES,
    Document,
    Notification,
    RiskRecord,
    User,
)
from .notifications import add_user_notification
from .tenant import current_company_id, scoped_query


bp = Blueprint("compliance", __name__, url_prefix="/mevzuat-takibi")

LEGAL_NOTICE = (
    "Bu modül hukuki danışmanlık sunmaz. Mevzuatın güncelliği ve kuruluşa "
    "uygulanabilirliği yetkili kullanıcı tarafından resmî kaynaktan doğrulanmalıdır."
)
OBLIGATION_STATUS_LABELS = {
    "draft": "Taslak",
    "verification_pending": "Doğrulama Bekliyor",
    "active": "Aktif",
    "repealed": "Yürürlükten Kalktı",
    "archived": "Arşiv",
}
REVISION_STATUS_LABELS = {
    "draft": "Taslak",
    "verification_pending": "Doğrulama Bekliyor",
    "returned": "Düzeltme Bekliyor",
    "verified": "Doğrulandı",
    "superseded": "Eski Sürüm",
}
EVALUATION_LABELS = {
    "not_assessed": "Değerlendirilmedi",
    "compliant": "Uygun",
    "partial": "Kısmen Uygun",
    "noncompliant": "Uygun Değil",
    "not_applicable": "Uygulanamaz",
}
APPLICABILITY_LABELS = {
    "applicable": "Uygulanabilir",
    "not_applicable": "Uygulanamaz",
    "under_review": "İnceleniyor",
}
CRITICALITY_LABELS = {"low": "Düşük", "medium": "Orta", "high": "Yüksek", "critical": "Kritik"}
OBLIGATION_TYPES = (
    "Kanun",
    "Yönetmelik",
    "Tebliğ",
    "Standart",
    "Ruhsat / İzin",
    "Sözleşmesel Şart",
    "Diğer",
)
CATEGORIES = (
    "Kalite",
    "İş Sağlığı ve Güvenliği",
    "Çevre",
    "Ürün Güvenliği",
    "İnsan Kaynakları",
    "Mali / Vergi",
    "Bilgi Güvenliği",
    "Sektörel",
    "Diğer",
)
ALLOWED_EXTENSIONS = {
    "pdf", "doc", "docx", "xls", "xlsx", "csv", "txt", "jpg", "jpeg", "png"
}


@event.listens_for(ComplianceRevision, "before_update")
def prevent_verified_revision_mutation(_mapper, _connection, target):
    state = sa_inspect(target)
    history = state.attrs.status.history
    previous = history.deleted[0] if history.deleted else target.status
    changed = {attr.key for attr in state.attrs if attr.history.has_changes()}
    if previous in {"verified", "superseded"}:
        if previous == "verified" and target.status == "superseded" and changed <= {"status", "updated_at"}:
            return
        raise ValueError("Doğrulanmış mevzuat sürümü değiştirilemez; yeni revizyon açın.")


@event.listens_for(ComplianceRevision, "before_delete")
def prevent_revision_delete(_mapper, _connection, target):
    if target.status in {"verified", "superseded"}:
        raise ValueError("Doğrulanmış mevzuat sürümü silinemez.")


@event.listens_for(ComplianceEvaluation, "before_update")
@event.listens_for(ComplianceEvaluation, "before_delete")
def prevent_evaluation_mutation(_mapper, _connection, _target):
    raise ValueError("Mevzuat uygunluk değerlendirme geçmişi değiştirilemez.")


def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if getattr(g, "current_user", None) is None:
            return redirect(url_for("main.login", next=request.full_path))
        return view(*args, **kwargs)

    return wrapped_view


def has_permission(permission_key):
    user = getattr(g, "current_user", None)
    return bool(user and user.has_permission(permission_key))


def require_permission(*permission_keys):
    if not any(has_permission(key) for key in permission_keys):
        abort(403)


def module_enabled():
    checker = getattr(g, "company_module_enabled", None)
    return checker("compliance_management") if checker else True


def obligation_query():
    return scoped_query(ComplianceObligation.query, ComplianceObligation)


def revision_query():
    return scoped_query(ComplianceRevision.query, ComplianceRevision)


def evaluation_query():
    return scoped_query(ComplianceEvaluation.query, ComplianceEvaluation)


def file_query():
    return scoped_query(ComplianceFile.query, ComplianceFile)


def can_access_all_obligations():
    user = getattr(g, "current_user", None)
    return bool(
        user
        and (
            has_permission("compliance.manage")
            or has_permission("compliance.verify")
            or has_permission("compliance.archive")
            or user.has_role("management")
        )
    )


def user_matches_department(department):
    from .dynamic_forms import user_matches_department as matches

    return matches(g.current_user, department)


def can_access_obligation(obligation):
    user = getattr(g, "current_user", None)
    if user is None:
        return False
    if can_access_all_obligations() or obligation.owner_user_id == user.id:
        return True
    if user.has_role("department_manager"):
        return user_matches_department(obligation.department)
    return bool(
        has_permission("compliance.view")
        and not user.has_role("department_staff")
        and obligation.status in {"active", "repealed"}
    )


def can_evaluate_obligation(obligation):
    user = getattr(g, "current_user", None)
    if user is None or not has_permission("compliance.evaluate"):
        return False
    if can_access_all_obligations() or obligation.owner_user_id == user.id:
        return True
    return bool(
        user.has_role("department_manager")
        and user_matches_department(obligation.department)
    )


def visible_obligation_query():
    query = obligation_query()
    user = g.current_user
    if can_access_all_obligations():
        return query
    if user.has_role("department_manager"):
        departments = [
            department
            for (department,) in query.with_entities(ComplianceObligation.department)
            .distinct()
            .all()
            if user_matches_department(department)
        ]
        return query.filter(
            or_(
                ComplianceObligation.owner_user_id == user.id,
                ComplianceObligation.department.in_(departments),
            )
        )
    if user.has_role("department_staff"):
        return query.filter(ComplianceObligation.owner_user_id == user.id)
    return query.filter(ComplianceObligation.status.in_(("active", "repealed")))


def get_obligation_or_404(obligation_id):
    obligation = obligation_query().filter_by(id=obligation_id).first_or_404()
    if not can_access_obligation(obligation):
        abort(403)
    return obligation


def get_revision_or_404(revision_id):
    return revision_query().filter_by(id=revision_id).first_or_404()


def parse_date(value, *, required=False):
    value = str(value or "").strip()
    if not value:
        if required:
            raise ValueError("Tarih alanı zorunludur.")
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ValueError("Geçerli bir tarih girin.") from error


def parse_int(value, label, minimum, maximum):
    try:
        parsed = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label} {minimum}-{maximum} arasında olmalıdır.") from error
    if parsed < minimum or parsed > maximum:
        raise ValueError(f"{label} {minimum}-{maximum} arasında olmalıdır.")
    return parsed


def active_users():
    return (
        User.query.filter_by(company_id=current_company_id(), is_active=True)
        .order_by(User.full_name.asc(), User.id.asc())
        .all()
    )


def eligible_owners():
    return [
        user
        for user in active_users()
        if user.has_permission("compliance.evaluate")
        and (
            user.has_permission("compliance.view")
            or user.has_permission("compliance.manage")
        )
    ]


def active_departments():
    return [
        row.name
        for row in CompanyDepartment.query.filter_by(
            company_id=current_company_id(), is_active=True
        ).order_by(CompanyDepartment.sort_order.asc(), CompanyDepartment.name.asc()).all()
    ]


def valid_user(user_id):
    user = next((item for item in eligible_owners() if item.id == user_id), None)
    if user is None:
        raise ValueError("Mevzuat görüntüleme ve değerlendirme yetkisi olan aktif bir sorumlu seçin.")
    return user


def accessible_related_records(model):
    rows = scoped_query(model.query, model).all()
    user = g.current_user
    if can_access_all_obligations():
        return rows
    if model is Document:
        if not (
            has_permission("documents.view")
            or has_permission("documents.manage")
        ):
            return []
        if user.has_role("department_manager"):
            return [
                row
                for row in rows
                if not row.department
                or row.department == "Tüm Departmanlar"
                or user_matches_department(row.department)
            ]
        return rows
    if model is RiskRecord:
        return [
            row
            for row in rows
            if row.owner_user_id == user.id
            or row.created_by_user_id == user.id
            or (
                user.has_role("department_manager")
                and user_matches_department(row.department)
            )
        ]
    if model is Action:
        return [
            row
            for row in rows
            if user.id
            in {
                row.responsible_user_id,
                row.related_user_1_id,
                row.related_user_2_id,
            }
            or (
                user.has_role("department_manager")
                and user_matches_department(row.department)
            )
        ]
    return []


def valid_related(model, record_id, message):
    if not record_id:
        return None
    row = next(
        (item for item in accessible_related_records(model) if item.id == record_id),
        None,
    )
    if row is None:
        raise ValueError(message)
    return row


def reserve_obligation_no():
    prefix = f"MEV-{date.today().year}-"
    numbers = []
    for (value,) in obligation_query().with_entities(ComplianceObligation.obligation_no).filter(
        ComplianceObligation.obligation_no.like(f"{prefix}%")
    ).all():
        match = re.fullmatch(rf"{re.escape(prefix)}(\d+)", value or "")
        if match:
            numbers.append(int(match.group(1)))
    return f"{prefix}{max(numbers, default=0) + 1:04d}"


def parse_obligation_form():
    title = (request.form.get("title") or "").strip()[:240]
    category = (request.form.get("category") or "").strip()[:100]
    obligation_type = (request.form.get("obligation_type") or "").strip()[:80]
    department = (request.form.get("department") or "").strip()[:160]
    if not all((title, category, obligation_type, department)):
        raise ValueError("Başlık, kategori, yükümlülük türü ve departman zorunludur.")
    applicability = (request.form.get("applicability_status") or "").strip()
    criticality = (request.form.get("criticality") or "").strip()
    if applicability not in APPLICABILITY_LABELS:
        raise ValueError("Geçerli bir uygulanabilirlik durumu seçin.")
    if criticality not in CRITICALITY_LABELS:
        raise ValueError("Geçerli bir kritiklik seçin.")
    owner = valid_user(request.form.get("owner_user_id", type=int))
    return {
        "title": title,
        "category": category,
        "authority": (request.form.get("authority") or "").strip()[:180] or None,
        "region": (request.form.get("region") or "").strip()[:100] or None,
        "obligation_type": obligation_type,
        "legal_reference": (request.form.get("legal_reference") or "").strip()[:255] or None,
        "applicability_status": applicability,
        "applicability_reason": (request.form.get("applicability_reason") or "").strip()[:10000] or None,
        "department": department,
        "process": (request.form.get("process") or "").strip()[:160] or None,
        "owner_user_id": owner.id,
        "criticality": criticality,
        "review_interval_months": parse_int(
            request.form.get("review_interval_months"), "İnceleme periyodu", 1, 60
        ),
        "next_review_date": parse_date(request.form.get("next_review_date"), required=True),
    }


def parse_revision_form():
    revision_no = (request.form.get("revision_no") or "").strip()[:40]
    source_url = (request.form.get("official_source_url") or "").strip()[:1000]
    summary = (request.form.get("change_summary") or "").strip()[:10000]
    if not revision_no or not source_url or not summary:
        raise ValueError("Revizyon no, resmî kaynak bağlantısı ve değişiklik özeti zorunludur.")
    if not source_url.lower().startswith(("https://", "http://")):
        raise ValueError("Resmî kaynak bağlantısı http:// veya https:// ile başlamalıdır.")
    return {
        "revision_no": revision_no,
        "publication_date": parse_date(request.form.get("publication_date")),
        "effective_date": parse_date(request.form.get("effective_date")),
        "repeal_date": parse_date(request.form.get("repeal_date")),
        "official_source_url": source_url,
        "change_summary": summary,
    }


def form_context(obligation=None, values=None):
    return {
        "obligation": obligation,
        "values": values or {},
        "users": eligible_owners(),
        "departments": active_departments(),
        "categories": CATEGORIES,
        "types": OBLIGATION_TYPES,
        "applicability_labels": APPLICABILITY_LABELS,
        "criticality_labels": CRITICALITY_LABELS,
        "legal_notice": LEGAL_NOTICE,
    }


def revision_form_context(obligation, values=None):
    return {"obligation": obligation, "values": values or {}, "legal_notice": LEGAL_NOTICE}


def evaluation_form_context(obligation, revision, values=None):
    return {
        "obligation": obligation,
        "revision": revision,
        "values": values or {},
        "outcome_labels": EVALUATION_LABELS,
        "risks": sorted(
            accessible_related_records(RiskRecord),
            key=lambda item: (item.risk_no or "", item.id),
        ),
        "actions": sorted(
            accessible_related_records(Action), key=lambda item: item.id, reverse=True
        ),
        "documents": sorted(
            accessible_related_records(Document),
            key=lambda item: (item.document_code or "", item.id),
        ),
        "legal_notice": LEGAL_NOTICE,
    }


def store_file(uploaded_file, *, company_id, folder, kind, revision=None, evaluation=None):
    if not uploaded_file or not uploaded_file.filename:
        return None
    extension = Path(uploaded_file.filename).suffix.lower().lstrip(".")
    if extension not in ALLOWED_EXTENSIONS:
        raise ValueError("PDF, Word, Excel, CSV, metin veya görsel dosyası yükleyin.")
    from .routes import (
        assert_company_storage_quota,
        safe_original_filename,
        upload_storage_path,
        uploaded_stream_size,
    )

    original_name = safe_original_filename(uploaded_file.filename, "mevzuat-kaniti")
    stored_name = f"{uuid4().hex}.{extension}"
    relative_path, absolute_path = upload_storage_path(stored_name, folder, company_id)
    assert_company_storage_quota(company_id, uploaded_stream_size(uploaded_file))
    uploaded_file.save(absolute_path)
    max_bytes = current_app.config.get("MAX_CONTENT_LENGTH") or 25 * 1024 * 1024
    size = absolute_path.stat().st_size
    if size > max_bytes:
        absolute_path.unlink(missing_ok=True)
        raise ValueError("Dosya izin verilen boyutu aşıyor.")
    try:
        assert_company_storage_quota(company_id)
    except ValueError:
        absolute_path.unlink(missing_ok=True)
        raise
    digest = hashlib.sha256(absolute_path.read_bytes()).hexdigest()
    row = ComplianceFile(
        company_id=company_id,
        revision_id=revision.id if revision else None,
        evaluation_id=evaluation.id if evaluation else None,
        file_kind=kind,
        original_name=original_name,
        stored_path=str(relative_path).replace("\\", "/"),
        mime_type=uploaded_file.mimetype,
        file_size=size,
        sha256_hash=digest,
        uploaded_by_user_id=g.current_user.id,
    )
    db.session.add(row)
    return row


def notify_verifiers(obligation, revision):
    for user in active_users():
        if user.id != revision.created_by_user_id and user.has_permission("compliance.verify"):
            add_user_notification(
                user,
                f"{obligation.obligation_no} mevzuat revizyonu doğrulamanızı bekliyor.",
                company_id=obligation.company_id,
                notification_type="warning",
                source_key=f"compliance-verification:{revision.id}",
                target_url=url_for("compliance.detail", obligation_id=obligation.id),
            )


def notify_owner(obligation):
    add_user_notification(
        obligation.owner,
        f"{obligation.obligation_no} mevzuat yükümlülüğü size atandı.",
        company_id=obligation.company_id,
        notification_type="info",
        source_key=f"compliance-owner:{obligation.id}",
        target_url=url_for("compliance.detail", obligation_id=obligation.id),
        due_date=obligation.next_review_date,
    )


def mark_readiness_complete():
    key = "sales_readiness:competitor_compliance_obligations"
    setting = db.session.get(AppSetting, key)
    if setting is None:
        db.session.add(AppSetting(key=key, value="1"))
    else:
        setting.value = "1"


@bp.before_request
@login_required
def before_request():
    if not module_enabled():
        abort(404)


@bp.get("")
def dashboard():
    require_permission("compliance.view", "compliance.manage", "compliance.verify", "compliance.evaluate")
    query = visible_obligation_query()
    search = (request.args.get("search") or "").strip()
    status = (request.args.get("status") or "").strip()
    department = (request.args.get("department") or "").strip()
    if search:
        term = f"%{search}%"
        query = query.filter(or_(
            ComplianceObligation.obligation_no.ilike(term),
            ComplianceObligation.title.ilike(term),
            ComplianceObligation.legal_reference.ilike(term),
            ComplianceObligation.authority.ilike(term),
        ))
    if status in COMPLIANCE_OBLIGATION_STATUSES:
        query = query.filter_by(status=status)
    if department:
        query = query.filter_by(department=department)
    records = query.order_by(ComplianceObligation.next_review_date.asc(), ComplianceObligation.id.desc()).all()
    return render_template(
        "compliance/dashboard.html",
        records=records,
        filters={"search": search, "status": status, "department": department},
        departments=active_departments(),
        status_labels=OBLIGATION_STATUS_LABELS,
        evaluation_labels=EVALUATION_LABELS,
        criticality_labels=CRITICALITY_LABELS,
        can_manage=has_permission("compliance.manage"),
        can_export=has_permission("compliance.export") or has_permission("compliance.manage"),
        legal_notice=LEGAL_NOTICE,
        today=date.today(),
    )


@bp.route("/yeni", methods=("GET", "POST"))
def create_obligation():
    require_permission("compliance.manage")
    if request.method == "POST":
        try:
            values = parse_obligation_form()
            revision_values = parse_revision_form()
            obligation = ComplianceObligation(
                company_id=current_company_id(),
                obligation_no=reserve_obligation_no(),
                status="verification_pending",
                created_by_user_id=g.current_user.id,
                **values,
            )
            db.session.add(obligation)
            db.session.flush()
            revision = ComplianceRevision(
                company_id=obligation.company_id,
                obligation_id=obligation.id,
                status="verification_pending",
                created_by_user_id=g.current_user.id,
                **revision_values,
            )
            db.session.add(revision)
            db.session.flush()
            store_file(
                request.files.get("source_file"), company_id=obligation.company_id,
                folder="compliance/sources", kind="source", revision=revision,
            )
            notify_owner(obligation)
            notify_verifiers(obligation, revision)
            record_audit_event(
                "ComplianceObligation", "compliance_created",
                f"{obligation.obligation_no} mevzuat yükümlülüğü oluşturuldu",
                entity_id=obligation.id, commit=False,
            )
            db.session.commit()
            flash("Mevzuat yükümlülüğü oluşturuldu ve doğrulamaya gönderildi.", "success")
            return redirect(url_for("compliance.detail", obligation_id=obligation.id))
        except IntegrityError:
            db.session.rollback()
            flash("Kayıt veya revizyon numarası çakıştı. Lütfen tekrar deneyin.", "danger")
        except ValueError as error:
            db.session.rollback()
            flash(str(error), "danger")
    return render_template("compliance/form.html", **form_context(values=request.form))


@bp.route("/<int:obligation_id>/duzenle", methods=("GET", "POST"))
def edit_obligation(obligation_id):
    require_permission("compliance.manage")
    obligation = get_obligation_or_404(obligation_id)
    if obligation.status in {"active", "repealed", "archived"}:
        abort(409)
    if request.method == "POST":
        try:
            old_owner = obligation.owner_user_id
            for key, value in parse_obligation_form().items():
                setattr(obligation, key, value)
            if old_owner != obligation.owner_user_id:
                notify_owner(obligation)
            record_audit_event(
                "ComplianceObligation", "compliance_updated",
                f"{obligation.obligation_no} mevzuat yükümlülüğü güncellendi",
                entity_id=obligation.id, commit=False,
            )
            db.session.commit()
            flash("Mevzuat yükümlülüğü güncellendi.", "success")
            return redirect(url_for("compliance.detail", obligation_id=obligation.id))
        except ValueError as error:
            db.session.rollback()
            flash(str(error), "danger")
    return render_template("compliance/form.html", **form_context(obligation, request.form))


@bp.get("/<int:obligation_id>")
def detail(obligation_id):
    require_permission("compliance.view", "compliance.manage", "compliance.verify", "compliance.evaluate")
    obligation = get_obligation_or_404(obligation_id)
    return render_template(
        "compliance/detail.html", obligation=obligation,
        status_labels=OBLIGATION_STATUS_LABELS,
        revision_status_labels=REVISION_STATUS_LABELS,
        evaluation_labels=EVALUATION_LABELS,
        applicability_labels=APPLICABILITY_LABELS,
        criticality_labels=CRITICALITY_LABELS,
        can_manage=has_permission("compliance.manage"),
        can_verify=has_permission("compliance.verify"),
        can_evaluate=can_evaluate_obligation(obligation),
        can_archive=has_permission("compliance.archive") or has_permission("compliance.manage"),
        can_download=has_permission("compliance.evidence_download") or has_permission("compliance.manage"),
        legal_notice=LEGAL_NOTICE,
    )


@bp.route("/<int:obligation_id>/revizyon", methods=("GET", "POST"))
def create_revision(obligation_id):
    require_permission("compliance.manage")
    obligation = get_obligation_or_404(obligation_id)
    if obligation.status not in {"active", "repealed"} or obligation.pending_revision:
        abort(409)
    if request.method == "POST":
        try:
            revision = ComplianceRevision(
                company_id=obligation.company_id,
                obligation_id=obligation.id,
                status="verification_pending",
                created_by_user_id=g.current_user.id,
                **parse_revision_form(),
            )
            db.session.add(revision)
            db.session.flush()
            store_file(
                request.files.get("source_file"), company_id=obligation.company_id,
                folder="compliance/sources", kind="source", revision=revision,
            )
            notify_verifiers(obligation, revision)
            record_audit_event(
                "ComplianceRevision", "compliance_revision_submitted",
                f"{obligation.obligation_no} için {revision.revision_no} revizyonu doğrulamaya gönderildi",
                entity_id=revision.id, commit=False,
            )
            db.session.commit()
            flash("Yeni revizyon doğrulamaya gönderildi.", "success")
            return redirect(url_for("compliance.detail", obligation_id=obligation.id))
        except (IntegrityError, ValueError) as error:
            db.session.rollback()
            flash("Revizyon numarası daha önce kullanılmış." if isinstance(error, IntegrityError) else str(error), "danger")
    return render_template("compliance/revision_form.html", **revision_form_context(obligation, request.form))


@bp.route("/revizyon/<int:revision_id>/duzenle", methods=("GET", "POST"))
def edit_revision(revision_id):
    require_permission("compliance.manage")
    revision = get_revision_or_404(revision_id)
    obligation = revision.obligation
    if revision.status != "returned":
        abort(409)
    if request.method == "POST":
        try:
            for key, value in parse_revision_form().items():
                setattr(revision, key, value)
            store_file(
                request.files.get("source_file"),
                company_id=obligation.company_id,
                folder="compliance/sources",
                kind="source",
                revision=revision,
            )
            revision.status = "verification_pending"
            revision.verification_note = None
            notify_verifiers(obligation, revision)
            record_audit_event(
                "ComplianceRevision",
                "compliance_revision_resubmitted",
                f"{obligation.obligation_no} {revision.revision_no} revizyonu yeniden doğrulamaya gönderildi",
                entity_id=revision.id,
                commit=False,
            )
            db.session.commit()
            flash("Revizyon güncellendi ve yeniden doğrulamaya gönderildi.", "success")
            return redirect(url_for("compliance.detail", obligation_id=obligation.id))
        except (IntegrityError, ValueError) as error:
            db.session.rollback()
            flash(
                "Revizyon numarası daha önce kullanılmış."
                if isinstance(error, IntegrityError)
                else str(error),
                "danger",
            )
    values = {
        "revision_no": revision.revision_no,
        "publication_date": revision.publication_date.isoformat() if revision.publication_date else "",
        "effective_date": revision.effective_date.isoformat() if revision.effective_date else "",
        "repeal_date": revision.repeal_date.isoformat() if revision.repeal_date else "",
        "official_source_url": revision.official_source_url,
        "change_summary": revision.change_summary,
    }
    if request.method == "POST":
        values.update(request.form)
    return render_template(
        "compliance/revision_form.html",
        **revision_form_context(obligation, values),
        revision=revision,
    )


@bp.post("/revizyon/<int:revision_id>/duzeltmeye-gonder")
def return_revision(revision_id):
    require_permission("compliance.verify")
    revision = get_revision_or_404(revision_id)
    obligation = revision.obligation
    if revision.status != "verification_pending":
        abort(409)
    if revision.created_by_user_id == g.current_user.id:
        abort(403)
    reason = (request.form.get("reason") or "").strip()[:2000]
    if not reason:
        flash("Düzeltme gerekçesi zorunludur.", "danger")
        return redirect(url_for("compliance.detail", obligation_id=obligation.id))
    revision.status = "returned"
    revision.verification_note = reason
    Notification.query.filter_by(
        company_id=obligation.company_id,
        source_key=f"compliance-verification:{revision.id}",
    ).update({Notification.is_read: True}, synchronize_session=False)
    if revision.created_by:
        add_user_notification(
            revision.created_by,
            f"{obligation.obligation_no} {revision.revision_no} revizyonu düzeltmeye gönderildi: {reason}",
            company_id=obligation.company_id,
            notification_type="warning",
            source_key=f"compliance-returned:{revision.id}:{datetime.now().timestamp()}",
            target_url=url_for("compliance.detail", obligation_id=obligation.id),
        )
    record_audit_event(
        "ComplianceRevision",
        "compliance_revision_returned",
        f"{obligation.obligation_no} {revision.revision_no} revizyonu düzeltmeye gönderildi",
        entity_id=revision.id,
        details={"reason": reason},
        commit=False,
    )
    db.session.commit()
    flash("Revizyon düzeltme için kaydı oluşturan kullanıcıya gönderildi.", "success")
    return redirect(url_for("compliance.detail", obligation_id=obligation.id))


@bp.post("/revizyon/<int:revision_id>/dogrula")
def verify_revision(revision_id):
    require_permission("compliance.verify")
    revision = get_revision_or_404(revision_id)
    obligation = revision.obligation
    if revision.status != "verification_pending":
        abort(409)
    if revision.created_by_user_id == g.current_user.id:
        abort(403)
    for item in obligation.revisions:
        if item.id != revision.id and item.status == "verified":
            item.status = "superseded"
    revision.status = "verified"
    revision.verified_by_user_id = g.current_user.id
    revision.verified_at = datetime.now()
    revision.verification_note = None
    obligation.status = "repealed" if revision.repeal_date and revision.repeal_date <= date.today() else "active"
    obligation.activated_at = obligation.activated_at or datetime.now()
    mark_readiness_complete()
    Notification.query.filter_by(
        company_id=obligation.company_id, source_key=f"compliance-verification:{revision.id}"
    ).update({Notification.is_read: True}, synchronize_session=False)
    notify_owner(obligation)
    record_audit_event(
        "ComplianceRevision", "compliance_revision_verified",
        f"{obligation.obligation_no} {revision.revision_no} revizyonu doğrulandı",
        entity_id=revision.id, commit=False,
    )
    db.session.commit()
    flash("Mevzuat revizyonu doğrulandı ve kayıt aktifleştirildi.", "success")
    return redirect(url_for("compliance.detail", obligation_id=obligation.id))


@bp.route("/<int:obligation_id>/degerlendir", methods=("GET", "POST"))
def evaluate(obligation_id):
    obligation = get_obligation_or_404(obligation_id)
    if not can_evaluate_obligation(obligation):
        abort(403)
    revision = obligation.latest_verified_revision
    if obligation.status != "active" or revision is None:
        abort(409)
    if request.method == "POST":
        try:
            outcome = (request.form.get("outcome") or "").strip()
            summary = (request.form.get("summary") or "").strip()[:10000]
            improvement_plan = (request.form.get("improvement_plan") or "").strip()[:10000] or None
            if outcome not in COMPLIANCE_EVALUATION_OUTCOMES or outcome == "not_assessed" or not summary:
                raise ValueError("Değerlendirme sonucu ve özeti zorunludur.")
            risk = valid_related(RiskRecord, request.form.get("risk_id", type=int), "Geçerli bir risk seçin.")
            action = valid_related(Action, request.form.get("action_id", type=int), "Geçerli bir aksiyon seçin.")
            document = valid_related(Document, request.form.get("document_id", type=int), "Geçerli bir doküman seçin.")
            if outcome in {"partial", "noncompliant"} and not (risk or action or improvement_plan):
                raise ValueError("Kısmen uygun veya uygun değil sonucu için risk, aksiyon ya da iyileştirme planı zorunludur.")
            open_actions = [
                item.action
                for item in obligation.evaluations
                if item.action is not None and not item.action.is_completed
            ]
            if action is not None and not action.is_completed and action not in open_actions:
                open_actions.append(action)
            if outcome == "compliant" and open_actions:
                raise ValueError(
                    "Bağlı açık aksiyonlar tamamlanmadan yükümlülük uygun olarak değerlendirilemez."
                )
            next_review = parse_date(request.form.get("next_review_date"), required=True)
            evaluation = ComplianceEvaluation(
                company_id=obligation.company_id,
                obligation_id=obligation.id,
                revision_id=revision.id,
                evaluator_user_id=g.current_user.id,
                outcome=outcome,
                summary=summary,
                evidence_note=(request.form.get("evidence_note") or "").strip()[:10000] or None,
                next_review_date=next_review,
                risk_id=risk.id if risk else None,
                action_id=action.id if action else None,
                document_id=document.id if document else None,
                improvement_plan=improvement_plan,
                obligation_no_snapshot=obligation.obligation_no,
                obligation_title_snapshot=obligation.title,
                legal_reference_snapshot=obligation.legal_reference,
                revision_no_snapshot=revision.revision_no,
                official_source_url_snapshot=revision.official_source_url,
                owner_name_snapshot=obligation.owner.full_name,
            )
            db.session.add(evaluation)
            db.session.flush()
            store_file(
                request.files.get("evidence_file"), company_id=obligation.company_id,
                folder="compliance/evidence", kind="evidence", evaluation=evaluation,
            )
            obligation.last_review_date = date.today()
            obligation.next_review_date = next_review
            record_audit_event(
                "ComplianceEvaluation", "compliance_evaluated",
                f"{obligation.obligation_no} uygunluk değerlendirmesi kaydedildi: {EVALUATION_LABELS[outcome]}",
                entity_id=evaluation.id, commit=False,
            )
            db.session.commit()
            flash("Uygunluk değerlendirmesi denetim iziyle kaydedildi.", "success")
            return redirect(url_for("compliance.detail", obligation_id=obligation.id))
        except ValueError as error:
            db.session.rollback()
            flash(str(error), "danger")
    return render_template(
        "compliance/evaluation_form.html",
        **evaluation_form_context(obligation, revision, request.form),
    )


@bp.post("/<int:obligation_id>/yururlukten-kaldir")
def repeal(obligation_id):
    require_permission("compliance.manage", "compliance.archive")
    obligation = get_obligation_or_404(obligation_id)
    if obligation.status != "active":
        abort(409)
    obligation.status = "repealed"
    obligation.repealed_at = datetime.now()
    record_audit_event(
        "ComplianceObligation", "compliance_repealed",
        f"{obligation.obligation_no} yürürlükten kaldırıldı",
        entity_id=obligation.id, commit=False,
    )
    db.session.commit()
    flash("Yükümlülük yürürlükten kalktı olarak işaretlendi.", "success")
    return redirect(url_for("compliance.detail", obligation_id=obligation.id))


@bp.post("/<int:obligation_id>/arsivle")
def archive(obligation_id):
    require_permission("compliance.archive", "compliance.manage")
    obligation = get_obligation_or_404(obligation_id)
    if obligation.status == "archived":
        abort(409)
    obligation.status = "archived"
    obligation.archived_at = datetime.now()
    revision_ids = [item.id for item in obligation.revisions]
    source_keys = [f"compliance-owner:{obligation.id}"]
    source_keys.extend(f"compliance-verification:{item_id}" for item_id in revision_ids)
    Notification.query.filter_by(company_id=obligation.company_id).filter(
        or_(
            Notification.source_key.in_(source_keys),
            Notification.source_key.like(f"compliance-review:{obligation.id}:%"),
            *[
                Notification.source_key.like(f"compliance-verification:{item_id}:%")
                for item_id in revision_ids
            ],
        )
    ).update({Notification.is_read: True}, synchronize_session=False)
    record_audit_event(
        "ComplianceObligation", "compliance_archived",
        f"{obligation.obligation_no} arşivlendi",
        entity_id=obligation.id, commit=False,
    )
    db.session.commit()
    flash("Mevzuat yükümlülüğü arşivlendi; geçmiş kayıtlar korundu.", "success")
    return redirect(url_for("compliance.detail", obligation_id=obligation.id))


@bp.get("/dosya/<int:file_id>")
def download_file(file_id):
    row = file_query().filter_by(id=file_id, is_active=True).first_or_404()
    if not (
        has_permission("compliance.evidence_download")
        or has_permission("compliance.manage")
        or row.uploaded_by_user_id == g.current_user.id
    ):
        abort(403)
    obligation = row.revision.obligation if row.revision else row.evaluation.obligation
    if not can_access_obligation(obligation):
        abort(403)
    upload_root = Path(current_app.config["UPLOAD_FOLDER"]).resolve()
    file_path = (upload_root / row.stored_path).resolve()
    try:
        file_path.relative_to(upload_root)
    except ValueError:
        abort(404)
    if not file_path.is_file():
        abort(404)
    record_audit_event(
        "ComplianceFile",
        "compliance_file_downloaded",
        f"{obligation.obligation_no} kanıt dosyası indirildi",
        entity_id=row.id,
        details={"file_name": row.original_name, "sha256": row.sha256_hash},
    )
    return send_from_directory(
        str(file_path.parent), file_path.name, as_attachment=True,
        download_name=row.original_name, mimetype=row.mime_type,
    )


@bp.get("/excel")
def export_excel():
    require_permission("compliance.export", "compliance.manage")
    rows = []
    for obligation in obligation_query().order_by(ComplianceObligation.obligation_no.asc()).all():
        for revision in obligation.revisions or [None]:
            evaluations = revision.evaluations if revision and revision.evaluations else [None]
            for evaluation in evaluations:
                rows.append((
                    obligation.obligation_no, obligation.title, obligation.category,
                    obligation.obligation_type, obligation.authority or "", obligation.region or "",
                    obligation.legal_reference or "", APPLICABILITY_LABELS.get(obligation.applicability_status, obligation.applicability_status),
                    obligation.department, obligation.process or "", obligation.owner.full_name,
                    CRITICALITY_LABELS.get(obligation.criticality, obligation.criticality),
                    OBLIGATION_STATUS_LABELS.get(obligation.status, obligation.status),
                    obligation.next_review_date.strftime("%d.%m.%Y"),
                    revision.revision_no if revision else "", REVISION_STATUS_LABELS.get(revision.status, revision.status) if revision else "",
                    revision.official_source_url if revision else "", revision.change_summary if revision else "",
                    revision.verified_by.full_name if revision and revision.verified_by else "",
                    evaluation.evaluator.full_name if evaluation else "",
                    evaluation.evaluated_at.strftime("%d.%m.%Y") if evaluation else "",
                    EVALUATION_LABELS.get(evaluation.outcome, evaluation.outcome) if evaluation else "",
                    evaluation.summary if evaluation else "", evaluation.evidence_note or "" if evaluation else "",
                    evaluation.risk.risk_no if evaluation and evaluation.risk else "",
                    str(evaluation.action.action_number or evaluation.action.id) if evaluation and evaluation.action else "",
                    evaluation.document.document_code if evaluation and evaluation.document else "",
                    evaluation.improvement_plan or "" if evaluation else "",
                    ", ".join(
                        file.original_name
                        for file in (revision.files if revision else [])
                        if file.is_active
                    ),
                    ", ".join(
                        file.original_name
                        for file in (evaluation.files if evaluation else [])
                        if file.is_active
                    ),
                ))
    from .routes import build_simple_xlsx
    workbook = build_simple_xlsx(
        (
            "Kayıt No", "Yükümlülük", "Kategori", "Tür", "Yetkili Kurum", "Bölge",
            "Yasal Referans", "Uygulanabilirlik", "Departman", "Süreç", "Sorumlu", "Kritiklik",
            "Durum", "Sonraki İnceleme", "Revizyon", "Revizyon Durumu", "Resmî Kaynak",
            "Değişiklik Özeti", "Doğrulayan", "Değerlendiren", "Değerlendirme Tarihi",
            "Uygunluk Sonucu", "Değerlendirme Özeti", "Kanıt Notu", "Risk", "Aksiyon",
            "Doküman", "İyileştirme Planı", "Kaynak Dosyaları", "Kanıt Dosyaları",
        ),
        rows, sheet_name="Mevzuat Takibi",
        column_widths=(18, 36, 22, 20, 26, 16, 28, 20, 20, 22, 24, 14, 20, 18, 14, 20, 44, 44, 24, 24, 18, 20, 44, 36, 16, 16, 16, 44, 32, 32),
    )
    record_audit_event(
        "ComplianceObligation", "compliance_exported",
        "Yasal şartlar ve mevzuat takip raporu indirildi", details={"row_count": len(rows)},
    )
    return send_file(
        workbook, as_attachment=True,
        download_name=f"mevzuat-takip-raporu-{date.today().strftime('%Y%m%d')}.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def assigned_task_rows(scope, row_builder):
    if not module_enabled() or getattr(g, "current_user", None) is None:
        return []
    user = g.current_user
    rows = []
    if scope == "created":
        records = obligation_query().filter(
            ComplianceObligation.created_by_user_id == user.id,
            ComplianceObligation.status.notin_(("archived", "repealed")),
        ).order_by(ComplianceObligation.next_review_date.asc()).all()
    else:
        records = obligation_query().filter(
            ComplianceObligation.owner_user_id == user.id,
            ComplianceObligation.status.notin_(("archived", "repealed")),
        ).order_by(ComplianceObligation.next_review_date.asc()).all()
    for obligation in records:
        delayed = obligation.status == "active" and obligation.next_review_date < date.today()
        rows.append(row_builder(
            module_key="compliance", module_label="Mevzuat", module_icon="bank",
            module_tone="quality", title=f"{obligation.obligation_no} {obligation.title}",
            description=f"{obligation.category} / {obligation.owner.full_name}",
            reference_no=obligation.obligation_no, department=obligation.department,
            due_date=obligation.next_review_date,
            status="Gecikti" if delayed else OBLIGATION_STATUS_LABELS.get(obligation.status, obligation.status),
            status_key="delayed" if delayed else "pending" if obligation.status == "verification_pending" else "draft" if obligation.status == "draft" else "open",
            priority=CRITICALITY_LABELS.get(obligation.criticality, obligation.criticality),
            detail_url=url_for("compliance.detail", obligation_id=obligation.id),
            created_at=obligation.created_at, sort_id=obligation.id, date_label="İnceleme",
        ))
    if scope != "created" and has_permission("compliance.verify"):
        pending = revision_query().filter(
            ComplianceRevision.status == "verification_pending",
            ComplianceRevision.created_by_user_id != user.id,
        ).order_by(ComplianceRevision.created_at.asc()).all()
        for revision in pending:
            obligation = revision.obligation
            if obligation.status == "archived":
                continue
            rows.append(row_builder(
                module_key="compliance", module_label="Mevzuat Doğrulama", module_icon="patch-check",
                module_tone="quality", title=f"{obligation.obligation_no} {revision.revision_no} doğrulaması",
                description=obligation.title, reference_no=obligation.obligation_no,
                department=obligation.department, due_date=None, status="Doğrulama Bekliyor",
                status_key="pending", priority=CRITICALITY_LABELS.get(obligation.criticality, obligation.criticality),
                detail_url=url_for("compliance.detail", obligation_id=obligation.id),
                created_at=revision.created_at, sort_id=revision.id, date_label="Gönderim",
            ))
    return rows
