from datetime import datetime, timedelta, timezone
import http.client
import json
import socket
import ssl
import time
from uuid import uuid4

from flask import Blueprint, abort, current_app, flash, g, has_request_context, redirect, render_template, request, url_for
from sqlalchemy import event, inspect as sa_inspect, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .audit import record_audit_event
from .extensions import db
from .integration_security import (
    IntegrationSecurityError,
    decrypt_secret,
    encrypt_secret,
    generate_api_token,
    generate_webhook_secret,
    hash_api_token,
    resolve_webhook_target,
    validate_webhook_url,
    webhook_signature,
)
from .models import (
    Action,
    AuditLog,
    Dof,
    Document,
    IntegrationApiClient,
    IntegrationApiAuthRateBucket,
    IntegrationApiRateBucket,
    IntegrationApiRequest,
    IntegrationEvent,
    AppSetting,
    WebhookDelivery,
    WebhookDeliveryAttempt,
    WebhookEndpoint,
)
from .routes import company_module_enabled, has_permission
from .tenant import current_company_id


bp = Blueprint("integrations", __name__, url_prefix="/entegrasyonlar")

API_SCOPES = (
    ("actions:read", "Aksiyonlari okuma"),
    ("dofs:read", "IF/DOF kayitlarini okuma"),
    ("documents:read", "Dokuman metadatasini okuma"),
)
WEBHOOK_EVENTS = (
    "action.created",
    "action.updated",
    "action.completed",
    "dof.created",
    "dof.status_changed",
    "document.created",
    "document.revised",
    "document.archived",
    "webhook.test",
)
RETRY_DELAYS = (60, 300, 900, 3600, 21600)
_LISTENERS_REGISTERED = False


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _json_list(value):
    try:
        result = json.loads(value or "[]")
    except (TypeError, ValueError):
        return []
    return [str(item) for item in result] if isinstance(result, list) else []


def _integration_access(permission):
    def decorator(view):
        from functools import wraps

        @wraps(view)
        def wrapped(*args, **kwargs):
            if getattr(g, "current_user", None) is None:
                return redirect(url_for("main.login", next=request.full_path))
            if not company_module_enabled("integration_management"):
                abort(403)
            if not has_permission(g.current_user, permission):
                abort(403)
            if not current_company_id():
                abort(400)
            return view(*args, **kwargs)

        return wrapped

    return decorator


def _company_query(model):
    return model.query.filter(model.company_id == current_company_id())


@bp.route("/", methods=("GET",))
@_integration_access("integrations.view")
def dashboard():
    clients = _company_query(IntegrationApiClient).order_by(IntegrationApiClient.created_at.desc()).all()
    endpoints = _company_query(WebhookEndpoint).order_by(WebhookEndpoint.created_at.desc()).all()
    deliveries = (
        _company_query(WebhookDelivery)
        .order_by(WebhookDelivery.created_at.desc())
        .limit(50)
        .all()
    )
    return render_template(
        "integrations/dashboard.html",
        clients=clients,
        endpoints=endpoints,
        deliveries=deliveries,
        api_scopes=API_SCOPES,
        webhook_events=WEBHOOK_EVENTS,
        one_time_token=None,
        one_time_webhook_secret=None,
        now=utcnow(),
    )


def _dashboard_with_secret(*, token=None, webhook_secret=None, status=201):
    clients = _company_query(IntegrationApiClient).order_by(IntegrationApiClient.created_at.desc()).all()
    endpoints = _company_query(WebhookEndpoint).order_by(WebhookEndpoint.created_at.desc()).all()
    deliveries = _company_query(WebhookDelivery).order_by(WebhookDelivery.created_at.desc()).limit(50).all()
    return (
        render_template(
            "integrations/dashboard.html",
            clients=clients,
            endpoints=endpoints,
            deliveries=deliveries,
            api_scopes=API_SCOPES,
            webhook_events=WEBHOOK_EVENTS,
            one_time_token=token,
            one_time_webhook_secret=webhook_secret,
            now=utcnow(),
        ),
        status,
    )


@bp.post("/api-anahtarlari")
@_integration_access("integrations.manage_api_keys")
def create_api_client():
    name = str(request.form.get("name") or "").strip()[:160]
    selected_scopes = sorted(set(request.form.getlist("scopes")))
    allowed_scopes = {item[0] for item in API_SCOPES}
    selected_scopes = [scope for scope in selected_scopes if scope in allowed_scopes]
    if not name or not selected_scopes:
        flash("Ad ve en az bir API kapsami gereklidir.", "danger")
        return redirect(url_for("integrations.dashboard"))
    try:
        rate_limit = max(1, min(600, int(request.form.get("rate_limit") or 60)))
    except ValueError:
        rate_limit = 60
    expires_at = None
    expires_raw = str(request.form.get("expires_at") or "").strip()
    if expires_raw:
        try:
            expires_at = datetime.strptime(expires_raw, "%Y-%m-%d") + timedelta(days=1)
        except ValueError:
            flash("Gecerlilik tarihi hatali.", "danger")
            return redirect(url_for("integrations.dashboard"))

    prefix, token, last_four = generate_api_token()
    client = IntegrationApiClient(
        company_id=current_company_id(),
        name=name,
        key_prefix=prefix,
        token_hash=hash_api_token(token),
        token_last_four=last_four,
        scopes_json=json.dumps(selected_scopes, ensure_ascii=True),
        rate_limit_per_minute=rate_limit,
        expires_at=expires_at,
        created_by_user_id=g.current_user.id,
    )
    db.session.add(client)
    db.session.flush()
    record_audit_event(
        "IntegrationApiClient",
        "api_client_created",
        f"API istemcisi olusturuldu: {name}",
        entity_id=client.id,
        details={"name": name, "scopes": selected_scopes, "rate_limit": rate_limit},
        commit=False,
    )
    db.session.commit()
    return _dashboard_with_secret(token=token)


@bp.post("/api-anahtarlari/<int:client_id>/iptal")
@_integration_access("integrations.manage_api_keys")
def revoke_api_client(client_id):
    client = _company_query(IntegrationApiClient).filter_by(id=client_id).first_or_404()
    if client.revoked_at is None:
        client.revoked_at = utcnow()
        record_audit_event(
            "IntegrationApiClient",
            "api_client_revoked",
            f"API istemcisi iptal edildi: {client.name}",
            entity_id=client.id,
            details={"key_prefix": client.key_prefix},
            commit=False,
        )
        db.session.commit()
    flash("API anahtari iptal edildi.", "success")
    return redirect(url_for("integrations.dashboard"))


@bp.post("/webhooklar")
@_integration_access("integrations.manage_webhooks")
def create_webhook():
    name = str(request.form.get("name") or "").strip()[:160]
    endpoint_url = str(request.form.get("endpoint_url") or "").strip()
    events = sorted(set(request.form.getlist("events")) & set(WEBHOOK_EVENTS))
    if not name or not events:
        flash("Webhook adi ve en az bir olay gereklidir.", "danger")
        return redirect(url_for("integrations.dashboard"))
    try:
        endpoint_url = validate_webhook_url(endpoint_url)
        secret = generate_webhook_secret()
        ciphertext = encrypt_secret(secret)
    except IntegrationSecurityError as error:
        flash(str(error), "danger")
        return redirect(url_for("integrations.dashboard"))
    endpoint = WebhookEndpoint(
        company_id=current_company_id(),
        name=name,
        endpoint_url=endpoint_url,
        events_json=json.dumps(events, ensure_ascii=True),
        secret_ciphertext=ciphertext,
        secret_hint=secret[-6:],
        created_by_user_id=g.current_user.id,
    )
    db.session.add(endpoint)
    db.session.flush()
    record_audit_event(
        "WebhookEndpoint",
        "webhook_created",
        f"Webhook olusturuldu: {name}",
        entity_id=endpoint.id,
        details={"endpoint_url": endpoint_url, "events": events},
        commit=False,
    )
    db.session.commit()
    return _dashboard_with_secret(webhook_secret=secret)


@bp.post("/webhooklar/<int:endpoint_id>/durum")
@_integration_access("integrations.manage_webhooks")
def toggle_webhook(endpoint_id):
    endpoint = _company_query(WebhookEndpoint).filter_by(id=endpoint_id).first_or_404()
    endpoint.is_active = not endpoint.is_active
    endpoint.disabled_reason = None if endpoint.is_active else "Kullanici tarafindan durduruldu"
    if not endpoint.is_active:
        _company_query(WebhookDelivery).filter(
            WebhookDelivery.webhook_endpoint_id == endpoint.id,
            WebhookDelivery.status.in_(("pending", "retry")),
        ).update(
            {
                WebhookDelivery.status: "failed",
                WebhookDelivery.next_attempt_at: None,
                WebhookDelivery.last_error_code: "endpoint_disabled",
            },
            synchronize_session=False,
        )
    record_audit_event(
        "WebhookEndpoint",
        "webhook_enabled" if endpoint.is_active else "webhook_disabled",
        f"Webhook durumu degisti: {endpoint.name}",
        entity_id=endpoint.id,
        details={"is_active": endpoint.is_active},
        commit=False,
    )
    db.session.commit()
    return redirect(url_for("integrations.dashboard"))


@bp.post("/webhooklar/<int:endpoint_id>/test")
@_integration_access("integrations.manage_webhooks")
def test_webhook(endpoint_id):
    endpoint = _company_query(WebhookEndpoint).filter_by(id=endpoint_id).first_or_404()
    if not endpoint.is_active:
        flash("Kapali webhook test edilemez. Once webhooku etkinlestirin.", "danger")
        return redirect(url_for("integrations.dashboard"))
    event_row = publish_integration_event(
        company_id=current_company_id(),
        event_type="webhook.test",
        subject_type="WebhookEndpoint",
        subject_id=str(endpoint.id),
        payload={
            "message": "VolkaPortal webhook test olayi",
            "target_endpoint_id": endpoint.id,
        },
        actor_user_id=g.current_user.id,
        commit=False,
    )
    db.session.commit()
    record_audit_event(
        "WebhookEndpoint",
        "webhook_tested",
        f"Webhook test olayi kuyruga alindi: {endpoint.name}",
        entity_id=endpoint.id,
        details={"event_id": event_row.event_uuid},
    )
    flash("Test olayi teslimat kuyruguna alindi.", "success")
    return redirect(url_for("integrations.dashboard"))


@bp.post("/teslimatlar/<int:delivery_id>/yeniden-dene")
@_integration_access("integrations.retry_deliveries")
def retry_delivery(delivery_id):
    delivery = _company_query(WebhookDelivery).filter_by(id=delivery_id).first_or_404()
    if delivery.status not in {"failed", "retry"}:
        abort(409, "Yalnizca basarisiz teslimatlar yeniden denenebilir.")
    if not delivery.endpoint.is_active:
        abort(409, "Kapali webhook icin teslimat yeniden denenemez.")
    delivery.status = "pending"
    delivery.next_attempt_at = utcnow()
    delivery.locked_at = None
    record_audit_event(
        "WebhookDelivery",
        "delivery_retried",
        "Webhook teslimati manuel olarak yeniden kuyruga alindi.",
        entity_id=delivery.id,
        details={"delivery_id": delivery.delivery_uuid},
        commit=False,
    )
    db.session.commit()
    return redirect(url_for("integrations.dashboard"))


def publish_integration_event(
    *, company_id, event_type, subject_type, subject_id, payload, actor_user_id=None, commit=False
):
    row = IntegrationEvent(
        event_uuid=str(uuid4()),
        company_id=company_id,
        event_type=event_type,
        subject_type=subject_type,
        subject_id=str(subject_id),
        actor_user_id=actor_user_id,
        payload_json=json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str),
    )
    db.session.add(row)
    if commit:
        db.session.commit()
    return row


def _domain_event_descriptor(obj, is_new):
    state = sa_inspect(obj)
    if isinstance(obj, Action):
        event_type = "action.created" if is_new else "action.updated"
        if not is_new and state.attrs.is_completed.history.has_changes() and obj.is_completed:
            event_type = "action.completed"
        payload = {
            "id": obj.id,
            "number": obj.action_number,
            "title": obj.title,
            "department": obj.department,
            "due_date": obj.termin_date,
            "completed": bool(obj.is_completed),
        }
    elif isinstance(obj, Dof):
        if not is_new and not state.attrs.status.history.has_changes():
            return None
        event_type = "dof.created" if is_new else "dof.status_changed"
        payload = {
            "id": obj.id,
            "number": obj.dof_no,
            "title": obj.title,
            "department": obj.department,
            "status": obj.status,
            "due_date": obj.due_date,
        }
    elif isinstance(obj, Document):
        if is_new:
            event_type = "document.created"
        elif state.attrs.archived_at.history.has_changes() and obj.archived_at:
            event_type = "document.archived"
        elif state.attrs.revision_no.history.has_changes():
            event_type = "document.revised"
        else:
            return None
        payload = {
            "id": obj.id,
            "code": obj.document_code,
            "title": obj.title,
            "revision": obj.revision_no,
            "publish_date": obj.publish_date,
            "status": obj.status,
        }
    else:
        return None
    return event_type, obj.__class__.__name__, obj, payload


def queue_domain_events(session, flush_context, instances):
    queued = []
    for obj in list(session.new):
        descriptor = _domain_event_descriptor(obj, True)
        if descriptor and obj.company_id:
            queued.append(descriptor)
    for obj in list(session.dirty):
        if not session.is_modified(obj, include_collections=False):
            continue
        descriptor = _domain_event_descriptor(obj, False)
        if descriptor and obj.company_id:
            queued.append(descriptor)
    if queued:
        session.info.setdefault("integration_domain_events", []).extend(queued)


def write_domain_events(session, flush_context):
    queued = session.info.pop("integration_domain_events", [])
    actor_id = (
        getattr(getattr(g, "current_user", None), "id", None)
        if has_request_context()
        else None
    )
    for event_type, subject_type, obj, payload in queued:
        payload["id"] = obj.id
        session.add(
            IntegrationEvent(
                event_uuid=str(uuid4()),
                company_id=obj.company_id,
                event_type=event_type,
                subject_type=subject_type,
                subject_id=str(obj.id),
                actor_user_id=actor_id,
                payload_json=json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str),
            )
        )


def register_integration_event_listeners():
    global _LISTENERS_REGISTERED
    if _LISTENERS_REGISTERED:
        return
    event.listen(Session, "before_flush", queue_domain_events)
    event.listen(Session, "after_flush_postexec", write_domain_events)
    _LISTENERS_REGISTERED = True


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, hostname, resolved_ip, *, port=443, timeout=10):
        super().__init__(
            hostname,
            port=port,
            timeout=timeout,
            context=ssl.create_default_context(),
        )
        self._resolved_ip = resolved_ip

    def connect(self):
        sock = socket.create_connection(
            (self._resolved_ip, self.port),
            self.timeout,
            self.source_address,
        )
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


def _post_webhook(target, body, headers, timeout):
    connection = _PinnedHTTPSConnection(
        target.hostname,
        target.addresses[0],
        port=target.port,
        timeout=timeout,
    )
    try:
        connection.request("POST", target.path, body=body, headers=headers)
        response = connection.getresponse()
        response.read(65537)
        return int(response.status), response.headers
    finally:
        connection.close()


def _event_body(event_row):
    company = event_row.company
    source = f"https://{company.slug}.{current_app.config['TENANT_BASE_DOMAIN']}" if company.slug else "https://volkaportal.com"
    return json.dumps(
        {
            "specversion": "1.0",
            "id": event_row.event_uuid,
            "source": source,
            "type": f"com.volkaportal.{event_row.event_type}.v1",
            "subject": f"{event_row.subject_type}/{event_row.subject_id}",
            "time": event_row.occurred_at.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z"),
            "datacontenttype": "application/json",
            "data": json.loads(event_row.payload_json),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def _materialize_deliveries(limit):
    events = IntegrationEvent.query.filter(IntegrationEvent.dispatched_at.is_(None)).order_by(IntegrationEvent.id).limit(limit).all()
    for event_row in events:
        endpoints = WebhookEndpoint.query.filter_by(company_id=event_row.company_id, is_active=True).all()
        payload = json.loads(event_row.payload_json)
        for endpoint in endpoints:
            if event_row.event_type not in _json_list(endpoint.events_json):
                continue
            if (
                event_row.event_type == "webhook.test"
                and payload.get("target_endpoint_id") != endpoint.id
            ):
                continue
            db.session.add(
                WebhookDelivery(
                    delivery_uuid=str(uuid4()),
                    company_id=event_row.company_id,
                    endpoint=endpoint,
                    event=event_row,
                    next_attempt_at=utcnow(),
                )
            )
        event_row.dispatched_at = utcnow()
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()


def _deliver(delivery):
    if (
        delivery.endpoint.company_id != delivery.company_id
        or delivery.event.company_id != delivery.company_id
    ):
        delivery.status = "failed"
        delivery.next_attempt_at = None
        delivery.locked_at = None
        delivery.last_error_code = "tenant_mismatch"
        record_audit_event(
            "WebhookDispatcher",
            "delivery_blocked",
            "Webhook teslimati sirket uyusmazligi nedeniyle engellendi.",
            entity_id=delivery.id,
            company_id=delivery.company_id,
            details={
                "service": "volkaportal-webhook-dispatcher",
                "delivery_id": delivery.delivery_uuid,
                "event_id": delivery.event.event_uuid,
                "reason": "tenant_mismatch",
            },
            commit=False,
        )
        db.session.commit()
        return
    if not delivery.endpoint.is_active:
        delivery.status = "failed"
        delivery.next_attempt_at = None
        delivery.locked_at = None
        delivery.last_error_code = "endpoint_disabled"
        db.session.commit()
        return
    now = utcnow()
    delivery.locked_at = delivery.locked_at or now
    delivery.status = "processing"
    delivery.attempt_count += 1
    attempt = WebhookDeliveryAttempt(
        company_id=delivery.company_id,
        delivery=delivery,
        attempt_no=delivery.attempt_count,
        started_at=now,
    )
    db.session.add(attempt)
    db.session.commit()
    started = time.monotonic()
    status = None
    excerpt = None
    error_code = None
    retry_after_seconds = None
    try:
        target = resolve_webhook_target(delivery.endpoint.endpoint_url)
        secret = decrypt_secret(delivery.endpoint.secret_ciphertext)
        body = _event_body(delivery.event)
        timestamp = str(int(time.time()))
        headers = {
            "Content-Type": "application/cloudevents+json",
            "User-Agent": "VolkaPortal-Webhooks/1.0",
            "VolkaPortal-Event-Id": delivery.event.event_uuid,
            "VolkaPortal-Delivery-Id": delivery.delivery_uuid,
            "VolkaPortal-Timestamp": timestamp,
            "VolkaPortal-Signature": webhook_signature(
                secret, timestamp, delivery.event.event_uuid, body
            ),
        }
        status, response_headers = _post_webhook(
            target,
            body,
            headers,
            min(max(delivery.endpoint.timeout_seconds, 3), 10),
        )
        excerpt = f"HTTP {status}"
        if status >= 400:
            error_code = f"http_{status}"
        if status == 429:
            try:
                retry_after_seconds = max(
                    1, min(int(response_headers.get("Retry-After", "")), 21600)
                )
            except (TypeError, ValueError):
                retry_after_seconds = None
    except (
        OSError,
        ssl.SSLError,
        http.client.HTTPException,
        TimeoutError,
        IntegrationSecurityError,
    ) as error:
        error_code = error.__class__.__name__.lower()
        excerpt = str(error)[:500]
    finished = utcnow()
    attempt.finished_at = finished
    attempt.http_status = status
    attempt.duration_ms = int((time.monotonic() - started) * 1000)
    attempt.error_code = error_code
    attempt.response_excerpt = excerpt
    delivery.last_http_status = status
    delivery.last_error_code = error_code
    delivery.locked_at = None
    if status is not None and 200 <= status < 300:
        delivery.status = "delivered"
        delivery.delivered_at = finished
        delivery.next_attempt_at = None
    elif status == 410:
        delivery.status = "failed"
        delivery.next_attempt_at = None
        delivery.endpoint.is_active = False
        delivery.endpoint.disabled_reason = "Hedef 410 Gone dondu"
    elif delivery.attempt_count >= len(RETRY_DELAYS) or (
        status is not None
        and (
            300 <= status < 400
            or (400 <= status < 500 and status not in {408, 425, 429})
        )
    ):
        delivery.status = "failed"
        delivery.next_attempt_at = None
    else:
        delivery.status = "retry"
        index = min(delivery.attempt_count - 1, len(RETRY_DELAYS) - 1)
        delay_seconds = retry_after_seconds or RETRY_DELAYS[index]
        delivery.next_attempt_at = finished + timedelta(seconds=delay_seconds)
    record_audit_event(
        "WebhookDispatcher",
        {
            "delivered": "delivery_delivered",
            "retry": "delivery_retry_scheduled",
            "failed": "delivery_failed",
        }[delivery.status],
        f"Webhook teslimati sonucu: {delivery.status}",
        entity_id=delivery.id,
        company_id=delivery.company_id,
        details={
            "service": "volkaportal-webhook-dispatcher",
            "delivery_id": delivery.delivery_uuid,
            "event_id": delivery.event.event_uuid,
            "http_status": status,
            "error_code": error_code,
            "attempt_no": delivery.attempt_count,
        },
        commit=False,
    )
    db.session.commit()


def _claim_delivery(delivery_id, stale_before):
    now = utcnow()
    result = db.session.execute(
        update(WebhookDelivery)
        .where(
            WebhookDelivery.id == delivery_id,
            WebhookDelivery.status.in_(("pending", "retry", "processing")),
            db.or_(
                WebhookDelivery.next_attempt_at.is_(None),
                WebhookDelivery.next_attempt_at <= now,
            ),
            db.or_(
                WebhookDelivery.locked_at.is_(None),
                WebhookDelivery.locked_at < stale_before,
            ),
        )
        .values(status="processing", locked_at=now)
    )
    db.session.commit()
    return result.rowcount == 1


def _purge_integration_history():
    now = utcnow()
    request_cutoff = now - timedelta(
        days=max(7, int(current_app.config.get("INTEGRATION_LOG_RETENTION_DAYS", 90)))
    )
    event_cutoff = now - timedelta(
        days=max(30, int(current_app.config.get("INTEGRATION_EVENT_RETENTION_DAYS", 365)))
    )
    IntegrationApiRateBucket.query.filter(
        IntegrationApiRateBucket.window_start < now - timedelta(days=2)
    ).delete(synchronize_session=False)
    IntegrationApiAuthRateBucket.query.filter(
        IntegrationApiAuthRateBucket.window_start < now - timedelta(days=2)
    ).delete(synchronize_session=False)
    IntegrationApiRequest.query.filter(
        IntegrationApiRequest.created_at < request_cutoff
    ).delete(synchronize_session=False)
    AuditLog.query.filter(
        AuditLog.entity_type == "IntegrationApiAuth",
        AuditLog.created_at < request_cutoff,
    ).delete(synchronize_session=False)

    completed_ids = [
        row[0]
        for row in db.session.query(WebhookDelivery.id)
        .filter(
            WebhookDelivery.status.in_(("delivered", "failed")),
            WebhookDelivery.updated_at < event_cutoff,
        )
        .all()
    ]
    if completed_ids:
        WebhookDeliveryAttempt.query.filter(
            WebhookDeliveryAttempt.delivery_id.in_(completed_ids)
        ).delete(synchronize_session=False)
        WebhookDelivery.query.filter(WebhookDelivery.id.in_(completed_ids)).delete(
            synchronize_session=False
        )
    IntegrationEvent.query.filter(
        IntegrationEvent.dispatched_at.is_not(None),
        IntegrationEvent.occurred_at < event_cutoff,
        ~IntegrationEvent.id.in_(db.session.query(WebhookDelivery.integration_event_id)),
    ).delete(synchronize_session=False)
    db.session.commit()


def dispatch_webhooks(limit=100):
    limit = max(1, min(int(limit), 500))
    _purge_integration_history()
    _materialize_deliveries(limit)
    stale_before = utcnow() - timedelta(minutes=10)
    delivery_ids = [
        row[0]
        for row in db.session.query(WebhookDelivery.id).filter(
            WebhookDelivery.status.in_(("pending", "retry", "processing")),
            db.or_(WebhookDelivery.next_attempt_at.is_(None), WebhookDelivery.next_attempt_at <= utcnow()),
            db.or_(WebhookDelivery.locked_at.is_(None), WebhookDelivery.locked_at < stale_before),
        )
        .order_by(WebhookDelivery.next_attempt_at, WebhookDelivery.id)
        .limit(limit)
        .all()
    ]
    processed = 0
    for delivery_id in delivery_ids:
        if not _claim_delivery(delivery_id, stale_before):
            continue
        delivery = db.session.get(WebhookDelivery, delivery_id)
        if delivery is None:
            continue
        _deliver(delivery)
        processed += 1
    return processed


def verify_integration_readiness(*, mark=False):
    required_tables = {
        "integration_api_clients",
        "integration_api_rate_buckets",
        "integration_api_auth_rate_buckets",
        "integration_api_requests",
        "integration_events",
        "webhook_endpoints",
        "webhook_deliveries",
        "webhook_delivery_attempts",
    }
    missing = sorted(required_tables - set(sa_inspect(db.engine).get_table_names()))
    if missing:
        raise RuntimeError(f"Eksik entegrasyon tablolari: {', '.join(missing)}")
    probe = "volkaportal-integration-readiness"
    if decrypt_secret(encrypt_secret(probe)) != probe:
        raise RuntimeError("Entegrasyon sifreleme anahtari dogrulanamadi.")
    if mark:
        setting = db.session.get(AppSetting, "sales_readiness:competitor_api_webhooks")
        if setting is None:
            setting = AppSetting(
                key="sales_readiness:competitor_api_webhooks",
                value="1",
            )
            db.session.add(setting)
        else:
            setting.value = "1"
        db.session.commit()
    return {"tables": len(required_tables), "encryption": True, "marked": bool(mark)}
