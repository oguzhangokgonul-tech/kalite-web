from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from functools import wraps
from io import BytesIO
import json
import re
import unicodedata

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
    DynamicFormAnswer,
    DynamicFormAssignment,
    DynamicFormAssignmentRecipient,
    DynamicFormField,
    DynamicFormSubmission,
    DynamicFormTemplate,
    DynamicFormVersion,
    DYNAMIC_FORM_FIELD_TYPES,
    Notification,
    PersonnelContact,
    User,
)
from .notifications import add_notifications, add_user_notification
from .tenant import assign_current_company, current_company_id, scoped_query


bp = Blueprint("dynamic_forms", __name__, url_prefix="/dinamik-formlar")

FIELD_TYPE_OPTIONS = (
    ("short_text", "Kısa metin"),
    ("long_text", "Uzun metin"),
    ("number", "Sayı"),
    ("date", "Tarih"),
    ("yes_no", "Evet / Hayır"),
    ("single_choice", "Tekli seçim"),
    ("multiple_choice", "Çoklu seçim"),
)
CHOICE_FIELD_TYPES = {"single_choice", "multiple_choice"}


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
    return checker("dynamic_forms") if checker else True


def ensure_module_access():
    if not module_enabled():
        abort(404)


def normalize_text(value):
    value = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(char for char in value if not unicodedata.combining(char)).casefold().strip()


def user_department_values(user):
    contact = getattr(user, "personnel_contact", None)
    department_values = {
        normalize_text(getattr(contact, "department", None)) if contact else "",
    }
    title_values = {
        normalize_text(getattr(user, "title", None)),
        normalize_text(getattr(contact, "title", None)) if contact else "",
    }
    return department_values - {""}, title_values - {""}


def user_matches_department(user, department):
    target = normalize_text(department)
    if not target:
        return False
    department_values, title_values = user_department_values(user)
    if target in department_values:
        return True
    # Ünvanlar yalnızca departman adıyla başlıyorsa eşleşir. Böylece "IT"
    # departmanı, "Kalite" gibi içinde aynı harfleri taşıyan ünvanlarla eşleşmez.
    return any(
        value == target or re.match(rf"^{re.escape(target)}(?:\s|/|-|\(|$)", value)
        for value in title_values
    )


def active_company_users():
    company_id = current_company_id()
    if company_id is None:
        return []
    return (
        User.query.filter_by(company_id=company_id, is_active=True)
        .order_by(User.full_name.asc(), User.id.asc())
        .all()
    )


def active_departments():
    company_id = current_company_id()
    if company_id is None:
        return []
    return [
        row.name
        for row in CompanyDepartment.query.filter_by(
            company_id=company_id,
            is_active=True,
        )
        .order_by(CompanyDepartment.sort_order.asc(), CompanyDepartment.name.asc())
        .all()
    ]


def template_query():
    return scoped_query(DynamicFormTemplate.query, DynamicFormTemplate)


def version_query():
    return scoped_query(DynamicFormVersion.query, DynamicFormVersion)


def assignment_query():
    return scoped_query(DynamicFormAssignment.query, DynamicFormAssignment)


def submission_query():
    return scoped_query(DynamicFormSubmission.query, DynamicFormSubmission)


def get_template_or_404(template_id):
    return template_query().filter_by(id=template_id).first_or_404()


def get_version_or_404(version_id):
    return version_query().filter_by(id=version_id).first_or_404()


def get_assignment_or_404(assignment_id):
    return assignment_query().filter_by(id=assignment_id).first_or_404()


def parse_date(value):
    value = str(value or "").strip()
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ValueError("invalid_date") from error


def reserve_template_code():
    numbers = []
    for (code,) in template_query().with_entities(DynamicFormTemplate.code).all():
        match = re.search(r"(\d+)$", code or "")
        if match:
            numbers.append(int(match.group(1)))
    return f"DF-{max(numbers, default=0) + 1:04d}"


def clean_options(raw_value):
    values = []
    for part in re.split(r"[\r\n]+", str(raw_value or "")):
        value = part.strip()[:160]
        if value and value.casefold() not in {item.casefold() for item in values}:
            values.append(value)
    return values


def parse_designer_fields():
    labels = request.form.getlist("field_label")
    types = request.form.getlist("field_type")
    options = request.form.getlist("field_options")
    required_indexes = set(request.form.getlist("field_required"))
    rows = []
    for index, raw_label in enumerate(labels):
        label = raw_label.strip()[:180]
        if not label:
            continue
        field_type = types[index] if index < len(types) else "short_text"
        if field_type not in DYNAMIC_FORM_FIELD_TYPES:
            raise ValueError("invalid_field_type")
        field_options = clean_options(options[index] if index < len(options) else "")
        if field_type in CHOICE_FIELD_TYPES and len(field_options) < 2:
            raise ValueError("choice_options_required")
        rows.append(
            {
                "field_key": f"field_{len(rows) + 1}",
                "label": label,
                "field_type": field_type,
                "is_required": str(index) in required_indexes,
                "sort_order": len(rows) + 1,
                "options_json": json.dumps(field_options, ensure_ascii=False)
                if field_options
                else None,
            }
        )
    if not rows:
        raise ValueError("field_required")
    return rows


def save_draft_version(version):
    if version.status != "draft":
        abort(409)
    name = (request.form.get("name") or "").strip()[:180]
    description = (request.form.get("description") or "").strip()
    if not name:
        raise ValueError("name_required")
    fields = parse_designer_fields()
    version.name_snapshot = name
    version.description_snapshot = description or None
    version.template.name = name
    version.template.description = description or None
    for existing in list(version.fields):
        db.session.delete(existing)
    db.session.flush()
    for values in fields:
        field = DynamicFormField(version_id=version.id, **values)
        assign_current_company(field)
        db.session.add(field)


def clone_fields(source_version, target_version):
    for source in source_version.fields:
        field = DynamicFormField(
            version=target_version,
            field_key=source.field_key,
            label=source.label,
            field_type=source.field_type,
            is_required=source.is_required,
            sort_order=source.sort_order,
            options_json=source.options_json,
        )
        assign_current_company(field)
        db.session.add(field)


def can_manage_forms():
    return has_permission("dynamic_forms.manage")


def can_assign_forms():
    return has_permission("dynamic_forms.assign") or can_manage_forms()


def can_respond_forms():
    return has_permission("dynamic_forms.respond")


def can_export_forms():
    return has_permission("dynamic_forms.export") or can_manage_forms()


def assignment_is_for_user(assignment, user):
    if assignment.recipients:
        return any(recipient.user_id == user.id for recipient in assignment.recipients)
    if assignment.assigned_user_id:
        return assignment.assigned_user_id == user.id
    return user_matches_department(user, assignment.assigned_department)


def submission_for_user(assignment, user=None):
    user = user or g.current_user
    return submission_query().filter_by(
        assignment_id=assignment.id,
        respondent_user_id=user.id,
    ).first()


def eligible_users_for_department(department):
    return [
        user
        for user in active_company_users()
        if user.has_permission("dynamic_forms.respond")
        and user_matches_department(user, department)
    ]


def assignment_recipients(assignment):
    if assignment.recipients:
        return [recipient.user for recipient in assignment.recipients if recipient.user is not None]
    if assignment.assigned_user is not None:
        return [assignment.assigned_user]
    return eligible_users_for_department(assignment.assigned_department)


def snapshot_assignment_recipients(assignment, users):
    for user in users:
        recipient = DynamicFormAssignmentRecipient(assignment=assignment, user_id=user.id)
        assign_current_company(recipient)
        db.session.add(recipient)


def assignment_progress(assignment):
    recipients = assignment_recipients(assignment)
    recipient_ids = {user.id for user in recipients}
    completed_user_ids = {
        submission.respondent_user_id
        for submission in assignment.submissions
        if submission.status == "completed"
    }
    completed_count = len(recipient_ids & completed_user_ids)
    total_count = len(recipient_ids)
    is_completed = bool(total_count and completed_count == total_count)
    return completed_count, total_count, is_completed


def refresh_assignment_status(assignment):
    _completed_count, _total_count, is_completed = assignment_progress(assignment)
    if not is_completed:
        return
    assignment.status = "completed"
    completed_times = [
        submission.submitted_at
        for submission in assignment.submissions
        if submission.status == "completed" and submission.submitted_at is not None
    ]
    assignment.completed_at = max(completed_times, default=datetime.utcnow())


def mark_readiness_complete():
    key = "sales_readiness:competitor_dynamic_checklist"
    setting = db.session.get(AppSetting, key)
    if setting is None:
        db.session.add(AppSetting(key=key, value="1"))
    else:
        setting.value = "1"


def flash_form_error(error):
    messages = {
        "name_required": "Form adı zorunludur.",
        "field_required": "En az bir alan ekleyin.",
        "invalid_field_type": "Geçersiz alan tipi seçildi.",
        "choice_options_required": "Seçim alanlarında en az iki seçenek bulunmalıdır.",
        "invalid_date": "Termin tarihi geçersiz.",
        "target_required": "Kullanıcı veya departman seçin.",
        "no_eligible_user": "Seçilen hedefte formu yanıtlayabilecek aktif kullanıcı bulunamadı.",
    }
    flash(messages.get(str(error), "İşlem tamamlanamadı."), "danger")


def designer_rows(version=None):
    if request.method == "POST":
        labels = request.form.getlist("field_label")
        types = request.form.getlist("field_type")
        options = request.form.getlist("field_options")
        required_indexes = set(request.form.getlist("field_required"))
        return [
            {
                "label": label,
                "field_type": types[index] if index < len(types) else "short_text",
                "options_text": options[index] if index < len(options) else "",
                "is_required": str(index) in required_indexes,
            }
            for index, label in enumerate(labels)
        ]
    return [
        {
            "label": field.label,
            "field_type": field.field_type,
            "options_text": "\n".join(field.options),
            "is_required": field.is_required,
        }
        for field in (version.fields if version else [])
    ]


@bp.before_request
@login_required
def before_dynamic_form_request():
    ensure_module_access()


@bp.get("")
def dashboard():
    require_permission("dynamic_forms.view", "dynamic_forms.manage", "dynamic_forms.respond")
    templates = template_query().order_by(DynamicFormTemplate.updated_at.desc()).all()
    visible_templates = templates if (has_permission("dynamic_forms.view") or can_manage_forms()) else []
    for template in visible_templates:
        template.draft_version = next(
            (version for version in template.versions if version.status == "draft"),
            None,
        )
        template.published_version = next(
            (version for version in template.versions if version.status == "published"),
            None,
        )
    assignments = assignment_query().order_by(
        DynamicFormAssignment.status.asc(),
        DynamicFormAssignment.due_date.asc(),
        DynamicFormAssignment.id.desc(),
    ).all()
    if not (can_manage_forms() or can_export_forms()):
        assignments = [item for item in assignments if assignment_is_for_user(item, g.current_user)]
    for assignment in assignments:
        assignment.current_submission = submission_for_user(assignment)
        completed_count, recipient_count, is_completed = assignment_progress(assignment)
        assignment.completed_submission_count = completed_count
        assignment.recipient_count = recipient_count
        assignment.is_fully_completed = is_completed
        assignment.current_user_can_respond = (
            can_respond_forms() and assignment_is_for_user(assignment, g.current_user)
        )
    return render_template(
        "dynamic_forms/dashboard.html",
        templates=visible_templates,
        assignments=assignments,
        can_manage=can_manage_forms(),
        can_assign=can_assign_forms(),
        can_export=can_export_forms(),
        completed_assignment_count=sum(item.is_fully_completed for item in assignments),
        pending_assignment_count=sum(not item.is_fully_completed for item in assignments),
    )


@bp.route("/sablon/yeni", methods=["GET", "POST"])
def create_template():
    require_permission("dynamic_forms.manage")
    if request.method == "POST":
        try:
            template = DynamicFormTemplate(
                code=reserve_template_code(),
                name=(request.form.get("name") or "Yeni Form").strip()[:180],
                status="draft",
                current_version_number=1,
                created_by_user_id=g.current_user.id,
            )
            assign_current_company(template)
            db.session.add(template)
            db.session.flush()
            version = DynamicFormVersion(
                template=template,
                version_number=1,
                status="draft",
                name_snapshot=template.name,
                created_by_user_id=g.current_user.id,
            )
            assign_current_company(version)
            db.session.add(version)
            db.session.flush()
            save_draft_version(version)
            record_audit_event(
                "DynamicFormTemplate",
                "form_template_created",
                f"{template.code} form şablonu oluşturuldu",
                entity_id=template.id,
                details={"code": template.code, "version": 1, "field_count": len(version.fields)},
                commit=False,
            )
            db.session.commit()
            flash("Form şablonu taslak olarak oluşturuldu.", "success")
            return redirect(url_for("dynamic_forms.edit_version", version_id=version.id))
        except (ValueError, IntegrityError) as error:
            db.session.rollback()
            flash_form_error(error)
    return render_template(
        "dynamic_forms/designer.html",
        template=None,
        version=None,
        field_types=FIELD_TYPE_OPTIONS,
        form_data=request.form,
        designer_rows=designer_rows(),
    )


@bp.route("/surum/<int:version_id>/duzenle", methods=["GET", "POST"])
def edit_version(version_id):
    require_permission("dynamic_forms.manage")
    version = get_version_or_404(version_id)
    if version.status != "draft":
        flash("Yayınlanmış sürüm değiştirilemez. Yeni sürüm oluşturun.", "warning")
        return redirect(url_for("dynamic_forms.dashboard"))
    if request.method == "POST":
        try:
            save_draft_version(version)
            db.session.commit()
            flash("Taslak kaydedildi.", "success")
            return redirect(url_for("dynamic_forms.edit_version", version_id=version.id))
        except ValueError as error:
            db.session.rollback()
            flash_form_error(error)
    return render_template(
        "dynamic_forms/designer.html",
        template=version.template,
        version=version,
        field_types=FIELD_TYPE_OPTIONS,
        form_data=request.form,
        designer_rows=designer_rows(version),
    )


@bp.post("/surum/<int:version_id>/yayinla")
def publish_version(version_id):
    require_permission("dynamic_forms.manage")
    version = get_version_or_404(version_id)
    if version.status != "draft":
        abort(409)
    if not version.fields:
        flash("Alan eklenmeden form yayınlanamaz.", "danger")
        return redirect(url_for("dynamic_forms.edit_version", version_id=version.id))
    for old_version in version.template.versions:
        if old_version.status == "published":
            old_version.status = "archived"
    version.status = "published"
    version.published_at = datetime.utcnow()
    version.published_by_user_id = g.current_user.id
    version.template.status = "published"
    version.template.current_version_number = version.version_number
    record_audit_event(
        "DynamicFormVersion",
        "form_version_published",
        f"{version.template.code} v{version.version_number} yayınlandı",
        entity_id=version.id,
        details={"template_id": version.template_id, "version": version.version_number},
        commit=False,
    )
    db.session.commit()
    flash("Form sürümü yayınlandı ve artık değiştirilemez.", "success")
    return redirect(url_for("dynamic_forms.dashboard"))


@bp.post("/sablon/<int:template_id>/yeni-surum")
def create_new_version(template_id):
    require_permission("dynamic_forms.manage")
    template = get_template_or_404(template_id)
    if any(version.status == "draft" for version in template.versions):
        draft = next(version for version in template.versions if version.status == "draft")
        return redirect(url_for("dynamic_forms.edit_version", version_id=draft.id))
    source = template.current_version
    if source is None:
        abort(409)
    next_number = max(version.version_number for version in template.versions) + 1
    version = DynamicFormVersion(
        template=template,
        version_number=next_number,
        status="draft",
        name_snapshot=template.name,
        description_snapshot=template.description,
        created_by_user_id=g.current_user.id,
    )
    assign_current_company(version)
    db.session.add(version)
    clone_fields(source, version)
    db.session.commit()
    flash(f"v{next_number} taslağı oluşturuldu.", "success")
    return redirect(url_for("dynamic_forms.edit_version", version_id=version.id))


@bp.post("/sablon/<int:template_id>/kopyala")
def copy_template(template_id):
    require_permission("dynamic_forms.manage")
    source_template = get_template_or_404(template_id)
    source_version = source_template.current_version
    if source_version is None:
        abort(409)
    template = DynamicFormTemplate(
        code=reserve_template_code(),
        name=f"{source_template.name} - Kopya"[:180],
        description=source_template.description,
        status="draft",
        current_version_number=1,
        created_by_user_id=g.current_user.id,
    )
    assign_current_company(template)
    version = DynamicFormVersion(
        template=template,
        version_number=1,
        status="draft",
        name_snapshot=template.name,
        description_snapshot=template.description,
        created_by_user_id=g.current_user.id,
    )
    assign_current_company(version)
    db.session.add(template)
    db.session.add(version)
    clone_fields(source_version, version)
    db.session.commit()
    flash("Form şablonu kopyalandı.", "success")
    return redirect(url_for("dynamic_forms.edit_version", version_id=version.id))


@bp.post("/sablon/<int:template_id>/arsivle")
def archive_template(template_id):
    require_permission("dynamic_forms.manage")
    template = get_template_or_404(template_id)
    template.status = "archived"
    for version in template.versions:
        if version.status == "published":
            version.status = "archived"
    record_audit_event(
        "DynamicFormTemplate",
        "form_template_archived",
        f"{template.code} form şablonu arşivlendi",
        entity_id=template.id,
        commit=False,
    )
    db.session.commit()
    flash("Form şablonu arşivlendi.", "success")
    return redirect(url_for("dynamic_forms.dashboard"))


@bp.route("/surum/<int:version_id>/ata", methods=["GET", "POST"])
def assign_form(version_id):
    require_permission("dynamic_forms.assign", "dynamic_forms.manage")
    version = get_version_or_404(version_id)
    if version.status != "published":
        abort(409)
    if request.method == "POST":
        try:
            target_type = request.form.get("target_type")
            due_date = parse_date(request.form.get("due_date"))
            assignment = DynamicFormAssignment(
                version=version,
                due_date=due_date,
                status="assigned",
                created_by_user_id=g.current_user.id,
            )
            assign_current_company(assignment)
            db.session.add(assignment)
            if target_type == "user":
                user_id = request.form.get("assigned_user_id", type=int)
                user = User.query.filter_by(
                    id=user_id,
                    company_id=current_company_id(),
                    is_active=True,
                ).first()
                if user is None or not user.has_permission("dynamic_forms.respond"):
                    raise ValueError("target_required")
                assignment.assigned_user = user
                recipients = [user]
            elif target_type == "department":
                department = (request.form.get("assigned_department") or "").strip()
                if department not in active_departments():
                    raise ValueError("target_required")
                assignment.assigned_department = department
                recipients = eligible_users_for_department(department)
                if not recipients:
                    raise ValueError("no_eligible_user")
            else:
                raise ValueError("target_required")
            db.session.flush()
            snapshot_assignment_recipients(assignment, recipients)
            target_url = url_for("dynamic_forms.fill_assignment", assignment_id=assignment.id)
            notifications = add_notifications(
                recipients,
                f"{version.name_snapshot} formu size atandı.",
                company_id=assignment.company_id,
                notification_type="task",
                source_key=f"dynamic-form-assignment:{assignment.id}",
                target_url=target_url,
                due_date=assignment.due_date,
            )
            record_audit_event(
                "DynamicFormAssignment",
                "form_assigned",
                f"{version.template.code} formu {assignment.target_label} hedefine atandı",
                entity_id=assignment.id,
                details={
                    "version_id": version.id,
                    "target_type": target_type,
                    "target": assignment.target_label,
                    "due_date": assignment.due_date,
                    "recipient_count": len(notifications),
                },
                commit=False,
            )
            db.session.commit()
            flash("Form atandı ve bildirimler oluşturuldu.", "success")
            return redirect(url_for("dynamic_forms.dashboard"))
        except ValueError as error:
            db.session.rollback()
            flash_form_error(error)
    users = [user for user in active_company_users() if user.has_permission("dynamic_forms.respond")]
    return render_template(
        "dynamic_forms/assignment_form.html",
        version=version,
        users=users,
        departments=active_departments(),
        form_data=request.form,
    )


def parse_answer(field):
    name = f"field_{field.id}"
    if field.field_type == "multiple_choice":
        values = [value for value in request.form.getlist(name) if value in field.options]
        value = values
        missing = not values
    else:
        raw_value = (request.form.get(name) or "").strip()
        missing = not raw_value
        if field.field_type == "number" and raw_value:
            try:
                value = str(Decimal(raw_value.replace(",", ".")))
            except InvalidOperation as error:
                raise ValueError(f"{field.label}: sayısal bir değer girin") from error
        elif field.field_type == "date" and raw_value:
            try:
                value = date.fromisoformat(raw_value).isoformat()
            except ValueError as error:
                raise ValueError(f"{field.label}: geçerli bir tarih girin") from error
        elif field.field_type == "yes_no" and raw_value:
            if raw_value not in {"Evet", "Hayır"}:
                raise ValueError(f"{field.label}: Evet veya Hayır seçin")
            value = raw_value
        elif field.field_type == "single_choice" and raw_value:
            if raw_value not in field.options:
                raise ValueError(f"{field.label}: geçerli bir seçenek seçin")
            value = raw_value
        else:
            value = raw_value[:5000]
    return value, missing


@bp.route("/atama/<int:assignment_id>/doldur", methods=["GET", "POST"])
def fill_assignment(assignment_id):
    require_permission("dynamic_forms.respond")
    assignment = get_assignment_or_404(assignment_id)
    if not assignment_is_for_user(assignment, g.current_user):
        abort(403)
    if assignment.status == "cancelled":
        abort(409)
    submission = submission_for_user(assignment)
    if submission is not None and submission.status == "completed":
        return redirect(url_for("dynamic_forms.submission_detail", submission_id=submission.id))
    if request.method == "POST":
        action = request.form.get("action", "draft")
        completing = action == "complete"
        try:
            parsed = []
            missing_labels = []
            for field in assignment.version.fields:
                value, missing = parse_answer(field)
                parsed.append((field, value))
                if completing and field.is_required and missing:
                    missing_labels.append(field.label)
            if missing_labels:
                raise ValueError("Zorunlu alanları doldurun: " + ", ".join(missing_labels))
            if submission is None:
                submission = DynamicFormSubmission(
                    assignment=assignment,
                    respondent_user_id=g.current_user.id,
                    status="draft",
                )
                assign_current_company(submission)
                db.session.add(submission)
                db.session.flush()
            existing = {answer.field_id: answer for answer in submission.answers}
            for field, value in parsed:
                answer = existing.get(field.id)
                if answer is None:
                    answer = DynamicFormAnswer(submission=submission, field=field)
                    assign_current_company(answer)
                    db.session.add(answer)
                answer.value_json = json.dumps(value, ensure_ascii=False)
            if completing:
                submission.status = "completed"
                submission.submitted_at = datetime.utcnow()
                db.session.flush()
                refresh_assignment_status(assignment)
                Notification.query.filter_by(
                    company_id=assignment.company_id,
                    user_id=g.current_user.id,
                    source_key=f"dynamic-form-assignment:{assignment.id}",
                ).update({Notification.is_read: True}, synchronize_session=False)
                if assignment.created_by is not None and assignment.created_by.id != g.current_user.id:
                    add_user_notification(
                        assignment.created_by,
                        f"{assignment.version.name_snapshot} formu {g.current_user.full_name} tarafından tamamlandı.",
                        company_id=assignment.company_id,
                        notification_type="success",
                        source_key=f"dynamic-form-completed:{submission.id}",
                        target_url=url_for(
                            "dynamic_forms.submission_detail",
                            submission_id=submission.id,
                        ),
                    )
                record_audit_event(
                    "DynamicFormSubmission",
                    "form_submission_completed",
                    f"{assignment.version.template.code} form yanıtı tamamlandı",
                    entity_id=submission.id,
                    details={
                        "assignment_id": assignment.id,
                        "version_id": assignment.version_id,
                        "respondent_user_id": g.current_user.id,
                        "answered_field_ids": [field.id for field, _value in parsed],
                    },
                    commit=False,
                )
                mark_readiness_complete()
            db.session.commit()
            flash(
                "Form tamamlanarak gönderildi." if completing else "Form taslağı kaydedildi.",
                "success",
            )
            if completing:
                return redirect(url_for("dynamic_forms.submission_detail", submission_id=submission.id))
            return redirect(url_for("dynamic_forms.fill_assignment", assignment_id=assignment.id))
        except ValueError as error:
            db.session.rollback()
            flash(str(error), "danger")
    if request.method == "POST":
        answer_values = {
            field.id: (
                request.form.getlist(f"field_{field.id}")
                if field.field_type == "multiple_choice"
                else request.form.get(f"field_{field.id}", "")
            )
            for field in assignment.version.fields
        }
    else:
        answer_values = {
            answer.field_id: answer.value
            for answer in (submission.answers if submission else [])
        }
    return render_template(
        "dynamic_forms/fill.html",
        assignment=assignment,
        submission=submission,
        answer_values=answer_values,
    )


@bp.get("/sonuc/<int:submission_id>")
def submission_detail(submission_id):
    submission = submission_query().filter_by(id=submission_id).first_or_404()
    if not (
        can_manage_forms()
        or can_export_forms()
        or submission.respondent_user_id == g.current_user.id
    ):
        abort(403)
    answers = {answer.field_id: answer.value for answer in submission.answers}
    return render_template(
        "dynamic_forms/detail.html",
        submission=submission,
        answers=answers,
        can_export=can_export_forms(),
    )


@bp.get("/surum/<int:version_id>/sonuclar")
def version_results(version_id):
    require_permission("dynamic_forms.manage", "dynamic_forms.export")
    version = get_version_or_404(version_id)
    submissions = (
        submission_query()
        .join(DynamicFormAssignment)
        .filter(DynamicFormAssignment.version_id == version.id)
        .order_by(DynamicFormSubmission.submitted_at.desc(), DynamicFormSubmission.id.desc())
        .all()
    )
    return render_template(
        "dynamic_forms/results.html",
        version=version,
        submissions=submissions,
        can_export=can_export_forms(),
    )


def answer_display(value):
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    if value is None:
        return ""
    return str(value)


@bp.get("/surum/<int:version_id>/excel")
def export_version(version_id):
    require_permission("dynamic_forms.export", "dynamic_forms.manage")
    version = get_version_or_404(version_id)
    submissions = (
        submission_query()
        .join(DynamicFormAssignment)
        .filter(DynamicFormAssignment.version_id == version.id)
        .order_by(DynamicFormSubmission.id.asc())
        .all()
    )
    fields = list(version.fields)
    rows = []
    for submission in submissions:
        values = {answer.field_id: answer.value for answer in submission.answers}
        rows.append(
            (
                version.template.code,
                f"v{version.version_number}",
                submission.assignment.target_label,
                submission.respondent.full_name,
                "Tamamlandı" if submission.status == "completed" else "Taslak",
                submission.submitted_at.strftime("%d.%m.%Y %H:%M") if submission.submitted_at else "",
                *(answer_display(values.get(field.id)) for field in fields),
            )
        )
    from .routes import build_simple_xlsx

    workbook = build_simple_xlsx(
        ("Form Kodu", "Sürüm", "Atanan", "Yanıtlayan", "Durum", "Gönderim", *(field.label for field in fields)),
        rows,
        sheet_name="Form Sonuçları",
        column_widths=(16, 10, 24, 24, 14, 20, *([24] * len(fields))),
    )
    record_audit_event(
        "DynamicFormVersion",
        "form_results_exported",
        f"{version.template.code} v{version.version_number} sonuçları Excel olarak indirildi",
        entity_id=version.id,
        details={"submission_count": len(submissions), "field_count": len(fields)},
    )
    return send_file(
        workbook,
        as_attachment=True,
        download_name=f"{version.template.code.lower()}-v{version.version_number}-sonuclar.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def assigned_task_rows(scope, row_builder):
    if not module_enabled() or getattr(g, "current_user", None) is None:
        return []
    query = assignment_query()
    if scope == "created":
        query = query.filter_by(created_by_user_id=g.current_user.id)
    rows = []
    for assignment in query.all():
        if scope != "created" and not assignment_is_for_user(assignment, g.current_user):
            continue
        submission = submission_for_user(assignment)
        _completed_count, _recipient_count, is_completed = assignment_progress(assignment)
        if is_completed:
            status, status_key = "Tamamlandı", "completed"
        elif assignment.status == "cancelled":
            status, status_key = "İptal", "cancelled"
        elif assignment.due_date and assignment.due_date < date.today():
            status, status_key = "Gecikti", "delayed"
        elif submission:
            status, status_key = "Taslak", "draft"
        else:
            status, status_key = "Yanıt Bekliyor", "pending"
        if scope == "created":
            detail_url = url_for(
                "dynamic_forms.version_results",
                version_id=assignment.version_id,
            )
        else:
            detail_url = (
                url_for("dynamic_forms.submission_detail", submission_id=submission.id)
                if submission and submission.status == "completed"
                else url_for("dynamic_forms.fill_assignment", assignment_id=assignment.id)
            )
        rows.append(
            row_builder(
                module_key="dynamic_form",
                module_label="Dinamik Form",
                module_icon="ui-checks-grid",
                module_tone="quality",
                title=assignment.version.name_snapshot,
                description=f"{assignment.version.template.code} v{assignment.version.version_number}",
                reference_no=f"DF-A-{assignment.id:04d}",
                department=assignment.assigned_department or "Kişisel Atama",
                due_date=assignment.due_date,
                status=status,
                status_key=status_key,
                priority="Yüksek" if status_key == "delayed" else "Orta",
                detail_url=detail_url,
                created_at=assignment.created_at,
                sort_id=assignment.id,
            )
        )
    return rows
