from datetime import UTC, date, datetime
from functools import wraps

from flask import Blueprint, abort, flash, g, redirect, render_template, request, send_file, url_for
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload, joinedload
from sqlalchemy.orm.exc import StaleDataError

from .audit import TRACKED_MODEL_NAMES, record_audit_event
from .extensions import db
from .meeting_models import MeetingDecision, MeetingParticipant, MeetingRecord
from .models import User
from .notifications import add_user_notification
from .tenant import assign_current_company, current_company_id, scoped_query


bp = Blueprint("meetings", __name__, url_prefix="/toplantilar")
STATUSES = {"draft": "Taslak", "open": "Devam Ediyor", "completed": "Tutanak Kesinleşti", "archived": "Arşiv"}
DECISION_STATUSES = {"open": "Açık", "completed": "Tamamlandı"}
EDITABLE = {"draft", "open"}
READ_PERMISSIONS = ("meetings.view", "meetings.view_all", "meetings.manage")


def has_permission(key):
    user = getattr(g, "current_user", None)
    return bool(user and user.is_active and user.has_permission(key))


def require_permission(*keys):
    if not any(has_permission(key) for key in keys):
        abort(403)


def company_id_required():
    company_id = current_company_id()
    if not company_id:
        abort(403, description="L\u00fctfen bir firma se\u00e7in.")
    return company_id


def company_query(model):
    return scoped_query(model.query, model).filter_by(company_id=company_id_required())


@bp.before_request
def guard():
    if getattr(g, "current_user", None) is None:
        return redirect(url_for("main.login", next=request.full_path))
    if not g.current_user.is_active:
        abort(403)
    company_id_required()
    checker = getattr(g, "company_module_enabled", None)
    if checker and not checker("meetings"):
        abort(404)


def atomic(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        try:
            # Validation and authorization must finish before any implicit flush.
            with db.session.no_autoflush:
                return view(*args, **kwargs)
        except (StaleDataError, IntegrityError):
            db.session.rollback()
            abort(409, description="Kay\u0131t de\u011fi\u015fti. Sayfay\u0131 yenileyip tekrar deneyin.")
        except ValueError as error:
            db.session.rollback()
            abort(400, description=str(error))
        except Exception:
            db.session.rollback()
            raise
    return wrapped


def visible_meetings():
    query = company_query(MeetingRecord).options(
        joinedload(MeetingRecord.creator),
        selectinload(MeetingRecord.participants).joinedload(MeetingParticipant.user),
        selectinload(MeetingRecord.decisions).joinedload(MeetingDecision.owner),
    )
    if has_permission("meetings.view_all") or has_permission("meetings.manage"):
        return query
    user_id = g.current_user.id
    company_id = company_id_required()
    return query.filter(or_(
        MeetingRecord.created_by_user_id == user_id,
        MeetingRecord.participants.any(db.and_(
            MeetingParticipant.company_id == company_id, MeetingParticipant.user_id == user_id,
        )),
        MeetingRecord.decisions.any(db.and_(
            MeetingDecision.company_id == company_id, MeetingDecision.owner_user_id == user_id,
        )),
    ))


def get_meeting(meeting_id):
    require_permission(*READ_PERMISSIONS)
    return visible_meetings().filter_by(id=meeting_id).first_or_404()


def can_edit(meeting):
    """Organizer/manage authority, independent of state; routes enforce state separately."""
    return bool(
        meeting.company_id == current_company_id()
        and any(has_permission(key) for key in READ_PERMISSIONS)
        and (has_permission("meetings.manage") or (
            has_permission("meetings.create") and meeting.created_by_user_id == g.current_user.id
        ))
    )


def can_decide(meeting, decision):
    return bool(
        meeting.company_id == current_company_id()
        and decision.company_id == meeting.company_id
        and decision.meeting_id == meeting.id
        and meeting.status in {"open", "completed"}
        and any(has_permission(key) for key in READ_PERMISSIONS)
        and (can_edit(meeting) or (
            decision.owner_user_id == g.current_user.id and has_permission("meetings.decide")
        ))
    )


def require_editor(meeting):
    if not can_edit(meeting):
        abort(403)


def check_version(row, field="version_id"):
    try:
        version = int(request.form.get(field, ""))
    except (TypeError, ValueError):
        abort(409, description="Kay\u0131t s\u00fcr\u00fcm\u00fc eksik veya ge\u00e7ersiz.")
    if version != row.version_id:
        abort(409, description="Kay\u0131t de\u011fi\u015fti. Sayfay\u0131 yenileyin.")


def touch(meeting):
    # Every child mutation competes with archive/edit on the same parent version.
    meeting.version_id += 1
    meeting.updated_at = datetime.now(UTC).replace(tzinfo=None)
    db.session.flush([meeting])


def active_users():
    return company_query(User).filter_by(is_active=True).order_by(User.full_name, User.id).all()


def validate_users(user_ids):
    if user_ids:
        actual = {user.id for user in company_query(User).filter(
            User.id.in_(user_ids), User.is_active.is_(True),
        ).all()}
        if actual != set(user_ids):
            raise ValueError("Se\u00e7ilen personel bu firmada aktif de\u011fil.")


def parse_id(raw):
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ValueError("Ge\u00e7erli bir personel se\u00e7in.") from None
    if value <= 0:
        raise ValueError("Ge\u00e7erli bir personel se\u00e7in.")
    return value


def text_field(name, limit=None, required=False):
    value = request.form.get(name, "").strip()
    if required and not value:
        raise ValueError("Zorunlu alanlar\u0131 doldurun.")
    if limit and len(value) > limit:
        raise ValueError(f"Alan en fazla {limit} karakter olabilir.")
    return value


def meeting_values(meeting=None):
    title = text_field("title", 240, required=True)
    location = text_field("location", 240)
    try:
        raw_date = request.form.get("meeting_at", "")
        meeting_at = datetime.fromisoformat(raw_date)
        if "T" not in raw_date or meeting_at.tzinfo is not None:
            raise ValueError
    except ValueError:
        raise ValueError("Ge\u00e7erli bir toplant\u0131 tarihi ve saati girin.") from None
    participant_ids = {parse_id(raw) for raw in request.form.getlist("participant_ids")}
    validate_users(participant_ids)
    agenda, minutes = text_field("agenda", 20000), text_field("minutes", 30000)
    if meeting:
        decisions = company_query(MeetingDecision).filter_by(meeting_id=meeting.id).all()
        if any(item.due_date < meeting_at.date() for item in decisions):
            raise ValueError("Toplant\u0131 tarihi mevcut karar terminlerinden sonra olamaz.")
        removed = {item.user_id for item in meeting.participants} - participant_ids
        if removed & {item.owner_user_id for item in decisions}:
            raise ValueError("Karar sorumlusu kat\u0131l\u0131mc\u0131lar \u00e7\u0131kar\u0131lamaz; \u00f6nce sorumluyu de\u011fi\u015ftirin.")
        if meeting.status == "open" and (not agenda or not participant_ids):
            raise ValueError("A\u00e7\u0131k toplant\u0131da g\u00fcndem ve kat\u0131l\u0131mc\u0131 zorunludur.")
    return {
        "title": title, "meeting_at": meeting_at, "location": location or None,
        "agenda": agenda or None, "minutes": minutes or None,
    }, participant_ids


def decision_values(meeting):
    title = text_field("title", 240, required=True)
    owner_id = parse_id(request.form.get("owner_user_id"))
    validate_users({owner_id})
    try:
        due_date = date.fromisoformat(request.form.get("due_date", ""))
    except ValueError:
        raise ValueError("Ge\u00e7erli bir karar termini girin.") from None
    if due_date < meeting.meeting_at.date():
        raise ValueError("Karar termini toplant\u0131 tarihinden \u00f6nce olamaz.")
    return {"title": title, "owner_user_id": owner_id, "due_date": due_date}


def snapshot(row):
    values = {column.name: getattr(row, column.name) for column in row.__table__.columns}
    if isinstance(row, MeetingRecord):
        values["participant_ids"] = sorted(item.user_id for item in row.participants)
    return values


def audit(row, action, old=None):
    if action in {"created", "updated"} and type(row).__name__ in TRACKED_MODEL_NAMES:
        return
    record_audit_event(
        type(row).__name__, action, getattr(row, "title", None), entity_id=row.id,
        company_id=row.company_id, old_values=old, new_values=snapshot(row), commit=False,
    )


def notify(meeting, user_id, source, message, due_date=None):
    user = company_query(User).filter_by(id=user_id, is_active=True).first()
    if user:
        add_user_notification(
            user, f"{meeting.meeting_no} - {message}", company_id=meeting.company_id,
            source_key=f"meeting:{meeting.id}:{source}:{user.id}",
            target_url=url_for("meetings.detail", meeting_id=meeting.id), due_date=due_date,
        )


def notify_assignment(meeting, decision):
    if meeting.status == "open":
        notify(meeting, decision.owner_user_id, f"decision:{decision.id}:assignment:{decision.version_id}",
               "Toplant\u0131 karar\u0131 size atand\u0131.", decision.due_date)


def sync_participants(meeting, participant_ids):
    existing = {item.user_id: item for item in meeting.participants}
    if meeting.id and set(existing) != participant_ids:
        record_audit_event(
            "MeetingRecord", "participants_updated", "Toplantı katılımcıları güncellendi",
            entity_id=meeting.id, company_id=meeting.company_id,
            old_values={"participant_ids": sorted(existing)},
            new_values={"participant_ids": sorted(participant_ids)}, commit=False,
        )
    for user_id in existing.keys() - participant_ids:
        meeting.participants.remove(existing[user_id])
    for user_id in sorted(participant_ids - existing.keys()):
        meeting.participants.append(assign_current_company(MeetingParticipant(user_id=user_id)))
        if meeting.status == "open":
            notify(meeting, user_id, "published", "Toplant\u0131 kat\u0131l\u0131mc\u0131s\u0131 olarak eklendiniz.")


def form_context(meeting=None):
    if request.method == "POST":
        values = request.form
        selected = {int(raw) for raw in request.form.getlist("participant_ids") if raw.isdecimal()}
    else:
        values = {} if meeting is None else {
            "title": meeting.title, "meeting_at": meeting.meeting_at.strftime("%Y-%m-%dT%H:%M"),
            "location": meeting.location or "", "agenda": meeting.agenda or "",
            "minutes": meeting.minutes or "", "version_id": meeting.version_id,
        }
        selected = {item.user_id for item in meeting.participants} if meeting else set()
    return {"meeting": meeting, "values": values, "users": active_users(), "selected_participant_ids": selected}


def detail_redirect(meeting):
    return redirect(url_for("meetings.detail", meeting_id=meeting.id))


@bp.get("")
def dashboard():
    require_permission(*READ_PERMISSIONS)
    query = visible_meetings()
    search = request.args.get("q", "").strip()
    selected_status = request.args.get("status", "").strip()
    if search:
        query = query.filter(or_(MeetingRecord.title.ilike(f"%{search}%"), MeetingRecord.agenda.ilike(f"%{search}%")))
    if selected_status in STATUSES:
        query = query.filter_by(status=selected_status)
    else:
        selected_status = ""
    pagination = query.order_by(MeetingRecord.meeting_at.desc(), MeetingRecord.id.desc()).paginate(
        page=request.args.get("page", 1, type=int), per_page=25, error_out=False,
    )
    return render_template(
        "meetings/dashboard.html", pagination=pagination, meetings=pagination.items,
        search=search, selected_status=selected_status, statuses=STATUSES,
        can_create=has_permission("meetings.create"),
    )


@bp.route("/yeni", methods=["GET", "POST"])
@atomic
def create():
    require_permission("meetings.create")
    if request.method == "POST":
        try:
            values, participant_ids = meeting_values()
        except ValueError as error:
            db.session.rollback()
            flash(str(error), "danger")
            return render_template("meetings/form.html", **form_context()), 400
        meeting = assign_current_company(MeetingRecord(**values, created_by_user_id=g.current_user.id))
        db.session.add(meeting)
        sync_participants(meeting, participant_ids)
        db.session.flush()
        audit(meeting, "created")
        db.session.commit()
        return detail_redirect(meeting)
    return render_template("meetings/form.html", **form_context())


@bp.get("/<int:meeting_id>")
def detail(meeting_id):
    meeting = get_meeting(meeting_id)
    return render_template(
        "meetings/detail.html", meeting=meeting, users=active_users(),
        can_edit=can_edit(meeting), can_export=has_permission("meetings.export"),
        can_decide=lambda decision: can_decide(meeting, decision), statuses=STATUSES, today=date.today(),
    )


@bp.route("/<int:meeting_id>/duzenle", methods=["GET", "POST"])
@atomic
def edit(meeting_id):
    meeting = get_meeting(meeting_id)
    require_editor(meeting)
    if meeting.status not in EDITABLE:
        abort(409)
    if request.method == "POST":
        check_version(meeting)
        try:
            values, participant_ids = meeting_values(meeting)
        except ValueError as error:
            db.session.rollback()
            flash(str(error), "danger")
            return render_template("meetings/form.html", **form_context(meeting)), 400
        old = snapshot(meeting)
        for name, value in values.items():
            setattr(meeting, name, value)
        touch(meeting)
        sync_participants(meeting, participant_ids)
        db.session.flush()
        audit(meeting, "updated", old)
        db.session.commit()
        return detail_redirect(meeting)
    return render_template("meetings/form.html", **form_context(meeting))


@bp.post("/<int:meeting_id>/durum")
@atomic
def transition(meeting_id):
    meeting = get_meeting(meeting_id)
    require_editor(meeting)
    check_version(meeting)
    action = request.form.get("action")
    transitions = {
        "publish": ("draft", "open"), "complete": ("open", "completed"),
        "archive": ("completed", "archived"), "reopen": ("completed", "open"),
    }
    if action not in transitions:
        abort(400)
    source, target = transitions[action]
    if meeting.status != source:
        abort(409)
    if action == "publish":
        if not (meeting.agenda or "").strip() or not meeting.participants:
            raise ValueError("Yay\u0131nlamak i\u00e7in g\u00fcndem ve kat\u0131l\u0131mc\u0131 zorunludur.")
        validate_users({item.user_id for item in meeting.participants} | {item.owner_user_id for item in meeting.decisions})
    if action == "complete" and not (meeting.minutes or "").strip():
        raise ValueError("Toplant\u0131y\u0131 tamamlamak i\u00e7in tutanak zorunludur.")
    if action == "archive" and company_query(MeetingDecision).filter_by(meeting_id=meeting.id, status="open").first():
        raise ValueError("Ar\u015fivlemek i\u00e7in t\u00fcm kararlar tamamlanmal\u0131d\u0131r.")
    old = snapshot(meeting)
    meeting.status = target
    touch(meeting)
    if action == "publish":
        for participant in meeting.participants:
            notify(meeting, participant.user_id, "published", "Toplant\u0131 yay\u0131nland\u0131.")
        for decision in meeting.decisions:
            notify_assignment(meeting, decision)
    audit(meeting, {"publish": "published", "complete": "completed", "archive": "archived", "reopen": "reopened"}[action], old)
    db.session.commit()
    return detail_redirect(meeting)


@bp.post("/<int:meeting_id>/kararlar")
@atomic
def add_decision(meeting_id):
    meeting = get_meeting(meeting_id)
    require_editor(meeting)
    check_version(meeting)
    if meeting.status not in EDITABLE:
        abort(409)
    values = decision_values(meeting)
    touch(meeting)
    decision = assign_current_company(MeetingDecision(meeting=meeting, **values))
    db.session.add(decision)
    db.session.flush()
    audit(decision, "created")
    notify_assignment(meeting, decision)
    db.session.commit()
    return detail_redirect(meeting)


@bp.post("/<int:meeting_id>/kararlar/<int:decision_id>")
@atomic
def update_decision(meeting_id, decision_id):
    meeting = get_meeting(meeting_id)
    decision = company_query(MeetingDecision).filter_by(id=decision_id, meeting_id=meeting.id).first_or_404()
    action = request.form.get("action")
    if action == "edit":
        require_editor(meeting)
        if meeting.status not in EDITABLE or decision.status != "open":
            abort(409)
        values = decision_values(meeting)
    elif action in {"complete", "reopen"}:
        if meeting.status not in {"open", "completed"}:
            abort(409)
        if not can_decide(meeting, decision):
            abort(403)
        expected = "open" if action == "complete" else "completed"
        if decision.status != expected:
            abort(409)
        note = text_field("completion_note", 10000, required=action == "complete")
        values = {
            "status": "completed" if action == "complete" else "open",
            "completion_note": note if action == "complete" else None,
            "completed_at": datetime.now(UTC).replace(tzinfo=None) if action == "complete" else None,
        }
    else:
        abort(400)
    check_version(decision)
    if "meeting_version_id" in request.form:
        check_version(meeting, "meeting_version_id")
    old = snapshot(decision)
    touch(meeting)
    for name, value in values.items():
        setattr(decision, name, value)
    decision.version_id += 1
    db.session.flush()
    audit(decision, {"edit": "updated", "complete": "completed", "reopen": "reopened"}[action], old)
    if action == "edit" and old["owner_user_id"] != decision.owner_user_id:
        notify_assignment(meeting, decision)
    db.session.commit()
    return detail_redirect(meeting)


@bp.get("/<int:meeting_id>/rapor")
@atomic
def export(meeting_id):
    require_permission("meetings.export")
    meeting = get_meeting(meeting_id)
    from .routes import build_simple_xlsx

    decisions = company_query(MeetingDecision).filter_by(meeting_id=meeting.id).order_by(MeetingDecision.id).all()
    rows = [(
        item.title, item.owner.full_name if item.owner else "", item.due_date.isoformat(),
        DECISION_STATUSES[item.status], item.completion_note or "",
        item.completed_at.isoformat(sep=" ", timespec="minutes") if item.completed_at else "",
    ) for item in decisions]
    workbook = build_simple_xlsx(
        ("Karar", "Sorumlu", "Termin", "Durum", "Tamamlama Notu", "Tamamlanma Tarihi"),
        rows, sheet_name="Toplant\u0131 Kararlar\u0131", metadata=[
            ("Toplant\u0131 No", meeting.meeting_no), ("Ba\u015fl\u0131k", meeting.title),
            ("Tarih", meeting.meeting_at.isoformat(sep=" ", timespec="minutes")),
            ("Yer", meeting.location or ""), ("Durum", STATUSES[meeting.status]),
            ("D\u00fczenleyen", meeting.creator.full_name if meeting.creator else ""),
            ("Kat\u0131l\u0131mc\u0131lar", ", ".join(item.user.full_name for item in meeting.participants if item.user)),
            ("G\u00fcndem", meeting.agenda or ""), ("Tutanak", meeting.minutes or ""),
        ],
    )
    record_audit_event("MeetingRecord", "exported", meeting.meeting_no, entity_id=meeting.id,
                       company_id=meeting.company_id, details={"decision_count": len(rows)}, commit=False)
    db.session.commit()
    return send_file(workbook, as_attachment=True, download_name=f"{meeting.meeting_no}.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


def assigned_task_rows(scope, row_builder):
    user = getattr(g, "current_user", None)
    if not user or not current_company_id() or scope == "created":
        return []
    if not any(has_permission(key) for key in READ_PERMISSIONS):
        return []
    checker = getattr(g, "company_module_enabled", None)
    if checker and not checker("meetings"):
        return []
    decisions = company_query(MeetingDecision).join(MeetingDecision.meeting).filter(
        MeetingRecord.company_id == current_company_id(),
        MeetingRecord.status.in_(("open", "completed")),
        MeetingDecision.owner_user_id == user.id,
        MeetingDecision.status == "open",
    ).options(joinedload(MeetingDecision.meeting)).order_by(MeetingDecision.due_date, MeetingDecision.id).all()
    return [row_builder(
        module_key="meetings", module_label="Toplant\u0131lar", module_icon="people", module_tone="quality",
        title=item.title, description=item.meeting.title, reference_no=item.meeting.meeting_no,
        department="", due_date=item.due_date, status=DECISION_STATUSES[item.status],
        status_key="delayed" if item.due_date < date.today() else "pending", priority="Orta",
        detail_url=url_for("meetings.detail", meeting_id=item.meeting_id),
        created_at=item.meeting.created_at, sort_id=item.id,
    ) for item in decisions if can_decide(item.meeting, item)]


def report_data():
    """Report Center summary; its caller controls export permission and period filtering."""
    require_permission(*READ_PERMISSIONS)
    checker = getattr(g, "company_module_enabled", None)
    if checker and not checker("meetings"):
        abort(404)
    meetings = visible_meetings().order_by(MeetingRecord.meeting_at.desc(), MeetingRecord.id.desc()).all() if current_company_id() else []
    return {
        "headers": ("Toplant\u0131 No", "Ba\u015fl\u0131k", "Toplant\u0131 Tarihi", "Yer", "D\u00fczenleyen", "Durum", "Kat\u0131l\u0131mc\u0131", "A\u00e7\u0131k Karar", "Tamamlanan Karar"),
        "rows": [(
            meeting.meeting_no, meeting.title, meeting.meeting_at.strftime("%d.%m.%Y"),
            meeting.location or "", meeting.creator.full_name if meeting.creator else "",
            STATUSES[meeting.status], str(len(meeting.participants)),
            str(sum(item.status == "open" for item in meeting.decisions)),
            str(sum(item.status == "completed" for item in meeting.decisions)),
        ) for meeting in meetings],
        "sheet_name": "Toplant\u0131lar",
        "column_widths": (22, 48, 20, 28, 28, 20, 16, 16, 20),
    }
