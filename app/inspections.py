from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from functools import wraps
import json
import re

from flask import (
    Blueprint,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from .audit import record_audit_event
from .extensions import db
from .models import (
    AppSetting,
    CompanyDepartment,
    DynamicFormField,
    DynamicFormVersion,
    INSPECTION_FINDING_SEVERITIES,
    INSPECTION_ITEM_RESULTS,
    InspectionFinding,
    InspectionItemResult,
    InspectionRecord,
    Notification,
    User,
)
from .notifications import add_user_notification
from .tenant import assign_current_company, current_company_id, scoped_query


bp = Blueprint("inspections", __name__, url_prefix="/saha-kontrol")

STATUS_LABELS = {
    "planned": "Planlandı",
    "in_progress": "Devam Ediyor",
    "review_pending": "İnceleme Bekliyor",
    "correction_pending": "Düzeltme Bekliyor",
    "effectiveness_review": "Etkinlik Kontrolü",
    "completed": "Tamamlandı",
    "archived": "Arşiv",
}
ACTIVE_STATUSES = {
    "planned",
    "in_progress",
    "review_pending",
    "correction_pending",
    "effectiveness_review",
}


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
    return checker("inspection_management") if checker else True


def inspection_query():
    return scoped_query(InspectionRecord.query, InspectionRecord)


def finding_query():
    return scoped_query(InspectionFinding.query, InspectionFinding)


def can_manage():
    return has_permission("inspection.manage")


def can_view_all():
    user = getattr(g, "current_user", None)
    return bool(
        can_manage()
        or user
        and (user.has_role("management") or user.has_role("viewer"))
    )


def can_view_department_record(inspection):
    user = getattr(g, "current_user", None)
    if user is None or not user.has_role("department_manager"):
        return False
    from .dynamic_forms import user_matches_department

    return user_matches_department(user, inspection.department)


def can_perform_record(inspection):
    return can_manage() or (
        has_permission("inspection.perform")
        and inspection.inspector_user_id == g.current_user.id
    )


def can_review_record(inspection):
    return can_manage() or (
        has_permission("inspection.review")
        and inspection.reviewer_user_id == g.current_user.id
    )


def can_access_record(inspection):
    return can_view_all() or can_view_department_record(inspection) or can_perform_record(inspection) or (
        has_permission("inspection.review")
        and inspection.reviewer_user_id == g.current_user.id
    ) or (
        any(
            finding.responsible_user_id == g.current_user.id
            for finding in inspection.findings
        )
    )


def get_inspection_or_404(inspection_id):
    inspection = inspection_query().filter_by(id=inspection_id).first_or_404()
    if not can_access_record(inspection):
        abort(403)
    return inspection


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


def active_users(permission_key=None):
    users = (
        User.query.filter_by(company_id=current_company_id(), is_active=True)
        .order_by(User.full_name.asc(), User.id.asc())
        .all()
    )
    if permission_key:
        users = [user for user in users if user.has_permission(permission_key)]
    return users


def active_departments():
    return [
        item.name
        for item in CompanyDepartment.query.filter_by(
            company_id=current_company_id(),
            is_active=True,
        )
        .order_by(CompanyDepartment.sort_order.asc(), CompanyDepartment.name.asc())
        .all()
    ]


def published_versions():
    return (
        scoped_query(DynamicFormVersion.query, DynamicFormVersion)
        .filter(DynamicFormVersion.status == "published")
        .order_by(DynamicFormVersion.name_snapshot.asc(), DynamicFormVersion.id.desc())
        .all()
    )


def reserve_inspection_no():
    year = date.today().year
    prefix = f"MUY-{year}-"
    numbers = []
    for (value,) in (
        inspection_query()
        .with_entities(InspectionRecord.inspection_no)
        .filter(InspectionRecord.inspection_no.like(f"{prefix}%"))
        .all()
    ):
        match = re.fullmatch(rf"{re.escape(prefix)}(\d+)", value or "")
        if match:
            numbers.append(int(match.group(1)))
    return f"{prefix}{max(numbers, default=0) + 1:04d}"


def valid_company_user(user_id, permission_key):
    user = User.query.filter_by(
        id=user_id,
        company_id=current_company_id(),
        is_active=True,
    ).first()
    if user is None or not user.has_permission(permission_key):
        raise ValueError("Yetkili ve aktif bir personel seçin.")
    return user


def status_label(status):
    return STATUS_LABELS.get(status, status or "-")


def parse_field_value(field):
    input_name = f"answer_{field.id}"
    if field.field_type == "multiple_choice":
        values = [value for value in request.form.getlist(input_name) if value in field.options]
        return values, not values

    raw_value = (request.form.get(input_name) or "").strip()
    if not raw_value:
        return "", True
    if field.field_type == "number":
        try:
            return str(Decimal(raw_value.replace(",", "."))), False
        except InvalidOperation as error:
            raise ValueError(f"{field.label}: sayısal bir değer girin.") from error
    if field.field_type == "date":
        try:
            return date.fromisoformat(raw_value).isoformat(), False
        except ValueError as error:
            raise ValueError(f"{field.label}: geçerli bir tarih girin.") from error
    if field.field_type == "yes_no" and raw_value not in {"Evet", "Hayır"}:
        raise ValueError(f"{field.label}: Evet veya Hayır seçin.")
    if field.field_type == "single_choice" and raw_value not in field.options:
        raise ValueError(f"{field.label}: geçerli bir seçenek seçin.")
    return raw_value[:5000], False


def posted_result_values(inspection):
    return {
        field.id: {
            "value": request.form.getlist(f"answer_{field.id}")
            if field.field_type == "multiple_choice"
            else request.form.get(f"answer_{field.id}", ""),
            "compliance_result": request.form.get(f"result_{field.id}", ""),
            "explanation": request.form.get(f"explanation_{field.id}", ""),
        }
        for field in inspection.version.fields
    }


def stored_result_values(inspection):
    by_field = {item.field_id: item for item in inspection.item_results}
    return {
        field.id: {
            "value": by_field[field.id].value if field.id in by_field else "",
            "compliance_result": by_field[field.id].compliance_result if field.id in by_field else "",
            "explanation": by_field[field.id].explanation if field.id in by_field else "",
        }
        for field in inspection.version.fields
    }


def parse_results(inspection, completing):
    parsed = []
    errors = []
    for field in inspection.version.fields:
        value, missing = parse_field_value(field)
        result = (request.form.get(f"result_{field.id}") or "").strip()
        explanation = (request.form.get(f"explanation_{field.id}") or "").strip()[:5000]
        if completing and result not in INSPECTION_ITEM_RESULTS:
            errors.append(f"{field.label}: sonuç seçin")
        if completing and field.is_required and result != "Uygulanamaz" and missing:
            errors.append(f"{field.label}: zorunlu değeri girin")
        if completing and result == "Uygun Değil" and not explanation:
            errors.append(f"{field.label}: uygunsuzluk açıklaması girin")
        if result and result not in INSPECTION_ITEM_RESULTS:
            errors.append(f"{field.label}: geçerli bir sonuç seçin")
        parsed.append((field, value, result or None, explanation or None))
    if errors:
        raise ValueError("; ".join(errors))
    return parsed


def save_results(inspection, parsed):
    existing = {item.field_id: item for item in inspection.item_results}
    for field, value, compliance_result, explanation in parsed:
        item = existing.get(field.id)
        if item is None:
            item = InspectionItemResult(inspection=inspection, field=field)
            assign_current_company(item)
            db.session.add(item)
        item.value_json = json.dumps(value, ensure_ascii=False)
        item.compliance_result = compliance_result
        item.explanation = explanation
    db.session.flush()


def calculate_overall_result(inspection):
    values = [item.compliance_result for item in inspection.item_results if item.compliance_result]
    if "Uygun Değil" in values:
        return "Uygun Değil"
    if values and all(value == "Uygulanamaz" for value in values):
        return "Uygulanamaz"
    return "Uygun" if values else None


def missing_finding_fields(inspection):
    finding_field_ids = {
        finding.item_result.field_id
        for finding in inspection.findings
        if finding.item_result is not None
    }
    return [
        item.field.label
        for item in inspection.item_results
        if item.compliance_result == "Uygun Değil" and item.field_id not in finding_field_ids
    ]


def mark_readiness_complete():
    key = "sales_readiness:competitor_inspection_management"
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
    require_permission("inspection.view", "inspection.manage", "inspection.perform", "inspection.review")
    query = inspection_query()
    status = (request.args.get("status") or "").strip()
    department = (request.args.get("department") or "").strip()
    search = (request.args.get("search") or "").strip()
    if status:
        query = query.filter(InspectionRecord.status == status)
    if department:
        query = query.filter(InspectionRecord.department == department)
    if search:
        pattern = f"%{search}%"
        query = query.filter(
            or_(
                InspectionRecord.inspection_no.ilike(pattern),
                InspectionRecord.title.ilike(pattern),
                InspectionRecord.location.ilike(pattern),
                InspectionRecord.reference.ilike(pattern),
            )
        )
    records = query.order_by(
        InspectionRecord.status.in_(["completed", "archived"]).asc(),
        InspectionRecord.due_date.asc(),
        InspectionRecord.id.desc(),
    ).all()
    if not can_view_all():
        records = [item for item in records if can_access_record(item)]
    return render_template(
        "inspections/dashboard.html",
        records=records,
        statuses=STATUS_LABELS,
        departments=active_departments(),
        filters={"status": status, "department": department, "search": search},
        can_manage=can_manage(),
        can_export=has_permission("inspection.export") or can_manage(),
    )


@bp.route("/yeni", methods=["GET", "POST"])
def create_inspection():
    require_permission("inspection.manage")
    versions = published_versions()
    if request.method == "POST":
        try:
            version_id = request.form.get("version_id", type=int)
            version = next((item for item in versions if item.id == version_id), None)
            if version is None:
                raise ValueError("Yayınlanmış bir kontrol şablonu seçin.")
            title = (request.form.get("title") or "").strip()[:180]
            if not title:
                raise ValueError("Muayene başlığı zorunludur.")
            inspector = valid_company_user(
                request.form.get("inspector_user_id", type=int),
                "inspection.perform",
            )
            reviewer = valid_company_user(
                request.form.get("reviewer_user_id", type=int),
                "inspection.review",
            )
            planned_date = parse_date(request.form.get("planned_date"))
            due_date = parse_date(request.form.get("due_date"), required=True)
            if planned_date and due_date < planned_date:
                raise ValueError("Termin, plan tarihinden önce olamaz.")
            inspection = InspectionRecord(
                version=version,
                inspection_no=reserve_inspection_no(),
                title=title,
                department=(request.form.get("department") or "").strip()[:160] or None,
                location=(request.form.get("location") or "").strip()[:255] or None,
                reference=(request.form.get("reference") or "").strip()[:255] or None,
                inspector=inspector,
                reviewer=reviewer,
                created_by_user_id=g.current_user.id,
                planned_date=planned_date,
                due_date=due_date,
                status="planned",
            )
            assign_current_company(inspection)
            db.session.add(inspection)
            db.session.flush()
            add_user_notification(
                inspector,
                f"{inspection.inspection_no} saha kontrolü size atandı.",
                company_id=inspection.company_id,
                notification_type="task",
                source_key=f"inspection-perform:{inspection.id}",
                target_url=url_for("inspections.perform", inspection_id=inspection.id),
                due_date=inspection.due_date,
            )
            record_audit_event(
                "InspectionRecord",
                "inspection_created",
                f"{inspection.inspection_no} saha kontrolü oluşturuldu",
                entity_id=inspection.id,
                details={
                    "version_id": version.id,
                    "inspector_user_id": inspector.id,
                    "reviewer_user_id": reviewer.id,
                    "due_date": due_date,
                },
                commit=False,
            )
            db.session.commit()
            flash("Saha kontrolü oluşturuldu ve uygulayıcıya bildirildi.", "success")
            return redirect(url_for("inspections.detail", inspection_id=inspection.id))
        except (ValueError, IntegrityError) as error:
            db.session.rollback()
            flash(str(error), "danger")
    return render_template(
        "inspections/form.html",
        inspection=None,
        versions=versions,
        inspectors=active_users("inspection.perform"),
        reviewers=active_users("inspection.review"),
        departments=active_departments(),
        form_data=request.form,
    )


@bp.route("/<int:inspection_id>/duzenle", methods=["GET", "POST"])
def edit_inspection(inspection_id):
    require_permission("inspection.manage")
    inspection = get_inspection_or_404(inspection_id)
    if inspection.status != "planned":
        abort(409)
    versions = published_versions()
    if request.method == "POST":
        try:
            version_id = request.form.get("version_id", type=int)
            version = next((item for item in versions if item.id == version_id), None)
            if version is None:
                raise ValueError("Yayınlanmış bir kontrol şablonu seçin.")
            title = (request.form.get("title") or "").strip()[:180]
            if not title:
                raise ValueError("Muayene başlığı zorunludur.")
            inspector = valid_company_user(
                request.form.get("inspector_user_id", type=int),
                "inspection.perform",
            )
            reviewer = valid_company_user(
                request.form.get("reviewer_user_id", type=int),
                "inspection.review",
            )
            planned_date = parse_date(request.form.get("planned_date"))
            due_date = parse_date(request.form.get("due_date"), required=True)
            if planned_date and due_date < planned_date:
                raise ValueError("Termin, plan tarihinden önce olamaz.")
            old_inspector_id = inspection.inspector_user_id
            inspection.version = version
            inspection.title = title
            inspection.department = (request.form.get("department") or "").strip()[:160] or None
            inspection.location = (request.form.get("location") or "").strip()[:255] or None
            inspection.reference = (request.form.get("reference") or "").strip()[:255] or None
            inspection.inspector = inspector
            inspection.reviewer = reviewer
            inspection.planned_date = planned_date
            inspection.due_date = due_date
            if old_inspector_id != inspector.id:
                Notification.query.filter_by(
                    company_id=inspection.company_id,
                    user_id=old_inspector_id,
                    source_key=f"inspection-perform:{inspection.id}",
                ).delete(synchronize_session=False)
                add_user_notification(
                    inspector,
                    f"{inspection.inspection_no} saha kontrolü size atandı.",
                    company_id=inspection.company_id,
                    notification_type="task",
                    source_key=f"inspection-perform:{inspection.id}",
                    target_url=url_for("inspections.perform", inspection_id=inspection.id),
                    due_date=inspection.due_date,
                )
            else:
                Notification.query.filter_by(
                    company_id=inspection.company_id,
                    user_id=inspector.id,
                    source_key=f"inspection-perform:{inspection.id}",
                ).update({Notification.due_date: due_date}, synchronize_session=False)
            record_audit_event(
                "InspectionRecord",
                "inspection_updated",
                f"{inspection.inspection_no} saha kontrolü güncellendi",
                entity_id=inspection.id,
                details={
                    "version_id": version.id,
                    "inspector_user_id": inspector.id,
                    "reviewer_user_id": reviewer.id,
                    "due_date": due_date,
                },
                commit=False,
            )
            db.session.commit()
            flash("Saha kontrolü güncellendi.", "success")
            return redirect(url_for("inspections.detail", inspection_id=inspection.id))
        except ValueError as error:
            db.session.rollback()
            flash(str(error), "danger")
    if request.method == "POST":
        form_data = request.form
    else:
        form_data = {
            "title": inspection.title,
            "version_id": str(inspection.version_id),
            "department": inspection.department or "",
            "location": inspection.location or "",
            "reference": inspection.reference or "",
            "inspector_user_id": str(inspection.inspector_user_id),
            "reviewer_user_id": str(inspection.reviewer_user_id),
            "planned_date": inspection.planned_date.isoformat() if inspection.planned_date else "",
            "due_date": inspection.due_date.isoformat() if inspection.due_date else "",
        }
    return render_template(
        "inspections/form.html",
        inspection=inspection,
        versions=versions,
        inspectors=active_users("inspection.perform"),
        reviewers=active_users("inspection.review"),
        departments=active_departments(),
        form_data=form_data,
    )


@bp.post("/<int:inspection_id>/baslat")
def start(inspection_id):
    require_permission("inspection.perform", "inspection.manage")
    inspection = get_inspection_or_404(inspection_id)
    if not can_perform_record(inspection):
        abort(403)
    if inspection.status != "planned":
        abort(409)
    inspection.status = "in_progress"
    inspection.started_at = datetime.utcnow()
    record_audit_event(
        "InspectionRecord",
        "inspection_started",
        f"{inspection.inspection_no} saha kontrolü başlatıldı",
        entity_id=inspection.id,
        details={"field_ids": [field.id for field in inspection.version.fields]},
        commit=False,
    )
    db.session.commit()
    return redirect(url_for("inspections.perform", inspection_id=inspection.id))


@bp.route("/<int:inspection_id>/uygula", methods=["GET", "POST"])
def perform(inspection_id):
    require_permission("inspection.perform", "inspection.manage")
    inspection = get_inspection_or_404(inspection_id)
    if not can_perform_record(inspection):
        abort(403)
    if inspection.status == "planned":
        return redirect(url_for("inspections.detail", inspection_id=inspection.id))
    if inspection.status != "in_progress":
        return redirect(url_for("inspections.detail", inspection_id=inspection.id))
    if request.method == "POST":
        completing = request.form.get("action") == "submit"
        try:
            parsed = parse_results(inspection, completing)
            save_results(inspection, parsed)
            inspection.overall_result = calculate_overall_result(inspection)
            if completing:
                missing = missing_finding_fields(inspection)
                if missing:
                    db.session.commit()
                    flash(
                        "Uygun olmayan maddeler için bulgu oluşturun: " + ", ".join(missing),
                        "warning",
                    )
                    return redirect(url_for("inspections.detail", inspection_id=inspection.id))
                inspection.submitted_at = datetime.utcnow()
                inspection.status = (
                    "correction_pending"
                    if inspection.open_findings
                    else "effectiveness_review"
                    if inspection.findings
                    else "review_pending"
                )
                Notification.query.filter_by(
                    company_id=inspection.company_id,
                    user_id=g.current_user.id,
                    source_key=f"inspection-perform:{inspection.id}",
                ).update({Notification.is_read: True}, synchronize_session=False)
                if inspection.status in {"review_pending", "effectiveness_review"}:
                    add_user_notification(
                        inspection.reviewer,
                        f"{inspection.inspection_no} inceleme onayınızı bekliyor.",
                        company_id=inspection.company_id,
                        notification_type="approval",
                        source_key=f"inspection-review:{inspection.id}:{inspection.status}",
                        target_url=url_for("inspections.detail", inspection_id=inspection.id),
                        due_date=inspection.due_date,
                    )
                record_audit_event(
                    "InspectionRecord",
                    "inspection_submitted",
                    f"{inspection.inspection_no} saha kontrolü incelemeye gönderildi",
                    entity_id=inspection.id,
                    details={
                        "result_item_ids": [item.id for item in inspection.item_results],
                        "overall_result": inspection.overall_result,
                        "finding_count": len(inspection.findings),
                        "status": inspection.status,
                    },
                    commit=False,
                )
            db.session.commit()
            flash(
                "Kontrol incelemeye gönderildi." if completing else "Kontrol taslağı kaydedildi.",
                "success",
            )
            return redirect(
                url_for("inspections.detail", inspection_id=inspection.id)
                if completing
                else url_for("inspections.perform", inspection_id=inspection.id)
            )
        except ValueError as error:
            db.session.rollback()
            flash(str(error), "danger")
    values = posted_result_values(inspection) if request.method == "POST" else stored_result_values(inspection)
    return render_template(
        "inspections/perform.html",
        inspection=inspection,
        values=values,
        result_options=INSPECTION_ITEM_RESULTS,
    )


@bp.get("/<int:inspection_id>")
def detail(inspection_id):
    require_permission("inspection.view", "inspection.manage", "inspection.perform", "inspection.review")
    inspection = get_inspection_or_404(inspection_id)
    results = {item.field_id: item for item in inspection.item_results}
    return render_template(
        "inspections/detail.html",
        inspection=inspection,
        results=results,
        status_label=status_label,
        can_perform=can_perform_record(inspection),
        can_review=can_review_record(inspection),
        can_manage=can_manage(),
        can_archive=has_permission("inspection.archive") or can_manage(),
        severities=INSPECTION_FINDING_SEVERITIES,
    )


@bp.route("/<int:inspection_id>/bulgu/yeni", methods=["GET", "POST"])
def create_finding(inspection_id):
    require_permission("inspection.perform", "inspection.manage")
    inspection = get_inspection_or_404(inspection_id)
    if not can_perform_record(inspection):
        abort(403)
    if inspection.status not in {"in_progress", "correction_pending"}:
        abort(409)
    nonconforming_items = [
        item for item in inspection.item_results if item.compliance_result == "Uygun Değil"
    ]
    if request.method == "POST":
        try:
            item_result_id = request.form.get("item_result_id", type=int)
            item = next((row for row in nonconforming_items if row.id == item_result_id), None)
            if item is None:
                raise ValueError("Uygun olmayan bir kontrol maddesi seçin.")
            title = (request.form.get("title") or "").strip()[:180]
            if not title:
                raise ValueError("Bulgu başlığı zorunludur.")
            severity = (request.form.get("severity") or "").strip()
            if severity not in INSPECTION_FINDING_SEVERITIES:
                raise ValueError("Geçerli bir önem seviyesi seçin.")
            responsible = valid_company_user(
                request.form.get("responsible_user_id", type=int),
                "inspection.perform",
            )
            finding = InspectionFinding(
                inspection=inspection,
                item_result=item,
                item_label_snapshot=item.field.label,
                observed_value_json=item.value_json,
                result_snapshot=item.compliance_result,
                explanation_snapshot=item.explanation,
                title=title,
                description=(request.form.get("description") or "").strip()[:5000] or None,
                severity=severity,
                responsible=responsible,
                due_date=parse_date(request.form.get("due_date"), required=True),
                status="open",
                created_by_user_id=g.current_user.id,
            )
            assign_current_company(finding)
            db.session.add(finding)
            db.session.flush()
            add_user_notification(
                responsible,
                f"{inspection.inspection_no} kaydında bir bulgu size atandı.",
                company_id=inspection.company_id,
                notification_type="task",
                source_key=f"inspection-finding:{finding.id}",
                target_url=url_for("inspections.detail", inspection_id=inspection.id),
                due_date=finding.due_date,
            )
            record_audit_event(
                "InspectionFinding",
                "inspection_finding_created",
                f"{inspection.inspection_no} için bulgu oluşturuldu",
                entity_id=finding.id,
                details={
                    "inspection_id": inspection.id,
                    "item_result_id": item.id,
                    "responsible_user_id": responsible.id,
                    "severity": severity,
                    "due_date": finding.due_date,
                },
                commit=False,
            )
            db.session.commit()
            flash("Bulgu oluşturuldu ve sorumluya bildirildi.", "success")
            return redirect(url_for("inspections.detail", inspection_id=inspection.id))
        except ValueError as error:
            db.session.rollback()
            flash(str(error), "danger")
    return render_template(
        "inspections/finding_form.html",
        inspection=inspection,
        items=nonconforming_items,
        users=active_users("inspection.perform"),
        severities=INSPECTION_FINDING_SEVERITIES,
        form_data=request.form,
    )


@bp.post("/bulgu/<int:finding_id>/kapat")
def close_finding(finding_id):
    require_permission("inspection.perform", "inspection.manage")
    finding = finding_query().filter_by(id=finding_id).first_or_404()
    inspection = finding.inspection
    if not (can_manage() or finding.responsible_user_id == g.current_user.id):
        abort(403)
    if finding.status != "open":
        abort(409)
    resolution = (request.form.get("resolution") or "").strip()[:5000]
    if not resolution:
        flash("Bulgu kapatma açıklaması zorunludur.", "danger")
        return redirect(url_for("inspections.detail", inspection_id=inspection.id))
    finding.status = "closed"
    finding.resolution = resolution
    finding.closed_by_user_id = g.current_user.id
    finding.closed_at = datetime.utcnow()
    db.session.flush()
    if inspection.status == "correction_pending" and not inspection.open_findings:
        inspection.status = "effectiveness_review"
        add_user_notification(
            inspection.reviewer,
            f"{inspection.inspection_no} etkinlik kontrolünüzü bekliyor.",
            company_id=inspection.company_id,
            notification_type="approval",
            source_key=f"inspection-review:{inspection.id}:effectiveness_review",
            target_url=url_for("inspections.detail", inspection_id=inspection.id),
            due_date=inspection.due_date,
        )
    record_audit_event(
        "InspectionFinding",
        "inspection_finding_closed",
        f"{inspection.inspection_no} bulgusu kapatıldı",
        entity_id=finding.id,
        details={"inspection_id": inspection.id, "status": finding.status},
        commit=False,
    )
    db.session.commit()
    flash("Bulgu kapatıldı.", "success")
    return redirect(url_for("inspections.detail", inspection_id=inspection.id))


@bp.post("/<int:inspection_id>/onayla")
def approve(inspection_id):
    require_permission("inspection.review", "inspection.manage")
    inspection = get_inspection_or_404(inspection_id)
    if not can_review_record(inspection):
        abort(403)
    if inspection.status not in {"review_pending", "effectiveness_review"}:
        abort(409)
    if inspection.open_findings:
        flash("Açık bulgular kapanmadan muayene tamamlanamaz.", "danger")
        return redirect(url_for("inspections.detail", inspection_id=inspection.id))
    inspection.status = "completed"
    inspection.reviewed_at = datetime.utcnow()
    inspection.completed_at = inspection.reviewed_at
    Notification.query.filter_by(
        company_id=inspection.company_id,
        user_id=g.current_user.id,
    ).filter(Notification.source_key.like(f"inspection-review:{inspection.id}:%")).update(
        {Notification.is_read: True}, synchronize_session=False
    )
    add_user_notification(
        inspection.inspector,
        f"{inspection.inspection_no} saha kontrolü tamamlandı.",
        company_id=inspection.company_id,
        notification_type="success",
        source_key=f"inspection-completed:{inspection.id}",
        target_url=url_for("inspections.detail", inspection_id=inspection.id),
    )
    mark_readiness_complete()
    record_audit_event(
        "InspectionRecord",
        "inspection_completed",
        f"{inspection.inspection_no} saha kontrolü tamamlandı",
        entity_id=inspection.id,
        details={
            "overall_result": inspection.overall_result,
            "finding_count": len(inspection.findings),
            "reviewer_user_id": g.current_user.id,
        },
        commit=False,
    )
    db.session.commit()
    flash("Muayene onaylanarak tamamlandı.", "success")
    return redirect(url_for("inspections.detail", inspection_id=inspection.id))


@bp.post("/<int:inspection_id>/duzeltmeye-gonder")
def return_for_correction(inspection_id):
    require_permission("inspection.review", "inspection.manage")
    inspection = get_inspection_or_404(inspection_id)
    if not can_review_record(inspection):
        abort(403)
    if inspection.status not in {"review_pending", "effectiveness_review"}:
        abort(409)
    review_note = (request.form.get("review_note") or "").strip()[:5000]
    if not review_note:
        flash("Düzeltme gerekçesi zorunludur.", "danger")
        return redirect(url_for("inspections.detail", inspection_id=inspection.id))
    previous_status = inspection.status
    inspection.status = "in_progress"
    inspection.review_note = review_note
    inspection.submitted_at = None
    inspection.reviewed_at = datetime.utcnow()
    Notification.query.filter_by(
        company_id=inspection.company_id,
        user_id=g.current_user.id,
    ).filter(Notification.source_key.like(f"inspection-review:{inspection.id}:%")).update(
        {Notification.is_read: True}, synchronize_session=False
    )
    add_user_notification(
        inspection.inspector,
        f"{inspection.inspection_no} saha kontrolü düzeltme için size geri gönderildi.",
        company_id=inspection.company_id,
        notification_type="warning",
        source_key=f"inspection-correction:{inspection.id}:{inspection.updated_at or inspection.created_at}",
        target_url=url_for("inspections.detail", inspection_id=inspection.id),
        due_date=inspection.due_date,
    )
    record_audit_event(
        "InspectionRecord",
        "inspection_returned_for_correction",
        f"{inspection.inspection_no} saha kontrolü düzeltmeye gönderildi",
        entity_id=inspection.id,
        details={
            "previous_status": previous_status,
            "status": inspection.status,
            "reviewer_user_id": g.current_user.id,
        },
        commit=False,
    )
    db.session.commit()
    flash("Muayene düzeltme için uygulayıcıya geri gönderildi.", "success")
    return redirect(url_for("inspections.detail", inspection_id=inspection.id))


@bp.post("/<int:inspection_id>/arsivle")
def archive(inspection_id):
    require_permission("inspection.archive", "inspection.manage")
    inspection = get_inspection_or_404(inspection_id)
    if inspection.status != "completed":
        abort(409)
    inspection.status = "archived"
    inspection.archived_at = datetime.utcnow()
    record_audit_event(
        "InspectionRecord",
        "inspection_archived",
        f"{inspection.inspection_no} saha kontrolü arşivlendi",
        entity_id=inspection.id,
        commit=False,
    )
    db.session.commit()
    flash("Muayene arşive alındı.", "success")
    return redirect(url_for("inspections.dashboard"))


def display_value(value):
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return "" if value is None else str(value)


@bp.get("/excel")
def export_excel():
    require_permission("inspection.export", "inspection.manage")
    query = inspection_query()
    rows = []
    for inspection in query.order_by(InspectionRecord.id.asc()).all():
        if not can_access_record(inspection):
            continue
        for field in inspection.version.fields:
            item = next((row for row in inspection.item_results if row.field_id == field.id), None)
            findings = [
                row
                for row in inspection.findings
                if row.item_result_id == getattr(item, "id", None)
            ]
            for finding in findings or [None]:
                rows.append((
                    inspection.inspection_no,
                    inspection.title,
                    inspection.version.name_snapshot,
                    inspection.department or "",
                    inspection.location or "",
                    inspection.reference or "",
                    inspection.inspector.full_name,
                    inspection.reviewer.full_name,
                    inspection.planned_date.strftime("%d.%m.%Y") if inspection.planned_date else "",
                    inspection.due_date.strftime("%d.%m.%Y") if inspection.due_date else "",
                    status_label(inspection.status),
                    inspection.overall_result or "",
                    field.label,
                    display_value(item.value) if item else "",
                    item.compliance_result if item else "",
                    item.explanation if item else "",
                    finding.title if finding else "",
                    finding.severity if finding else "",
                    finding.responsible.full_name if finding else "",
                    "Açık" if finding and finding.status == "open" else "Kapandı" if finding else "",
                    finding.resolution if finding else "",
                    finding.closed_at.strftime("%d.%m.%Y %H:%M")
                    if finding and finding.closed_at
                    else "",
                ))
    from .routes import build_simple_xlsx

    workbook = build_simple_xlsx(
        (
            "Muayene No",
            "Başlık",
            "Şablon",
            "Departman",
            "Konum",
            "Referans",
            "Uygulayıcı",
            "İnceleyen",
            "Plan Tarihi",
            "Termin",
            "Durum",
            "Genel Sonuç",
            "Kontrol Maddesi",
            "Yanıt",
            "Madde Sonucu",
            "Açıklama",
            "Bulgu",
            "Bulgu Önemi",
            "Bulgu Sorumlusu",
            "Bulgu Durumu",
            "Kapanış Açıklaması",
            "Kapanış Tarihi",
        ),
        rows,
        sheet_name="Saha Kontrolleri",
        column_widths=(
            18, 28, 28, 20, 22, 22, 22, 22, 14, 14, 20,
            18, 30, 28, 18, 36, 28, 16, 22, 16, 36, 20,
        ),
    )
    record_audit_event(
        "InspectionRecord",
        "inspection_results_exported",
        "Saha kontrol sonuçları Excel olarak indirildi",
        details={"row_count": len(rows)},
    )
    return send_file(
        workbook,
        as_attachment=True,
        download_name=f"saha-kontrol-raporu-{date.today().strftime('%Y%m%d')}.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def assigned_task_rows(scope, row_builder):
    if not module_enabled() or getattr(g, "current_user", None) is None:
        return []
    query = inspection_query()
    if scope == "created":
        query = query.filter(InspectionRecord.created_by_user_id == g.current_user.id)
    else:
        query = query.outerjoin(InspectionFinding).filter(
            or_(
                InspectionRecord.inspector_user_id == g.current_user.id,
                InspectionRecord.reviewer_user_id == g.current_user.id,
                InspectionFinding.responsible_user_id == g.current_user.id,
            )
        ).distinct()
    rows = []
    for inspection in query.all():
        if scope != "created":
            relevant = False
            if inspection.status in {"planned", "in_progress"}:
                relevant = inspection.inspector_user_id == g.current_user.id
            elif inspection.status in {"review_pending", "effectiveness_review"}:
                relevant = inspection.reviewer_user_id == g.current_user.id
            elif inspection.status == "correction_pending":
                relevant = any(
                    finding.status == "open" and finding.responsible_user_id == g.current_user.id
                    for finding in inspection.findings
                )
            if not relevant:
                continue
        if inspection.status in {"completed", "archived"} and scope != "created":
            continue
        status = status_label(inspection.status)
        status_key = (
            "completed"
            if inspection.status in {"completed", "archived"}
            else "delayed"
            if inspection.due_date and inspection.due_date < date.today()
            else "pending"
            if inspection.status in {"review_pending", "effectiveness_review", "correction_pending"}
            else "open"
        )
        rows.append(
            row_builder(
                module_key="inspection",
                module_label="Saha Kontrol",
                module_icon="clipboard2-check",
                module_tone="quality",
                title=f"{inspection.inspection_no} {inspection.title}",
                description=inspection.location or inspection.reference or inspection.version.name_snapshot,
                reference_no=inspection.inspection_no,
                department=inspection.department or "Saha Kontrol",
                due_date=inspection.due_date,
                status="Gecikti" if status_key == "delayed" else status,
                status_key=status_key,
                priority="Yüksek" if inspection.open_findings else "Orta",
                detail_url=url_for("inspections.detail", inspection_id=inspection.id),
                created_at=inspection.created_at,
                sort_id=inspection.id,
            )
        )
    return rows
