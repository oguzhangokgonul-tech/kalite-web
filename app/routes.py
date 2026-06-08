from datetime import date, datetime
from functools import wraps
from pathlib import Path
import re
from uuid import uuid4

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
from werkzeug.utils import secure_filename
from sqlalchemy import inspect, or_, text
from sqlalchemy.exc import OperationalError

from .extensions import db
from .internal_audit_data import INTERNAL_AUDIT_QUESTION_BANK, INTERNAL_AUDIT_RESULTS
from .mail import send_action_notification_email, send_dof_notification_email
from .models import (
    Action,
    ActionComment,
    ActionClosureFile,
    ActionHistory,
    AppSetting,
    DEPARTMENTS,
    DOF_APPROVAL_STEPS,
    DOF_PRIORITIES,
    DOF_SOURCES,
    Dof,
    DofComment,
    DofFile,
    InternalAudit,
    InternalAuditAnswer,
    InternalAuditQuestion,
    Notification,
    ORGANIZATION_NODE_TYPES,
    OrientationNode,
    User,
)


bp = Blueprint("main", __name__)
HEX_COLOR_PATTERN = re.compile(r"^#[0-9a-fA-F]{6}$")
ALLOWED_EXTENSIONS = {
    "pdf",
    "doc",
    "docx",
    "xls",
    "xlsx",
    "jpg",
    "jpeg",
    "png",
    "webp",
}
DOF_EVIDENCE_EXTENSIONS = {"pdf", "jpg", "jpeg", "png"}
DOF_OPENING_FILE_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
DOF_EVIDENCE_MAX_BYTES = 10 * 1024 * 1024
INTERNAL_AUDIT_RESULT_MAP = {
    value: {"label": label, "tone": tone}
    for value, label, tone in INTERNAL_AUDIT_RESULTS
}
INTERNAL_AUDIT_FINDING_REQUIRED_RESULTS = {"Hayır", "Kısmen"}


@bp.app_errorhandler(403)
def forbidden(error):
    return render_template("403.html"), 403


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


@bp.before_app_request
def load_logged_in_user():
    user_id = session.get("user_id")
    g.current_user = User.query.get(user_id) if user_id else None
    g.current_user_initials = ""
    g.unread_notification_count = 0
    g.latest_notifications = []
    if g.current_user is not None:
        g.current_user_initials = user_initials(g.current_user)
        ensure_notification_dof_column()
        ensure_dof_rejection_schema()
        ensure_dof_files_schema()
        try:
            notification_query = Notification.query.filter_by(user_id=g.current_user.id)
            g.unread_notification_count = notification_query.filter_by(
                is_read=False
            ).count()
            g.latest_notifications = (
                notification_query.order_by(Notification.created_at.desc())
                .limit(5)
                .all()
            )
        except OperationalError:
            db.session.rollback()
            current_app.logger.exception("Bildirimler yüklenemedi.")


def ensure_notification_dof_column():
    if current_app.extensions.get("notification_dof_column_checked"):
        return

    try:
        inspector = inspect(db.engine)
        if "notifications" in inspector.get_table_names():
            columns = {
                column["name"] for column in inspector.get_columns("notifications")
            }
            if "dof_id" not in columns:
                with db.engine.begin() as connection:
                    connection.execute(
                        text("ALTER TABLE notifications ADD COLUMN dof_id INTEGER")
                    )
        current_app.extensions["notification_dof_column_checked"] = True
    except OperationalError as error:
        if "duplicate column name" in str(error).lower():
            current_app.extensions["notification_dof_column_checked"] = True
            return
        db.session.rollback()
        current_app.logger.exception("DÖF bildirim kolonu kontrol edilemedi.")


def ensure_dof_rejection_schema():
    if current_app.extensions.get("dof_rejection_schema_checked"):
        return

    try:
        inspector = inspect(db.engine)
        tables = set(inspector.get_table_names())
        if "dofs" in tables:
            columns = {column["name"] for column in inspector.get_columns("dofs")}
            column_sql = {
                "rejection_reason": "ALTER TABLE dofs ADD COLUMN rejection_reason TEXT",
                "rejected_by_user_id": "ALTER TABLE dofs ADD COLUMN rejected_by_user_id INTEGER",
                "rejected_at": "ALTER TABLE dofs ADD COLUMN rejected_at DATETIME",
                "rejected_step": "ALTER TABLE dofs ADD COLUMN rejected_step VARCHAR(40)",
            }
            with db.engine.begin() as connection:
                for column_name, statement in column_sql.items():
                    if column_name not in columns:
                        connection.execute(text(statement))
                if "dof_comments" not in tables:
                    connection.execute(
                        text(
                            """
                            CREATE TABLE dof_comments (
                                id INTEGER PRIMARY KEY,
                                dof_id INTEGER NOT NULL,
                                user_id INTEGER,
                                comment TEXT NOT NULL,
                                comment_type VARCHAR(40) NOT NULL DEFAULT 'note',
                                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                            )
                            """
                        )
                    )
        current_app.extensions["dof_rejection_schema_checked"] = True
    except OperationalError:
        db.session.rollback()
        current_app.logger.exception("DÖF red/revizyon şeması kontrol edilemedi.")


def ensure_dof_files_schema():
    if current_app.extensions.get("dof_files_schema_checked"):
        return

    try:
        inspector = inspect(db.engine)
        tables = set(inspector.get_table_names())
        if "dofs" in tables and "dof_files" not in tables:
            with db.engine.begin() as connection:
                connection.execute(
                    text(
                        """
                        CREATE TABLE dof_files (
                            id INTEGER PRIMARY KEY,
                            dof_id INTEGER NOT NULL,
                            original_name VARCHAR(255) NOT NULL,
                            stored_name VARCHAR(255) NOT NULL,
                            mime_type VARCHAR(120),
                            file_type VARCHAR(40) NOT NULL DEFAULT 'opening',
                            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                        )
                        """
                    )
                )
        current_app.extensions["dof_files_schema_checked"] = True
    except OperationalError:
        db.session.rollback()
        current_app.logger.exception("DÖF dosya şeması kontrol edilemedi.")


def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if g.current_user is None:
            return redirect(url_for("main.login", next=request.full_path))
        return view(*args, **kwargs)

    return wrapped_view


def permission_required(permission):
    def decorator(view):
        @wraps(view)
        def wrapped_view(*args, **kwargs):
            if g.current_user is None:
                return redirect(url_for("main.login", next=request.full_path))
            if not getattr(g.current_user, permission, False):
                abort(403)
            return view(*args, **kwargs)

        return wrapped_view

    return decorator


def is_assigned_to_current_user(action):
    return (
        g.current_user is not None
        and action.responsible_user_id is not None
        and action.responsible_user_id == g.current_user.id
    )


def is_related_to_current_user(action):
    return (
        g.current_user is not None
        and g.current_user.id
        in {action.related_user_1_id, action.related_user_2_id}
    )


def is_oguzhan_admin():
    return g.current_user is not None and g.current_user.username == "oguzhan"


def normalize_for_role(value):
    replacements = str.maketrans(
        {
            "ç": "c",
            "Ç": "c",
            "ğ": "g",
            "Ğ": "g",
            "ı": "i",
            "I": "i",
            "İ": "i",
            "ö": "o",
            "Ö": "o",
            "ş": "s",
            "Ş": "s",
            "ü": "u",
            "Ü": "u",
        }
    )
    return (value or "").translate(replacements).lower()


def user_title_has(user, expected_title):
    return normalize_for_role(expected_title) in normalize_for_role(
        getattr(user, "title", "")
    )


def is_management_representative(user=None):
    user = user or g.current_user
    return user is not None and (
        user.username == "oguzhan" or user_title_has(user, "Yönetim Temsilcisi")
    )


def is_deputy_general_manager(user=None):
    user = user or g.current_user
    return user is not None and (
        user.username == "oguzhan" or user_title_has(user, "Genel Müdür Yardımcısı")
    )


def is_general_manager(user=None):
    user = user or g.current_user
    if user is None:
        return False
    normalized_title = normalize_for_role(getattr(user, "title", ""))
    return "genel mudur" in normalized_title and "yardimci" not in normalized_title


def can_view_all_dofs():
    return (
        is_management_representative()
        or is_deputy_general_manager()
        or is_general_manager()
    )


def can_view_dof(dof):
    return (
        g.current_user is not None
        and (
            can_view_all_dofs()
            or dof.responsible_id == g.current_user.id
        )
    )


def can_delete_dof(dof=None):
    return can_view_all_dofs()


def can_approve_dof_management(dof):
    return (
        is_management_representative()
        and dof.approval_step == "management_representative"
        and dof.status != "Tamamlandı"
    )


def can_approve_dof_deputy(dof):
    return (
        is_deputy_general_manager()
        and dof.approval_step == "general_manager_deputy"
        and dof.status != "Tamamlandı"
    )


def can_reject_dof(dof):
    if (
        g.current_user is None
        or dof.status in {"Taslak", "Tamamlandı"}
        or dof.approval_step not in {"management_representative", "general_manager_deputy"}
    ):
        return False
    return (
        is_general_manager()
        or (
            is_management_representative()
            and dof.approval_step == "management_representative"
        )
        or (
            is_deputy_general_manager()
            and dof.approval_step == "general_manager_deputy"
        )
    )


def can_revise_rejected_dof(dof):
    if (
        g.current_user is None
        or dof.status != "Revizyon Bekleniyor"
        or dof.approval_step != "revision_requested"
    ):
        return False
    if dof.responsible_id == g.current_user.id:
        return True
    return (
        dof.rejected_step == "general_manager_deputy"
        and is_management_representative()
    )


def can_manage_orientation():
    return g.current_user is not None and (
        is_oguzhan_admin() or g.current_user.can_manage_users
    )


def can_complete_action(action):
    if g.current_user is None:
        return False
    return can_approve_closure_action(action)


def can_request_closure_action(action):
    if (
        g.current_user is None
        or is_oguzhan_admin()
        or action.is_completed
        or action.closure_approval_requested
    ):
        return False
    return (
        (
            g.current_user.can_close_assigned_actions
            and is_assigned_to_current_user(action)
        )
        or (
            g.current_user.can_comment_assigned_actions
            and is_related_to_current_user(action)
        )
    )


def can_approve_closure_action(action):
    return (
        is_oguzhan_admin()
        and not action.is_completed
        and action.closure_approval_requested
    )


def can_comment_action(action):
    if g.current_user is None:
        return False
    return is_oguzhan_admin() or (
        g.current_user.can_comment_assigned_actions
        and (is_assigned_to_current_user(action) or is_related_to_current_user(action))
    )


def can_reassign_action(action):
    if g.current_user is None:
        return False
    return is_oguzhan_admin() or (
        g.current_user.can_close_assigned_actions and is_assigned_to_current_user(action)
    )


def can_view_action(action):
    if g.current_user is None:
        return False
    return (
        is_oguzhan_admin()
        or is_assigned_to_current_user(action)
        or is_related_to_current_user(action)
    )


def can_revise_termin(action):
    if g.current_user is None or action.is_completed:
        return False
    return (
        is_oguzhan_admin()
        or is_assigned_to_current_user(action)
        or is_related_to_current_user(action)
    )


def visible_actions_query():
    query = Action.query
    if is_oguzhan_admin():
        return query
    return query.filter(
        or_(
            Action.responsible_user_id == g.current_user.id,
            Action.related_user_1_id == g.current_user.id,
            Action.related_user_2_id == g.current_user.id,
        )
    )


def active_users():
    return User.query.filter_by(is_active=True).order_by(User.full_name.asc()).all()


def user_initials(user):
    parts = (user.full_name or user.username or "").split()
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return f"{parts[0][0]}{parts[-1][0]}".upper()


def oguzhan_user():
    return User.query.filter_by(username="oguzhan", is_active=True).first()


def reserve_action_number():
    max_number = (
        db.session.query(db.func.max(db.func.coalesce(Action.action_number, Action.id)))
        .scalar()
        or 0
    )
    setting = db.session.get(AppSetting, "next_action_number")
    if setting is None:
        setting = AppSetting(key="next_action_number", value=str(max_number + 1))
        db.session.add(setting)

    next_number = int(setting.value)
    if next_number <= max_number:
        next_number = max_number + 1

    setting.value = str(next_number + 1)
    return next_number


def reserve_dof_number(today=None):
    today = today or date.today()
    year = today.year
    prefix = f"DÖF-{year}-"
    existing_numbers = (
        db.session.query(Dof.dof_no)
        .filter(Dof.dof_no.like(f"{prefix}%"))
        .all()
    )
    max_number = 0
    for (dof_no,) in existing_numbers:
        try:
            max_number = max(max_number, int((dof_no or "").replace(prefix, "")))
        except ValueError:
            continue

    setting_key = f"next_dof_number_{year}"
    setting = db.session.get(AppSetting, setting_key)
    if setting is None:
        setting = AppSetting(key=setting_key, value=str(max_number + 1))
        db.session.add(setting)

    next_number = int(setting.value)
    if next_number <= max_number:
        next_number = max_number + 1

    setting.value = str(next_number + 1)
    return f"{prefix}{next_number:04d}"


def reserve_internal_audit_number(today=None):
    today = today or date.today()
    year = today.year
    prefix = f"ICD-{year}-"
    existing_numbers = (
        db.session.query(InternalAudit.audit_no)
        .filter(InternalAudit.audit_no.like(f"{prefix}%"))
        .all()
    )
    max_number = 0
    for (audit_no,) in existing_numbers:
        try:
            max_number = max(max_number, int((audit_no or "").replace(prefix, "")))
        except ValueError:
            continue

    setting_key = f"next_internal_audit_number_{year}"
    setting = db.session.get(AppSetting, setting_key)
    if setting is None:
        setting = AppSetting(key=setting_key, value=str(max_number + 1))
        db.session.add(setting)

    next_number = int(setting.value)
    if next_number <= max_number:
        next_number = max_number + 1

    setting.value = str(next_number + 1)
    return f"{prefix}{next_number:04d}"


def can_view_internal_audit(audit):
    return (
        g.current_user is not None
        and (
            audit.auditor_id == g.current_user.id
            or is_oguzhan_admin()
            or g.current_user.can_manage_users
            or can_view_all_dofs()
        )
    )


def create_internal_audit_for_current_user():
    audit = InternalAudit(
        audit_no=reserve_internal_audit_number(),
        title=f"{date.today().year} İç Denetim",
        auditor_id=g.current_user.id,
        planned_date=date.today(),
        status="Devam Ediyor",
        active_question_order=1,
    )
    db.session.add(audit)
    db.session.flush()

    for order_no, item in enumerate(INTERNAL_AUDIT_QUESTION_BANK, start=1):
        db.session.add(
            InternalAuditQuestion(
                audit=audit,
                order_no=order_no,
                standard=item["standard"],
                audit_topic=item["audit_topic"],
                question_text=item["question_text"],
                evaluated_department=item.get("evaluated_department"),
                is_required=item.get("is_required", True),
            )
        )

    db.session.commit()
    return audit


def current_internal_audit():
    audit = (
        InternalAudit.query.filter(
            InternalAudit.auditor_id == g.current_user.id,
            InternalAudit.status != "Tamamlandı",
        )
        .order_by(InternalAudit.created_at.desc(), InternalAudit.id.desc())
        .first()
    )
    if audit is None:
        audit = create_internal_audit_for_current_user()
    elif not audit.questions:
        for order_no, item in enumerate(INTERNAL_AUDIT_QUESTION_BANK, start=1):
            db.session.add(
                InternalAuditQuestion(
                    audit=audit,
                    order_no=order_no,
                    standard=item["standard"],
                    audit_topic=item["audit_topic"],
                    question_text=item["question_text"],
                    evaluated_department=item.get("evaluated_department"),
                    is_required=item.get("is_required", True),
                )
            )
        db.session.commit()
    return audit


def internal_audit_answer_for_question(audit, question):
    return InternalAuditAnswer.query.filter_by(
        audit_id=audit.id,
        question_id=question.id,
    ).first()


def internal_audit_answer_map(audit):
    return {
        answer.question_id: answer
        for answer in InternalAuditAnswer.query.filter_by(audit_id=audit.id).all()
    }


def completed_internal_audit_answers(audit):
    return [
        answer
        for answer in audit.answers
        if answer.result and not answer.is_draft
    ]


def internal_audit_progress(audit):
    total = len(audit.questions)
    completed = len(completed_internal_audit_answers(audit))
    remaining = max(total - completed, 0)
    percent = int((completed / total) * 100) if total else 0
    return {
        "total": total,
        "completed": completed,
        "remaining": remaining,
        "percent": percent,
    }


def internal_audit_is_complete(audit):
    required_question_ids = {question.id for question in audit.questions if question.is_required}
    completed_question_ids = {
        answer.question_id
        for answer in completed_internal_audit_answers(audit)
    }
    return required_question_ids.issubset(completed_question_ids)


def internal_audit_question_by_order(audit, order_no):
    return InternalAuditQuestion.query.filter_by(
        audit_id=audit.id,
        order_no=order_no,
    ).first()


def internal_audit_next_order(audit, question):
    total = len(audit.questions)
    return min(question.order_no + 1, total) if total else question.order_no


def internal_audit_previous_order(audit, question):
    return max(question.order_no - 1, 1)


def internal_audit_result_meta(result):
    return INTERNAL_AUDIT_RESULT_MAP.get(
        result,
        {"label": result or "Bekliyor", "tone": "secondary"},
    )


def internal_audit_history_items(audit, active_question):
    answers_by_question = internal_audit_answer_map(audit)
    questions = list(audit.questions)
    if not questions:
        return []

    active_index = max(active_question.order_no - 1, 0)
    start = max(active_index - 4, 0)
    end = min(start + 8, len(questions))
    start = max(end - 8, 0)
    items = []
    for question in questions[start:end]:
        answer = answers_by_question.get(question.id)
        result = answer.result if answer and not answer.is_draft else None
        result_meta = internal_audit_result_meta(result)
        items.append(
            {
                "question": question,
                "answer": answer,
                "is_active": question.id == active_question.id,
                "is_complete": bool(answer and answer.result and not answer.is_draft),
                "result": result,
                "result_label": result_meta["label"],
                "tone": result_meta["tone"],
                "date": answer.answered_at or answer.updated_at if answer else None,
            }
        )
    return items


def internal_audit_previous_nonconformities(question, selected_dof_id=None):
    query = Dof.query.filter(Dof.source == "İç Denetim")
    conditions = []
    if question.evaluated_department:
        conditions.append(Dof.department == question.evaluated_department)
    if question.standard:
        conditions.append(Dof.nonconformity_description.ilike(f"%{question.standard}%"))
    if question.audit_topic:
        topic_pattern = f"%{question.audit_topic}%"
        conditions.append(
            or_(
                Dof.title.ilike(topic_pattern),
                Dof.nonconformity_description.ilike(topic_pattern),
            )
        )
    if conditions:
        query = query.filter(or_(*conditions))

    candidates = [
        dof
        for dof in query.order_by(Dof.created_at.desc(), Dof.id.desc()).limit(40).all()
        if can_view_dof(dof)
    ]
    if selected_dof_id and all(dof.id != selected_dof_id for dof in candidates):
        selected_dof = Dof.query.get(selected_dof_id)
        if selected_dof and can_view_dof(selected_dof):
            candidates.insert(0, selected_dof)
    return candidates


def parse_internal_audit_answer_form(audit, question, is_draft=False):
    evaluated_department = (
        request.form.get("evaluated_department", "").strip()
        or question.evaluated_department
        or ""
    )
    result = request.form.get("result", "").strip()
    technical_findings = request.form.get("technical_findings", "").strip()
    previous_nonconformity_id = request.form.get("previous_nonconformity_id", "").strip()

    if len(technical_findings) > 1000:
        raise ValueError("technical_findings_too_long")
    if evaluated_department and evaluated_department not in DEPARTMENTS:
        raise ValueError("invalid_department")
    if result and result not in INTERNAL_AUDIT_RESULT_MAP:
        raise ValueError("invalid_result")
    if not is_draft and (
        not question.standard
        or not question.audit_topic
        or not question.question_text
        or not evaluated_department
        or not result
    ):
        raise ValueError("required_fields")
    if (
        not is_draft
        and result in INTERNAL_AUDIT_FINDING_REQUIRED_RESULTS
        and not technical_findings
    ):
        raise ValueError("technical_findings_required")

    previous_dof = None
    if previous_nonconformity_id:
        try:
            previous_dof_id = int(previous_nonconformity_id)
        except ValueError:
            raise ValueError("invalid_previous_nonconformity") from None
        previous_dof = Dof.query.get(previous_dof_id)
        if previous_dof is None or not can_view_dof(previous_dof):
            raise ValueError("invalid_previous_nonconformity")

    answer = internal_audit_answer_for_question(audit, question)
    if answer is None:
        answer = InternalAuditAnswer(audit=audit, question=question)
        db.session.add(answer)

    answer.standard = question.standard
    answer.audit_topic = question.audit_topic
    answer.question_text = question.question_text
    answer.evaluated_department = evaluated_department
    answer.technical_findings = technical_findings or None
    answer.result = result or None
    answer.previous_nonconformity_id = previous_dof.id if previous_dof else None
    answer.answered_by_user_id = g.current_user.id
    answer.answered_at = datetime.utcnow()
    answer.is_draft = is_draft
    return answer


def internal_audit_dof_prefill(answer):
    finding_text = answer.technical_findings or "Teknik bulgu girilmemiş."
    return {
        "internal_audit_answer_id": str(answer.id),
        "title": short_text(answer.audit_topic or answer.question_text, 150),
        "department": answer.evaluated_department or "",
        "responsible_id": str(g.current_user.id),
        "opening_date": date.today().isoformat(),
        "priority": "Orta",
        "source": "İç Denetim",
        "nonconformity_description": (
            f"Soru: {answer.question_text}\n\n"
            f"İlgili Standart: {answer.standard}\n"
            f"Tetkik Konusu: {answer.audit_topic}\n"
            f"Sonuç: {answer.result or '-'}\n\n"
            f"Teknik Bulgular: {finding_text}"
        ),
        "root_cause_analysis": "",
        "corrective_action": "",
        "preventive_action": "",
    }


def parse_optional_date(field_name):
    value = request.form.get(field_name, "").strip()
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise ValueError("invalid_date") from None


def parse_optional_active_user(field_name):
    value = request.form.get(field_name, "").strip()
    if not value:
        return None
    try:
        user_id = int(value)
    except ValueError:
        raise ValueError("invalid_user") from None
    user = User.query.filter_by(id=user_id, is_active=True).first()
    if user is None:
        raise ValueError("invalid_user")
    return user


def validate_dof_evidence_file(uploaded_file):
    if "." not in uploaded_file.filename:
        raise ValueError("invalid_dof_file_type")
    extension = uploaded_file.filename.rsplit(".", 1)[1].lower()
    if extension not in DOF_EVIDENCE_EXTENSIONS:
        raise ValueError("invalid_dof_file_type")


def validate_dof_opening_file(uploaded_file):
    if "." not in uploaded_file.filename:
        raise ValueError("invalid_dof_opening_file_type")
    extension = uploaded_file.filename.rsplit(".", 1)[1].lower()
    if extension not in DOF_OPENING_FILE_EXTENSIONS:
        raise ValueError("invalid_dof_opening_file_type")


def dof_opening_file_uploads():
    uploaded_files = request.files.getlist("opening_files")
    return [uploaded_file for uploaded_file in uploaded_files if uploaded_file.filename]


def save_dof_opening_files(dof):
    uploaded_files = dof_opening_file_uploads()
    if not uploaded_files:
        return

    for uploaded_file in uploaded_files:
        validate_dof_opening_file(uploaded_file)

    saved_paths = []
    try:
        for uploaded_file in uploaded_files:
            safe_name = secure_filename(uploaded_file.filename) or "dof-gorsel"
            extension = uploaded_file.filename.rsplit(".", 1)[1].lower()
            stored_name = f"dof-opening-{uuid4().hex}.{extension}"
            upload_path = Path(current_app.config["UPLOAD_FOLDER"]) / stored_name
            uploaded_file.save(upload_path)
            saved_paths.append(upload_path)
            if upload_path.stat().st_size > DOF_EVIDENCE_MAX_BYTES:
                raise ValueError("dof_opening_file_too_large")
            db.session.add(
                DofFile(
                    dof=dof,
                    original_name=safe_name,
                    stored_name=stored_name,
                    mime_type=uploaded_file.mimetype,
                    file_type="opening",
                )
            )
    except ValueError:
        for saved_path in saved_paths:
            if saved_path.exists():
                saved_path.unlink()
        raise


def save_dof_evidence_file(dof):
    uploaded_file = request.files.get("evidence_file")
    if not uploaded_file or not uploaded_file.filename:
        return

    validate_dof_evidence_file(uploaded_file)
    safe_name = secure_filename(uploaded_file.filename) or "dof-kanit"
    extension = safe_name.rsplit(".", 1)[1].lower()
    stored_name = f"dof-{uuid4().hex}.{extension}"
    upload_path = Path(current_app.config["UPLOAD_FOLDER"]) / stored_name
    uploaded_file.save(upload_path)
    if upload_path.stat().st_size > DOF_EVIDENCE_MAX_BYTES:
        upload_path.unlink(missing_ok=True)
        raise ValueError("dof_file_too_large")

    dof.evidence_original_name = safe_name
    dof.evidence_stored_name = stored_name
    dof.evidence_mime_type = uploaded_file.mimetype


def delete_dof_evidence_file(dof):
    for dof_file in list(dof.files):
        file_path = Path(current_app.config["UPLOAD_FOLDER"]) / dof_file.stored_name
        if file_path.exists():
            file_path.unlink()
        db.session.delete(dof_file)

    if dof.evidence_stored_name:
        file_path = Path(current_app.config["UPLOAD_FOLDER"]) / dof.evidence_stored_name
        if file_path.exists():
            file_path.unlink()

    dof.evidence_original_name = None
    dof.evidence_stored_name = None
    dof.evidence_mime_type = None


def parse_optional_user(field_name):
    value = request.form.get(field_name, "").strip()
    if not value:
        return None

    try:
        user_id = int(value)
    except ValueError:
        raise ValueError("invalid_user") from None

    user = User.query.filter_by(id=user_id, is_active=True).first()
    if user is None:
        raise ValueError("invalid_user")
    return user


def user_name(user_id):
    if not user_id:
        return "-"
    user = User.query.get(user_id)
    return user.full_name if user else "-"


def format_date(value):
    return value.strftime("%d.%m.%Y") if value else "-"


def action_snapshot(action):
    return {
        "title": action.title,
        "responsible_user_id": action.responsible_user_id,
        "related_user_1_id": action.related_user_1_id,
        "related_user_2_id": action.related_user_2_id,
        "department": action.department,
        "description": action.description or "",
        "termin_date": action.termin_date,
        "file_original_name": action.file_original_name,
    }


def describe_action_changes(before, action):
    changes = []
    if before["title"] != action.title:
        changes.append(f"başlığı \"{before['title']}\" -> \"{action.title}\"")
    if before["responsible_user_id"] != action.responsible_user_id:
        changes.append(
            "sorumlusu "
            f"{user_name(before['responsible_user_id'])} -> {user_name(action.responsible_user_id)}"
        )
    if before["related_user_1_id"] != action.related_user_1_id:
        changes.append(
            "İlgili 1 "
            f"{user_name(before['related_user_1_id'])} -> {user_name(action.related_user_1_id)}"
        )
    if before["related_user_2_id"] != action.related_user_2_id:
        changes.append(
            "İlgili 2 "
            f"{user_name(before['related_user_2_id'])} -> {user_name(action.related_user_2_id)}"
        )
    if before["department"] != action.department:
        changes.append(f"departmanı {before['department']} -> {action.department}")
    if before["termin_date"] != action.termin_date:
        changes.append(
            f"termini {format_date(before['termin_date'])} -> {format_date(action.termin_date)}"
        )
    if before["description"] != (action.description or ""):
        changes.append("açıklaması güncellendi")
    if before["file_original_name"] != action.file_original_name:
        changes.append("dosyası güncellendi")
    return changes


def add_action_history(action, event_type, message, actor=None):
    history = ActionHistory(
        action=action,
        actor_user_id=actor.id if actor else None,
        event_type=event_type,
        message=message,
    )
    db.session.add(history)
    return history


def notify_users(user_ids, action, message, exclude_user_id=None):
    target_user_ids = {user_id for user_id in user_ids if user_id}
    if exclude_user_id:
        target_user_ids.discard(exclude_user_id)

    users = (
        User.query.filter(User.id.in_(target_user_ids), User.is_active.is_(True)).all()
        if target_user_ids
        else []
    )

    for user in users:
        user_id = user.id
        if exclude_user_id and user_id == exclude_user_id:
            continue
        db.session.add(
            Notification(
                user_id=user_id,
                action=action,
                message=message,
            )
        )
    send_action_notification_email(users, action, message)


def notify_action_participants(action, message, exclude_user_id=None, extra_user_ids=None):
    user_ids = set(action.participant_user_ids())
    if extra_user_ids:
        user_ids.update(extra_user_ids)
    notify_users(user_ids, action, message, exclude_user_id=exclude_user_id)


def unique_users(users):
    unique_by_id = {}
    for user in users:
        if user is not None and user.id:
            unique_by_id[user.id] = user
    return list(unique_by_id.values())


def dof_management_approver_users():
    return unique_users(
        user for user in active_users() if is_management_representative(user)
    )


def dof_deputy_approver_users():
    users = [
        user for user in active_users() if user_title_has(user, "Genel Müdür Yardımcısı")
    ]
    if not users:
        users = [oguzhan_user()]
    return unique_users(users)


def dof_primary_users(dof):
    return unique_users([dof.responsible, dof.created_by])


def add_dof_comment(dof, message, comment_type="note", actor=None):
    comment = DofComment(
        dof=dof,
        user_id=actor.id if actor else None,
        comment=message,
        comment_type=comment_type,
    )
    db.session.add(comment)
    return comment


def dof_approver_label(step):
    if step == "general_manager_deputy":
        return "Genel Müdür Yardımcısı"
    if step == "management_representative":
        return "Yönetim Temsilcisi"
    return "Onay"


def dof_rejection_recipients(dof, rejected_step):
    recipients = dof_primary_users(dof)
    if rejected_step == "general_manager_deputy":
        recipients.extend(dof_management_approver_users())
    return unique_users(recipients)


def dof_label(dof):
    return dof.dof_no or "DÖF kaydı"


def notify_dof_users(users, dof, message, exclude_user_id=None):
    users = [
        user
        for user in unique_users(users)
        if getattr(user, "is_active", True)
        and not (exclude_user_id and user.id == exclude_user_id)
    ]

    for user in users:
        db.session.add(
            Notification(
                user_id=user.id,
                dof=dof,
                message=message,
            )
        )
    send_dof_notification_email(users, dof, message)


def notify_dof_waiting_approvers(dof):
    if dof.approval_step == "management_representative":
        notify_dof_users(
            dof_management_approver_users(),
            dof,
            f"{dof_label(dof)} için Yönetim Temsilcisi onayınız bekleniyor.",
        )
    elif dof.approval_step == "general_manager_deputy":
        notify_dof_users(
            dof_deputy_approver_users(),
            dof,
            f"{dof_label(dof)} için Genel Müdür Yardımcısı onayınız bekleniyor.",
        )


def orientation_nodes_payload():
    nodes = (
        OrientationNode.query.order_by(
            OrientationNode.y.asc(),
            OrientationNode.x.asc(),
            OrientationNode.id.asc(),
        )
        .all()
    )
    payloads = [node.to_dict() for node in nodes]
    payload_by_id = {payload["id"]: payload for payload in payloads}
    child_map = {}
    for payload in payloads:
        child_map.setdefault(payload["parent_id"], []).append(payload["id"])

    def descendant_person_count(node_id):
        total = 0
        for child_id in child_map.get(node_id, []):
            child = payload_by_id[child_id]
            if child["node_type"] == "person":
                total += 1
            total += descendant_person_count(child_id)
        return total

    for payload in payloads:
        payload["descendant_count"] = descendant_person_count(payload["id"])
    return payloads


def parse_node_parent(parent_id, current_node=None):
    if parent_id in (None, "", "null"):
        return None

    try:
        parent_id = int(parent_id)
    except (TypeError, ValueError):
        raise ValueError("invalid_parent") from None

    parent = OrientationNode.query.get(parent_id)
    if parent is None:
        raise ValueError("invalid_parent")

    if current_node is not None:
        check_parent = parent
        while check_parent is not None:
            if check_parent.id == current_node.id:
                raise ValueError("invalid_parent")
            check_parent = check_parent.parent

    return parent


def parse_coordinate(data, key, default):
    try:
        value = int(float(data.get(key, default)))
    except (TypeError, ValueError):
        value = default
    return max(20, min(value, 4000))


def parse_node_color(value):
    value = (value or "").strip()
    if HEX_COLOR_PATTERN.match(value):
        return value.lower()
    return "#198754"


def short_text(value, length=90):
    value = " ".join((value or "").split())
    if len(value) <= length:
        return value
    return f"{value[: length - 3]}..."


def dashboard_filters():
    return {
        "search": request.args.get("search", "").strip(),
        "department": request.args.get("department", "").strip(),
        "responsible_user_id": request.args.get("responsible_user_id", "").strip(),
        "status": request.args.get("status", "").strip(),
    }


def filtered_actions(actions, filters):
    search = filters["search"].lower()
    department = filters["department"]
    responsible_user_id = filters["responsible_user_id"]
    status = filters["status"]

    if responsible_user_id:
        try:
            responsible_user_id = int(responsible_user_id)
        except ValueError:
            responsible_user_id = None

    result = []
    for action in actions:
        if search and search not in " ".join(
            [
                action.title or "",
                action.description or "",
                action.responsible_owner or "",
                action.related_user_1.full_name if action.related_user_1 else "",
                action.related_user_2.full_name if action.related_user_2 else "",
                action.department or "",
            ]
        ).lower():
            continue
        if department and action.department != department:
            continue
        if responsible_user_id and action.responsible_user_id != responsible_user_id:
            continue
        if status == "open" and (
            action.is_completed
            or action.closure_approval_requested
            or action.closure_rejection_reason
            or action.delay_days > 0
        ):
            continue
        if status == "pending" and (
            action.is_completed or not action.closure_approval_requested
        ):
            continue
        if status == "rejected" and (
            action.is_completed
            or action.closure_approval_requested
            or not action.closure_rejection_reason
        ):
            continue
        if status == "delayed" and (action.is_completed or action.delay_days == 0):
            continue
        if status == "completed" and not action.is_completed:
            continue
        result.append(action)

    return result


def dof_display_status(dof, today=None):
    if dof.status == "Taslak" or dof.approval_step == "draft":
        return "Taslak"
    if dof.status == "Revizyon Bekleniyor" or dof.approval_step == "revision_requested":
        return "Revizyon Bekleniyor"
    if dof.status == "Tamamlandı" or dof.approval_step == "completed":
        return "Tamamlandı"
    if dof.approval_step in {
        "management_representative",
        "general_manager_deputy",
    }:
        return "Onay Akışı Bekleniyor"
    return dof.status or "Onay Akışı Bekleniyor"


def dof_delay_days(dof, today=None):
    today = today or date.today()
    if dof.status in {"Taslak", "Tamamlandı"} or not dof.due_date:
        return 0
    return max((today - dof.due_date).days, 0)


def attach_dof_view_state(dofs):
    today = date.today()
    for dof in dofs:
        if dof.approval_step not in DOF_APPROVAL_STEPS:
            dof.approval_step = "draft" if dof.status == "Taslak" else "management_representative"
        dof.display_status = dof_display_status(dof, today=today)
        dof.delay_days = dof_delay_days(dof, today=today)
    return dofs


def dof_approval_steps(dof):
    step = dof.approval_step or "draft"
    is_rejected = step == "revision_requested" or dof.status == "Revizyon Bekleniyor"
    rejected_step = dof.rejected_step if is_rejected else None
    return [
        {
            "key": "opened",
            "title": "DÖF Açılması",
            "status": "Tamamlandı" if step != "draft" else "Beklemede",
            "is_active": step == "draft",
            "is_complete": step != "draft",
            "actor": dof.created_by.full_name if dof.created_by else "",
            "date": dof.created_at,
        },
        {
            "key": "management_representative",
            "title": "Yönetim Temsilcisi",
            "status": "Reddedildi"
            if rejected_step == "management_representative"
            else (
                "Tamamlandı"
                if dof.management_approved_at
                else ("Onay Bekliyor" if step == "management_representative" else "Beklemede")
            ),
            "is_active": step == "management_representative"
            or rejected_step == "management_representative",
            "is_complete": bool(dof.management_approved_at)
            or step in {"general_manager_deputy", "completed"},
            "is_rejected": rejected_step == "management_representative",
            "actor": (
                dof.rejected_by.full_name
                if rejected_step == "management_representative" and dof.rejected_by
                else (
                    dof.management_approved_by.full_name
                    if dof.management_approved_by
                    else ""
                )
            ),
            "date": (
                dof.rejected_at
                if rejected_step == "management_representative"
                else dof.management_approved_at
            ),
        },
        {
            "key": "general_manager_deputy",
            "title": "Genel Müdür Yardımcısı",
            "status": "Reddedildi"
            if rejected_step == "general_manager_deputy"
            else (
                "Tamamlandı"
                if dof.deputy_approved_at
                else ("Onay Bekliyor" if step == "general_manager_deputy" else "Beklemede")
            ),
            "is_active": step == "general_manager_deputy"
            or rejected_step == "general_manager_deputy",
            "is_complete": bool(dof.deputy_approved_at) or step == "completed",
            "is_rejected": rejected_step == "general_manager_deputy",
            "actor": (
                dof.rejected_by.full_name
                if rejected_step == "general_manager_deputy" and dof.rejected_by
                else (
                    dof.deputy_approved_by.full_name
                    if dof.deputy_approved_by
                    else ""
                )
            ),
            "date": (
                dof.rejected_at
                if rejected_step == "general_manager_deputy"
                else dof.deputy_approved_at
            ),
        },
    ]


def visible_dofs_query():
    query = Dof.query
    if can_view_all_dofs():
        return query
    return query.filter(Dof.responsible_id == g.current_user.id)


def dof_filters():
    return {
        "search": request.args.get("search", "").strip(),
        "department": request.args.get("department", "").strip(),
        "responsible_id": request.args.get("responsible_id", "").strip(),
        "status": request.args.get("status", "").strip(),
    }


def filtered_dofs(dofs, filters):
    search = filters["search"].lower()
    department = filters["department"]
    responsible_id = filters["responsible_id"]
    status = filters["status"]

    if responsible_id:
        try:
            responsible_id = int(responsible_id)
        except ValueError:
            responsible_id = None

    result = []
    for dof in dofs:
        if search and search not in " ".join(
            [
                dof.dof_no or "",
                dof.title or "",
                dof.nonconformity_description or "",
                dof.department or "",
                dof.priority or "",
                dof.source or "",
                dof.responsible.full_name if dof.responsible else "",
            ]
        ).lower():
            continue
        if department and dof.department != department:
            continue
        if responsible_id and dof.responsible_id != responsible_id:
            continue
        if status == "draft" and dof.display_status != "Taslak":
            continue
        if status == "approval" and dof.display_status != "Onay Akışı Bekleniyor":
            continue
        if status == "revision" and dof.display_status != "Revizyon Bekleniyor":
            continue
        if status == "completed" and dof.display_status != "Tamamlandı":
            continue
        if status == "delayed" and (
            dof.display_status == "Tamamlandı" or dof.delay_days == 0
        ):
            continue
        result.append(dof)

    return result


def delete_uploaded_file(action):
    if not action.file_stored_name:
        return

    file_path = Path(current_app.config["UPLOAD_FOLDER"]) / action.file_stored_name
    if file_path.exists():
        file_path.unlink()

    action.file_original_name = None
    action.file_stored_name = None
    action.file_mime_type = None


def store_uploaded_file(uploaded_file):
    if not allowed_file(uploaded_file.filename):
        raise ValueError("invalid_file_type")

    safe_name = secure_filename(uploaded_file.filename)
    extension = safe_name.rsplit(".", 1)[1].lower()
    stored_name = f"{uuid4().hex}.{extension}"
    upload_path = Path(current_app.config["UPLOAD_FOLDER"]) / stored_name
    uploaded_file.save(upload_path)
    return safe_name, stored_name, uploaded_file.mimetype


def save_uploaded_file(action):
    uploaded_file = request.files.get("action_file")
    if not uploaded_file or not uploaded_file.filename:
        return

    delete_uploaded_file(action)
    safe_name, stored_name, mime_type = store_uploaded_file(uploaded_file)

    action.file_original_name = safe_name
    action.file_stored_name = stored_name
    action.file_mime_type = mime_type


def delete_closure_evidence_file(action):
    for closure_file in list(action.closure_files):
        file_path = Path(current_app.config["UPLOAD_FOLDER"]) / closure_file.stored_name
        if file_path.exists():
            file_path.unlink()
        db.session.delete(closure_file)

    if action.closure_file_stored_name:
        file_path = Path(current_app.config["UPLOAD_FOLDER"]) / action.closure_file_stored_name
        if file_path.exists():
            file_path.unlink()

    action.closure_file_original_name = None
    action.closure_file_stored_name = None
    action.closure_file_mime_type = None


def closure_evidence_uploads():
    uploaded_files = request.files.getlist("closure_files")
    if not uploaded_files:
        uploaded_file = request.files.get("closure_file")
        uploaded_files = [uploaded_file] if uploaded_file else []
    return [uploaded_file for uploaded_file in uploaded_files if uploaded_file.filename]


def save_closure_evidence_files(action):
    uploaded_files = closure_evidence_uploads()
    for uploaded_file in uploaded_files:
        if not allowed_file(uploaded_file.filename):
            raise ValueError("invalid_file_type")

    delete_closure_evidence_file(action)
    for uploaded_file in uploaded_files:
        safe_name, stored_name, mime_type = store_uploaded_file(uploaded_file)
        db.session.add(
            ActionClosureFile(
                action=action,
                original_name=safe_name,
                stored_name=stored_name,
                mime_type=mime_type,
            )
        )


def refresh_all_actions():
    actions = visible_actions_query().order_by(Action.termin_date.asc(), Action.id.asc()).all()
    changed = False
    for action in actions:
        old_delay_days = action.delay_days
        action.refresh_delay()
        changed = changed or old_delay_days != action.delay_days

    if changed:
        db.session.commit()

    return actions


def parse_action_form(action=None):
    action = action or Action()
    title = request.form.get("title", "").strip()
    responsible_user_id = request.form.get("responsible_user_id", "").strip()
    department = request.form.get("department", "").strip()

    if not title or not responsible_user_id or not department:
        raise ValueError("required_fields")
    if department not in DEPARTMENTS:
        raise ValueError("invalid_department")

    try:
        responsible_user_id = int(responsible_user_id)
    except ValueError:
        raise ValueError("invalid_user") from None

    responsible_user = User.query.filter_by(
        id=responsible_user_id, is_active=True
    ).first()
    if responsible_user is None:
        raise ValueError("invalid_user")
    related_user_1 = parse_optional_user("related_user_1_id")
    related_user_2 = parse_optional_user("related_user_2_id")

    action.title = title
    action.responsible_user_id = responsible_user.id
    action.responsible_owner = responsible_user.full_name
    action.related_user_1_id = related_user_1.id if related_user_1 else None
    action.related_user_2_id = related_user_2.id if related_user_2 else None
    action.department = department
    action.description = request.form.get("description", "").strip()

    termin_value = request.form.get("termin_date", "")
    action.termin_date = datetime.strptime(termin_value, "%Y-%m-%d").date()
    action.refresh_delay()
    save_uploaded_file(action)
    return action


def parse_dof_form(dof=None, save_mode="open"):
    dof = dof or Dof()
    is_draft = save_mode == "draft"
    title = request.form.get("title", "").strip()
    department = request.form.get("department", "").strip()
    priority = request.form.get("priority", "").strip()
    source = request.form.get("source", "").strip()
    responsible = parse_optional_active_user("responsible_id")
    opening_date = parse_optional_date("opening_date")
    due_date = parse_optional_date("due_date")
    nonconformity_description = request.form.get(
        "nonconformity_description", ""
    ).strip()
    root_cause_analysis = request.form.get("root_cause_analysis", "").strip()
    corrective_action = request.form.get("corrective_action", "").strip()
    preventive_action = request.form.get("preventive_action", "").strip()

    for text_value in (
        nonconformity_description,
        root_cause_analysis,
        corrective_action,
        preventive_action,
    ):
        if len(text_value) > 2000:
            raise ValueError("text_too_long")

    if department and department not in DEPARTMENTS:
        raise ValueError("invalid_department")
    if priority and priority not in DOF_PRIORITIES:
        raise ValueError("invalid_priority")
    if source and source not in DOF_SOURCES:
        raise ValueError("invalid_source")

    if not is_draft and (
        not title
        or not department
        or not responsible
        or not opening_date
        or not priority
        or not source
        or not nonconformity_description
    ):
        raise ValueError("required_fields")

    dof.title = title or None
    dof.department = department or None
    dof.responsible_id = responsible.id if responsible else None
    dof.opening_date = opening_date
    dof.due_date = due_date
    dof.priority = priority or None
    dof.source = source or None
    dof.nonconformity_description = nonconformity_description or None
    dof.root_cause_analysis = root_cause_analysis or None
    dof.corrective_action = corrective_action or None
    dof.preventive_action = preventive_action or None
    if is_draft:
        dof.status = "Taslak"
        dof.approval_step = "draft"
    else:
        dof.status = "Onay Akışı Bekleniyor"
        if is_management_representative():
            dof.approval_step = "general_manager_deputy"
            dof.management_approved_by_user_id = g.current_user.id
            dof.management_approved_at = datetime.utcnow()
        else:
            dof.approval_step = "management_representative"
    return dof


def dof_revision_snapshot(dof):
    return {
        "title": dof.title or "",
        "department": dof.department or "",
        "responsible_id": dof.responsible_id,
        "opening_date": dof.opening_date,
        "due_date": dof.due_date,
        "priority": dof.priority or "",
        "source": dof.source or "",
        "nonconformity_description": dof.nonconformity_description or "",
        "root_cause_analysis": dof.root_cause_analysis or "",
        "corrective_action": dof.corrective_action or "",
        "preventive_action": dof.preventive_action or "",
        "closing_evidence": dof.closing_evidence or "",
        "evidence_original_name": dof.evidence_original_name or "",
    }


def parse_dof_revision_form(dof):
    title = request.form.get("title", "").strip()
    department = request.form.get("department", "").strip()
    priority = request.form.get("priority", "").strip()
    source = request.form.get("source", "").strip()
    responsible = parse_optional_active_user("responsible_id")
    opening_date = parse_optional_date("opening_date")
    due_date = parse_optional_date("due_date")
    nonconformity_description = request.form.get(
        "nonconformity_description", ""
    ).strip()
    root_cause_analysis = request.form.get("root_cause_analysis", "").strip()
    corrective_action = request.form.get("corrective_action", "").strip()
    preventive_action = request.form.get("preventive_action", "").strip()
    closing_evidence = request.form.get("closing_evidence", "").strip()

    for text_value in (
        nonconformity_description,
        root_cause_analysis,
        corrective_action,
        preventive_action,
        closing_evidence,
    ):
        if len(text_value) > 2000:
            raise ValueError("text_too_long")

    if (
        not title
        or not department
        or not responsible
        or not opening_date
        or not priority
        or not source
        or not nonconformity_description
    ):
        raise ValueError("required_fields")
    if department not in DEPARTMENTS:
        raise ValueError("invalid_department")
    if priority not in DOF_PRIORITIES:
        raise ValueError("invalid_priority")
    if source not in DOF_SOURCES:
        raise ValueError("invalid_source")

    dof.title = title
    dof.department = department
    dof.responsible_id = responsible.id
    dof.opening_date = opening_date
    dof.due_date = due_date
    dof.priority = priority
    dof.source = source
    dof.nonconformity_description = nonconformity_description
    dof.root_cause_analysis = root_cause_analysis or None
    dof.corrective_action = corrective_action or None
    dof.preventive_action = preventive_action or None
    dof.closing_evidence = closing_evidence or None
    save_dof_evidence_file(dof)


def describe_dof_revision_changes(before, dof):
    labels = {
        "title": "başlık",
        "department": "departman",
        "opening_date": "açılış tarihi",
        "due_date": "termin",
        "priority": "öncelik",
        "source": "kaynak",
        "nonconformity_description": "uygunsuzluk açıklaması",
        "root_cause_analysis": "kök neden analizi",
        "corrective_action": "düzeltici faaliyet",
        "preventive_action": "önleyici faaliyet",
        "closing_evidence": "kapanış kanıtı açıklaması",
    }
    after = dof_revision_snapshot(dof)
    changes = []

    if before["responsible_id"] != after["responsible_id"]:
        old_user = User.query.get(before["responsible_id"]) if before["responsible_id"] else None
        new_user = User.query.get(after["responsible_id"]) if after["responsible_id"] else None
        changes.append(
            "sorumlu "
            f"{old_user.full_name if old_user else '-'} -> "
            f"{new_user.full_name if new_user else '-'}"
        )

    for field, label in labels.items():
        old_value = before[field]
        new_value = after[field]
        if field in {"opening_date", "due_date"}:
            old_value = format_date(old_value)
            new_value = format_date(new_value)
        if old_value != new_value:
            changes.append(f"{label} güncellendi")

    if before["evidence_original_name"] != after["evidence_original_name"]:
        changes.append("kanıt dosyası güncellendi")

    return changes


def parse_user_form(user=None):
    user = user or User()
    username = request.form.get("username", "").strip().lower()
    full_name = request.form.get("full_name", "").strip()
    password = request.form.get("password", "")

    if not username or not full_name:
        raise ValueError("required_fields")
    if user.id is None and not password:
        raise ValueError("password_required")

    existing_user = User.query.filter(User.username == username, User.id != user.id).first()
    if existing_user:
        raise ValueError("username_exists")

    user.username = username
    user.full_name = full_name
    user.title = request.form.get("title", "").strip()
    user.email = request.form.get("email", "").strip() or None
    user.is_active = request.form.get("is_active") == "on"
    user.can_create_actions = request.form.get("can_create_actions") == "on"
    user.can_edit_actions = request.form.get("can_edit_actions") == "on"
    user.can_delete_actions = request.form.get("can_delete_actions") == "on"
    user.can_comment_assigned_actions = (
        request.form.get("can_comment_assigned_actions") == "on"
    )
    user.can_close_assigned_actions = request.form.get("can_close_assigned_actions") == "on"
    user.can_manage_users = request.form.get("can_manage_users") == "on"

    if password:
        user.set_password(password)

    return user


@bp.route("/login", methods=["GET", "POST"])
def login():
    if g.current_user is not None:
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        identity = request.form.get("identity", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter(
            or_(
                db.func.lower(User.username) == identity,
                db.func.lower(User.full_name) == identity,
            )
        ).first()

        if user and user.is_active and user.check_password(password):
            session.clear()
            session["user_id"] = user.id
            flash("Giriş başarılı.", "success")
            next_url = request.args.get("next") or url_for("main.dashboard")
            return redirect(next_url)

        flash("Kullanıcı adı veya şifre hatalı.", "danger")

    return render_template("login.html")


@bp.get("/logout")
def logout():
    session.clear()
    flash("Çıkış yapıldı.", "success")
    return redirect(url_for("main.login"))


@bp.get("/notifications")
@login_required
def notifications():
    notification_list = (
        Notification.query.filter_by(user_id=g.current_user.id)
        .order_by(Notification.created_at.desc())
        .limit(100)
        .all()
    )
    unread_notifications = Notification.query.filter_by(
        user_id=g.current_user.id, is_read=False
    ).all()
    for notification in unread_notifications:
        notification.is_read = True
    if unread_notifications:
        db.session.commit()
        g.unread_notification_count = 0
    return render_template("notifications.html", notifications=notification_list)


@bp.get("/notifications/count")
@login_required
def notification_count():
    unread_count = Notification.query.filter_by(
        user_id=g.current_user.id, is_read=False
    ).count()
    return jsonify({"count": unread_count})


@bp.get("/notifications/<int:notification_id>/open")
@login_required
def open_notification(notification_id):
    notification = Notification.query.filter_by(
        id=notification_id, user_id=g.current_user.id
    ).first_or_404()
    notification.is_read = True
    db.session.commit()
    if notification.action and can_view_action(notification.action):
        return redirect(url_for("main.action_detail", action_id=notification.action.id))
    if notification.dof and can_view_dof(notification.dof):
        return redirect(url_for("main.dof_detail", dof_id=notification.dof.id))
    return redirect(url_for("main.notifications"))


@bp.get("/organization")
@login_required
def organization():
    return render_template(
        "organization.html",
        nodes=orientation_nodes_payload(),
        can_edit=can_manage_orientation(),
    )


@bp.get("/organization1")
@login_required
def organization_legacy():
    return render_template(
        "orientation.html",
        nodes=orientation_nodes_payload(),
        can_edit=can_manage_orientation(),
    )


@bp.get("/orientation")
@login_required
def orientation():
    return redirect(url_for("main.organization"))


@bp.post("/orientation/nodes")
@login_required
def create_orientation_node():
    if not can_manage_orientation():
        abort(403)

    data = request.get_json(silent=True) or {}
    node_type = (data.get("node_type") or "person").strip()
    if node_type not in ORGANIZATION_NODE_TYPES:
        node_type = "person"

    default_name = "Yeni departman" if node_type == "department" else "Yeni kişi"
    name = (data.get("name") or default_name).strip()
    title = (data.get("title") or "").strip()
    color = parse_node_color(data.get("color"))

    try:
        parent = parse_node_parent(data.get("parent_id"))
    except ValueError:
        return jsonify({"ok": False, "message": "Geçerli bir üst kişi seçin."}), 400

    if parent is not None:
        child_count = OrientationNode.query.filter_by(parent_id=parent.id).count()
        default_x = parent.x + (child_count * 24)
        default_y = parent.y + 170
    else:
        root_count = OrientationNode.query.filter_by(parent_id=None).count()
        default_x = 120 + (root_count * 32)
        default_y = 80

    node = OrientationNode(
        parent_id=parent.id if parent else None,
        name=name[:160],
        title=title[:160],
        node_type=node_type,
        color=color,
        x=parse_coordinate(data, "x", default_x),
        y=parse_coordinate(data, "y", default_y),
    )
    db.session.add(node)
    db.session.commit()
    return jsonify({"ok": True, "node": node.to_dict(), "nodes": orientation_nodes_payload()})


@bp.post("/orientation/nodes/<int:node_id>/update")
@login_required
def update_orientation_node(node_id):
    if not can_manage_orientation():
        abort(403)

    node = OrientationNode.query.get_or_404(node_id)
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    title = (data.get("title") or "").strip()
    node_type = (data.get("node_type") or node.node_type or "person").strip()
    if node_type not in ORGANIZATION_NODE_TYPES:
        node_type = "person"
    color = parse_node_color(data.get("color") or node.color)

    if not name:
        return jsonify({"ok": False, "message": "İsim alanı boş bırakılamaz."}), 400

    try:
        parent = parse_node_parent(data.get("parent_id"), current_node=node)
    except ValueError:
        return jsonify({"ok": False, "message": "Geçerli bir üst kişi seçin."}), 400

    node.name = name[:160]
    node.title = title[:160]
    node.node_type = node_type
    node.color = color
    node.parent_id = parent.id if parent else None
    db.session.commit()
    return jsonify({"ok": True, "node": node.to_dict(), "nodes": orientation_nodes_payload()})


@bp.post("/orientation/nodes/<int:node_id>/move")
@login_required
def move_orientation_node(node_id):
    if not can_manage_orientation():
        abort(403)

    node = OrientationNode.query.get_or_404(node_id)
    data = request.get_json(silent=True) or {}
    node.x = parse_coordinate(data, "x", node.x)
    node.y = parse_coordinate(data, "y", node.y)
    db.session.commit()
    return jsonify({"ok": True, "node": node.to_dict()})


@bp.post("/orientation/nodes/<int:node_id>/delete")
@login_required
def delete_orientation_node(node_id):
    if not can_manage_orientation():
        abort(403)

    node = OrientationNode.query.get_or_404(node_id)
    db.session.delete(node)
    db.session.commit()
    return jsonify({"ok": True, "nodes": orientation_nodes_payload()})


def dashboard_context():
    all_actions = refresh_all_actions()
    filters = dashboard_filters()
    actions = filtered_actions(all_actions, filters)
    delayed_count = sum(
        1 for action in all_actions if not action.is_completed and action.delay_days > 0
    )
    completed_count = sum(1 for action in all_actions if action.is_completed)
    pending_approval_count = sum(
        1
        for action in all_actions
        if not action.is_completed and action.closure_approval_requested
    )
    total_count = len(all_actions)

    return {
        "actions": actions,
        "delayed_count": delayed_count,
        "completed_count": completed_count,
        "pending_approval_count": pending_approval_count,
        "total_count": total_count,
        "can_complete_action": can_complete_action,
        "can_request_closure_action": can_request_closure_action,
        "can_approve_closure_action": can_approve_closure_action,
        "departments": DEPARTMENTS,
        "filters": filters,
        "users": active_users(),
        "current_user_initials": user_initials(g.current_user),
    }


def dof_dashboard_context():
    all_dofs = attach_dof_view_state(
        visible_dofs_query().order_by(Dof.dof_no.asc(), Dof.id.asc()).all()
    )
    filters = dof_filters()
    dofs = filtered_dofs(all_dofs, filters)
    total_count = len(all_dofs)
    draft_count = sum(1 for dof in all_dofs if dof.display_status == "Taslak")
    approval_count = sum(
        1 for dof in all_dofs if dof.display_status == "Onay Akışı Bekleniyor"
    )
    revision_count = sum(
        1 for dof in all_dofs if dof.display_status == "Revizyon Bekleniyor"
    )
    completed_count = sum(1 for dof in all_dofs if dof.display_status == "Tamamlandı")
    delayed_count = sum(
        1
        for dof in all_dofs
        if dof.display_status != "Tamamlandı" and dof.delay_days > 0
    )

    return {
        "dofs": dofs,
        "total_count": total_count,
        "draft_count": draft_count,
        "approval_count": approval_count,
        "revision_count": revision_count,
        "completed_count": completed_count,
        "delayed_count": delayed_count,
        "departments": DEPARTMENTS,
        "filters": filters,
        "users": active_users() if can_view_all_dofs() else [g.current_user],
        "can_delete_dof": can_delete_dof,
    }


def internal_audit_question_context(audit, question):
    answer = internal_audit_answer_for_question(audit, question)
    selected_previous_dof_id = answer.previous_nonconformity_id if answer else None
    return {
        "audit": audit,
        "question": question,
        "answer": answer,
        "progress": internal_audit_progress(audit),
        "result_choices": INTERNAL_AUDIT_RESULTS,
        "result_map": INTERNAL_AUDIT_RESULT_MAP,
        "departments": DEPARTMENTS,
        "history_items": internal_audit_history_items(audit, question),
        "previous_nonconformities": internal_audit_previous_nonconformities(
            question,
            selected_previous_dof_id,
        ),
        "previous_question": internal_audit_question_by_order(
            audit,
            internal_audit_previous_order(audit, question),
        ),
        "next_question": internal_audit_question_by_order(
            audit,
            internal_audit_next_order(audit, question),
        ),
        "is_complete": internal_audit_is_complete(audit),
    }


@bp.route("/")
@login_required
def dashboard():
    return render_template("dashboard.html", **dashboard_context())


@bp.route("/dashboard-liste")
@login_required
def dashboard_list():
    return render_template("dashboard_list.html", **dashboard_context())


@bp.route("/dashboard-eski")
@login_required
def dashboard_legacy():
    return render_template("dashboard_legacy.html", **dashboard_context())


@bp.route("/dofs")
@login_required
def dof_management():
    return render_template("dof_dashboard.html", **dof_dashboard_context())


@bp.route("/ic-denetim")
@login_required
def internal_audit():
    audit = current_internal_audit()
    question = internal_audit_question_by_order(
        audit,
        audit.active_question_order or 1,
    ) or internal_audit_question_by_order(audit, 1)
    if question is None:
        flash("İç denetim soru listesi oluşturulamadı.", "danger")
        return redirect(url_for("main.dashboard"))
    return redirect(
        url_for(
            "main.internal_audit_question",
            audit_id=audit.id,
            question_id=question.id,
        )
    )


@bp.get("/ic-denetim/<int:audit_id>/soru/<int:question_id>")
@login_required
def internal_audit_question(audit_id, question_id):
    audit = InternalAudit.query.get_or_404(audit_id)
    if not can_view_internal_audit(audit):
        abort(403)

    question = InternalAuditQuestion.query.filter_by(
        id=question_id,
        audit_id=audit.id,
    ).first_or_404()
    if audit.active_question_order != question.order_no:
        audit.active_question_order = question.order_no
        db.session.commit()

    return render_template(
        "internal_audit_flow.html",
        **internal_audit_question_context(audit, question),
    )


@bp.get("/ic-denetim/<int:audit_id>/onceki-soru")
@login_required
def previous_internal_audit_question(audit_id):
    audit = InternalAudit.query.get_or_404(audit_id)
    if not can_view_internal_audit(audit):
        abort(403)
    current_question_id = request.args.get("question_id", type=int)
    question = InternalAuditQuestion.query.filter_by(
        id=current_question_id,
        audit_id=audit.id,
    ).first()
    if question is None:
        question = internal_audit_question_by_order(audit, audit.active_question_order or 1)
    previous_question = internal_audit_question_by_order(
        audit,
        internal_audit_previous_order(audit, question),
    )
    return redirect(
        url_for(
            "main.internal_audit_question",
            audit_id=audit.id,
            question_id=previous_question.id,
        )
    )


@bp.post("/ic-denetim/<int:audit_id>/cevap-kaydet")
@login_required
def save_internal_audit_answer(audit_id):
    audit = InternalAudit.query.get_or_404(audit_id)
    if not can_view_internal_audit(audit):
        abort(403)

    question_id = request.form.get("question_id", type=int)
    question = InternalAuditQuestion.query.filter_by(
        id=question_id,
        audit_id=audit.id,
    ).first_or_404()
    submit_action = request.form.get("submit_action", "next")
    is_draft = submit_action == "draft"

    try:
        answer = parse_internal_audit_answer_form(audit, question, is_draft=is_draft)
    except ValueError as error:
        error_key = str(error)
        if error_key == "required_fields":
            flash("Kaydetmek için değerlendirilecek departman ve sonucu seçin.", "danger")
        elif error_key == "technical_findings_required":
            flash("Hayır veya Kısmen sonucunda teknik bulgular alanı zorunludur.", "danger")
        elif error_key == "technical_findings_too_long":
            flash("Teknik bulgular en fazla 1000 karakter olabilir.", "danger")
        else:
            flash("Lütfen iç denetim cevap alanlarını geçerli biçimde doldurun.", "danger")
        return redirect(
            url_for(
                "main.internal_audit_question",
                audit_id=audit.id,
                question_id=question.id,
            )
        )

    if is_draft:
        audit.active_question_order = question.order_no
        db.session.commit()
        flash("Soru taslak olarak kaydedildi.", "success")
        return redirect(
            url_for(
                "main.internal_audit_question",
                audit_id=audit.id,
                question_id=question.id,
            )
        )

    next_question = internal_audit_question_by_order(
        audit,
        internal_audit_next_order(audit, question),
    )
    if internal_audit_is_complete(audit):
        audit.status = "Tamamlandı"
        audit.active_question_order = question.order_no
        db.session.commit()
        flash("İç denetimdeki tüm zorunlu sorular tamamlandı.", "success")
        return redirect(
            url_for(
                "main.internal_audit_question",
                audit_id=audit.id,
                question_id=question.id,
            )
        )

    audit.status = "Devam Ediyor"
    audit.active_question_order = next_question.order_no if next_question else question.order_no
    db.session.commit()
    if answer.result == "Hayır":
        flash("Soru kaydedildi. Bu cevap için Uygunsuzluk Aç butonu ile DÖF oluşturabilirsiniz.", "warning")
    else:
        flash("Soru kaydedildi ve bir sonraki soruya geçildi.", "success")

    return redirect(
        url_for(
            "main.internal_audit_question",
            audit_id=audit.id,
            question_id=(next_question.id if next_question else question.id),
        )
    )


@bp.post("/ic-denetim/<int:audit_id>/uygunsuzluk-ac")
@login_required
def open_internal_audit_nonconformity(audit_id):
    audit = InternalAudit.query.get_or_404(audit_id)
    if not can_view_internal_audit(audit):
        abort(403)

    question_id = request.form.get("question_id", type=int)
    question = InternalAuditQuestion.query.filter_by(
        id=question_id,
        audit_id=audit.id,
    ).first_or_404()

    try:
        answer = parse_internal_audit_answer_form(audit, question, is_draft=False)
    except ValueError as error:
        error_key = str(error)
        if error_key == "technical_findings_required":
            flash("DÖF açmak için teknik bulgular alanını doldurun.", "danger")
        elif error_key == "required_fields":
            flash("DÖF açmak için departman, sonuç ve zorunlu alanları tamamlayın.", "danger")
        else:
            flash("DÖF açmadan önce iç denetim cevabını geçerli biçimde doldurun.", "danger")
        return redirect(
            url_for(
                "main.internal_audit_question",
                audit_id=audit.id,
                question_id=question.id,
            )
        )

    if answer.result not in INTERNAL_AUDIT_FINDING_REQUIRED_RESULTS:
        db.session.rollback()
        flash("DÖF açmak için sonuç Hayır veya Kısmen olmalıdır.", "warning")
        return redirect(
            url_for(
                "main.internal_audit_question",
                audit_id=audit.id,
                question_id=question.id,
            )
        )

    db.session.flush()
    if answer.dof_id:
        db.session.commit()
        flash("Bu soru için daha önce DÖF açılmış. Mevcut DÖF detayına yönlendirildiniz.", "info")
        return redirect(url_for("main.dof_detail", dof_id=answer.dof_id))

    audit.active_question_order = question.order_no
    db.session.commit()
    return redirect(url_for("main.create_dof", internal_audit_answer_id=answer.id))


@bp.post("/ic-denetim/<int:audit_id>/bitir")
@login_required
def complete_internal_audit(audit_id):
    audit = InternalAudit.query.get_or_404(audit_id)
    if not can_view_internal_audit(audit):
        abort(403)
    if not internal_audit_is_complete(audit):
        flash("Tüm zorunlu sorular tamamlanmadan denetim bitirilemez.", "danger")
        return redirect(url_for("main.internal_audit"))

    audit.status = "Tamamlandı"
    db.session.commit()
    flash("İç denetim tamamlandı. Rapor ekranı için özet kayıt hazır.", "success")
    question = internal_audit_question_by_order(audit, audit.active_question_order or 1)
    return redirect(
        url_for(
            "main.internal_audit_question",
            audit_id=audit.id,
            question_id=question.id,
        )
    )


@bp.route("/dofs/new", methods=["GET", "POST"])
@login_required
def create_dof():
    if request.method == "POST":
        save_mode = request.form.get("save_mode", "open")
        if save_mode not in {"draft", "open"}:
            save_mode = "open"
        audit_answer = None
        audit_answer_id = request.form.get("internal_audit_answer_id", type=int)
        if audit_answer_id:
            audit_answer = InternalAuditAnswer.query.get(audit_answer_id)
            if audit_answer is None or not can_view_internal_audit(audit_answer.audit):
                flash("İç denetim cevabı bulunamadı veya erişim yetkiniz yok.", "danger")
                return redirect(url_for("main.dof_management"))
            if audit_answer.dof_id:
                flash("Bu iç denetim cevabı için daha önce DÖF açılmış.", "info")
                return redirect(url_for("main.dof_detail", dof_id=audit_answer.dof_id))
        try:
            dof = parse_dof_form(save_mode=save_mode)
            dof.dof_no = reserve_dof_number()
            dof.created_by_user_id = g.current_user.id
            db.session.add(dof)
            db.session.flush()
            save_dof_opening_files(dof)
            if audit_answer is not None:
                audit_answer.dof_id = dof.id
                add_dof_comment(
                    dof,
                    (
                        "DÖF iç denetim soru akışından açıldı. "
                        f"Soru: {short_text(audit_answer.question_text, 140)}"
                    ),
                    comment_type="internal_audit",
                    actor=g.current_user,
                )
            if save_mode != "draft":
                notify_dof_users(
                    [dof.responsible],
                    dof,
                    f"{dof_label(dof)} size atandı.",
                )
                notify_dof_waiting_approvers(dof)
            db.session.commit()
            flash(
                f"{dof.dof_no} numaralı DÖF kaydı "
                f"{'taslak olarak ' if save_mode == 'draft' else ''}kaydedildi.",
                "success",
            )
            return redirect(url_for("main.dof_management"))
        except ValueError as error:
            db.session.rollback()
            error_key = str(error)
            if error_key == "invalid_dof_file_type":
                flash("Kapanış kanıtı için sadece PDF, JPG veya PNG yükleyebilirsiniz.", "danger")
            elif error_key == "dof_file_too_large":
                flash("Kapanış kanıtı dosyası en fazla 10 MB olabilir.", "danger")
            elif error_key == "invalid_dof_opening_file_type":
                flash("Uygunsuzluk görselleri için sadece JPG, PNG veya WEBP yükleyebilirsiniz.", "danger")
            elif error_key == "dof_opening_file_too_large":
                flash("Uygunsuzluk görsellerinin her biri en fazla 10 MB olabilir.", "danger")
            elif error_key == "required_fields":
                flash("Kaydetmek için yıldızlı zorunlu alanları doldurun.", "danger")
            elif error_key == "text_too_long":
                flash("Açıklama alanları en fazla 2000 karakter olabilir.", "danger")
            else:
                flash("Lütfen DÖF form alanlarını geçerli biçimde doldurun.", "danger")

    form_data = request.form if request.method == "POST" else {}
    if request.method == "GET":
        audit_answer_id = request.args.get("internal_audit_answer_id", type=int)
        if audit_answer_id:
            audit_answer = InternalAuditAnswer.query.get(audit_answer_id)
            if audit_answer is None or not can_view_internal_audit(audit_answer.audit):
                flash("İç denetim cevabı bulunamadı veya erişim yetkiniz yok.", "danger")
                return redirect(url_for("main.dof_management"))
            if audit_answer.dof_id:
                flash("Bu iç denetim cevabı için daha önce DÖF açılmış.", "info")
                return redirect(url_for("main.dof_detail", dof_id=audit_answer.dof_id))
            form_data = internal_audit_dof_prefill(audit_answer)

    return render_template(
        "dof_form.html",
        users=active_users(),
        departments=DEPARTMENTS,
        priorities=DOF_PRIORITIES,
        sources=DOF_SOURCES,
        today=date.today().isoformat(),
        form_data=form_data,
    )


@bp.get("/dofs/<int:dof_id>")
@login_required
def dof_detail(dof_id):
    dof = Dof.query.get_or_404(dof_id)
    if not can_view_dof(dof):
        abort(403)
    attach_dof_view_state([dof])
    return render_template(
        "dof_detail.html",
        dof=dof,
        approval_steps=dof_approval_steps(dof),
        can_approve_management=can_approve_dof_management(dof),
        can_approve_deputy=can_approve_dof_deputy(dof),
        can_reject=can_reject_dof(dof),
        can_revise=can_revise_rejected_dof(dof),
        can_delete=can_delete_dof(dof),
        users=active_users(),
        departments=DEPARTMENTS,
        priorities=DOF_PRIORITIES,
        sources=DOF_SOURCES,
    )


@bp.post("/dofs/<int:dof_id>/approve-management")
@login_required
def approve_dof_management(dof_id):
    dof = Dof.query.get_or_404(dof_id)
    if not can_view_dof(dof):
        abort(403)
    attach_dof_view_state([dof])
    if not can_approve_dof_management(dof):
        abort(403)

    dof.management_approved_by_user_id = g.current_user.id
    dof.management_approved_at = datetime.utcnow()
    dof.approval_step = "general_manager_deputy"
    dof.status = "Onay Akışı Bekleniyor"
    add_dof_comment(
        dof,
        f"{g.current_user.full_name} Yönetim Temsilcisi onayını verdi.",
        comment_type="approval",
        actor=g.current_user,
    )
    notify_dof_waiting_approvers(dof)
    db.session.commit()
    flash("DÖF kaydı Yönetim Temsilcisi tarafından onaylandı.", "success")
    return redirect(url_for("main.dof_detail", dof_id=dof.id))


@bp.post("/dofs/<int:dof_id>/approve-deputy")
@login_required
def approve_dof_deputy(dof_id):
    dof = Dof.query.get_or_404(dof_id)
    if not can_view_dof(dof):
        abort(403)
    attach_dof_view_state([dof])
    if not can_approve_dof_deputy(dof):
        abort(403)

    now = datetime.utcnow()
    dof.deputy_approved_by_user_id = g.current_user.id
    dof.deputy_approved_at = now
    dof.completed_at = now
    dof.approval_step = "completed"
    dof.status = "Tamamlandı"
    add_dof_comment(
        dof,
        f"{g.current_user.full_name} Genel Müdür Yardımcısı onayını verdi ve DÖF kapandı.",
        comment_type="approval",
        actor=g.current_user,
    )
    notify_dof_users(
        dof_primary_users(dof),
        dof,
        f"{dof_label(dof)} kapatıldı.",
    )
    db.session.commit()
    flash("DÖF kaydı Genel Müdür Yardımcısı onayıyla tamamlandı.", "success")
    return redirect(url_for("main.dof_detail", dof_id=dof.id))


@bp.post("/dofs/<int:dof_id>/reject")
@login_required
def reject_dof(dof_id):
    dof = Dof.query.get_or_404(dof_id)
    if not can_view_dof(dof):
        abort(403)
    attach_dof_view_state([dof])
    if not can_reject_dof(dof):
        abort(403)

    rejection_reason = request.form.get("rejection_reason", "").strip()
    if not rejection_reason:
        flash("Red sebebi alanını doldurun.", "danger")
        return redirect(url_for("main.dof_detail", dof_id=dof.id))

    rejected_step = dof.approval_step
    dof.status = "Revizyon Bekleniyor"
    dof.approval_step = "revision_requested"
    dof.rejected_step = rejected_step
    dof.rejection_reason = rejection_reason
    dof.rejected_by_user_id = g.current_user.id
    dof.rejected_at = datetime.utcnow()
    if rejected_step == "management_representative":
        dof.management_approved_by_user_id = None
        dof.management_approved_at = None
        dof.deputy_approved_by_user_id = None
        dof.deputy_approved_at = None
    elif rejected_step == "general_manager_deputy":
        dof.deputy_approved_by_user_id = None
        dof.deputy_approved_at = None

    add_dof_comment(
        dof,
        (
            f"{g.current_user.full_name} {dof_approver_label(rejected_step)} "
            f"onayını reddetti: \"{short_text(rejection_reason)}\""
        ),
        comment_type="rejection",
        actor=g.current_user,
    )
    notify_dof_users(
        dof_rejection_recipients(dof, rejected_step),
        dof,
        (
            f"{dof_label(dof)} {dof_approver_label(rejected_step)} tarafından "
            f"reddedildi. Sebep: {short_text(rejection_reason)}"
        ),
        exclude_user_id=g.current_user.id,
    )
    db.session.commit()
    flash("DÖF kaydı reddedildi ve revizyon beklemeye alındı.", "success")
    return redirect(url_for("main.dof_detail", dof_id=dof.id))


@bp.post("/dofs/<int:dof_id>/revision")
@login_required
def revise_dof(dof_id):
    dof = Dof.query.get_or_404(dof_id)
    if not can_view_dof(dof):
        abort(403)
    attach_dof_view_state([dof])
    if not can_revise_rejected_dof(dof):
        abort(403)

    target_step = (
        dof.rejected_step
        if dof.rejected_step in {"management_representative", "general_manager_deputy"}
        else "management_representative"
    )
    before = dof_revision_snapshot(dof)
    revision_note = request.form.get("revision_note", "").strip()
    try:
        parse_dof_revision_form(dof)
    except ValueError as error:
        error_key = str(error)
        if error_key == "invalid_dof_file_type":
            flash("Kanıt dosyası için sadece PDF, JPG veya PNG yükleyebilirsiniz.", "danger")
        elif error_key == "dof_file_too_large":
            flash("Kanıt dosyası en fazla 10 MB olabilir.", "danger")
        elif error_key == "required_fields":
            flash("Tekrar onay talep etmek için zorunlu alanları doldurun.", "danger")
        elif error_key == "text_too_long":
            flash("Açıklama alanları en fazla 2000 karakter olabilir.", "danger")
        else:
            flash("Lütfen DÖF revizyon alanlarını geçerli biçimde doldurun.", "danger")
        return redirect(url_for("main.dof_detail", dof_id=dof.id))

    changes = describe_dof_revision_changes(before, dof)
    dof.status = "Onay Akışı Bekleniyor"
    dof.approval_step = target_step
    dof.rejection_reason = None
    dof.rejected_by_user_id = None
    dof.rejected_at = None
    dof.rejected_step = None
    if target_step == "management_representative":
        dof.management_approved_by_user_id = None
        dof.management_approved_at = None
        dof.deputy_approved_by_user_id = None
        dof.deputy_approved_at = None
    elif target_step == "general_manager_deputy":
        dof.deputy_approved_by_user_id = None
        dof.deputy_approved_at = None

    comment_parts = [
        f"{g.current_user.full_name} revizyon yaptı ve tekrar onay talep etti."
    ]
    if changes:
        comment_parts.append("Değişiklikler: " + ", ".join(changes) + ".")
    if revision_note:
        comment_parts.append(f"Not: {revision_note}")
    add_dof_comment(
        dof,
        " ".join(comment_parts),
        comment_type="revision",
        actor=g.current_user,
    )
    notify_dof_waiting_approvers(dof)
    db.session.commit()
    flash("DÖF revizyonu kaydedildi ve tekrar onaya gönderildi.", "success")
    return redirect(url_for("main.dof_detail", dof_id=dof.id))


@bp.get("/dofs/<int:dof_id>/evidence/download")
@login_required
def download_dof_evidence_file(dof_id):
    dof = Dof.query.get_or_404(dof_id)
    if not can_view_dof(dof):
        abort(403)
    if not dof.evidence_stored_name:
        flash("Bu DÖF kaydına ait kapanış kanıt dosyası bulunamadı.", "warning")
        return redirect(url_for("main.dof_detail", dof_id=dof.id))

    return send_from_directory(
        current_app.config["UPLOAD_FOLDER"],
        dof.evidence_stored_name,
        as_attachment=True,
        download_name=dof.evidence_original_name,
    )


@bp.get("/dofs/<int:dof_id>/files/<int:file_id>/download")
@login_required
def download_dof_file(dof_id, file_id):
    dof = Dof.query.get_or_404(dof_id)
    if not can_view_dof(dof):
        abort(403)

    dof_file = DofFile.query.filter_by(id=file_id, dof_id=dof.id).first_or_404()
    return send_from_directory(
        current_app.config["UPLOAD_FOLDER"],
        dof_file.stored_name,
        as_attachment=True,
        download_name=dof_file.original_name,
    )


@bp.route("/dofs/<int:dof_id>/delete", methods=["GET", "POST"])
@login_required
def delete_dof(dof_id):
    dof = Dof.query.get_or_404(dof_id)
    if not can_delete_dof(dof):
        abort(403)

    if request.method == "POST":
        InternalAuditAnswer.query.filter_by(dof_id=dof.id).update(
            {"dof_id": None},
            synchronize_session=False,
        )
        InternalAuditAnswer.query.filter_by(previous_nonconformity_id=dof.id).update(
            {"previous_nonconformity_id": None},
            synchronize_session=False,
        )
        delete_dof_evidence_file(dof)
        db.session.delete(dof)
        db.session.commit()
        flash("DÖF kaydı silindi.", "success")
        return redirect(url_for("main.dof_management"))

    return render_template("dof_confirm_delete.html", dof=dof)


@bp.route("/actions/new", methods=["GET", "POST"])
@login_required
@permission_required("can_create_actions")
def create_action():
    if request.method == "POST":
        try:
            action = parse_action_form()
            action.action_number = reserve_action_number()
            db.session.add(action)
            db.session.flush()
            add_action_history(
                action,
                "created",
                f"{g.current_user.full_name} aksiyonu oluşturdu.",
                actor=g.current_user,
            )
            notify_action_participants(
                action,
                f"{action.number_label} {action.title} aksiyonu size atandı.",
                exclude_user_id=g.current_user.id,
            )
            db.session.commit()
            flash("Aksiyon kaydı başarıyla eklendi.", "success")
            return redirect(url_for("main.dashboard"))
        except ValueError as error:
            if str(error) == "invalid_file_type":
                flash(
                    "Sadece PDF, Word, Excel veya görsel dosyası yükleyebilirsiniz.",
                    "danger",
                )
            else:
                flash("Lütfen form alanlarını geçerli biçimde doldurun.", "danger")

    return render_template(
        "action_form.html",
        action=None,
        users=active_users(),
        departments=DEPARTMENTS,
        today=date.today().isoformat(),
        title="Yeni Aksiyon",
    )


@bp.route("/actions/<int:action_id>")
@login_required
def action_detail(action_id):
    action = Action.query.get_or_404(action_id)
    if not can_view_action(action):
        abort(403)

    return render_template(
        "action_detail.html",
        action=action,
        users=active_users(),
        can_complete=can_complete_action(action),
        can_request_closure=can_request_closure_action(action),
        can_approve_closure=can_approve_closure_action(action),
        can_comment=can_comment_action(action),
        can_reassign=can_reassign_action(action),
        can_revise_termin=can_revise_termin(action),
    )


@bp.post("/actions/<int:action_id>/reassign")
@login_required
def reassign_action(action_id):
    action = Action.query.get_or_404(action_id)
    if not can_reassign_action(action):
        abort(403)

    responsible_user_id = request.form.get("responsible_user_id", "").strip()
    try:
        responsible_user_id = int(responsible_user_id)
    except ValueError:
        flash("Lütfen geçerli bir aksiyon sorumlusu seçin.", "danger")
        return redirect(url_for("main.action_detail", action_id=action.id))

    responsible_user = User.query.filter_by(
        id=responsible_user_id, is_active=True
    ).first()
    if responsible_user is None:
        flash("Seçilen kullanıcı bulunamadı.", "danger")
        return redirect(url_for("main.action_detail", action_id=action.id))

    try:
        related_user_1 = parse_optional_user("related_user_1_id")
        related_user_2 = parse_optional_user("related_user_2_id")
    except ValueError:
        flash("Lütfen geçerli ilgili kullanıcı seçin.", "danger")
        return redirect(url_for("main.action_detail", action_id=action.id))

    before = action_snapshot(action)
    action.responsible_user_id = responsible_user.id
    action.responsible_owner = responsible_user.full_name
    action.related_user_1_id = related_user_1.id if related_user_1 else None
    action.related_user_2_id = related_user_2.id if related_user_2 else None

    changes = describe_action_changes(before, action)
    if not changes:
        flash("Sorumlu ve ilgili bilgilerinde değişiklik yapılmadı.", "warning")
        return redirect(url_for("main.action_detail", action_id=action.id))

    add_action_history(
        action,
        "reassigned",
        (
            f"{g.current_user.full_name} sorumlu/ilgili bilgilerini güncelledi: "
            + "; ".join(changes)
        ),
        actor=g.current_user,
    )
    notify_action_participants(
        action,
        (
            f"{action.number_label} {action.title} aksiyonunda "
            "sorumlu/ilgili bilgileri güncellendi."
        ),
        exclude_user_id=g.current_user.id,
        extra_user_ids={
            before["responsible_user_id"],
            before["related_user_1_id"],
            before["related_user_2_id"],
        },
    )
    db.session.commit()
    flash("Sorumlu ve ilgili bilgileri güncellendi.", "success")

    if can_view_action(action):
        return redirect(url_for("main.action_detail", action_id=action.id))
    return redirect(url_for("main.dashboard"))


@bp.post("/actions/<int:action_id>/revise-termin")
@login_required
def revise_action_termin(action_id):
    action = Action.query.get_or_404(action_id)
    if not can_revise_termin(action):
        abort(403)

    termin_value = request.form.get("termin_date", "")
    try:
        new_termin_date = datetime.strptime(termin_value, "%Y-%m-%d").date()
    except ValueError:
        flash("Lütfen geçerli bir termin tarihi girin.", "danger")
        return redirect(url_for("main.action_detail", action_id=action.id))

    old_termin_date = action.termin_date
    if old_termin_date == new_termin_date:
        flash("Termin tarihi zaten bu değerle kayıtlı.", "warning")
        return redirect(url_for("main.action_detail", action_id=action.id))

    action.termin_date = new_termin_date
    action.refresh_delay()
    add_action_history(
        action,
        "termin_revised",
        (
            f"{g.current_user.full_name} termini "
            f"{format_date(old_termin_date)} -> {format_date(new_termin_date)} "
            "olarak revize etti."
        ),
        actor=g.current_user,
    )
    notify_action_participants(
        action,
        f"{action.number_label} {action.title} aksiyonunda termin revize edildi.",
        exclude_user_id=g.current_user.id,
    )
    db.session.commit()
    flash("Termin tarihi revize edildi.", "success")
    return redirect(url_for("main.action_detail", action_id=action.id))


@bp.post("/actions/<int:action_id>/comments")
@login_required
def add_action_comment(action_id):
    action = Action.query.get_or_404(action_id)
    if not can_comment_action(action):
        abort(403)

    comment_text = request.form.get("comment", "").strip()
    if not comment_text:
        flash("Yorum alanı boş bırakılamaz.", "danger")
        return redirect(url_for("main.action_detail", action_id=action.id))

    comment = ActionComment(
        action_id=action.id,
        user_id=g.current_user.id,
        comment=comment_text,
    )
    db.session.add(comment)
    add_action_history(
        action,
        "commented",
        f"{g.current_user.full_name} yorum ekledi: \"{short_text(comment_text)}\"",
        actor=g.current_user,
    )
    notify_action_participants(
        action,
        f"{action.number_label} {action.title} aksiyonuna yeni yorum eklendi.",
        exclude_user_id=g.current_user.id,
    )
    db.session.commit()
    flash("Yorum eklendi.", "success")
    return redirect(url_for("main.action_detail", action_id=action.id))


@bp.route("/actions/<int:action_id>/edit", methods=["GET", "POST"])
@login_required
@permission_required("can_edit_actions")
def edit_action(action_id):
    action = Action.query.get_or_404(action_id)

    if request.method == "POST":
        try:
            before = action_snapshot(action)
            parse_action_form(action)
            changes = describe_action_changes(before, action)
            if changes:
                add_action_history(
                    action,
                    "updated",
                    (
                        f"{g.current_user.full_name} aksiyonu revize etti: "
                        + "; ".join(changes)
                    ),
                    actor=g.current_user,
                )
                notify_action_participants(
                    action,
                    f"{action.number_label} {action.title} aksiyonunda revizyon yapıldı.",
                    exclude_user_id=g.current_user.id,
                    extra_user_ids={
                        before["responsible_user_id"],
                        before["related_user_1_id"],
                        before["related_user_2_id"],
                    },
                )
            db.session.commit()
            flash("Aksiyon kaydı güncellendi.", "success")
            return redirect(url_for("main.dashboard"))
        except ValueError as error:
            if str(error) == "invalid_file_type":
                flash(
                    "Sadece PDF, Word, Excel veya görsel dosyası yükleyebilirsiniz.",
                    "danger",
                )
            else:
                flash("Lütfen form alanlarını geçerli biçimde doldurun.", "danger")

    return render_template(
        "action_form.html",
        action=action,
        users=active_users(),
        departments=DEPARTMENTS,
        today=date.today().isoformat(),
        title="Aksiyon Düzenle",
    )


@bp.post("/actions/<int:action_id>/request-closure")
@login_required
def request_action_closure(action_id):
    action = Action.query.get_or_404(action_id)
    if not can_request_closure_action(action):
        abort(403)

    evidence_note = request.form.get("closure_evidence_note", "").strip()
    if not evidence_note:
        flash("Kapatma onayı için açıklama alanını doldurun.", "danger")
        return redirect(url_for("main.action_detail", action_id=action.id))

    try:
        save_closure_evidence_files(action)
    except ValueError:
        flash("Sadece PDF, Word, Excel veya görsel dosyası yükleyebilirsiniz.", "danger")
        return redirect(url_for("main.action_detail", action_id=action.id))

    action.closure_approval_requested = True
    action.closure_requested_at = datetime.utcnow()
    action.closure_requested_by_user_id = g.current_user.id
    action.closure_evidence_note = evidence_note
    action.closure_rejected_at = None
    action.closure_rejected_by_user_id = None
    action.closure_rejection_reason = None
    add_action_history(
        action,
        "closure_requested",
        f"{g.current_user.full_name} kapatma onayı gönderdi.",
        actor=g.current_user,
    )
    admin_user = oguzhan_user()
    if admin_user:
        notify_users(
            {admin_user.id},
            action,
            f"{action.number_label} {action.title} aksiyonu için kapatma onayı bekliyor.",
            exclude_user_id=g.current_user.id,
        )
    db.session.commit()
    flash("Kapatma onayı Oğuzhan'a gönderildi.", "success")
    return redirect(url_for("main.action_detail", action_id=action.id))


@bp.post("/actions/<int:action_id>/complete")
@login_required
def complete_action(action_id):
    action = Action.query.get_or_404(action_id)
    if not can_approve_closure_action(action):
        abort(403)

    action.mark_completed()
    add_action_history(
        action,
        "completed",
        f"{g.current_user.full_name} kapatma onayını verdi ve aksiyonu tamamladı.",
        actor=g.current_user,
    )
    notify_action_participants(
        action,
        f"{action.number_label} {action.title} aksiyonunun kapanışı Oğuzhan tarafından onaylandı.",
        exclude_user_id=g.current_user.id,
    )
    db.session.commit()
    flash("Kapatma onayı verildi ve aksiyon tamamlandı.", "success")
    return redirect(url_for("main.action_detail", action_id=action.id))


@bp.post("/actions/<int:action_id>/reject-closure")
@login_required
def reject_action_closure(action_id):
    action = Action.query.get_or_404(action_id)
    if not can_approve_closure_action(action):
        abort(403)

    rejection_reason = request.form.get("closure_rejection_reason", "").strip()
    if not rejection_reason:
        flash("Red sebebi alanını doldurun.", "danger")
        return redirect(url_for("main.action_detail", action_id=action.id))

    action.closure_approval_requested = False
    action.closure_rejected_at = datetime.utcnow()
    action.closure_rejected_by_user_id = g.current_user.id
    action.closure_rejection_reason = rejection_reason
    add_action_history(
        action,
        "closure_rejected",
        (
            f"{g.current_user.full_name} kapatma onayını reddetti: "
            f"\"{short_text(rejection_reason)}\""
        ),
        actor=g.current_user,
    )
    notify_action_participants(
        action,
        (
            f"{action.number_label} {action.title} aksiyonunun kapatma onayı "
            f"reddedildi. Sebep: {short_text(rejection_reason)}"
        ),
        exclude_user_id=g.current_user.id,
        extra_user_ids={action.closure_requested_by_user_id},
    )
    db.session.commit()
    flash("Kapatma onayı reddedildi.", "success")
    return redirect(url_for("main.action_detail", action_id=action.id))


@bp.route("/actions/<int:action_id>/delete", methods=["GET", "POST"])
@login_required
@permission_required("can_delete_actions")
def delete_action(action_id):
    action = Action.query.get_or_404(action_id)

    if request.method == "POST":
        delete_uploaded_file(action)
        delete_closure_evidence_file(action)
        db.session.delete(action)
        db.session.commit()
        flash("Aksiyon kaydı silindi.", "success")
        return redirect(url_for("main.dashboard"))

    return render_template("confirm_delete.html", action=action)


@bp.get("/actions/<int:action_id>/download")
@login_required
def download_action_file(action_id):
    action = Action.query.get_or_404(action_id)
    if not can_view_action(action):
        abort(403)

    if not action.file_stored_name:
        flash("Bu kayda ait yüklenmiş dosya bulunamadı.", "warning")
        return redirect(url_for("main.dashboard"))

    return send_from_directory(
        current_app.config["UPLOAD_FOLDER"],
        action.file_stored_name,
        as_attachment=True,
        download_name=action.file_original_name,
    )


@bp.get("/actions/<int:action_id>/closure-evidence/<int:file_id>/download")
@login_required
def download_closure_evidence_file(action_id, file_id):
    action = Action.query.get_or_404(action_id)
    if not can_view_action(action):
        abort(403)

    closure_file = ActionClosureFile.query.filter_by(
        id=file_id,
        action_id=action.id,
    ).first_or_404()

    return send_from_directory(
        current_app.config["UPLOAD_FOLDER"],
        closure_file.stored_name,
        as_attachment=True,
        download_name=closure_file.original_name,
    )


@bp.get("/actions/<int:action_id>/closure-evidence/download")
@login_required
def download_latest_closure_evidence_file(action_id):
    action = Action.query.get_or_404(action_id)
    if not can_view_action(action):
        abort(403)

    if action.closure_files:
        closure_file = action.closure_files[-1]
        return redirect(
            url_for(
                "main.download_closure_evidence_file",
                action_id=action.id,
                file_id=closure_file.id,
            )
        )

    if not action.closure_file_stored_name:
        flash("Bu aksiyona ait kapanış kanıt dosyası bulunamadı.", "warning")
        return redirect(url_for("main.action_detail", action_id=action.id))

    return send_from_directory(
        current_app.config["UPLOAD_FOLDER"],
        action.closure_file_stored_name,
        as_attachment=True,
        download_name=action.closure_file_original_name,
    )


@bp.route("/users")
@login_required
@permission_required("can_manage_users")
def users():
    user_list = User.query.order_by(User.full_name.asc()).all()
    return render_template("users.html", users=user_list)


@bp.route("/users/new", methods=["GET", "POST"])
@login_required
@permission_required("can_manage_users")
def create_user():
    if request.method == "POST":
        try:
            user = parse_user_form()
            db.session.add(user)
            db.session.commit()
            flash("Kullanıcı oluşturuldu.", "success")
            return redirect(url_for("main.users"))
        except ValueError as error:
            if str(error) == "username_exists":
                flash("Bu kullanıcı adı zaten kullanılıyor.", "danger")
            else:
                flash("Lütfen kullanıcı bilgilerini eksiksiz doldurun.", "danger")

    return render_template("user_form.html", user=None, title="Yeni Kullanıcı")


@bp.route("/users/<int:user_id>/edit", methods=["GET", "POST"])
@login_required
@permission_required("can_manage_users")
def edit_user(user_id):
    user = User.query.get_or_404(user_id)

    if request.method == "POST":
        try:
            parse_user_form(user)
            db.session.commit()
            flash("Kullanıcı güncellendi.", "success")
            return redirect(url_for("main.users"))
        except ValueError as error:
            if str(error) == "username_exists":
                flash("Bu kullanıcı adı zaten kullanılıyor.", "danger")
            else:
                flash("Lütfen kullanıcı bilgilerini eksiksiz doldurun.", "danger")

    return render_template("user_form.html", user=user, title="Kullanıcı Düzenle")
