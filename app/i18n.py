from flask import g, has_request_context, session
from flask_babel import format_date, format_datetime, get_locale


SUPPORTED_LOCALES = {
    "tr": {"label": "Türkçe", "babel": "tr_TR"},
    "en": {"label": "English", "babel": "en_US"},
}
DEFAULT_LOCALE = "tr"


def normalize_locale(value, default=None):
    normalized = str(value or "").strip().lower().replace("-", "_").split("_", 1)[0]
    if normalized in SUPPORTED_LOCALES:
        return normalized
    return default


def tenant_locale_session_key(company=None):
    company = company or getattr(g, "tenant_company", None)
    if company is None:
        return "locale:public"
    return f"locale:company:{company.id}"


def select_locale():
    if not has_request_context():
        return DEFAULT_LOCALE

    user = getattr(g, "current_user", None)
    preferred = normalize_locale(getattr(user, "preferred_locale", None))
    if preferred:
        return preferred

    company = getattr(g, "current_company", None) or getattr(g, "tenant_company", None)
    # Login language choices are isolated per tenant and stay effective until login.
    if user is None:
        anonymous = normalize_locale(session.get(tenant_locale_session_key(company)))
        if anonymous:
            return anonymous

    company_locale = normalize_locale(getattr(company, "default_locale", None))
    if company_locale:
        return company_locale

    anonymous = normalize_locale(session.get(tenant_locale_session_key(company)))
    return anonymous or DEFAULT_LOCALE


def current_locale_code():
    return normalize_locale(str(get_locale()), DEFAULT_LOCALE)


def locale_choices(include_inherit=False):
    choices = []
    if include_inherit:
        choices.append(("", "Şirket varsayılanı"))
    choices.extend((code, item["label"]) for code, item in SUPPORTED_LOCALES.items())
    return choices


def format_local_date(value, format="medium"):
    if value is None:
        return "-"
    return format_date(value, format=format)


def format_local_datetime(value, format="medium"):
    if value is None:
        return "-"
    return format_datetime(value, format=format)
