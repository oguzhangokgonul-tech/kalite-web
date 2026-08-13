from flask import abort, current_app, g, session
from sqlalchemy import or_

from .extensions import db
from .models import Company


def normalize_request_host(host):
    host = (host or "").split(":")[0].strip().lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def host_looks_local(host):
    return host in {"", "localhost", "127.0.0.1", "0.0.0.0"} or host.endswith(".local")


def tenant_company_from_host(host):
    host = normalize_request_host(host)
    if host_looks_local(host):
        return None

    base_domain = normalize_request_host(current_app.config.get("TENANT_BASE_DOMAIN"))
    company = (
        Company.query.filter(
            Company.is_active.is_(True),
            or_(
                db.func.lower(Company.primary_domain) == host,
                db.func.lower(Company.custom_domain) == host,
            ),
        )
        .first()
    )
    if company is not None:
        return company

    if base_domain and host.endswith(f".{base_domain}"):
        slug = host[: -(len(base_domain) + 1)]
        if slug and "." not in slug:
            return Company.query.filter_by(slug=slug, is_active=True).first()

    return None


def current_company_id():
    current_company = getattr(g, "current_company", None)
    if current_company is not None:
        return current_company.id

    current_user = getattr(g, "current_user", None)
    if current_user is not None and not getattr(g, "current_user_is_super_admin", False):
        return current_user.company_id

    return session.get("company_id")


def scoped_query(query, model):
    if not hasattr(model, "company_id"):
        return query

    company_id = current_company_id()
    if company_id:
        return query.filter(model.company_id == company_id)
    if getattr(g, "current_user_is_super_admin", False):
        return query
    return query.filter(model.company_id.is_(None))


def assign_current_company(record):
    if hasattr(record, "company_id"):
        record.company_id = current_company_id()
    return record


def ensure_same_company(record):
    if not hasattr(record, "company_id"):
        return record

    company_id = current_company_id()
    if company_id:
        if record.company_id != company_id:
            abort(404)
    elif not getattr(g, "current_user_is_super_admin", False) and record.company_id is not None:
        abort(404)
    return record
