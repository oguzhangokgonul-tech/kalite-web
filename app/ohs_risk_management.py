from datetime import UTC, date, datetime
from functools import wraps
import hashlib
from pathlib import Path
from uuid import uuid4

from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, send_file, url_for
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from .audit import record_audit_event
from .extensions import db
from .models import Action, CompanyDepartment, OhsRiskAssessment, OhsRiskEvaluation, RiskRecord, User
from .notifications import add_user_notification
from .tenant import current_company_id, scoped_query


bp = Blueprint("ohs_risk", __name__, url_prefix="/risk-yonetimi/isg")

STATUSES = (
    "Taslak",
    "Revizyon Bekliyor",
    "Onay Bekliyor",
    "Aktif",
    "Kapanış Onayı",
    "Tamamlandı",
    "Arşiv",
)
CONTROL_HIERARCHY = (
    ("Ortadan Kaldırma", "Tehlikeyi tamamen ortadan kaldır"),
    ("İkame", "Daha az tehlikeli yöntem veya malzeme kullan"),
    ("Mühendislik Kontrolü", "Tehlikeyi kaynağında teknik olarak sınırla"),
    ("İdari Kontrol", "Talimat, eğitim, süre veya erişim kontrolü uygula"),
    ("KKD", "Kişisel koruyucu donanım kullan"),
)
ALLOWED_EXTENSIONS = {"pdf", "doc", "docx", "xls", "xlsx", "jpg", "jpeg", "png"}


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if getattr(g, "current_user", None) is None:
            return redirect(url_for("main.login", next=request.full_path))
        return view(*args, **kwargs)

    return wrapped


def has_permission(key):
    return bool(getattr(g, "current_user", None) and g.current_user.has_permission(key))


def can_view():
    return has_permission("risk.ohs_view") or has_permission("risk.view") or can_manage()


def can_create():
    return has_permission("risk.ohs_create") or can_manage()


def can_manage():
    return has_permission("risk.ohs_manage") or has_permission("risk.manage")


def can_approve():
    return has_permission("risk.ohs_approve") or has_permission("risk.approve") or can_manage()


def can_export():
    return has_permission("risk.ohs_export") or has_permission("risk.export") or has_permission("reports.export") or can_manage()


def can_archive():
    return has_permission("risk.ohs_archive") or has_permission("risk.archive") or can_manage()


def can_view_all():
    return has_permission("risk.view_all") or can_manage()


def require(condition):
    if not condition:
        abort(403)


def company_id_required():
    company_id = current_company_id()
    if company_id is None:
        abort(400, "İSG risk kaydı için önce bir şirket bağlamı seçin.")
    return company_id


def now_utc():
    return datetime.now(UTC).replace(tzinfo=None)


def assessment_query():
    return scoped_query(OhsRiskAssessment.query, OhsRiskAssessment)


def visible_query(query=None):
    query = query or assessment_query()
    if can_view_all():
        return query
    department_ids = [row.id for row in available_departments()]
    return query.filter(
        or_(
            OhsRiskAssessment.department_id.in_(department_ids),
            OhsRiskAssessment.created_by_user_id == g.current_user.id,
            OhsRiskAssessment.responsible_user_id == g.current_user.id,
            OhsRiskAssessment.reviewer_user_id == g.current_user.id,
        )
    )


def get_assessment(assessment_id):
    return visible_query().filter_by(id=assessment_id).first_or_404()


def available_departments():
    rows = CompanyDepartment.query.filter_by(
        company_id=current_company_id(), is_active=True
    ).order_by(CompanyDepartment.sort_order, CompanyDepartment.name).all()
    if can_view_all():
        return rows
    if g.current_user.has_role("department_manager") or g.current_user.has_role("department_staff"):
        from .dynamic_forms import user_matches_department

        return [row for row in rows if user_matches_department(g.current_user, row.name)]
    return rows


def active_users():
    return User.query.filter_by(
        company_id=current_company_id(), is_active=True
    ).order_by(User.full_name).all()


def reviewer_users():
    return [user for user in active_users() if user.has_permission("risk.ohs_approve") or user.has_permission("risk.approve") or user.has_permission("risk.manage")]


def parse_int(name, minimum=1, maximum=5):
    try:
        value = int(request.form.get(name, ""))
    except (TypeError, ValueError):
        raise ValueError("Olasılık ve şiddet puanları geçerli olmalıdır.") from None
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


def parse_record(name, model, required=True):
    raw = request.form.get(name, "").strip()
    if not raw and not required:
        return None
    try:
        row_id = int(raw)
    except (TypeError, ValueError):
        raise ValueError("Seçilen kayıt geçerli değil.") from None
    row = scoped_query(model.query, model).filter_by(id=row_id).first()
    if row is None:
        raise ValueError("Seçilen kayıt bu şirkete ait değil.")
    return row


def user_matches_department(user, department):
    from .dynamic_forms import user_matches_department as matches

    return matches(user, department.name)


def next_number():
    prefix = f"ISG-{date.today().year}-"
    values = assessment_query().with_entities(OhsRiskAssessment.assessment_no).filter(
        OhsRiskAssessment.assessment_no.like(f"{prefix}%")
    ).all()
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
        token = hashlib.sha256(f"{reference}:{message}:{now_utc().isoformat()}".encode()).hexdigest()[:24]
        add_user_notification(
            user,
            f"{reference} - {message}",
            company_id=current_company_id(),
            source_key=f"ohs-risk:{token}:u{user_id}",
            target_url=target_url,
            due_date=due_date,
            notification_type=kind,
        )


def save_evidence(upload):
    if not upload or not upload.filename:
        raise ValueError("Kapanış kanıtı zorunludur.")
    extension = Path(upload.filename).suffix.lower().lstrip(".")
    if extension not in ALLOWED_EXTENSIONS:
        raise ValueError("Yalnızca PDF, Word, Excel veya görsel dosyası yüklenebilir.")
    from .routes import assert_company_storage_quota, safe_original_filename, upload_storage_path, uploaded_stream_size

    company_id = company_id_required()
    original = safe_original_filename(upload.filename, "isg-risk-kaniti")
    relative, absolute = upload_storage_path(
        f"{uuid4().hex}.{extension}", "ohs-risks/evidence", company_id
    )
    assert_company_storage_quota(company_id, uploaded_stream_size(upload))
    upload.save(absolute)
    return original, str(relative).replace("\\", "/"), hashlib.sha256(absolute.read_bytes()).hexdigest(), absolute


def safe_remove(path):
    if path:
        path.unlink(missing_ok=True)


def score_tone(level):
    if isinstance(level, int):
        level = OhsRiskAssessment.score_level(level)
    return {
        "Çok Yüksek": "danger",
        "Yüksek": "danger",
        "Orta": "warning",
        "Düşük": "success",
    }.get(level, "muted")


def sync_risk_record(row):
    risk = row.risk_record
    risk.title = f"İSG - {row.activity}"
    risk.department = row.department.name
    risk.process = row.activity
    risk.description = row.risk_description
    risk.cause = row.hazard
    risk.consequence = row.exposed_people
    risk.due_date = row.due_date
    risk.owner_user_id = row.responsible_user_id
    if row.status == "Tamamlandı" and row.residual_score is not None:
        risk.likelihood = row.residual_likelihood
        risk.severity = row.residual_severity
        risk.status = "Kapandı"
    else:
        risk.likelihood = row.initial_likelihood
        risk.severity = row.initial_severity
        if risk.action_id:
            risk.status = "Aksiyon Açıldı"
        elif row.status in {"Aktif", "Kapanış Onayı"}:
            risk.status = "İzlemede"
        else:
            risk.status = "Açık"


def form_values(row=None):
    department = parse_record("department_id", CompanyDepartment)
    if department.id not in {item.id for item in available_departments()}:
        raise ValueError("Bu departman için kayıt oluşturma yetkiniz yok.")
    responsible = parse_record("responsible_user_id", User)
    reviewer = parse_record("reviewer_user_id", User)
    if not responsible.is_active or not reviewer.is_active:
        raise ValueError("Sorumlu ve onaylayan aktif personel olmalıdır.")
    if not user_matches_department(responsible, department):
        raise ValueError("Sorumlu seçilen departmanda görevli olmalıdır.")
    if reviewer not in reviewer_users():
        raise ValueError("Onaylayan kullanıcının İSG risk onay yetkisi bulunmuyor.")
    creator_id = row.created_by_user_id if row else g.current_user.id
    if reviewer.id in {creator_id, responsible.id}:
        raise ValueError("Kaydı oluşturan veya sorumlu kişi bağımsız onaylayan olamaz.")
    hierarchy = request.form.get("control_hierarchy", "").strip()
    if hierarchy not in {item[0] for item in CONTROL_HIERARCHY}:
        raise ValueError("Kontrol hiyerarşisi seçimi geçerli değil.")
    required_text = {
        key: request.form.get(key, "").strip()
        for key in (
            "activity",
            "location",
            "hazard",
            "risk_description",
            "exposed_people",
            "existing_controls",
            "planned_controls",
        )
    }
    if not all(required_text.values()):
        raise ValueError("Tehlike, risk, maruz kalanlar ve kontrol alanlarının tamamı zorunludur.")
    due_date = parse_date("due_date")
    review_date = parse_date("review_date", required=False)
    if review_date and review_date < due_date:
        raise ValueError("Gözden geçirme tarihi kontrol termininden önce olamaz.")
    return {
        **required_text,
        "department_id": department.id,
        "responsible_user_id": responsible.id,
        "reviewer_user_id": reviewer.id,
        "initial_likelihood": parse_int("initial_likelihood"),
        "initial_severity": parse_int("initial_severity"),
        "control_hierarchy": hierarchy,
        "due_date": due_date,
        "review_date": review_date,
    }


def form_context(row=None):
    return {
        "assessment": row,
        "departments": available_departments(),
        "users": active_users(),
        "reviewers": reviewer_users(),
        "hierarchy_choices": CONTROL_HIERARCHY,
        "score_options": range(1, 6),
        "form_data": request.form,
    }


def add_evaluation(row, *, phase, likelihood, severity, decision, note):
    evaluation = OhsRiskEvaluation(
        company_id=row.company_id,
        assessment=row,
        version_no=max((item.version_no for item in row.evaluations), default=0) + 1,
        phase=phase,
        likelihood=likelihood,
        severity=severity,
        score=likelihood * severity,
        level=OhsRiskAssessment.score_level(likelihood * severity),
        existing_controls=row.existing_controls,
        planned_controls=row.planned_controls,
        control_hierarchy=row.control_hierarchy,
        decision=decision,
        note=note,
        evidence_name=row.evidence_name,
        evidence_path=row.evidence_path,
        evidence_hash=row.evidence_hash,
        evaluator_user_id=g.current_user.id,
    )
    db.session.add(evaluation)
    return evaluation


@bp.before_request
def guard_module():
    checker = getattr(g, "company_module_enabled", None)
    if checker and not checker("risk_management"):
        abort(404)


@bp.get("")
@login_required
def dashboard():
    require(can_view())
    filters = {
        "search": request.args.get("search", "").strip(),
        "department_id": request.args.get("department_id", type=int),
        "status": request.args.get("status", "").strip(),
        "level": request.args.get("level", "").strip(),
    }
    query = visible_query()
    if filters["search"]:
        term = f"%{filters['search']}%"
        query = query.filter(or_(
            OhsRiskAssessment.assessment_no.ilike(term),
            OhsRiskAssessment.activity.ilike(term),
            OhsRiskAssessment.location.ilike(term),
            OhsRiskAssessment.hazard.ilike(term),
            OhsRiskAssessment.risk_description.ilike(term),
        ))
    if filters["department_id"]:
        query = query.filter_by(department_id=filters["department_id"])
    if filters["status"]:
        query = query.filter_by(status=filters["status"])
    else:
        query = query.filter(OhsRiskAssessment.status != "Arşiv")
    rows = query.order_by(OhsRiskAssessment.due_date, OhsRiskAssessment.id.desc()).all()
    if filters["level"]:
        rows = [row for row in rows if (row.residual_level or row.initial_level) == filters["level"]]
    all_rows = visible_query().filter(OhsRiskAssessment.status != "Arşiv").all()
    today = date.today()
    return render_template(
        "ohs_risks/dashboard.html",
        assessments=rows,
        total_count=len(all_rows),
        critical_count=sum((row.residual_level or row.initial_level) == "Çok Yüksek" for row in all_rows),
        pending_count=sum(row.status in {"Onay Bekliyor", "Kapanış Onayı"} for row in all_rows),
        overdue_count=sum(row.status not in {"Tamamlandı", "Arşiv"} and row.due_date < today for row in all_rows),
        filters=filters,
        departments=available_departments(),
        statuses=STATUSES,
        can_create=can_create(),
        can_manage=can_manage(),
        can_approve=can_approve(),
        can_export=can_export(),
        score_tone=score_tone,
        today=today,
    )


@bp.route("/yeni", methods=("GET", "POST"))
@login_required
def create_assessment():
    require(can_create())
    company_id = company_id_required()
    if request.method == "POST":
        try:
            values = form_values()
            from .routes import next_risk_no

            mirror = RiskRecord(
                company_id=company_id,
                risk_no=next_risk_no(),
                title=f"İSG - {values['activity']}",
                department=db.session.get(CompanyDepartment, values["department_id"]).name,
                process=values["activity"],
                description=values["risk_description"],
                cause=values["hazard"],
                consequence=values["exposed_people"],
                likelihood=values["initial_likelihood"],
                severity=values["initial_severity"],
                status="Açık",
                due_date=values["due_date"],
                owner_user_id=values["responsible_user_id"],
                created_by_user_id=g.current_user.id,
            )
            db.session.add(mirror)
            db.session.flush()
            row = OhsRiskAssessment(
                company_id=company_id,
                assessment_no=next_number(),
                created_by_user_id=g.current_user.id,
                risk_record_id=mirror.id,
                status="Taslak",
                **values,
            )
            db.session.add(row)
            db.session.commit()
            notify(row.responsible_user_id, row.assessment_no, "İSG risk kaydı size atandı.", url_for("ohs_risk.assessment_detail", assessment_id=row.id), row.due_date)
            flash("İSG risk değerlendirmesi oluşturuldu.", "success")
            return redirect(url_for("ohs_risk.assessment_detail", assessment_id=row.id))
        except (ValueError, IntegrityError) as error:
            db.session.rollback()
            flash(str(error), "danger")
    return render_template("ohs_risks/form.html", **form_context())


@bp.route("/<int:assessment_id>/duzenle", methods=("GET", "POST"))
@login_required
def edit_assessment(assessment_id):
    row = get_assessment(assessment_id)
    require(can_manage() or row.created_by_user_id == g.current_user.id or row.responsible_user_id == g.current_user.id)
    if row.status not in {"Taslak", "Revizyon Bekliyor"}:
        abort(409)
    if request.method == "POST":
        try:
            for key, value in form_values(row).items():
                setattr(row, key, value)
            sync_risk_record(row)
            db.session.commit()
            flash("İSG risk değerlendirmesi güncellendi.", "success")
            return redirect(url_for("ohs_risk.assessment_detail", assessment_id=row.id))
        except (ValueError, IntegrityError) as error:
            db.session.rollback()
            flash(str(error), "danger")
    return render_template("ohs_risks/form.html", **form_context(row))


@bp.get("/<int:assessment_id>")
@login_required
def assessment_detail(assessment_id):
    require(can_view())
    row = get_assessment(assessment_id)
    owner = row.created_by_user_id == g.current_user.id or row.responsible_user_id == g.current_user.id or can_manage()
    reviewer = row.reviewer_user_id == g.current_user.id and row.created_by_user_id != g.current_user.id
    action = row.risk_record.action
    return render_template(
        "ohs_risks/detail.html",
        assessment=row,
        evaluations=row.evaluations,
        hierarchy_choices=CONTROL_HIERARCHY,
        score_tone=score_tone,
        can_edit=owner and row.status in {"Taslak", "Revizyon Bekliyor"},
        can_submit=owner and row.status in {"Taslak", "Revizyon Bekliyor"},
        can_review_initial=can_approve() and reviewer and row.status == "Onay Bekliyor",
        can_create_action=(can_manage() or has_permission("actions.create")) and action is None and row.status != "Arşiv",
        can_submit_residual=owner and row.status == "Aktif",
        can_review_residual=can_approve() and reviewer and row.status == "Kapanış Onayı",
        can_archive=can_archive() and row.status == "Tamamlandı",
    )


@bp.post("/<int:assessment_id>/onaya-gonder")
@login_required
def submit_initial(assessment_id):
    row = get_assessment(assessment_id)
    require(can_manage() or row.created_by_user_id == g.current_user.id or row.responsible_user_id == g.current_user.id)
    if row.status not in {"Taslak", "Revizyon Bekliyor"}:
        abort(409)
    row.status = "Onay Bekliyor"
    sync_risk_record(row)
    db.session.commit()
    notify(row.reviewer_user_id, row.assessment_no, "Başlangıç İSG risk değerlendirmesi onayınızı bekliyor.", url_for("ohs_risk.assessment_detail", assessment_id=row.id), row.due_date)
    flash("Başlangıç değerlendirmesi onaya gönderildi.", "success")
    return redirect(url_for("ohs_risk.assessment_detail", assessment_id=row.id))


@bp.post("/<int:assessment_id>/ilk-degerlendirme")
@login_required
def review_initial(assessment_id):
    row = get_assessment(assessment_id)
    require(can_approve() and row.reviewer_user_id == g.current_user.id and row.created_by_user_id != g.current_user.id)
    if row.status != "Onay Bekliyor":
        abort(409)
    decision = request.form.get("decision", "")
    note = (request.form.get("review_note") or request.form.get("note") or "").strip()
    if decision not in {"approve", "reject"} or not note:
        flash("Karar ve değerlendirme açıklaması zorunludur.", "danger")
        return redirect(url_for("ohs_risk.assessment_detail", assessment_id=row.id))
    if decision == "approve" and row.initial_score >= 10 and not row.risk_record.action_id:
        flash("Yüksek ve çok yüksek riskler onaylanmadan önce bir azaltma aksiyonuna bağlanmalıdır.", "danger")
        return redirect(url_for("ohs_risk.assessment_detail", assessment_id=row.id))
    add_evaluation(
        row,
        phase="İlk Değerlendirme",
        likelihood=row.initial_likelihood,
        severity=row.initial_severity,
        decision="Onaylandı" if decision == "approve" else "Reddedildi",
        note=note,
    )
    row.review_note = note
    if decision == "approve":
        row.status = "Aktif"
        row.approved_at = now_utc()
    else:
        row.status = "Revizyon Bekliyor"
    sync_risk_record(row)
    db.session.commit()
    notify(row.responsible_user_id, row.assessment_no, "İSG risk değerlendirmesi onaylandı." if decision == "approve" else "İSG risk değerlendirmesi revizyona gönderildi.", url_for("ohs_risk.assessment_detail", assessment_id=row.id), row.due_date, "success" if decision == "approve" else "warning")
    flash("Değerlendirme kararı kaydedildi.", "success")
    return redirect(url_for("ohs_risk.assessment_detail", assessment_id=row.id))


@bp.post("/<int:assessment_id>/artik-risk")
@login_required
def submit_residual(assessment_id):
    row = get_assessment(assessment_id)
    require(can_manage() or row.responsible_user_id == g.current_user.id)
    if row.status != "Aktif":
        abort(409)
    action = row.risk_record.action
    if row.initial_score >= 10 and (action is None or not action.is_completed):
        flash("Yüksek riskin azaltma aksiyonu tamamlanmadan artık risk değerlendirmesi gönderilemez.", "danger")
        return redirect(url_for("ohs_risk.assessment_detail", assessment_id=row.id))
    evidence_path = None
    try:
        likelihood = parse_int("residual_likelihood")
        severity = parse_int("residual_severity")
        note = request.form.get("completion_note", "").strip()
        if not note:
            raise ValueError("Uygulanan kontroller ve sonuç açıklaması zorunludur.")
        evidence = save_evidence(request.files.get("evidence_file") or request.files.get("evidence"))
        row.residual_likelihood = likelihood
        row.residual_severity = severity
        row.completion_note = note
        row.evidence_name, row.evidence_path, row.evidence_hash, evidence_path = evidence
        row.status = "Kapanış Onayı"
        row.residual_submitted_at = now_utc()
        sync_risk_record(row)
        db.session.commit()
        notify(row.reviewer_user_id, row.assessment_no, "Artık risk değerlendirmesi ve kapanış kanıtı onayınızı bekliyor.", url_for("ohs_risk.assessment_detail", assessment_id=row.id), row.due_date)
        flash("Artık risk değerlendirmesi kapanış onayına gönderildi.", "success")
    except ValueError as error:
        db.session.rollback()
        safe_remove(evidence_path)
        flash(str(error), "danger")
    return redirect(url_for("ohs_risk.assessment_detail", assessment_id=row.id))


@bp.post("/<int:assessment_id>/kapanis-degerlendirme")
@login_required
def review_residual(assessment_id):
    row = get_assessment(assessment_id)
    require(can_approve() and row.reviewer_user_id == g.current_user.id and row.created_by_user_id != g.current_user.id)
    if row.status != "Kapanış Onayı" or row.residual_score is None:
        abort(409)
    decision = request.form.get("decision", "")
    note = (request.form.get("review_note") or request.form.get("note") or "").strip()
    if decision not in {"approve", "reject"} or not note:
        flash("Karar ve kapanış değerlendirmesi zorunludur.", "danger")
        return redirect(url_for("ohs_risk.assessment_detail", assessment_id=row.id))
    add_evaluation(
        row,
        phase="Artık Risk",
        likelihood=row.residual_likelihood,
        severity=row.residual_severity,
        decision="Onaylandı" if decision == "approve" else "Reddedildi",
        note=note,
    )
    row.review_note = note
    if decision == "approve":
        row.status = "Tamamlandı"
        row.completed_at = now_utc()
    else:
        row.status = "Aktif"
    sync_risk_record(row)
    db.session.commit()
    notify(row.responsible_user_id, row.assessment_no, "İSG riski kapatıldı." if decision == "approve" else "Artık risk değerlendirmesi revizyona gönderildi.", url_for("ohs_risk.assessment_detail", assessment_id=row.id), kind="success" if decision == "approve" else "warning")
    flash("Kapanış kararı kaydedildi.", "success")
    return redirect(url_for("ohs_risk.assessment_detail", assessment_id=row.id))


@bp.post("/<int:assessment_id>/arsivle")
@login_required
def archive_assessment(assessment_id):
    require(can_archive())
    row = get_assessment(assessment_id)
    if row.status != "Tamamlandı":
        abort(409)
    archived_at = now_utc()
    row.status = "Arşiv"
    row.archived_at = archived_at
    row.risk_record.status = "Arşiv"
    row.risk_record.archived_at = archived_at
    db.session.commit()
    flash("İSG risk değerlendirmesi arşivlendi.", "success")
    return redirect(url_for("ohs_risk.dashboard"))


@bp.get("/kanit/<int:evaluation_id>")
@login_required
def download_evaluation_evidence(evaluation_id):
    require(can_view())
    evaluation = scoped_query(OhsRiskEvaluation.query, OhsRiskEvaluation).filter_by(id=evaluation_id).first_or_404()
    get_assessment(evaluation.assessment_id)
    if not evaluation.evidence_path:
        abort(404)
    root = Path(current_app.config["UPLOAD_FOLDER"]).resolve()
    path = (root / evaluation.evidence_path).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        abort(404)
    if not path.is_file():
        abort(404)
    record_audit_event("OhsRiskEvaluation", "downloaded", "İSG risk kanıtı indirildi", entity_id=evaluation.id, details={"file_name": evaluation.evidence_name})
    return send_file(path, as_attachment=True, download_name=evaluation.evidence_name)


@bp.get("/rapor.xlsx")
@login_required
def export_excel():
    require(can_export())
    from .routes import build_simple_xlsx

    rows = []
    for row in visible_query().order_by(OhsRiskAssessment.assessment_no).all():
        rows.append((
            row.assessment_no,
            row.department.name,
            row.activity,
            row.location,
            row.hazard,
            row.risk_description,
            row.exposed_people,
            row.existing_controls,
            row.initial_likelihood,
            row.initial_severity,
            row.initial_score,
            row.initial_level,
            row.control_hierarchy,
            row.planned_controls,
            row.risk_record.action.number_label if row.risk_record.action else "-",
            row.residual_likelihood or "",
            row.residual_severity or "",
            row.residual_score or "",
            row.residual_level or "",
            row.responsible.full_name,
            row.reviewer.full_name,
            row.due_date.strftime("%d.%m.%Y"),
            row.status,
        ))
    headers = (
        "Kayıt No", "Departman", "Faaliyet", "Lokasyon", "Tehlike", "Risk", "Maruz Kalanlar",
        "Mevcut Kontroller", "İlk Olasılık", "İlk Şiddet", "İlk Puan", "İlk Seviye",
        "Kontrol Hiyerarşisi", "Planlanan Kontroller", "Bağlı Aksiyon", "Artık Olasılık",
        "Artık Şiddet", "Artık Puan", "Artık Seviye", "Sorumlu", "Onaylayan", "Termin", "Durum",
    )
    workbook = build_simple_xlsx(headers, rows, sheet_name="İSG Risk Matrisi")
    record_audit_event("OhsRiskReport", "exported", "İSG risk matrisi raporu indirildi", details={"row_count": len(rows)})
    return send_file(
        workbook,
        as_attachment=True,
        download_name=f"isg-risk-matrisi-{date.today():%Y%m%d}.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def assigned_task_rows(scope, row_builder):
    user_id = g.current_user.id
    today = date.today()
    results = []
    for row in visible_query().filter(OhsRiskAssessment.status.notin_(("Tamamlandı", "Arşiv"))).all():
        if scope == "created" and row.created_by_user_id != user_id:
            continue
        if scope != "created" and user_id not in {row.responsible_user_id, row.reviewer_user_id}:
            continue
        waiting_reviewer = row.status in {"Onay Bekliyor", "Kapanış Onayı"}
        if scope != "created" and waiting_reviewer and row.reviewer_user_id != user_id:
            continue
        if scope != "created" and not waiting_reviewer and row.responsible_user_id != user_id:
            continue
        results.append(row_builder(
            module_key="ohs_risk",
            module_label="İSG Risk",
            module_icon="shield-exclamation",
            module_tone="risk",
            title=f"{row.assessment_no} - {row.activity}",
            description=row.hazard,
            reference_no=row.assessment_no,
            department=row.department.name,
            due_date=row.due_date,
            status=row.status,
            status_key="delayed" if row.due_date < today else "pending",
            priority="Yüksek" if (row.residual_level or row.initial_level) in {"Yüksek", "Çok Yüksek"} else "Orta",
            detail_url=url_for("ohs_risk.assessment_detail", assessment_id=row.id),
            created_at=row.created_at,
            sort_id=600000 + row.id,
            date_label="Kontrol Termini",
        ))
    return results


def report_data():
    rows = []
    for row in visible_query().order_by(OhsRiskAssessment.assessment_no).all():
        rows.append((
            row.assessment_no, row.department.name, row.activity, row.location, row.hazard,
            row.initial_score, row.initial_level, row.residual_score or "-", row.residual_level or "-",
            row.control_hierarchy, row.risk_record.action.number_label if row.risk_record.action else "-",
            row.responsible.full_name, row.due_date.strftime("%d.%m.%Y"), row.status,
        ))
    return {
        "title": "İSG Risk Matrisi Raporu",
        "headers": (
            "Kayıt No", "Departman", "Faaliyet", "Lokasyon", "Tehlike", "İlk Puan",
            "İlk Seviye", "Artık Puan", "Artık Seviye", "Kontrol Hiyerarşisi",
            "Bağlı Aksiyon", "Sorumlu", "Termin", "Durum",
        ),
        "rows": rows,
        "sheet_name": "İSG Risk Matrisi",
    }
