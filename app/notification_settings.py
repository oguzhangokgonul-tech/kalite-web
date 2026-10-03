"""Company-scoped notification preferences and policy editor."""

from copy import deepcopy
from functools import wraps
import json
import re

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from .audit import record_audit_event
from .extensions import db
from .models import AppSetting, Company
from .tenant import current_company_id


bp = Blueprint("notification_settings", __name__, url_prefix="/notifications/settings")

MODES = (
    ("important", "Önemli bildirimler ve haftalık özet"),
    ("weekly", "Yalnızca haftalık özet"),
    ("site", "Yalnızca site içi"),
)
WEEKDAYS = ("Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar")


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if getattr(g, "current_user", None) is None:
            return redirect(url_for("main.login", next=request.full_path))
        return view(*args, **kwargs)

    return wrapped


def _company():
    company_id = current_company_id()
    company = db.session.get(Company, company_id) if company_id else None
    if company is None or not company.is_active:
        abort(400, "Bildirim ayarları için aktif bir şirket seçilmelidir.")
    user = g.current_user
    if not user.has_role("super_admin") and user.company_id != company.id:
        abort(403)
    return company


def _can_manage():
    return any(g.current_user.has_role(role) for role in ("management_representative", "super_admin"))


@bp.app_context_processor
def settings_navigation():
    return {"notification_settings_available": True}


def _render(company, *, error=None, status=200):
    # Policy helpers may themselves import main routes; resolve them at request time.
    from .notification_policy import POLICY_DEFAULTS, get_company_policy, get_user_preference

    return render_template(
        "notification_settings.html",
        company=company,
        can_manage=_can_manage(),
        policy=get_company_policy(company.id),
        policy_defaults=POLICY_DEFAULTS,
        preference=get_user_preference(company.id, g.current_user.id),
        modes=MODES,
        weekdays=WEEKDAYS,
        error=error,
    ), status


def _payload(allowed_fields):
    if request.is_json:
        payload = request.get_json()
        if not isinstance(payload, dict):
            raise ValueError("Ayarlar geçerli bir nesne olmalıdır.")
    else:
        if any(len(values) != 1 for _, values in request.form.lists()):
            raise ValueError("Aynı alan birden fazla gönderilemez.")
        payload = request.form.to_dict()
        payload.pop("csrf_token", None)
    if set(payload) - set(allowed_fields):
        raise ValueError("Bilinmeyen ayar alanı gönderildi.")
    return payload


def _boolean(value):
    if request.is_json:
        if type(value) is not bool:
            raise ValueError("E-posta ve haftalık özet değerleri açık veya kapalı olmalıdır.")
        return value
    if value not in ("on", "1", "true", "0", "false"):
        raise ValueError("Geçersiz açık/kapalı değeri.")
    return value in ("on", "1", "true")


def _days(value):
    if not request.is_json:
        value = value.strip()
        if not value:
            return []
        parts = value.split(",")
        if any(not re.fullmatch(r"[0-9]{1,2}", part.strip()) for part in parts):
            raise ValueError("Günler 0 ile 90 arasında, virgülle ayrılmış tam sayılar olmalıdır.")
        value = [int(part.strip()) for part in parts]
    if not isinstance(value, list) or any(type(day) is not int or not 0 <= day <= 90 for day in value):
        raise ValueError("Günler 0 ile 90 arasında tam sayılar olmalıdır.")
    if len(value) != len(set(value)):
        raise ValueError("Aynı gün birden fazla tanımlanamaz.")
    return value


def _company_payload(company_id):
    from .notification_policy import POLICY_DEFAULTS, get_company_policy

    if request.is_json:
        payload = _payload(("enabled", "weekly_day", "modules"))
    else:
        fields = {"enabled", "weekly_day"}
        fields.update(f"modules.{kind}.{field}" for kind in POLICY_DEFAULTS for field in ("email", "days", "weekly"))
        form = _payload(fields)
        payload = {
            "enabled": form.get("enabled", "0"),
            "weekly_day": form.get("weekly_day"),
            "modules": {},
        }
        for kind in POLICY_DEFAULTS:
            prefix = f"modules.{kind}."
            if prefix + "days" not in form:
                raise ValueError("Modül gün bilgisi eksik.")
            payload["modules"][kind] = {
                "email": form.get(prefix + "email", "0"),
                "weekly": form.get(prefix + "weekly", "0"),
                "days": form[prefix + "days"],
            }
    if set(payload) != {"enabled", "weekly_day", "modules"}:
        raise ValueError("Şirket politikası alanları eksik.")
    weekly_day = payload["weekly_day"]
    if not request.is_json and isinstance(weekly_day, str) and re.fullmatch(r"[0-6]", weekly_day):
        weekly_day = int(weekly_day)
    if type(weekly_day) is not int or not 0 <= weekly_day <= 6:
        raise ValueError("Haftalık özet günü geçersiz.")
    modules = payload["modules"]
    if not isinstance(modules, dict) or set(modules) - set(POLICY_DEFAULTS):
        raise ValueError("Bilinmeyen bildirim modülü.")
    merged = deepcopy(get_company_policy(company_id))
    for kind, values in modules.items():
        if not isinstance(values, dict) or set(values) != {"email", "days", "weekly"}:
            raise ValueError("Modül ayarları e-posta, günler ve haftalık özet alanlarını içermelidir.")
        merged["modules"][kind].update(
            email=_boolean(values["email"]), days=_days(values["days"]), weekly=_boolean(values["weekly"]),
        )
    return {
        "enabled": _boolean(payload["enabled"]),
        "weekly_day": weekly_day,
        "modules": {
            kind: {field: merged["modules"][kind][field] for field in ("email", "days", "weekly")}
            for kind in POLICY_DEFAULTS
        },
    }


def _save(key, value, *, company_id, entity_type, summary, previous):
    setting = db.session.get(AppSetting, key)
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    if setting is not None:
        try:
            if json.loads(setting.value) == value:
                return
        except (TypeError, ValueError):
            pass
    if setting is None:
        setting = AppSetting(key=key, value=encoded)
        db.session.add(setting)
    else:
        setting.value = encoded
    record_audit_event(
        entity_type, "updated", summary,
        entity_id=key, company_id=company_id,
        old_values=previous, new_values=value, commit=False,
    )
    db.session.commit()


@bp.get("")
@login_required
def index():
    return _render(_company())


@bp.post("/preferences")
@login_required
def save_user_preference():
    from .notification_policy import get_user_preference

    company = _company()
    try:
        payload = _payload(("mode",))
        mode = payload.get("mode")
        if not isinstance(mode, str) or mode not in dict(MODES):
            raise ValueError("Geçerli bir e-posta tercihi seçilmelidir.")
    except ValueError as error:
        return _render(company, error=str(error), status=400)
    _save(
        f"notification_policy:user:{company.id}:{g.current_user.id}", {"mode": mode},
        company_id=company.id, entity_type="NotificationPreference",
        summary="Kişisel bildirim tercihi güncellendi.",
        previous={"mode": get_user_preference(company.id, g.current_user.id)},
    )
    flash("E-posta tercihiniz kaydedildi.", "success")
    return redirect(url_for("notification_settings.index"))


@bp.post("/company")
@login_required
def save_company_policy():
    company = _company()
    if not _can_manage():
        abort(403)
    from .notification_policy import get_company_policy

    try:
        payload = _company_payload(company.id)
    except ValueError as error:
        return _render(company, error=str(error), status=400)
    _save(
        f"notification_policy:company:{company.id}", payload,
        company_id=company.id, entity_type="NotificationPolicy",
        summary="Şirket bildirim politikası güncellendi.",
        previous=get_company_policy(company.id),
    )
    flash("Şirket bildirim politikası kaydedildi.", "success")
    return redirect(url_for("notification_settings.index"))
