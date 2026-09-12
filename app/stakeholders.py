from datetime import date, datetime
from functools import wraps
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
from sqlalchemy import event, or_
from sqlalchemy.exc import IntegrityError

from .audit import record_audit_event
from .extensions import db
from .models import (
    Action,
    AppSetting,
    CompanyDepartment,
    Notification,
    RiskRecord,
    STAKEHOLDER_FULFILLMENT_STATUSES,
    STAKEHOLDER_INTERNAL_EXTERNAL,
    STAKEHOLDER_PARTY_STATUSES,
    STAKEHOLDER_RELEVANCE_STATUSES,
    StakeholderParty,
    StakeholderRequirement,
    StakeholderReview,
    User,
)
from .notifications import add_user_notification
from .tenant import current_company_id, scoped_query


bp = Blueprint("stakeholders", __name__, url_prefix="/ilgili-taraflar")

PARTY_STATUS_LABELS = {
    "draft": "Taslak",
    "active": "Aktif",
    "archived": "Arşiv",
}
INTERNAL_EXTERNAL_LABELS = {"internal": "İç Taraf", "external": "Dış Taraf"}
RELEVANCE_LABELS = {
    "relevant": "İlgili",
    "not_relevant": "İlgili Değil",
    "under_review": "Değerlendiriliyor",
}
FULFILLMENT_LABELS = {
    "not_assessed": "Değerlendirilmedi",
    "met": "Karşılanıyor",
    "partial": "Kısmen Karşılanıyor",
    "not_met": "Karşılanmıyor",
}
REQUIREMENT_TYPES = {
    "customer": "Müşteri",
    "legal": "Yasal",
    "contractual": "Sözleşmesel",
    "employee": "Çalışan",
    "supplier": "Tedarikçi",
    "other": "Diğer",
}
CATEGORIES = (
    "Müşteri",
    "Çalışan",
    "Tedarikçi",
    "Kamu / Düzenleyici Kurum",
    "Ortak / Yönetim",
    "Toplum / Çevre",
    "Diğer",
)


@event.listens_for(StakeholderReview, "before_update")
@event.listens_for(StakeholderReview, "before_delete")
def prevent_review_mutation(_mapper, _connection, _target):
    raise ValueError("İlgili taraf değerlendirme geçmişi değiştirilemez.")


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
    return checker("stakeholder_management") if checker else True


def party_query():
    return scoped_query(StakeholderParty.query, StakeholderParty)


def requirement_query():
    return scoped_query(StakeholderRequirement.query, StakeholderRequirement)


def can_manage():
    return has_permission("stakeholder.manage")


def can_department_draft():
    user = getattr(g, "current_user", None)
    return bool(user and user.has_role("department_manager"))


def user_matches_department(department):
    from .dynamic_forms import user_matches_department as matches

    return matches(g.current_user, department)


def can_access_party(party):
    user = getattr(g, "current_user", None)
    if user is None:
        return False
    if can_manage() or has_permission("stakeholder.review") or user.has_role("management"):
        return True
    if user.has_role("viewer") and has_permission("stakeholder.view"):
        return party.status == "active"
    if can_department_draft() and user_matches_department(party.department):
        return True
    if party.owner_user_id == user.id:
        return True
    return any(row.responsible_user_id == user.id for row in party.requirements if row.is_active)


def can_edit_party(party):
    if party.status == "archived":
        return False
    if can_manage():
        return True
    return bool(
        party.status == "draft"
        and can_department_draft()
        and party.created_by_user_id == g.current_user.id
        and user_matches_department(party.department)
    )


def can_review_party(party, requirement=None):
    if party.status != "active":
        return False
    if can_manage() or has_permission("stakeholder.review"):
        return True
    if party.owner_user_id == g.current_user.id:
        return True
    return bool(requirement and requirement.responsible_user_id == g.current_user.id)


def get_party_or_404(party_id):
    party = party_query().filter_by(id=party_id).first_or_404()
    if not can_access_party(party):
        abort(403)
    return party


def get_requirement_or_404(requirement_id):
    requirement = requirement_query().filter_by(id=requirement_id).first_or_404()
    if not can_access_party(requirement.party):
        abort(403)
    return requirement


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


def active_departments():
    return [
        row.name
        for row in CompanyDepartment.query.filter_by(
            company_id=current_company_id(), is_active=True
        )
        .order_by(CompanyDepartment.sort_order.asc(), CompanyDepartment.name.asc())
        .all()
    ]


def valid_company_user(user_id):
    user = User.query.filter_by(
        id=user_id, company_id=current_company_id(), is_active=True
    ).first()
    if user is None:
        raise ValueError("Aktif ve geçerli bir sorumlu seçin.")
    return user


def valid_risk(risk_id):
    if not risk_id:
        return None
    risk = scoped_query(RiskRecord.query, RiskRecord).filter_by(id=risk_id).first()
    if risk is None:
        raise ValueError("Geçerli bir risk kaydı seçin.")
    return risk


def valid_action(action_id):
    if not action_id:
        return None
    action = scoped_query(Action.query, Action).filter_by(id=action_id).first()
    if action is None:
        raise ValueError("Geçerli bir aksiyon seçin.")
    return action


def reserve_party_no():
    year = date.today().year
    prefix = f"ILT-{year}-"
    numbers = []
    for (value,) in (
        party_query()
        .with_entities(StakeholderParty.party_no)
        .filter(StakeholderParty.party_no.like(f"{prefix}%"))
        .all()
    ):
        match = re.fullmatch(rf"{re.escape(prefix)}(\d+)", value or "")
        if match:
            numbers.append(int(match.group(1)))
    return f"{prefix}{max(numbers, default=0) + 1:04d}"


def form_context(party=None, values=None):
    values = values or {}
    return {
        "party": party,
        "values": values,
        "users": active_users(),
        "departments": active_departments(),
        "categories": CATEGORIES,
        "internal_external_labels": INTERNAL_EXTERNAL_LABELS,
        "relevance_labels": RELEVANCE_LABELS,
    }


def parse_party_form():
    name = (request.form.get("name") or "").strip()[:180]
    category = (request.form.get("category") or "").strip()[:100]
    department = (request.form.get("department") or "").strip()[:160]
    if not name or not category or not department:
        raise ValueError("Taraf adı, kategori ve departman zorunludur.")
    internal_external = (request.form.get("internal_external") or "").strip()
    relevance_status = (request.form.get("relevance_status") or "").strip()
    if internal_external not in STAKEHOLDER_INTERNAL_EXTERNAL:
        raise ValueError("Geçerli bir taraf sınıfı seçin.")
    if relevance_status not in STAKEHOLDER_RELEVANCE_STATUSES:
        raise ValueError("Geçerli bir ilgililik durumu seçin.")
    owner = valid_company_user(request.form.get("owner_user_id", type=int))
    if can_department_draft() and not can_manage() and not user_matches_department(department):
        abort(403)
    next_review_date = parse_date(request.form.get("next_review_date"), required=True)
    return {
        "name": name,
        "internal_external": internal_external,
        "category": category,
        "relevance_status": relevance_status,
        "relevance_reason": (request.form.get("relevance_reason") or "").strip()[:5000] or None,
        "department": department,
        "owner_user_id": owner.id,
        "influence_score": parse_int(request.form.get("influence_score"), "Etki puanı", 1, 5),
        "importance_score": parse_int(request.form.get("importance_score"), "Önem puanı", 1, 5),
        "review_interval_months": parse_int(
            request.form.get("review_interval_months"), "Gözden geçirme sıklığı", 1, 36
        ),
        "next_review_date": next_review_date,
    }


def requirement_form_context(party, requirement=None, values=None):
    return {
        "party": party,
        "requirement": requirement,
        "values": values or {},
        "users": active_users(),
        "requirement_types": REQUIREMENT_TYPES,
        "fulfillment_labels": FULFILLMENT_LABELS,
        "risks": scoped_query(RiskRecord.query, RiskRecord).order_by(RiskRecord.risk_no.asc()).all(),
        "actions": scoped_query(Action.query, Action).order_by(Action.id.desc()).all(),
    }


def parse_requirement_form():
    requirement_type = (request.form.get("requirement_type") or "").strip()
    fulfillment_status = (request.form.get("fulfillment_status") or "").strip()
    title = (request.form.get("title") or "").strip()[:180]
    if requirement_type not in REQUIREMENT_TYPES or not title:
        raise ValueError("Beklenti türü ve başlığı zorunludur.")
    if fulfillment_status not in STAKEHOLDER_FULFILLMENT_STATUSES:
        raise ValueError("Geçerli bir karşılama durumu seçin.")
    responsible = valid_company_user(request.form.get("responsible_user_id", type=int))
    risk = valid_risk(request.form.get("risk_id", type=int))
    action = valid_action(request.form.get("action_id", type=int))
    improvement_plan = (request.form.get("improvement_plan") or "").strip()[:5000] or None
    if fulfillment_status in {"partial", "not_met"} and not (
        risk or action or improvement_plan
    ):
        raise ValueError(
            "Kısmen karşılanan veya karşılanmayan beklenti için risk, aksiyon ya da iyileştirme planı girin."
        )
    return {
        "requirement_type": requirement_type,
        "title": title,
        "description": (request.form.get("description") or "").strip()[:10000] or None,
        "source": (request.form.get("source") or "").strip()[:255] or None,
        "climate_related": request.form.get("climate_related") == "on",
        "process": (request.form.get("process") or "").strip()[:160] or None,
        "fulfillment_status": fulfillment_status,
        "responsible_user_id": responsible.id,
        "due_date": parse_date(request.form.get("due_date")),
        "risk_id": risk.id if risk else None,
        "action_id": action.id if action else None,
        "improvement_plan": improvement_plan,
    }


def notify_assignment(party, requirement=None):
    user = requirement.responsible if requirement else party.owner
    source = f"stakeholder-requirement:{requirement.id}" if requirement else f"stakeholder-party:{party.id}"
    message = (
        f"{party.party_no} için '{requirement.title}' beklentisi size atandı."
        if requirement
        else f"{party.party_no} ilgili taraf kaydı size atandı."
    )
    add_user_notification(
        user,
        message,
        company_id=party.company_id,
        notification_type="info",
        source_key=source,
        target_url=url_for("stakeholders.detail", party_id=party.id),
        due_date=requirement.due_date if requirement else party.next_review_date,
    )


def mark_readiness_complete():
    key = "sales_readiness:competitor_stakeholder_management"
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
    require_permission("stakeholder.view", "stakeholder.manage", "stakeholder.review")
    query = party_query()
    status = (request.args.get("status") or "").strip()
    department = (request.args.get("department") or "").strip()
    search = (request.args.get("search") or "").strip()
    if status in STAKEHOLDER_PARTY_STATUSES:
        query = query.filter(StakeholderParty.status == status)
    if department:
        query = query.filter(StakeholderParty.department == department)
    if search:
        term = f"%{search}%"
        query = query.filter(
            or_(
                StakeholderParty.party_no.ilike(term),
                StakeholderParty.name.ilike(term),
                StakeholderParty.category.ilike(term),
            )
        )
    records = [row for row in query.order_by(StakeholderParty.id.desc()).all() if can_access_party(row)]
    return render_template(
        "stakeholders/dashboard.html",
        records=records,
        departments=active_departments(),
        filters={"status": status, "department": department, "search": search},
        status_labels=PARTY_STATUS_LABELS,
        fulfillment_labels=FULFILLMENT_LABELS,
        can_create=can_manage() or can_department_draft(),
        can_export=has_permission("stakeholder.export") or can_manage(),
        today=date.today(),
    )


@bp.route("/yeni", methods=("GET", "POST"))
def create_party():
    if not (can_manage() or can_department_draft()):
        abort(403)
    if request.method == "POST":
        try:
            values = parse_party_form()
            party = StakeholderParty(
                company_id=current_company_id(),
                party_no=reserve_party_no(),
                created_by_user_id=g.current_user.id,
                status="draft",
                **values,
            )
            db.session.add(party)
            db.session.flush()
            notify_assignment(party)
            record_audit_event(
                "StakeholderParty",
                "stakeholder_created",
                f"{party.party_no} ilgili taraf kaydı oluşturuldu",
                entity_id=party.id,
                commit=False,
            )
            db.session.commit()
            flash("İlgili taraf kaydı oluşturuldu.", "success")
            return redirect(url_for("stakeholders.detail", party_id=party.id))
        except IntegrityError:
            db.session.rollback()
            flash("Kayıt numarası çakıştı. Lütfen tekrar deneyin.", "danger")
        except ValueError as error:
            db.session.rollback()
            flash(str(error), "danger")
    return render_template("stakeholders/form.html", **form_context(values=request.form))


@bp.route("/<int:party_id>/duzenle", methods=("GET", "POST"))
def edit_party(party_id):
    party = get_party_or_404(party_id)
    if not can_edit_party(party):
        abort(403)
    if request.method == "POST":
        try:
            old_owner = party.owner_user_id
            values = parse_party_form()
            for key, value in values.items():
                setattr(party, key, value)
            if old_owner != party.owner_user_id:
                notify_assignment(party)
            record_audit_event(
                "StakeholderParty",
                "stakeholder_updated",
                f"{party.party_no} ilgili taraf kaydı güncellendi",
                entity_id=party.id,
                commit=False,
            )
            db.session.commit()
            flash("İlgili taraf kaydı güncellendi.", "success")
            return redirect(url_for("stakeholders.detail", party_id=party.id))
        except ValueError as error:
            db.session.rollback()
            flash(str(error), "danger")
    return render_template("stakeholders/form.html", **form_context(party, request.form))


@bp.get("/<int:party_id>")
def detail(party_id):
    require_permission("stakeholder.view", "stakeholder.manage", "stakeholder.review")
    party = get_party_or_404(party_id)
    return render_template(
        "stakeholders/detail.html",
        party=party,
        party_status_labels=PARTY_STATUS_LABELS,
        internal_external_labels=INTERNAL_EXTERNAL_LABELS,
        relevance_labels=RELEVANCE_LABELS,
        fulfillment_labels=FULFILLMENT_LABELS,
        requirement_types=REQUIREMENT_TYPES,
        can_edit=can_edit_party(party),
        can_manage=can_manage(),
        can_archive=has_permission("stakeholder.archive") or can_manage(),
        can_review=lambda requirement=None: can_review_party(party, requirement),
    )


@bp.post("/<int:party_id>/aktiflestir")
def activate(party_id):
    require_permission("stakeholder.manage")
    party = get_party_or_404(party_id)
    if party.status != "draft":
        abort(409)
    if not any(row.is_active for row in party.requirements):
        flash("Kayıt aktifleştirilmeden önce en az bir beklenti ekleyin.", "danger")
        return redirect(url_for("stakeholders.detail", party_id=party.id))
    party.status = "active"
    party.activated_at = datetime.utcnow()
    notify_assignment(party)
    mark_readiness_complete()
    record_audit_event(
        "StakeholderParty",
        "stakeholder_activated",
        f"{party.party_no} ilgili taraf kaydı aktifleştirildi",
        entity_id=party.id,
        commit=False,
    )
    db.session.commit()
    flash("İlgili taraf kaydı aktifleştirildi.", "success")
    return redirect(url_for("stakeholders.detail", party_id=party.id))


@bp.post("/<int:party_id>/arsivle")
def archive(party_id):
    require_permission("stakeholder.archive", "stakeholder.manage")
    party = get_party_or_404(party_id)
    if party.status == "archived":
        abort(409)
    party.status = "archived"
    party.archived_at = datetime.utcnow()
    requirement_source_keys = [
        f"stakeholder-requirement:{row.id}" for row in party.requirements
    ]
    Notification.query.filter_by(company_id=party.company_id).filter(
        Notification.source_key.in_(
            [f"stakeholder-party:{party.id}", *requirement_source_keys]
        )
    ).update(
        {
            Notification.is_read: True,
            Notification.target_url: url_for("stakeholders.dashboard"),
        },
        synchronize_session=False,
    )
    record_audit_event(
        "StakeholderParty",
        "stakeholder_archived",
        f"{party.party_no} ilgili taraf kaydı arşivlendi",
        entity_id=party.id,
        commit=False,
    )
    db.session.commit()
    flash("İlgili taraf kaydı arşivlendi.", "success")
    return redirect(url_for("stakeholders.dashboard"))


@bp.route("/<int:party_id>/beklenti/yeni", methods=("GET", "POST"))
def create_requirement(party_id):
    party = get_party_or_404(party_id)
    if not can_edit_party(party):
        abort(403)
    if request.method == "POST":
        try:
            values = parse_requirement_form()
            row = StakeholderRequirement(
                company_id=party.company_id,
                party_id=party.id,
                created_by_user_id=g.current_user.id,
                **values,
            )
            db.session.add(row)
            db.session.flush()
            notify_assignment(party, row)
            record_audit_event(
                "StakeholderRequirement",
                "stakeholder_requirement_created",
                f"{party.party_no} beklentisi eklendi",
                entity_id=row.id,
                commit=False,
            )
            db.session.commit()
            flash("İhtiyaç veya beklenti eklendi.", "success")
            return redirect(url_for("stakeholders.detail", party_id=party.id))
        except ValueError as error:
            db.session.rollback()
            flash(str(error), "danger")
    return render_template(
        "stakeholders/requirement_form.html", **requirement_form_context(party, values=request.form)
    )


@bp.route("/beklenti/<int:requirement_id>/duzenle", methods=("GET", "POST"))
def edit_requirement(requirement_id):
    row = get_requirement_or_404(requirement_id)
    if not row.is_active or not can_edit_party(row.party):
        abort(403)
    if request.method == "POST":
        try:
            old_responsible = row.responsible_user_id
            values = parse_requirement_form()
            for key, value in values.items():
                setattr(row, key, value)
            if old_responsible != row.responsible_user_id:
                notify_assignment(row.party, row)
            record_audit_event(
                "StakeholderRequirement",
                "stakeholder_requirement_updated",
                f"{row.party.party_no} beklentisi güncellendi",
                entity_id=row.id,
                commit=False,
            )
            db.session.commit()
            flash("İhtiyaç veya beklenti güncellendi.", "success")
            return redirect(url_for("stakeholders.detail", party_id=row.party_id))
        except ValueError as error:
            db.session.rollback()
            flash(str(error), "danger")
    return render_template(
        "stakeholders/requirement_form.html",
        **requirement_form_context(row.party, row, request.form),
    )


@bp.post("/beklenti/<int:requirement_id>/arsivle")
def archive_requirement(requirement_id):
    row = get_requirement_or_404(requirement_id)
    if not can_edit_party(row.party):
        abort(403)
    if not row.is_active:
        abort(409)
    row.is_active = False
    row.archived_at = datetime.utcnow()
    Notification.query.filter_by(
        company_id=row.company_id,
        source_key=f"stakeholder-requirement:{row.id}",
    ).update(
        {
            Notification.is_read: True,
            Notification.target_url: url_for("stakeholders.dashboard"),
        },
        synchronize_session=False,
    )
    record_audit_event(
        "StakeholderRequirement",
        "stakeholder_requirement_archived",
        f"{row.party.party_no} beklentisi arşivlendi",
        entity_id=row.id,
        commit=False,
    )
    db.session.commit()
    flash("İhtiyaç veya beklenti arşivlendi.", "success")
    return redirect(url_for("stakeholders.detail", party_id=row.party_id))


@bp.route("/<int:party_id>/degerlendir", methods=("GET", "POST"))
def review_party(party_id):
    party = get_party_or_404(party_id)
    requirement_id = request.values.get("requirement_id", type=int)
    requirement = None
    if requirement_id:
        requirement = requirement_query().filter_by(
            id=requirement_id, party_id=party.id, is_active=True
        ).first_or_404()
    if not can_review_party(party, requirement):
        abort(403)
    if request.method == "POST":
        outcome = (request.form.get("outcome") or "").strip()
        summary = (request.form.get("summary") or "").strip()[:10000]
        evidence_note = (request.form.get("evidence_note") or "").strip()[:10000] or None
        try:
            next_review_date = parse_date(request.form.get("next_review_date"), required=True)
            if outcome not in STAKEHOLDER_FULFILLMENT_STATUSES:
                raise ValueError("Geçerli bir değerlendirme sonucu seçin.")
            if not summary:
                raise ValueError("Değerlendirme özeti zorunludur.")
            if requirement and outcome in {"partial", "not_met"} and not (
                requirement.risk_id or requirement.action_id or requirement.improvement_plan
            ):
                raise ValueError(
                    "Olumsuz değerlendirme için risk, aksiyon veya iyileştirme planı bulunmalıdır."
                )
            review = StakeholderReview(
                company_id=party.company_id,
                party_id=party.id,
                requirement_id=requirement.id if requirement else None,
                reviewer_user_id=g.current_user.id,
                party_name_snapshot=party.name,
                requirement_title_snapshot=requirement.title if requirement else None,
                requirement_source_snapshot=requirement.source if requirement else None,
                fulfillment_status_before=(
                    requirement.fulfillment_status if requirement else None
                ),
                outcome=outcome,
                summary=summary,
                evidence_note=evidence_note,
                next_review_date=next_review_date,
            )
            db.session.add(review)
            party.last_review_date = date.today()
            party.next_review_date = next_review_date
            if requirement:
                requirement.fulfillment_status = outcome
            Notification.query.filter_by(
                company_id=party.company_id, user_id=g.current_user.id
            ).filter(
                Notification.source_key.in_(
                    [
                        f"stakeholder-party:{party.id}",
                        f"stakeholder-requirement:{requirement.id}" if requirement else "",
                    ]
                )
            ).update({Notification.is_read: True}, synchronize_session=False)
            add_user_notification(
                party.owner,
                f"{party.party_no} ilgili taraf değerlendirmesi kaydedildi.",
                company_id=party.company_id,
                notification_type="success",
                source_key=f"stakeholder-review:{party.id}:{datetime.utcnow().timestamp()}",
                target_url=url_for("stakeholders.detail", party_id=party.id),
                due_date=next_review_date,
            )
            record_audit_event(
                "StakeholderReview",
                "stakeholder_review_recorded",
                f"{party.party_no} değerlendirmesi kaydedildi",
                details={"outcome": outcome, "requirement_id": requirement.id if requirement else None},
                commit=False,
            )
            db.session.commit()
            flash("Değerlendirme değiştirilemez tarihçeye kaydedildi.", "success")
            return redirect(url_for("stakeholders.detail", party_id=party.id))
        except ValueError as error:
            db.session.rollback()
            flash(str(error), "danger")
    return render_template(
        "stakeholders/review_form.html",
        party=party,
        requirement=requirement,
        fulfillment_labels=FULFILLMENT_LABELS,
        values=request.form,
    )


@bp.get("/excel")
def export_excel():
    require_permission("stakeholder.export", "stakeholder.manage")
    rows = []
    for party in party_query().order_by(StakeholderParty.id.asc()).all():
        if not can_access_party(party):
            continue
        requirements = party.requirements or [None]
        for requirement in requirements:
            latest = requirement.reviews[0] if requirement and requirement.reviews else None
            rows.append(
                (
                    party.party_no,
                    party.name,
                    INTERNAL_EXTERNAL_LABELS.get(party.internal_external, party.internal_external),
                    party.category,
                    party.department or "",
                    party.owner.full_name,
                    party.influence_score,
                    party.importance_score,
                    party.priority_score,
                    PARTY_STATUS_LABELS.get(party.status, party.status),
                    requirement.title if requirement else "",
                    "Aktif" if requirement and requirement.is_active else "Arşiv" if requirement else "",
                    REQUIREMENT_TYPES.get(requirement.requirement_type, requirement.requirement_type) if requirement else "",
                    requirement.source or "" if requirement else "",
                    "Evet" if requirement and requirement.climate_related else "Hayır",
                    requirement.process or "" if requirement else "",
                    FULFILLMENT_LABELS.get(requirement.fulfillment_status, requirement.fulfillment_status) if requirement else "",
                    requirement.responsible.full_name if requirement else "",
                    requirement.due_date.strftime("%d.%m.%Y") if requirement and requirement.due_date else "",
                    requirement.risk.risk_no if requirement and requirement.risk else "",
                    str(requirement.action.action_number or requirement.action.id) if requirement and requirement.action else "",
                    latest.reviewer.full_name if latest else "",
                    latest.reviewed_at.strftime("%d.%m.%Y") if latest else "",
                    FULFILLMENT_LABELS.get(latest.outcome, latest.outcome) if latest else "",
                    latest.summary if latest else "",
                    latest.evidence_note or "" if latest else "",
                    len(requirement.reviews) if requirement else 0,
                    party.next_review_date.strftime("%d.%m.%Y"),
                )
            )
    from .routes import build_simple_xlsx

    workbook = build_simple_xlsx(
        (
            "Kayıt No", "İlgili Taraf", "Sınıf", "Kategori", "Departman", "Sorumlu",
            "Etki", "Önem", "Öncelik", "Durum", "İhtiyaç / Beklenti", "Beklenti Durumu", "Tür",
            "Kaynak", "İklimle İlgili", "Süreç", "Karşılama Durumu", "Beklenti Sorumlusu",
            "Termin", "Risk", "Aksiyon", "Son Değerlendiren", "Son Değerlendirme",
            "Son Değerlendirme Sonucu", "Son Değerlendirme Özeti", "Kanıt Notu", "Değerlendirme Sayısı",
            "Sonraki Gözden Geçirme",
        ),
        rows,
        sheet_name="İlgili Taraf Matrisi",
        column_widths=(18, 28, 14, 24, 22, 24, 10, 10, 10, 16, 34, 16, 18, 28, 16, 24, 24, 24, 14, 16, 14, 24, 18, 24, 42, 36, 18, 22),
    )
    record_audit_event(
        "StakeholderParty",
        "stakeholder_matrix_exported",
        "İlgili taraf ve beklenti matrisi indirildi",
        details={"row_count": len(rows)},
    )
    return send_file(
        workbook,
        as_attachment=True,
        download_name=f"ilgili-taraf-matrisi-{date.today().strftime('%Y%m%d')}.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def assigned_task_rows(scope, row_builder):
    if not module_enabled() or getattr(g, "current_user", None) is None:
        return []
    rows = []
    user_id = g.current_user.id
    if scope == "created":
        created_parties = party_query().filter(
            StakeholderParty.created_by_user_id == user_id
        )
        for party in created_parties.order_by(StakeholderParty.next_review_date.asc()).all():
            rows.append(
                row_builder(
                    module_key="stakeholder",
                    module_label="İlgili Taraf",
                    module_icon="people",
                    module_tone="quality",
                    title=f"{party.party_no} {party.name}",
                    description=f"{party.category} / {len([r for r in party.requirements if r.is_active])} beklenti",
                    reference_no=party.party_no,
                    department=party.department or "İlgili Taraflar",
                    due_date=party.next_review_date,
                    status=PARTY_STATUS_LABELS.get(party.status, party.status),
                    status_key=(
                        "completed" if party.status == "archived" else
                        "draft" if party.status == "draft" else "open"
                    ),
                    priority="Yüksek" if party.priority_score >= 16 else "Orta" if party.priority_score >= 8 else "Düşük",
                    detail_url=url_for("stakeholders.detail", party_id=party.id),
                    created_at=party.created_at,
                    sort_id=party.id,
                    date_label="Gözden Geçirme",
                )
            )
        return rows

    owned_parties = party_query().filter(
        StakeholderParty.owner_user_id == user_id,
        StakeholderParty.status != "archived",
    )
    for party in owned_parties.order_by(StakeholderParty.next_review_date.asc()).all():
        due_date = party.next_review_date
        delayed = bool(due_date and due_date < date.today() and party.status == "active")
        rows.append(
            row_builder(
                module_key="stakeholder",
                module_label="İlgili Taraf",
                module_icon="people",
                module_tone="quality",
                title=f"{party.party_no} {party.name}",
                description=f"{party.category} / {len([r for r in party.requirements if r.is_active])} beklenti",
                reference_no=party.party_no,
                department=party.department or "İlgili Taraflar",
                due_date=due_date,
                status="Gecikti" if delayed else PARTY_STATUS_LABELS.get(party.status, party.status),
                status_key="delayed" if delayed else "pending" if party.status == "active" else "draft",
                priority="Yüksek" if party.priority_score >= 16 else "Orta" if party.priority_score >= 8 else "Düşük",
                detail_url=url_for("stakeholders.detail", party_id=party.id),
                created_at=party.created_at,
                sort_id=party.id,
                date_label="Gözden Geçirme",
            )
        )

    assigned_requirements = (
        requirement_query()
        .join(StakeholderParty, StakeholderRequirement.party_id == StakeholderParty.id)
        .filter(
            StakeholderRequirement.responsible_user_id == user_id,
            StakeholderRequirement.is_active.is_(True),
            StakeholderRequirement.fulfillment_status != "met",
            StakeholderParty.status != "archived",
        )
        .order_by(StakeholderRequirement.due_date.asc(), StakeholderRequirement.id.asc())
        .all()
    )
    for requirement in assigned_requirements:
        party = requirement.party
        due_date = requirement.due_date or party.next_review_date
        delayed = bool(
            due_date and due_date < date.today() and party.status == "active"
        )
        rows.append(
            row_builder(
                module_key="stakeholder",
                module_label="İlgili Taraf Beklentisi",
                module_icon="card-checklist",
                module_tone="quality",
                title=f"{party.party_no} {requirement.title}",
                description=f"{party.name} / {FULFILLMENT_LABELS.get(requirement.fulfillment_status, requirement.fulfillment_status)}",
                reference_no=party.party_no,
                department=party.department or "İlgili Taraflar",
                due_date=due_date,
                status="Gecikti" if delayed else FULFILLMENT_LABELS.get(requirement.fulfillment_status, requirement.fulfillment_status),
                status_key="delayed" if delayed else "pending" if party.status == "active" else "draft",
                priority="Yüksek" if requirement.fulfillment_status == "not_met" else "Orta",
                detail_url=(
                    url_for(
                        "stakeholders.review_party",
                        party_id=party.id,
                        requirement_id=requirement.id,
                    )
                    if party.status == "active"
                    else url_for("stakeholders.detail", party_id=party.id)
                ),
                created_at=requirement.created_at,
                sort_id=requirement.id,
                date_label="Beklenti Termini",
            )
        )
    return rows
