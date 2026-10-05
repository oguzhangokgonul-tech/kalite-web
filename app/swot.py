from datetime import UTC, date, datetime, timedelta
from functools import wraps

from flask import Blueprint, abort, flash, g, redirect, render_template, request, send_file, url_for
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload
from sqlalchemy.orm.exc import StaleDataError

from .audit import record_audit_event
from .extensions import db
from .models import Notification, User
from .notifications import add_user_notification
from .swot_models import SwotAnalysis
from .tenant import assign_current_company, current_company_id, scoped_query

bp = Blueprint("swot", __name__, url_prefix="/swot")
STATUSES = {"draft": "Taslak", "reviewed": "Gözden Geçirildi", "archived": "Arşiv"}
QUADRANTS = {"strengths": "Güçlü Yönler", "weaknesses": "Zayıf Yönler",
             "opportunities": "Fırsatlar", "threats": "Tehditler"}
READ_PERMISSIONS = ("swot.view", "swot.view_all", "swot.manage")


def has_permission(key):
    user = getattr(g, "current_user", None)
    return bool(user and user.is_active and user.has_permission(key))


def require_permission(*keys):
    if not any(has_permission(key) for key in keys):
        abort(403)


def company_query(model):
    if not current_company_id():
        abort(403, description="Lütfen bir firma seçin.")
    return scoped_query(model.query, model).filter_by(company_id=current_company_id())


def require_module():
    checker = getattr(g, "company_module_enabled", None)
    if checker and not checker("swot"):
        abort(404)


@bp.before_request
def guard():
    if getattr(g, "current_user", None) is None:
        return redirect(url_for("main.login", next=request.full_path))
    require_permission(*READ_PERMISSIONS)
    company_query(SwotAnalysis)
    require_module()


@bp.context_processor
def quadrant_context():
    return {"quadrants": QUADRANTS}


def atomic(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        try:
            with db.session.no_autoflush:
                return view(*args, **kwargs)
        except (StaleDataError, IntegrityError):
            db.session.rollback()
            abort(409, description="Kayıt değişti. Sayfayı yenileyip tekrar deneyin.")
        except Exception:
            db.session.rollback()
            raise
    return wrapped


def visible_analyses():
    query = company_query(SwotAnalysis).options(joinedload(SwotAnalysis.owner), joinedload(SwotAnalysis.reviewer))
    if has_permission("swot.view_all") or has_permission("swot.manage"):
        return query
    return query.filter(or_(SwotAnalysis.created_by_user_id == g.current_user.id,
                            SwotAnalysis.owner_user_id == g.current_user.id))


def get_analysis(analysis_id):
    require_permission(*READ_PERMISSIONS)
    return visible_analyses().filter_by(id=analysis_id).first_or_404()


def manageable(analysis):
    return bool(analysis.company_id == current_company_id() and (
        has_permission("swot.manage") or (has_permission("swot.create") and
        g.current_user.id in (analysis.created_by_user_id, analysis.owner_user_id))))


def can_edit(analysis):
    return analysis.status == "draft" and manageable(analysis)


def can_review(analysis):
    return bool(analysis.company_id == current_company_id() and
                (has_permission("swot.review") or has_permission("swot.manage")))


def check_version(analysis):
    try:
        version = int(request.form.get("version_id", ""))
    except (TypeError, ValueError):
        abort(409)
    if version != analysis.version_id:
        abort(409, description="Kayıt değişti. Sayfayı yenileyin.")


def touch(analysis):
    analysis.version_id += 1
    analysis.updated_at = datetime.now(UTC).replace(tzinfo=None)
    db.session.flush([analysis])


def text_field(name, required=False, limit=20000):
    value = request.form.get(name, "").strip()
    if (required and not value) or len(value) > limit:
        raise ValueError("Zorunlu alanları ve metin uzunluklarını kontrol edin.")
    return value


def eligible_owner(user):
    return bool(user and user.is_active and any(user.has_permission(key) for key in READ_PERMISSIONS)
                and (user.has_permission("swot.create") or user.has_permission("swot.manage")))


def validate_owner(owner_id):
    owner = company_query(User).filter_by(id=owner_id).first()
    if not eligible_owner(owner):
        raise ValueError("Bu firmada SWOT düzenleme yetkisi olan aktif bir sorumlu seçin.")
    return owner


def analysis_values():
    title = text_field("title", required=True, limit=240)
    try:
        analysis_date = date.fromisoformat(request.form.get("analysis_date", ""))
        review_date = date.fromisoformat(request.form.get("review_date", ""))
        owner_id = int(request.form.get("owner_user_id", ""))
    except (TypeError, ValueError):
        raise ValueError("Geçerli tarih ve sorumlu seçin.") from None
    if review_date <= analysis_date:
        raise ValueError("Sonraki gözden geçirme tarihi analiz tarihinden sonra olmalıdır.")
    validate_owner(owner_id)
    values = {key: text_field(key) for key in (*QUADRANTS, "strategy")}
    values["scope"] = text_field("scope", required=True)
    return dict(values, title=title, owner_user_id=owner_id,
                analysis_date=analysis_date, review_date=review_date)


def snapshot(analysis):
    return {column.name: getattr(analysis, column.name) for column in analysis.__table__.columns}


def audit(analysis, action, old=None, reason=None):
    values = snapshot(analysis)
    if reason is not None:
        values["reason"] = reason
    record_audit_event("SwotAnalysis", action, analysis.title, entity_id=analysis.id,
        company_id=analysis.company_id, old_values=old, new_values=values, commit=False)


def retire_notices(analysis):
    Notification.query.filter_by(company_id=analysis.company_id).filter(
        Notification.source_key.like(f"swot:{analysis.id}:%")).delete(synchronize_session="fetch")


def notify(analysis):
    if analysis.status == "archived":
        return
    owner = company_query(User).filter_by(id=analysis.owner_user_id).first()
    if eligible_owner(owner):
        add_user_notification(owner, f"{analysis.record_no} - {analysis.title}", company_id=analysis.company_id,
            source_key=f"swot:{analysis.id}:owner:{owner.id}:{analysis.version_id}",
            target_url=url_for("swot.detail", analysis_id=analysis.id), due_date=analysis.review_date)


def form_context(analysis=None):
    values = request.form if request.method == "POST" else (snapshot(analysis) if analysis else {})
    users = company_query(User).filter_by(is_active=True).order_by(User.full_name, User.id).all()
    return dict(analysis=analysis, values=values, users=[user for user in users if eligible_owner(user)])


def detail_context(analysis):
    return dict(analysis=analysis, statuses=STATUSES, can_edit=can_edit(analysis),
        can_review=can_review(analysis), can_export=has_permission("swot.export"), today=date.today(),
        manageable=manageable(analysis), can_reopen=analysis.status == "reviewed" and (can_review(analysis) or manageable(analysis)),
        can_archive=analysis.status != "archived" and manageable(analysis), values=request.form)


def detail_redirect(analysis):
    return redirect(url_for("swot.detail", analysis_id=analysis.id))


@bp.get("")
def dashboard():
    query = visible_analyses()
    search = request.args.get("q", "").strip()[:240]
    status = request.args.get("status", "")
    if search:
        query = query.filter(SwotAnalysis.title.ilike(f"%{search}%"))
    if status in STATUSES:
        query = query.filter_by(status=status)
    else:
        status = ""
    pagination = query.order_by(SwotAnalysis.review_date, SwotAnalysis.id.desc()).paginate(
        page=request.args.get("page", 1, type=int), per_page=25, error_out=False)
    return render_template("swot/dashboard.html", analyses=pagination.items, pagination=pagination,
        search=search, selected_status=status, statuses=STATUSES, today=date.today(),
        can_create=has_permission("swot.create") or has_permission("swot.manage"))


@bp.route("/yeni", methods=["GET", "POST"])
@atomic
def create():
    require_permission("swot.create", "swot.manage")
    if request.method == "POST":
        try:
            values = analysis_values()
        except ValueError as error:
            flash(str(error), "danger")
            return render_template("swot/form.html", **form_context()), 400
        analysis = assign_current_company(SwotAnalysis(**values, created_by_user_id=g.current_user.id))
        db.session.add(analysis)
        db.session.flush()
        audit(analysis, "created")
        notify(analysis)
        db.session.commit()
        return detail_redirect(analysis)
    return render_template("swot/form.html", **form_context())


@bp.get("/<int:analysis_id>")
def detail(analysis_id):
    return render_template("swot/detail.html", **detail_context(get_analysis(analysis_id)))


@bp.route("/<int:analysis_id>/duzenle", methods=["GET", "POST"])
@atomic
def edit(analysis_id):
    analysis = get_analysis(analysis_id)
    if not manageable(analysis):
        abort(403)
    if analysis.status != "draft":
        abort(409)
    if request.method == "POST":
        check_version(analysis)
        try:
            values = analysis_values()
        except ValueError as error:
            flash(str(error), "danger")
            return render_template("swot/form.html", **form_context(analysis)), 400
        old = snapshot(analysis)
        for key, value in values.items():
            setattr(analysis, key, value)
        touch(analysis)
        audit(analysis, "updated", old)
        if any(old[key] != getattr(analysis, key) for key in ("owner_user_id", "review_date", "title", "analysis_date")):
            retire_notices(analysis)
            notify(analysis)
        db.session.commit()
        if not visible_analyses().filter_by(id=analysis.id).first():
            flash("Analiz sorumluluğu devredildi.", "success")
            return redirect(url_for("swot.dashboard"))
        return detail_redirect(analysis)
    return render_template("swot/form.html", **form_context(analysis))


@bp.post("/<int:analysis_id>/durum")
@atomic
def transition(analysis_id):
    analysis = get_analysis(analysis_id)
    action = request.form.get("action")
    if action == "review":
        if not can_review(analysis):
            abort(403)
    elif action == "reopen":
        if not (can_review(analysis) or manageable(analysis)):
            abort(403)
    elif action == "archive":
        if not manageable(analysis):
            abort(403)
    else:
        abort(400)
    check_version(analysis)
    old = snapshot(analysis)
    reason = None
    try:
        if action == "review" and analysis.status == "draft":
            if not all((getattr(analysis, key) or "").strip() for key in (*QUADRANTS, "strategy")):
                raise ValueError("Gözden geçirme için dört SWOT alanı ve strateji zorunludur.")
            validate_owner(analysis.owner_user_id)
            note = text_field("review_note" if "review_note" in request.form else "note", required=True)
            analysis.status, analysis.review_note = "reviewed", note
            analysis.reviewed_by_user_id = g.current_user.id
            analysis.reviewed_at = datetime.now(UTC).replace(tzinfo=None)
        elif action == "reopen" and analysis.status == "reviewed":
            reason = text_field("note", required=True)
            analysis.status = "draft"
            analysis.review_note = analysis.reviewed_by_user_id = analysis.reviewed_at = None
        elif action == "archive" and analysis.status in {"draft", "reviewed"}:
            reason = text_field("note", required=True)
            analysis.status, analysis.archive_note = "archived", reason
        else:
            abort(409)
    except ValueError as error:
        flash(str(error), "danger")
        return render_template("swot/detail.html", **detail_context(analysis)), 400
    touch(analysis)
    audit(analysis, action, old, reason)
    retire_notices(analysis)
    notify(analysis)
    db.session.commit()
    return detail_redirect(analysis)


def report_row(analysis):
    return (analysis.record_no, analysis.title, analysis.scope or "",
        analysis.owner.full_name if analysis.owner else "",
        analysis.analysis_date.strftime("%d.%m.%Y"), analysis.review_date.strftime("%d.%m.%Y"),
        STATUSES[analysis.status], *(getattr(analysis, key) or "" for key in QUADRANTS),
        analysis.strategy or "", analysis.review_note or "", analysis.archive_note or "",
        analysis.reviewer.full_name if analysis.reviewer else "",
        analysis.reviewed_at.strftime("%d.%m.%Y %H:%M") if analysis.reviewed_at else "")


REPORT_HEADERS = ("Analiz No", "Başlık", "Kapsam", "Sorumlu", "Analiz Tarihi", "Sonraki Gözden Geçirme",
                  "Durum", *QUADRANTS.values(), "Strateji", "Gözden Geçirme Notu", "Arşiv Gerekçesi",
                  "Gözden Geçiren", "Gözden Geçirme Zamanı (UTC)")


@bp.get("/<int:analysis_id>/rapor")
@atomic
def export(analysis_id):
    require_permission("swot.export")
    analysis = get_analysis(analysis_id)
    from .routes import build_simple_xlsx
    workbook = build_simple_xlsx(REPORT_HEADERS, [report_row(analysis)], sheet_name="SWOT Analizi")
    audit(analysis, "exported")
    db.session.commit()
    return send_file(workbook, as_attachment=True, download_name=f"{analysis.record_no}.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


def report_data():
    require_permission(*READ_PERMISSIONS)
    require_module()
    analyses = visible_analyses().order_by(SwotAnalysis.analysis_date, SwotAnalysis.id).all() if current_company_id() else []
    return {"headers": REPORT_HEADERS, "rows": [report_row(analysis) for analysis in analyses],
            "sheet_name": "SWOT Analizi", "column_widths": (22, 48, 48, 28, 18, 28, 22, 48, 48, 48, 48, 48, 48, 48, 28, 28)}


def assigned_task_rows(scope, row_builder):
    if not current_company_id() or scope == "created" or not any(has_permission(key) for key in READ_PERMISSIONS):
        return []
    checker = getattr(g, "company_module_enabled", None)
    if checker and not checker("swot"):
        return []
    if not (has_permission("swot.create") or has_permission("swot.manage")):
        return []
    today = date.today()
    analyses = company_query(SwotAnalysis).filter(
        SwotAnalysis.owner_user_id == g.current_user.id,
        or_(SwotAnalysis.status == "draft", db.and_(SwotAnalysis.status == "reviewed",
            SwotAnalysis.review_date <= today + timedelta(days=30))),
    ).order_by(SwotAnalysis.review_date, SwotAnalysis.id).all()
    return [row_builder(module_key="swot", module_label="SWOT Analizi", module_icon="grid-1x2", module_tone="quality",
        title=analysis.title, description=analysis.scope or "", reference_no=analysis.record_no, department="",
        due_date=analysis.review_date, status=STATUSES[analysis.status],
        status_key="delayed" if analysis.review_date < today else "pending", priority="Orta",
        detail_url=url_for("swot.detail", analysis_id=analysis.id), created_at=analysis.created_at,
        sort_id=analysis.id) for analysis in analyses]
