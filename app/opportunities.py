from datetime import UTC, date, datetime
from functools import wraps
from math import ceil
import re

from flask import Blueprint, abort, flash, g, redirect, render_template, request, send_file, url_for
from sqlalchemy import extract, literal, or_, union_all
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload
from sqlalchemy.orm.exc import StaleDataError

from .audit import record_audit_event
from .extensions import db
from .models import Action, Notification, RiskRecord, User
from .notifications import add_user_notification
from .opportunity_models import Opportunity
from .tenant import assign_current_company, current_company_id, scoped_query

bp = Blueprint("opportunities", __name__, url_prefix="/risk-firsat-portfoyu")
STATUSES = {"draft": "Taslak", "active": "Aktif", "realized": "Gerçekleşti",
            "not_realized": "Gerçekleşmedi", "archived": "Arşiv"}
OPEN_STATUSES = ("draft", "active")
CLOSED_STATUSES = ("realized", "not_realized")
READ_PERMISSIONS = ("opportunity.view", "opportunity.view_all", "opportunity.manage")
TEXT_FIELDS = {"description": "Açıklama", "expected_benefit": "Beklenen Fayda",
               "planned_action": "Planlanan Faaliyet", "success_criteria": "Başarı Ölçütü",
               "source_reference": "Kaynak Referansı"}
ACTION_READ_PERMISSIONS = ("actions.view_all", "actions.create", "actions.comment_assigned", "actions.request_close_assigned")
MAX_RECORD_ID = 2**63 - 1
INVALID_XML_CHARACTERS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]")


def has_permission(key):
    user = getattr(g, "current_user", None)
    return bool(user and user.is_active and user.has_permission(key))


def require_permission(*keys):
    if not any(has_permission(key) for key in keys):
        abort(403)


def module_enabled(key):
    from .routes import company_module_enabled
    return (getattr(g, "company_module_enabled", None) or company_module_enabled)(key)


def require_module():
    if not module_enabled("risk_management"):
        abort(404)


def company_query(model):
    if not current_company_id():
        abort(403, description="Lütfen bir firma seçin.")
    return scoped_query(model.query, model).filter_by(company_id=current_company_id())


def can_read():
    return any(has_permission(key) for key in READ_PERMISSIONS)


@bp.before_request
def guard():
    if getattr(g, "current_user", None) is None:
        return redirect(url_for("main.login", next=request.full_path))
    company_query(Opportunity)
    require_module()
    from .routes import can_view_risks
    if request.endpoint == "opportunities.dashboard":
        if not can_read() and not (g.current_user.is_active and can_view_risks()):
            abort(403)
    else:
        require_permission(*READ_PERMISSIONS)


def atomic(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        try:
            with db.session.no_autoflush:
                return view(*args, **kwargs)
        except (IntegrityError, StaleDataError):
            db.session.rollback()
            abort(409, description="Kayıt değişti. Sayfayı yenileyip tekrar deneyin.")
        except Exception:
            db.session.rollback()
            raise
    return wrapped


def visible_opportunities():
    require_permission(*READ_PERMISSIONS)
    require_module()
    query = company_query(Opportunity).options(joinedload(Opportunity.owner), joinedload(Opportunity.reviewer))
    if has_permission("opportunity.view_all") or has_permission("opportunity.manage"):
        return query
    return query.filter(or_(Opportunity.created_by_user_id == g.current_user.id,
                            Opportunity.owner_user_id == g.current_user.id))


def get_opportunity(opportunity_id):
    if not 0 < opportunity_id <= MAX_RECORD_ID:
        abort(404)
    return visible_opportunities().filter_by(id=opportunity_id).first_or_404()


def manageable(item):
    return bool(item.company_id == current_company_id() and (has_permission("opportunity.manage") or (
        has_permission("opportunity.create") and g.current_user.id in (item.owner_user_id, item.created_by_user_id))))


def can_edit(item):
    return item.status in OPEN_STATUSES and manageable(item)


def can_review(item):
    return item.company_id == current_company_id() and (has_permission("opportunity.review") or has_permission("opportunity.manage"))


def eligible_owner(user):
    return bool(user and user.is_active and any(user.has_permission(key) for key in READ_PERMISSIONS)
                and (user.has_permission("opportunity.create") or user.has_permission("opportunity.manage")))


def validate_owner(owner_id):
    if not 0 < owner_id <= MAX_RECORD_ID:
        raise ValueError("Geçerli bir sorumlu seçin.")
    owner = company_query(User).filter_by(id=owner_id).first()
    if not eligible_owner(owner):
        raise ValueError("Bu firmada fırsat düzenleme yetkisi olan aktif bir sorumlu seçin.")
    return owner


def action_choices():
    from .routes import visible_actions_query
    if not current_company_id() or not module_enabled("actions") or not any(has_permission(key) for key in ACTION_READ_PERMISSIONS):
        return company_query(Action).filter(db.false())
    return visible_actions_query().filter(Action.company_id == current_company_id())


def visible_linked_action(item):
    from .routes import can_view_action
    action = action_choices().filter(Action.id == item.action_id).first() if item.action_id else None
    return action if action and can_view_action(action) else None


def text_field(name, required=False, limit=20000):
    value = request.form.get(name, "").strip()
    if (required and not value) or len(value) > limit:
        raise ValueError("Zorunlu alanları ve metin uzunluklarını kontrol edin.")
    return value


def opportunity_values(item=None):
    values = {key: text_field(key) for key in TEXT_FIELDS}
    values["title"] = text_field("title", required=True, limit=240)
    try:
        values.update(analysis_date=date.fromisoformat(request.form.get("analysis_date", "")),
                      due_date=date.fromisoformat(request.form.get("due_date", "")),
                      review_date=date.fromisoformat(request.form["review_date"]) if request.form.get("review_date") else None,
                      owner_user_id=int(request.form.get("owner_user_id", "")),
                      likelihood=int(request.form.get("likelihood", "")), benefit=int(request.form.get("benefit", "")))
    except (TypeError, ValueError):
        raise ValueError("Geçerli tarih, sorumlu ve puan seçin.") from None
    if values["due_date"] < values["analysis_date"] or (values["review_date"] and values["review_date"] < values["analysis_date"]):
        raise ValueError("Termin ve gözden geçirme tarihi analiz tarihinden önce olamaz.")
    if values["likelihood"] not in range(1, 6) or values["benefit"] not in range(1, 6):
        raise ValueError("Olasılık ve fayda 1 ile 5 arasında olmalıdır.")
    validate_owner(values["owner_user_id"])
    action_value = request.form.get("action_id", "").strip()
    if item and item.action_id and action_value == "__keep__":
        values["action_id"] = item.action_id
    elif action_value:
        try:
            action_id = int(action_value)
        except ValueError:
            raise ValueError("Geçerli ve erişilebilir bir aksiyon seçin.") from None
        if not 0 < action_id <= MAX_RECORD_ID:
            raise ValueError("Geçerli ve erişilebilir bir aksiyon seçin.")
        action = action_choices().filter(Action.id == action_id).first()
        from .routes import can_view_action
        if not action or not can_view_action(action):
            raise ValueError("Geçerli ve erişilebilir bir aksiyon seçin.")
        values["action_id"] = action.id
    else:
        values["action_id"] = None
    if item and item.status == "active":
        validate_active(values)
    return values


def validate_active(values):
    if not all((values.get(key) or "").strip() for key in ("description", "expected_benefit", "planned_action", "success_criteria")) or not values.get("review_date"):
        raise ValueError("Aktivasyon için açıklama, beklenen fayda, planlanan faaliyet, başarı ölçütü ve gözden geçirme tarihi zorunludur.")
    validate_owner(values["owner_user_id"])


def check_version(item):
    try:
        version = int(request.form.get("version_id", ""))
    except (ValueError, TypeError):
        abort(409)
    if version != item.version_id:
        abort(409, description="Kayıt değişti. Sayfayı yenileyin.")


def touch(item):
    item.version_id += 1
    item.updated_at = datetime.now(UTC).replace(tzinfo=None)
    db.session.flush([item])


def snapshot(item):
    return {column.name: getattr(item, column.name) for column in item.__table__.columns}


def audit(item, action, old=None, reason=None):
    values = snapshot(item)
    if reason is not None:
        values["reason"] = reason
    record_audit_event("Opportunity", action, item.title, entity_id=item.id, company_id=item.company_id,
                       old_values=old, new_values=values, commit=False)


def retire_notices(item):
    Notification.query.filter_by(company_id=item.company_id).filter(
        Notification.source_key.like(f"opportunity:{item.id}:%")).delete(synchronize_session="fetch")


def notify(item):
    if item.status not in OPEN_STATUSES or item.owner_user_id == g.current_user.id:
        return
    owner = company_query(User).filter_by(id=item.owner_user_id).first()
    if eligible_owner(owner):
        add_user_notification(owner, f"{item.record_no} - {item.title}", company_id=item.company_id,
            source_key=f"opportunity:{item.id}:owner:{owner.id}:{item.version_id}",
            target_url=url_for("opportunities.detail", opportunity_id=item.id), due_date=item.due_date)


def form_context(item=None):
    from .routes import can_view_action
    values = dict(request.form) if request.method == "POST" else (snapshot(item) if item else {})
    hidden_action = bool(item and item.action_id and not visible_linked_action(item))
    if hidden_action and request.method != "POST":
        values["action_id"] = "__keep__"
    users = company_query(User).filter_by(is_active=True).order_by(User.full_name, User.id).all()
    return dict(opportunity=item, values=values, users=[user for user in users if eligible_owner(user)],
                actions=[action for action in action_choices().order_by(Action.id.desc()).all() if can_view_action(action)],
                hidden_action=hidden_action, text_fields=TEXT_FIELDS)


def detail_context(item):
    return dict(opportunity=item, statuses=STATUSES, text_fields=TEXT_FIELDS, values=request.form,
        linked_action=visible_linked_action(item), can_edit=can_edit(item), can_review=can_review(item),
        can_export=has_permission("opportunity.export"), can_activate=item.status == "draft" and manageable(item),
        can_reopen=item.status in CLOSED_STATUSES and (can_review(item) or manageable(item)),
        can_recover=item.status == "active" and has_permission("opportunity.manage") and not eligible_owner(item.owner),
        can_archive=item.status in ("draft", *CLOSED_STATUSES) and manageable(item))


def detail_redirect(item):
    if not visible_opportunities().filter_by(id=item.id).first():
        return redirect(url_for("opportunities.dashboard"))
    return redirect(url_for("opportunities.detail", opportunity_id=item.id))


@bp.get("")
def dashboard():
    from .routes import RISK_STATUSES, can_view_risks, risk_query
    risk_visible = g.current_user.is_active and can_view_risks()
    opportunity_visible = can_read()
    risks = risk_query().filter(RiskRecord.company_id == current_company_id()) if risk_visible else None
    opportunities = visible_opportunities() if opportunity_visible else None
    counts = dict(open_risks=0, high_risks=0, open_opportunities=0, high_benefit=0)
    if risks is not None:
        open_risks = risks.filter(RiskRecord.status.notin_(("Kapandı", "Arşiv")))
        counts.update(open_risks=open_risks.count(), high_risks=open_risks.filter(RiskRecord.likelihood * RiskRecord.severity >= 16).count())
    if opportunities is not None:
        open_opportunities = opportunities.filter(Opportunity.status.in_(OPEN_STATUSES))
        counts.update(open_opportunities=open_opportunities.count(), high_benefit=open_opportunities.filter(Opportunity.benefit >= 4).count())
    search = request.args.get("q", "").strip()[:240]
    kind = request.args.get("type", "")
    kind = kind if kind in ("risk", "opportunity") else ""
    statuses = {}
    if opportunity_visible and kind != "risk":
        statuses.update(STATUSES)
    if risk_visible and kind != "opportunity":
        statuses.update({status: status for status in RISK_STATUSES if status != "Arşiv"})
    status = request.args.get("status", "")
    status = status if status in statuses else ""
    queries = []
    if risks is not None and kind != "opportunity":
        if search:
            risks = risks.filter(or_(RiskRecord.title.ilike(f"%{search}%"), RiskRecord.risk_no.ilike(f"%{search}%"), RiskRecord.description.ilike(f"%{search}%")))
        if status:
            risks = risks.filter(RiskRecord.status == status)
        queries.append(risks.with_entities(RiskRecord.id.label("id"), literal("risk").label("kind"), RiskRecord.created_at.label("created_at")).statement)
    if opportunities is not None and kind != "risk":
        if search:
            reference = re.fullmatch(r"FRS-(\d{4})-(\d+)", search, re.IGNORECASE)
            filters = [Opportunity.title.ilike(f"%{search}%"), Opportunity.description.ilike(f"%{search}%")]
            if reference and 0 < int(reference[2]) <= MAX_RECORD_ID:
                filters.append(db.and_(Opportunity.id == int(reference[2]), extract("year", Opportunity.created_at) == int(reference[1])))
            opportunities = opportunities.filter(or_(*filters))
        if status:
            opportunities = opportunities.filter(Opportunity.status == status)
        queries.append(opportunities.with_entities(Opportunity.id.label("id"), literal("opportunity").label("kind"), Opportunity.created_at.label("created_at")).statement)
    rows, total = [], 0
    page = max(1, min(request.args.get("page", 1, type=int) or 1, 1000000))
    if queries:
        portfolio = union_all(*queries).subquery()
        query = db.session.query(portfolio)
        total = query.count()
        page = min(page, max(1, ceil(total / 25)))
        entries = query.order_by(portfolio.c.created_at.desc(), portfolio.c.kind, portfolio.c.id.desc()).offset((page - 1) * 25).limit(25).all()
        risk_ids = [entry.id for entry in entries if entry.kind == "risk"]
        opportunity_ids = [entry.id for entry in entries if entry.kind == "opportunity"]
        risk_map = {item.id: item for item in risks.filter(RiskRecord.id.in_(risk_ids)).all()} if risk_ids else {}
        opportunity_map = {item.id: item for item in opportunities.filter(Opportunity.id.in_(opportunity_ids)).all()} if opportunity_ids else {}
        for entry in entries:
            item = risk_map.get(entry.id) if entry.kind == "risk" else opportunity_map.get(entry.id)
            if item is None:
                continue
            is_risk = entry.kind == "risk"
            rows.append(dict(kind=entry.kind, title=item.title, reference=item.risk_no if is_risk else item.record_no,
                status=item.status if is_risk else STATUSES[item.status], due_date=item.due_date,
                score=item.rpn if is_risk else item.priority_score,
                url=url_for("main.risk_dashboard", search=item.risk_no) if is_risk else url_for("opportunities.detail", opportunity_id=item.id)))
    return render_template("opportunities/dashboard.html", rows=rows, counts=counts, page=page, pages=max(1, ceil(total / 25)),
        total=total, search=search, selected_type=kind, selected_status=status, statuses=statuses,
        risk_visible=risk_visible, opportunity_visible=opportunity_visible,
        can_create_risk=risk_visible and has_permission("risk.manage"),
        can_create_opportunity=opportunity_visible and (has_permission("opportunity.create") or has_permission("opportunity.manage")))


@bp.route("/firsat/yeni", methods=["GET", "POST"])
@atomic
def create():
    require_permission("opportunity.create", "opportunity.manage")
    if request.method == "POST":
        try:
            values = opportunity_values()
        except ValueError as error:
            flash(str(error), "danger")
            return render_template("opportunities/form.html", **form_context()), 400
        item = assign_current_company(Opportunity(**values, created_by_user_id=g.current_user.id))
        db.session.add(item)
        db.session.flush()
        audit(item, "created")
        notify(item)
        db.session.commit()
        return detail_redirect(item)
    return render_template("opportunities/form.html", **form_context())


@bp.get("/firsat/<int:opportunity_id>")
def detail(opportunity_id):
    return render_template("opportunities/detail.html", **detail_context(get_opportunity(opportunity_id)))


@bp.route("/firsat/<int:opportunity_id>/duzenle", methods=["GET", "POST"])
@atomic
def edit(opportunity_id):
    item = get_opportunity(opportunity_id)
    if not manageable(item):
        abort(403)
    if item.status not in OPEN_STATUSES:
        abort(409)
    if request.method == "POST":
        check_version(item)
        try:
            values = opportunity_values(item)
        except ValueError as error:
            flash(str(error), "danger")
            return render_template("opportunities/form.html", **form_context(item)), 400
        old = snapshot(item)
        for key, value in values.items():
            setattr(item, key, value)
        touch(item)
        audit(item, "updated", old)
        retire_notices(item)
        notify(item)
        db.session.commit()
        return detail_redirect(item)
    return render_template("opportunities/form.html", **form_context(item))


@bp.post("/firsat/<int:opportunity_id>/durum")
@atomic
def transition(opportunity_id):
    item = get_opportunity(opportunity_id)
    action = request.form.get("action")
    if action in CLOSED_STATUSES:
        allowed = can_review(item)
    elif action == "reopen":
        allowed = can_review(item) or manageable(item)
    elif action == "recover":
        allowed = has_permission("opportunity.manage")
    elif action in ("activate", "archive"):
        allowed = manageable(item)
    else:
        abort(400)
    if not allowed:
        abort(403)
    check_version(item)
    old, reason = snapshot(item), None
    try:
        if action == "activate" and item.status == "draft":
            validate_active(old)
            item.status = "active"
        elif action in CLOSED_STATUSES and item.status == "active":
            note = text_field("result_note", required=True)
            evidence = text_field("evidence_sources", required=True)
            if action == "realized" and item.action_id:
                linked = company_query(Action).filter_by(id=item.action_id).with_for_update().first()
                if not linked or not linked.is_completed:
                    raise ValueError("Bağlı aksiyon tamamlanmadan fırsat gerçekleşti olarak kapatılamaz.")
            item.status, item.result_note, item.evidence_sources = action, note, evidence
            item.reviewed_at, item.reviewed_by_user_id = datetime.now(UTC).replace(tzinfo=None), g.current_user.id
        elif (action == "reopen" and item.status in CLOSED_STATUSES) or (
                action == "recover" and item.status == "active" and not eligible_owner(item.owner)):
            reason = text_field("note", required=True)
            item.status = "draft"
            item.result_note = item.evidence_sources = item.reviewed_at = item.reviewed_by_user_id = None
        elif action == "archive" and item.status in ("draft", *CLOSED_STATUSES):
            reason = text_field("note", required=True)
            item.status, item.archive_note = "archived", reason
        else:
            abort(409)
    except ValueError as error:
        flash(str(error), "danger")
        return render_template("opportunities/detail.html", **detail_context(item)), 400
    touch(item)
    audit(item, action, old, reason)
    retire_notices(item)
    notify(item)
    db.session.commit()
    return detail_redirect(item)


REPORT_HEADERS = ("Fırsat No", "Başlık", "Açıklama", "Beklenen Fayda", "Planlanan Faaliyet", "Başarı Ölçütü",
    "Kaynak Referansı", "Sorumlu", "Analiz Tarihi", "Termin Tarihi", "Gözden Geçirme Tarihi", "Olasılık", "Fayda",
    "Öncelik Puanı", "Durum", "Bağlı Aksiyon", "Sonuç Notu", "Kanıt Kaynakları", "Değerlendiren",
    "Değerlendirme Zamanı (UTC)", "Arşiv Gerekçesi")


def report_row(item):
    linked = visible_linked_action(item)
    values = (item.record_no, item.title, *(getattr(item, key) or "" for key in TEXT_FIELDS),
        item.owner.full_name if item.owner else "", item.analysis_date.strftime("%d.%m.%Y"), item.due_date.strftime("%d.%m.%Y"),
        item.review_date.strftime("%d.%m.%Y") if item.review_date else "", item.likelihood, item.benefit, item.priority_score,
        STATUSES[item.status], f"{linked.number_label} - {linked.title}" if linked else "", item.result_note or "",
        item.evidence_sources or "", item.reviewer.full_name if item.reviewer else "",
        item.reviewed_at.strftime("%d.%m.%Y %H:%M") if item.reviewed_at else "", item.archive_note or "")
    # Keep original evidence in the database; replace only XML-illegal export characters.
    return tuple(INVALID_XML_CHARACTERS.sub("\ufffd", str(value)) for value in values)


@bp.get("/firsat/<int:opportunity_id>/rapor")
@atomic
def export(opportunity_id):
    require_permission("opportunity.export")
    item = get_opportunity(opportunity_id)
    from .routes import build_simple_xlsx
    workbook = build_simple_xlsx(REPORT_HEADERS, [report_row(item)], sheet_name="Fırsatlar")
    audit(item, "exported")
    db.session.commit()
    return send_file(workbook, as_attachment=True, download_name=f"{item.record_no}.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


def report_data():
    require_permission(*READ_PERMISSIONS)
    require_module()
    items = visible_opportunities().order_by(Opportunity.analysis_date, Opportunity.id).all()
    return dict(headers=REPORT_HEADERS, rows=[report_row(item) for item in items], sheet_name="Fırsatlar",
                column_widths=(22, 48, 48, 48, 48, 48, 48, 28, 18, 18, 24, 12, 12, 18, 22, 40, 48, 48, 28, 28, 48))


def assigned_task_rows(scope, row_builder):
    if not current_company_id() or scope == "created" or not can_read() or not module_enabled("risk_management"):
        return []
    if not (has_permission("opportunity.create") or has_permission("opportunity.manage")):
        return []
    items = visible_opportunities().filter(Opportunity.owner_user_id == g.current_user.id,
        Opportunity.status.in_(OPEN_STATUSES)).order_by(Opportunity.due_date, Opportunity.id).all()
    today = date.today()
    return [row_builder(module_key="opportunities", module_label="Fırsatlar", module_icon="lightbulb", module_tone="quality",
        title=item.title, description=item.planned_action or "", reference_no=item.record_no, department="",
        due_date=item.due_date, status=STATUSES[item.status], status_key="delayed" if item.due_date < today else "pending",
        priority="Yüksek" if item.priority_score >= 16 else "Orta" if item.priority_score >= 8 else "Düşük",
        detail_url=url_for("opportunities.detail", opportunity_id=item.id), created_at=item.created_at, sort_id=item.id) for item in items]
