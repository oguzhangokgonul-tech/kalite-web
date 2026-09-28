from base64 import urlsafe_b64decode, urlsafe_b64encode
from datetime import datetime, timezone
from functools import wraps
import hashlib
import hmac
import json
import time
from uuid import UUID, uuid4

from flask import Blueprint, current_app, g, jsonify, request
from sqlalchemy import text

from .extensions import db
from .integration_security import verify_api_token
from .models import (
    Action,
    AuditLog,
    Company,
    CompanyModule,
    Dof,
    Document,
    IntegrationApiClient,
    IntegrationApiAuthRateBucket,
    IntegrationApiRateBucket,
    IntegrationApiRequest,
)
from .request_security import request_client_ip


bp = Blueprint("integration_api", __name__, url_prefix="/api/v1")
MAX_API_BODY = 1024 * 1024


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def problem(status, code, title, detail=None):
    request_id = getattr(g, "api_request_id", None) or str(uuid4())
    payload = {
        "type": f"https://volkaportal.com/problems/{code}",
        "title": title,
        "status": status,
        "code": code,
        "request_id": request_id,
    }
    if detail:
        payload["detail"] = detail
    return jsonify(payload), status, {"Content-Type": "application/problem+json"}


def _scopes(client):
    try:
        value = json.loads(client.scopes_json or "[]")
    except (TypeError, ValueError):
        return set()
    return {str(item) for item in value} if isinstance(value, list) else set()


def _integration_module_enabled(company_id):
    setting = CompanyModule.query.filter_by(
        company_id=company_id, module_key="integration_management"
    ).first()
    return setting is None or bool(setting.is_enabled)


def _consume_rate_limit(client):
    window_start = utcnow().replace(second=0, microsecond=0)
    db.session.execute(
        text(
            "INSERT INTO integration_api_rate_buckets "
            "(company_id, api_client_id, window_start, request_count) "
            "VALUES (:company_id, :api_client_id, :window_start, 1) "
            "ON CONFLICT(api_client_id, window_start) DO UPDATE SET "
            "request_count = integration_api_rate_buckets.request_count + 1"
        ),
        {
            "company_id": client.company_id,
            "api_client_id": client.id,
            "window_start": window_start,
        },
    )
    count = db.session.execute(
        text(
            "SELECT request_count FROM integration_api_rate_buckets "
            "WHERE api_client_id = :api_client_id AND window_start = :window_start"
        ),
        {"api_client_id": client.id, "window_start": window_start},
    ).scalar_one()
    return count <= client.rate_limit_per_minute


def _auth_ip_hash(ip_address):
    secret = str(current_app.config["SECRET_KEY"]).encode("utf-8")
    return hmac.new(secret, str(ip_address).encode("utf-8"), hashlib.sha256).hexdigest()


def _auth_failure_limited(ip_address):
    if not ip_address:
        return False
    window_start = utcnow().replace(second=0, microsecond=0)
    limit = int(current_app.config.get("INTEGRATION_AUTH_FAILURES_PER_MINUTE", 30))
    bucket = IntegrationApiAuthRateBucket.query.filter_by(
        ip_hash=_auth_ip_hash(ip_address),
        window_start=window_start,
    ).first()
    return bucket is not None and bucket.request_count >= limit


def _record_auth_failure(reason, *, prefix="", company_id=None):
    ip_address = request_client_ip(default=None)
    if ip_address:
        window_start = utcnow().replace(second=0, microsecond=0)
        ip_hash = _auth_ip_hash(ip_address)
        db.session.execute(
            text(
                "INSERT INTO integration_api_auth_rate_buckets "
                "(ip_hash, window_start, request_count) VALUES (:ip_hash, :window_start, 1) "
                "ON CONFLICT(ip_hash, window_start) DO UPDATE SET "
                "request_count = integration_api_auth_rate_buckets.request_count + 1"
            ),
            {"ip_hash": ip_hash, "window_start": window_start},
        )
        count = db.session.execute(
            text(
                "SELECT request_count FROM integration_api_auth_rate_buckets "
                "WHERE ip_hash = :ip_hash AND window_start = :window_start"
            ),
            {"ip_hash": ip_hash, "window_start": window_start},
        ).scalar_one()
    else:
        count = 1
    limit = int(current_app.config.get("INTEGRATION_AUTH_FAILURES_PER_MINUTE", 30))
    if count > limit:
        db.session.commit()
        return True
    db.session.add(
        AuditLog(
            company_id=company_id,
            user_id=None,
            entity_type="IntegrationApiAuth",
            entity_id=(prefix[:32] or None),
            action="authentication_failed",
            summary="Entegrasyon API kimlik dogrulamasi basarisiz.",
            new_values=json.dumps(
                {"reason": reason, "key_prefix": prefix[:32] or None},
                ensure_ascii=False,
            ),
            ip_address=ip_address,
            user_agent=str(request.headers.get("User-Agent") or "")[:255] or None,
        )
    )
    db.session.commit()
    return count > limit


def _auth_failure_response(reason, *, prefix="", company_id=None, code, title):
    if _record_auth_failure(reason, prefix=prefix, company_id=company_id):
        response, status, headers = problem(
            429,
            "authentication_rate_limit",
            "Cok fazla basarisiz kimlik dogrulama denemesi yapildi.",
        )
        headers["Retry-After"] = "60"
        return response, status, headers
    return problem(401, code, title)


@bp.before_request
def authenticate_api_request():
    g.api_log = None
    g.api_client = None
    g.api_company = None
    supplied_request_id = str(request.headers.get("X-Request-ID") or "").strip()
    try:
        g.api_request_id = str(UUID(supplied_request_id)) if supplied_request_id else str(uuid4())
    except ValueError:
        g.api_request_id = str(uuid4())
    if IntegrationApiRequest.query.filter_by(request_id=g.api_request_id).first() is not None:
        g.api_request_id = str(uuid4())
    g.api_started_at = time.monotonic()
    ip_address = request_client_ip(default=None)
    if _auth_failure_limited(ip_address):
        response, status, headers = problem(
            429,
            "authentication_rate_limit",
            "Cok fazla basarisiz kimlik dogrulama denemesi yapildi.",
        )
        headers["Retry-After"] = "60"
        return response, status, headers
    if request.content_length and request.content_length > MAX_API_BODY:
        return problem(413, "payload_too_large", "Istek govdesi cok buyuk.")
    authorization = str(request.headers.get("Authorization") or "")
    if not authorization.startswith("Bearer "):
        return _auth_failure_response(
            "missing_token",
            code="missing_token",
            title="API anahtari gereklidir.",
        )
    token = authorization[7:].strip()
    if "." not in token:
        return _auth_failure_response(
            "invalid_token_format",
            code="invalid_token",
            title="API anahtari gecersiz.",
        )
    prefix = token.split(".", 1)[0]
    client = None
    candidates = IntegrationApiClient.query.filter_by(key_prefix=prefix).all()
    for candidate in candidates:
        if verify_api_token(token, candidate.token_hash):
            client = candidate
            break
    if client is None or client.revoked_at is not None:
        return _auth_failure_response(
            "revoked_token" if client is not None else "invalid_token",
            prefix=prefix,
            company_id=client.company_id if client is not None else (
                candidates[0].company_id if candidates else None
            ),
            code="invalid_token",
            title="API anahtari gecersiz veya iptal edilmis.",
        )
    if client.expires_at is not None and client.expires_at <= utcnow():
        return _auth_failure_response(
            "expired_token",
            prefix=prefix,
            company_id=client.company_id,
            code="expired_token",
            title="API anahtarinin suresi dolmus.",
        )
    company = db.session.get(Company, client.company_id)
    if company is None or not company.is_active:
        return problem(401, "inactive_tenant", "Firma API erisimine kapali.")
    if not _integration_module_enabled(client.company_id):
        return problem(403, "module_disabled", "Entegrasyon modulu bu firma icin kapali.")
    if not _consume_rate_limit(client):
        db.session.add(
            IntegrationApiRequest(
                company_id=client.company_id,
                api_client_id=client.id,
                request_id=g.api_request_id,
                endpoint=request.endpoint or request.path,
                method=request.method,
                status_code=429,
                ip_address=request_client_ip(default=None),
            )
        )
        db.session.commit()
        response, status, headers = problem(429, "rate_limit_exceeded", "API istek limiti asildi.")
        headers["Retry-After"] = "60"
        return response, status, headers
    log = IntegrationApiRequest(
        company_id=client.company_id,
        api_client_id=client.id,
        request_id=g.api_request_id,
        endpoint=request.endpoint or request.path,
        method=request.method,
        status_code=0,
        ip_address=request_client_ip(default=None),
    )
    client.last_used_at = utcnow()
    db.session.add(log)
    db.session.commit()
    g.api_client = client
    g.api_company = company
    g.api_log = log


@bp.after_request
def finalize_api_request(response):
    response.headers["X-Request-ID"] = getattr(g, "api_request_id", "")
    response.headers["Cache-Control"] = "no-store"
    log = getattr(g, "api_log", None)
    if log is not None:
        log.status_code = response.status_code
        log.duration_ms = int((time.monotonic() - g.api_started_at) * 1000)
        db.session.commit()
    return response


def scope_required(scope):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if scope not in _scopes(g.api_client):
                return problem(403, "insufficient_scope", "API anahtari bu kaynak icin yetkili degil.")
            return view(*args, **kwargs)

        return wrapped

    return decorator


def _encode_cursor(value):
    return urlsafe_b64encode(str(value).encode("ascii")).decode("ascii").rstrip("=")


def _decode_cursor(value):
    if not value:
        return None
    try:
        padded = value + "=" * (-len(value) % 4)
        decoded = int(urlsafe_b64decode(padded.encode("ascii")).decode("ascii"))
    except (ValueError, TypeError, UnicodeError):
        return None
    return decoded if decoded > 0 else None


def _list_parameters(query, model):
    try:
        limit = int(request.args.get("limit", 50))
    except ValueError:
        limit = 50
    limit = max(1, min(limit, 100))
    cursor_raw = request.args.get("cursor")
    cursor = _decode_cursor(cursor_raw)
    if cursor_raw and cursor is None:
        return None, None, problem(400, "invalid_cursor", "Sayfalama imleci gecersiz.")
    if cursor:
        query = query.filter(model.id > cursor)
    updated_after = str(request.args.get("updated_after") or "").strip()
    if updated_after and hasattr(model, "updated_at"):
        try:
            parsed = datetime.fromisoformat(updated_after.replace("Z", "+00:00"))
            if parsed.tzinfo is not None:
                parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        except ValueError:
            return None, None, problem(400, "invalid_updated_after", "updated_after ISO-8601 olmalidir.")
        query = query.filter(model.updated_at > parsed)
    rows = query.order_by(model.id.asc()).limit(limit + 1).all()
    next_cursor = _encode_cursor(rows[limit - 1].id) if len(rows) > limit else None
    return rows[:limit], next_cursor, None


def _date(value):
    return value.isoformat() if value else None


def _action(row):
    return {
        "id": row.id,
        "number": row.action_number,
        "title": row.title,
        "department": row.department,
        "description": row.description,
        "due_date": _date(row.termin_date),
        "completed": bool(row.is_completed),
        "completed_at": _date(row.completed_at),
        "updated_at": _date(row.updated_at),
    }


def _dof(row):
    return {
        "id": row.id,
        "number": row.dof_no,
        "title": row.title,
        "department": row.department,
        "source": row.source,
        "status": row.status,
        "opening_date": _date(row.opening_date),
        "due_date": _date(row.due_date),
        "updated_at": _date(row.updated_at),
    }


def _document(row):
    return {
        "id": row.id,
        "code": row.document_code,
        "title": row.title,
        "revision": row.revision_no,
        "publish_date": _date(row.publish_date),
        "revision_date": _date(row.revision_date),
        "department": row.department,
        "status": row.status,
        "file_type": row.file_type,
        "updated_at": _date(row.updated_at),
    }


def _list_response(query, model, serializer):
    rows, next_cursor, error = _list_parameters(query, model)
    if error:
        return error
    return jsonify({"data": [serializer(row) for row in rows], "next_cursor": next_cursor})


@bp.get("/ping")
def ping():
    return jsonify({"ok": True, "company": {"id": g.api_company.id, "name": g.api_company.name}})


@bp.get("/actions")
@scope_required("actions:read")
def actions():
    query = Action.query.filter(Action.company_id == g.api_client.company_id)
    status = request.args.get("status")
    if status in {"open", "completed"}:
        query = query.filter(Action.is_completed.is_(status == "completed"))
    department = str(request.args.get("department") or "").strip()
    if department:
        query = query.filter(Action.department == department)
    return _list_response(query, Action, _action)


@bp.get("/actions/<int:row_id>")
@scope_required("actions:read")
def action_detail(row_id):
    row = Action.query.filter_by(id=row_id, company_id=g.api_client.company_id).first()
    return jsonify({"data": _action(row)}) if row else problem(404, "not_found", "Kayit bulunamadi.")


@bp.get("/dofs")
@scope_required("dofs:read")
def dofs():
    query = Dof.query.filter(Dof.company_id == g.api_client.company_id)
    status = str(request.args.get("status") or "").strip()
    if status:
        query = query.filter(Dof.status == status)
    department = str(request.args.get("department") or "").strip()
    if department:
        query = query.filter(Dof.department == department)
    return _list_response(query, Dof, _dof)


@bp.get("/dofs/<int:row_id>")
@scope_required("dofs:read")
def dof_detail(row_id):
    row = Dof.query.filter_by(id=row_id, company_id=g.api_client.company_id).first()
    return jsonify({"data": _dof(row)}) if row else problem(404, "not_found", "Kayit bulunamadi.")


@bp.get("/documents")
@scope_required("documents:read")
def documents():
    query = Document.query.filter(Document.company_id == g.api_client.company_id)
    status = str(request.args.get("status") or "").strip()
    if status:
        query = query.filter(Document.status == status)
    department = str(request.args.get("department") or "").strip()
    if department:
        query = query.filter(Document.department == department)
    return _list_response(query, Document, _document)


@bp.get("/documents/<int:row_id>")
@scope_required("documents:read")
def document_detail(row_id):
    row = Document.query.filter_by(id=row_id, company_id=g.api_client.company_id).first()
    return jsonify({"data": _document(row)}) if row else problem(404, "not_found", "Kayit bulunamadi.")


@bp.get("/openapi.json")
def openapi():
    paths = {
        "/api/v1/ping": {"get": {"summary": "Baglanti ve firma dogrulama"}},
        "/api/v1/actions": {"get": {"summary": "Aksiyon listesi"}},
        "/api/v1/actions/{id}": {"get": {"summary": "Aksiyon detayi"}},
        "/api/v1/dofs": {"get": {"summary": "IF/DOF listesi"}},
        "/api/v1/dofs/{id}": {"get": {"summary": "IF/DOF detayi"}},
        "/api/v1/documents": {"get": {"summary": "Dokuman listesi"}},
        "/api/v1/documents/{id}": {"get": {"summary": "Dokuman detayi"}},
    }
    return jsonify(
        {
            "openapi": "3.1.0",
            "info": {"title": "VolkaPortal Integration API", "version": "1.0.0"},
            "servers": [{"url": "/api/v1"}],
            "components": {
                "securitySchemes": {
                    "bearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "VolkaPortal API key"}
                }
            },
            "security": [{"bearerAuth": []}],
            "paths": paths,
        }
    )


@bp.errorhandler(405)
def method_not_allowed(error):
    return problem(405, "method_not_allowed", "Bu API islemi desteklenmiyor.")


@bp.errorhandler(404)
def not_found(error):
    return problem(404, "not_found", "API kaynagi bulunamadi.")


@bp.errorhandler(500)
def api_server_error(error):
    db.session.rollback()
    return problem(500, "server_error", "API istegi islenemedi.")
