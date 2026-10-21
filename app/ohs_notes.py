from datetime import datetime, timezone
from functools import wraps
import re

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import joinedload
from sqlalchemy.orm.exc import StaleDataError

from .audit import record_audit_event
from .extensions import db
from .ohs_notes_models import OhsNote
from .tenant import assign_current_company, current_company_id, scoped_query

bp = Blueprint("ohs_notes", __name__, url_prefix="/isg-notlari")


def require_access():
    if not getattr(g, "current_user", None) or not g.current_user.is_active:
        abort(403)
    if not current_company_id() or not g.company_module_enabled("ohs_actions"):
        abort(403)


@bp.before_request
def guard():
    if not getattr(g, "current_user", None):
        return redirect(url_for("main.login", next=request.full_path))
    require_access()


def records():
    return scoped_query(OhsNote.query, OhsNote).filter_by(
        company_id=current_company_id(), deleted_at=None)


def get_note(note_id):
    if not 0 < note_id < 2**63:
        abort(404)
    return records().filter_by(id=note_id).first_or_404()


def can_edit(note):
    user = g.current_user
    return bool(note.company_id == current_company_id() and (
        note.author_id == user.id or
        user.role_keys & {"super_admin", "company_admin", "management_representative"}))


def atomic(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        try:
            return view(*args, **kwargs)
        except StaleDataError:
            db.session.rollback()
            abort(409, description="Not değişti. Sayfayı yenileyip tekrar deneyin.")
        except IntegrityError:
            db.session.rollback()
            abort(409, description="Kayıt eşzamanlı olarak değişti. Not havuzunu yenileyip kontrol edin.")
        except OperationalError as error:
            db.session.rollback()
            if "locked" in str(error.orig).lower():
                abort(409, description="Kayıt şu anda işleniyor. Kısa süre sonra tekrar deneyin.")
            raise
        except Exception:
            db.session.rollback()
            raise
    return wrapped


def check_version(note):
    if request.form.get("version_id", type=int) != note.version_id:
        abort(409, description="Not değişti. Sayfayı yenileyip tekrar deneyin.")


def snapshot(note):
    return {key: getattr(note, key) for key in (
        "title", "description", "location", "author_id", "action_id", "converted_at", "deleted_at")}


def audit(note, event, old=None):
    db.session.flush()
    record_audit_event("OhsNote", event, note.number, entity_id=note.id,
                       company_id=note.company_id, old_values=old,
                       new_values=snapshot(note), commit=False)


def form_values():
    result = {}
    for key, limit in (("title", 160), ("description", 5000), ("location", 200)):
        value = request.form.get(key, "").strip()
        if len(value) > limit or (key != "location" and not value) or re.search(
            r"[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff]", value
        ):
            raise ValueError("Başlık ve not alanlarını doldurun; metin uzunluklarını kontrol edin.")
        result[key] = value
    return result


@bp.get("")
def dashboard():
    query = records().options(joinedload(OhsNote.author))
    search = request.args.get("search", "").strip()[:160]
    status = request.args.get("status", "")
    if search:
        query = query.filter(or_(OhsNote.title.contains(search, autoescape=True),
                                 OhsNote.description.contains(search, autoescape=True)))
    if status == "open":
        query = query.filter(OhsNote.converted_at.is_(None))
    elif status == "converted":
        query = query.filter(OhsNote.converted_at.isnot(None))
    page = query.order_by(OhsNote.created_at.desc(), OhsNote.id.desc()).paginate(
        page=max(1, request.args.get("page", 1, type=int)), per_page=20, error_out=False)
    return render_template("ohs_notes/list.html", page=page, search=search, status=status)


@bp.route("/yeni", methods=["GET", "POST"])
@atomic
def create():
    if request.method == "POST":
        try:
            values = form_values()
        except ValueError as error:
            flash(str(error), "danger")
        else:
            note = OhsNote(author_id=g.current_user.id, **values)
            assign_current_company(note)
            db.session.add(note)
            audit(note, "created")
            db.session.commit()
            flash("İSG notu kaydedildi.", "success")
            return redirect(url_for("ohs_notes.detail", note_id=note.id))
    return render_template("ohs_notes/form.html", note=None)


@bp.get("/<int:note_id>")
def detail(note_id):
    from .routes import can_view_action
    note = get_note(note_id)
    action = note.action
    visible_action = action if action and action.company_id == current_company_id() and can_view_action(action) else None
    return render_template("ohs_notes/detail.html", note=note, editable=can_edit(note),
                           visible_action=visible_action)


@bp.route("/<int:note_id>/duzenle", methods=["GET", "POST"])
@atomic
def edit(note_id):
    note = get_note(note_id)
    if not can_edit(note):
        abort(403)
    if request.method == "POST":
        check_version(note)
        try:
            values = form_values()
        except ValueError as error:
            flash(str(error), "danger")
        else:
            old = snapshot(note)
            for key, value in values.items():
                setattr(note, key, value)
            audit(note, "updated", old)
            db.session.commit()
            flash("İSG notu güncellendi.", "success")
            return redirect(url_for("ohs_notes.detail", note_id=note.id))
    return render_template("ohs_notes/form.html", note=note)


@bp.post("/<int:note_id>/sil")
@atomic
def delete(note_id):
    note = get_note(note_id)
    if not can_edit(note):
        abort(403)
    check_version(note)
    old = snapshot(note)
    note.deleted_at = datetime.now(timezone.utc).replace(tzinfo=None)
    audit(note, "deleted", old)
    db.session.commit()
    flash("İSG notu silindi. Varsa bağlı aksiyon korundu.", "success")
    return redirect(url_for("ohs_notes.dashboard"))


def source_for_action():
    raw = (request.form if request.method == "POST" else request.args).get("ohs_note_id")
    if not raw:
        return None
    if request.endpoint != "main.create_ohs_action":
        abort(400)
    require_access()
    if not raw.isascii() or not raw.isdigit() or len(raw) > 18:
        abort(404)
    note = get_note(int(raw))
    if note.converted_at is not None:
        abort(409, description="Bu not daha önce aksiyona dönüştürüldü.")
    if request.method == "POST" and request.form.get("ohs_note_version", type=int) != note.version_id:
        abort(409, description="Not değişti. Aksiyon formunu yeniden açın.")
    return note


def link_action(note, action):
    from .routes import add_action_history
    if action.company_id != note.company_id or action.action_category != "ohs":
        abort(403)
    old = snapshot(note)
    note.action_id = action.id
    note.converted_at = datetime.now(timezone.utc).replace(tzinfo=None)
    # Versioned flush claims this note before notifications; a competing save rolls back.
    audit(note, "action_created", old)
    add_action_history(action, "ohs_note_linked",
                       f"Kaynak İSG notu: {note.number} - {note.title}",
                       actor=g.current_user)
