import json
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

from cryptography.fernet import Fernet
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.integration_security import (
    IntegrationSecurityError,
    encrypt_secret,
    generate_api_token,
    generate_webhook_secret,
    hash_api_token,
    resolve_webhook_target,
    validate_webhook_url,
)
from app.integrations import (
    dispatch_webhooks,
    publish_integration_event,
    verify_integration_readiness,
)
from app.models import (
    Action,
    AppSetting,
    AuditLog,
    IntegrationApiClient,
    IntegrationApiRequest,
    IntegrationEvent,
    WebhookDelivery,
    WebhookDeliveryAttempt,
    WebhookEndpoint,
)
from app.seed import ensure_runtime_schema

from .helpers import create_company, create_user, login, make_document


ALL_SCOPES = ["actions:read", "dofs:read", "documents:read"]


def create_api_client(company, *, scopes=ALL_SCOPES, limit=60, revoked=False):
    prefix, token, last_four = generate_api_token()
    row = IntegrationApiClient(
        company_id=company.id,
        name=f"{company.code} ERP",
        key_prefix=prefix,
        token_hash=hash_api_token(token),
        token_last_four=last_four,
        scopes_json=json.dumps(scopes),
        rate_limit_per_minute=limit,
        revoked_at=datetime.now(UTC).replace(tzinfo=None) if revoked else None,
    )
    db.session.add(row)
    db.session.commit()
    return row, token


def api_headers(token, **extra):
    return {"Authorization": f"Bearer {token}", **extra}


def make_action(company, title):
    row = Action(
        company_id=company.id,
        title=title,
        responsible_owner="Kalite Sorumlusu",
        department="Kalite",
        termin_date=date.today() + timedelta(days=7),
    )
    db.session.add(row)
    db.session.commit()
    return row


def test_api_uses_token_tenant_and_never_leaks_other_company(app, client):
    company_a = create_company("751", name="API Firma A")
    company_b = create_company("752", name="API Firma B")
    own = make_action(company_a, "Firma A aksiyonu")
    other = make_action(company_b, "Firma B gizli aksiyonu")
    api_client, token = create_api_client(company_a, scopes=["actions:read"])

    response = client.get(
        "/api/v1/actions",
        headers=api_headers(token),
        base_url="https://firma-752.volkaportal.com",
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert [item["id"] for item in payload["data"]] == [own.id]
    assert "Firma B gizli aksiyonu" not in response.get_data(as_text=True)
    assert client.get(
        f"/api/v1/actions/{other.id}", headers=api_headers(token)
    ).status_code == 404
    request_log = IntegrationApiRequest.query.filter_by(api_client_id=api_client.id).first()
    assert request_log.company_id == company_a.id
    assert request_log.status_code == 200


def test_api_auth_scope_revoke_expiry_rate_limit_and_request_id(app, client):
    company = create_company("753")
    client_row, token = create_api_client(company, scopes=[], limit=2)

    assert client.get("/api/v1/ping").status_code == 401
    assert client.get("/api/v1/actions", headers=api_headers(token)).status_code == 403
    first = client.get(
        "/api/v1/ping",
        headers=api_headers(token, **{"X-Request-ID": "not-a-uuid"}),
    )
    assert first.status_code == 200
    assert first.headers["X-Request-ID"] != "not-a-uuid"
    limited = client.get("/api/v1/ping", headers=api_headers(token))
    assert limited.status_code == 429
    assert limited.headers["Retry-After"] == "60"

    IntegrationApiRequest.query.delete()
    client_row.expires_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1)
    db.session.commit()
    assert client.get("/api/v1/ping", headers=api_headers(token)).status_code == 401
    client_row.expires_at = None
    client_row.revoked_at = datetime.now(UTC).replace(tzinfo=None)
    db.session.commit()
    assert client.get("/api/v1/ping", headers=api_headers(token)).status_code == 401


def test_api_cursor_limit_openapi_and_document_metadata(app, client):
    company = create_company("754")
    user = create_user("integration-uploader", company=company)
    first = make_document(app, company, uploader=user, document_code="PR.01", title="İlk Doküman")
    second = make_document(app, company, uploader=user, document_code="PR.02", title="İkinci Doküman")
    _client, token = create_api_client(company, scopes=["documents:read"])

    first_page = client.get("/api/v1/documents?limit=1", headers=api_headers(token))
    assert first_page.status_code == 200
    cursor = first_page.get_json()["next_cursor"]
    assert cursor
    second_page = client.get(
        f"/api/v1/documents?limit=1&cursor={cursor}", headers=api_headers(token)
    )
    assert second_page.get_json()["data"][0]["id"] == second.id
    assert client.get(
        "/api/v1/documents?cursor=invalid", headers=api_headers(token)
    ).status_code == 400
    detail = client.get(f"/api/v1/documents/{first.id}", headers=api_headers(token))
    assert detail.get_json()["data"]["code"] == "PR.01"
    assert client.get("/api/v1/openapi.json", headers=api_headers(token)).status_code == 200


def test_integration_ui_permissions_and_one_time_key_does_not_leak(app, client):
    company = create_company("755")
    manager = create_user(
        "integration-manager",
        company=company,
        permissions=(
            "integrations.view",
            "integrations.manage_api_keys",
            "integrations.manage_webhooks",
            "integrations.view_deliveries",
            "integrations.retry_deliveries",
        ),
    )
    staff = create_user("integration-staff", company=company)

    login(client, staff, company)
    assert client.get("/entegrasyonlar/").status_code == 403

    login(client, manager, company)
    page = client.get("/entegrasyonlar/")
    assert page.status_code == 200
    assert "API Anahtarları" in page.get_data(as_text=True)
    response = client.post(
        "/entegrasyonlar/api-anahtarlari",
        data={"name": "Logo Raporlama", "rate_limit": "30", "scopes": "actions:read"},
    )
    assert response.status_code == 201
    body = response.get_data(as_text=True)
    token = body.split("<code class=\"d-block mt-2 text-break user-select-all\">", 1)[1].split("</code>", 1)[0]
    row = IntegrationApiClient.query.one()
    assert token.startswith("vp_live_")
    assert token not in row.token_hash
    assert token not in json.dumps(
        [entry.new_values for entry in AuditLog.query.all()], ensure_ascii=False
    )
    follow_up = client.get("/entegrasyonlar/").get_data(as_text=True)
    assert token not in follow_up


def test_webhook_url_validation_blocks_ssrf_and_accepts_public_dns():
    def resolver(_host, _port, type=None):
        return [(2, 1, 6, "", ("93.184.216.34", 443))]

    assert validate_webhook_url("https://hooks.example.com/volka", resolver=resolver).startswith("https://")
    for target in (
        "http://hooks.example.com/volka",
        "https://localhost/hook",
        "https://127.0.0.1/hook",
        "https://hooks.example.com:8443/hook",
        "https://user:pass@hooks.example.com/hook",
        "https://hooks.example.com/hook?token=secret",
    ):
        try:
            validate_webhook_url(target, resolver=resolver)
        except IntegrationSecurityError:
            pass
        else:
            raise AssertionError(f"SSRF guvenlik kontrolu hedefi reddetmedi: {target}")

    def private_resolver(_host, _port, type=None):
        return [(2, 1, 6, "", ("10.0.0.12", 443))]

    try:
        validate_webhook_url("https://hooks.example.com/hook", resolver=private_resolver)
    except IntegrationSecurityError:
        pass
    else:
        raise AssertionError("Ozel IP cozumlemesi engellenmedi")

    target = resolve_webhook_target(
        "https://hooks.example.com/volka", resolver=resolver
    )
    assert target.hostname == "hooks.example.com"
    assert target.path == "/volka"
    assert target.addresses == ("93.184.216.34",)


def test_invalid_api_auth_is_audited_and_ip_limited(app, client):
    app.config["INTEGRATION_AUTH_FAILURES_PER_MINUTE"] = 2
    headers = {"Authorization": "Bearer invalid.token"}
    assert client.get("/api/v1/ping", headers=headers).status_code == 401
    assert client.get("/api/v1/ping", headers=headers).status_code == 401
    limited = client.get("/api/v1/ping", headers=headers)
    assert limited.status_code == 429
    assert limited.headers["Retry-After"] == "60"
    failures = AuditLog.query.filter_by(
        entity_type="IntegrationApiAuth", action="authentication_failed"
    ).all()
    assert len(failures) == 2
    assert all("invalid.token" not in (row.new_values or "") for row in failures)


def test_database_rejects_cross_tenant_webhook_delivery(app):
    company_a = create_company("760")
    company_b = create_company("761")
    endpoint = WebhookEndpoint(
        company_id=company_a.id,
        name="Firma A ERP",
        endpoint_url="https://erp.example.com/hook",
        events_json="[]",
        secret_ciphertext="encrypted",
        secret_hint="123456",
    )
    event = IntegrationEvent(
        event_uuid="00000000-0000-0000-0000-000000000761",
        company_id=company_b.id,
        event_type="webhook.test",
        subject_type="Test",
        subject_id="1",
        payload_json="{}",
    )
    db.session.add_all((endpoint, event))
    db.session.flush()
    db.session.add(
        WebhookDelivery(
            delivery_uuid="00000000-0000-0000-0000-000000000760",
            company_id=company_a.id,
            webhook_endpoint_id=endpoint.id,
            integration_event_id=event.id,
        )
    )
    try:
        db.session.commit()
    except (IntegrityError, ValueError):
        db.session.rollback()
    else:
        raise AssertionError("Sirketler arasi webhook teslimati veritabaninda engellenmedi")


def test_webhook_ui_encrypts_secret_and_only_shows_it_once(app, client, monkeypatch):
    app.config["INTEGRATION_ENCRYPTION_KEY"] = Fernet.generate_key().decode("ascii")
    company = create_company("758")
    manager = create_user(
        "webhook-manager",
        company=company,
        permissions=("integrations.view", "integrations.manage_webhooks"),
    )
    login(client, manager, company)
    monkeypatch.setattr("app.integrations.validate_webhook_url", lambda value: value)

    response = client.post(
        "/entegrasyonlar/webhooklar",
        data={
            "name": "ERP Bildirimleri",
            "endpoint_url": "https://erp.example.com/hooks/volkaportal",
            "events": ["action.completed", "dof.status_changed"],
        },
    )

    assert response.status_code == 201
    body = response.get_data(as_text=True)
    marker = '<code class="d-block mt-2 text-break user-select-all">'
    secret = body.split(marker, 1)[1].split("</code>", 1)[0]
    endpoint = WebhookEndpoint.query.one()
    assert secret not in endpoint.secret_ciphertext
    assert secret not in json.dumps(
        [entry.new_values for entry in AuditLog.query.all()], ensure_ascii=False
    )
    assert secret not in client.get("/entegrasyonlar/").get_data(as_text=True)


def test_webhook_outbox_signature_delivery_and_targeted_test(app, monkeypatch):
    app.config["INTEGRATION_ENCRYPTION_KEY"] = Fernet.generate_key().decode("ascii")
    company = create_company("756")
    secret_a = generate_webhook_secret()
    secret_b = generate_webhook_secret()
    endpoint_a = WebhookEndpoint(
        company_id=company.id,
        name="ERP A",
        endpoint_url="https://hooks-a.example.com/volka",
        events_json=json.dumps(["webhook.test"]),
        secret_ciphertext=encrypt_secret(secret_a),
        secret_hint=secret_a[-6:],
    )
    endpoint_b = WebhookEndpoint(
        company_id=company.id,
        name="ERP B",
        endpoint_url="https://hooks-b.example.com/volka",
        events_json=json.dumps(["webhook.test"]),
        secret_ciphertext=encrypt_secret(secret_b),
        secret_hint=secret_b[-6:],
    )
    db.session.add_all((endpoint_a, endpoint_b))
    db.session.flush()
    publish_integration_event(
        company_id=company.id,
        event_type="webhook.test",
        subject_type="WebhookEndpoint",
        subject_id=endpoint_a.id,
        payload={"message": "Test", "target_endpoint_id": endpoint_a.id},
        commit=True,
    )

    captured = {}

    monkeypatch.setattr(
        "app.integrations.resolve_webhook_target",
        lambda value: SimpleNamespace(
            url=value,
            hostname="hooks-a.example.com",
            port=443,
            path="/volka",
            addresses=("93.184.216.34",),
        ),
    )

    def fake_post(target, body, headers, timeout):
        captured["headers"] = headers
        captured["body"] = body
        captured["timeout"] = timeout
        captured["address"] = target.addresses[0]
        return 204, {}

    monkeypatch.setattr("app.integrations._post_webhook", fake_post)

    assert dispatch_webhooks() == 1
    delivery = WebhookDelivery.query.one()
    assert delivery.webhook_endpoint_id == endpoint_a.id
    assert delivery.status == "delivered"
    assert delivery.last_http_status == 204
    assert WebhookDeliveryAttempt.query.one().response_excerpt == "HTTP 204"
    captured_headers = {key.lower(): value for key, value in captured["headers"].items()}
    assert captured_headers["volkaportal-event-id"] == delivery.event.event_uuid
    assert captured_headers["volkaportal-signature"].startswith("v1=")
    assert json.loads(captured["body"])["specversion"] == "1.0"
    assert dispatch_webhooks() == 0


def test_domain_event_is_transactional_and_checklist_requires_readiness_gate(app):
    app.config["INTEGRATION_ENCRYPTION_KEY"] = Fernet.generate_key().decode("ascii")
    company = create_company("757")
    pending = Action(
        company_id=company.id,
        title="Rollback aksiyonu",
        responsible_owner="Sorumlu",
        department="Kalite",
        termin_date=date.today(),
    )
    db.session.add(pending)
    db.session.flush()
    assert IntegrationEvent.query.filter_by(subject_id=str(pending.id)).count() == 1
    db.session.rollback()
    assert IntegrationEvent.query.filter_by(event_type="action.created").count() == 0

    make_action(company, "Kalıcı aksiyon")
    assert IntegrationEvent.query.filter_by(event_type="action.created", company_id=company.id).count() == 1

    AppSetting.query.filter_by(key="sales_readiness:competitor_api_webhooks").delete()
    db.session.commit()
    ensure_runtime_schema()
    inspector = inspect(db.engine)
    for table in (
        "integration_api_clients",
        "webhook_endpoints",
        "integration_events",
        "webhook_deliveries",
        "webhook_delivery_attempts",
        "integration_api_requests",
    ):
        assert table in inspector.get_table_names()
    assert db.session.get(AppSetting, "sales_readiness:competitor_api_webhooks") is None
    verify_integration_readiness(mark=True)
    assert db.session.get(AppSetting, "sales_readiness:competitor_api_webhooks").value == "1"


def test_disabled_webhook_cancels_pending_and_delivered_cannot_retry(app, client):
    company = create_company("759")
    manager = create_user(
        "delivery-manager",
        company=company,
        permissions=(
            "integrations.view",
            "integrations.manage_webhooks",
            "integrations.view_deliveries",
            "integrations.retry_deliveries",
        ),
    )
    endpoint = WebhookEndpoint(
        company_id=company.id,
        name="ERP",
        endpoint_url="https://erp.example.com/hook",
        events_json=json.dumps(["webhook.test"]),
        secret_ciphertext="encrypted",
        secret_hint="123456",
    )
    db.session.add(endpoint)
    db.session.flush()
    event = publish_integration_event(
        company_id=company.id,
        event_type="webhook.test",
        subject_type="WebhookEndpoint",
        subject_id=endpoint.id,
        payload={"target_endpoint_id": endpoint.id},
    )
    db.session.flush()
    pending = WebhookDelivery(
        company_id=company.id,
        delivery_uuid="10000000-0000-0000-0000-000000000001",
        endpoint=endpoint,
        event=event,
        status="pending",
    )
    delivered = WebhookDelivery(
        company_id=company.id,
        delivery_uuid="10000000-0000-0000-0000-000000000002",
        endpoint=endpoint,
        event=publish_integration_event(
            company_id=company.id,
            event_type="webhook.test",
            subject_type="WebhookEndpoint",
            subject_id=endpoint.id,
            payload={"target_endpoint_id": endpoint.id},
        ),
        status="delivered",
    )
    db.session.add_all((pending, delivered))
    db.session.commit()
    login(client, manager, company)

    assert client.post(f"/entegrasyonlar/webhooklar/{endpoint.id}/durum").status_code == 302
    db.session.refresh(pending)
    assert pending.status == "failed"
    assert pending.last_error_code == "endpoint_disabled"
    before_count = IntegrationEvent.query.count()
    assert client.post(f"/entegrasyonlar/webhooklar/{endpoint.id}/test").status_code == 302
    assert IntegrationEvent.query.count() == before_count
    assert client.post(
        f"/entegrasyonlar/teslimatlar/{delivered.id}/yeniden-dene"
    ).status_code == 409


def test_default_roles_follow_least_privilege_for_integrations(app, client):
    company = create_company("760")
    representative = create_user(
        "integration-representative",
        company=company,
        role_key="management_representative",
    )
    management = create_user("integration-management", company=company, role_key="management")
    department_manager = create_user(
        "integration-department-manager",
        company=company,
        role_key="department_manager",
    )
    staff = create_user("integration-department-staff", company=company, role_key="department_staff")

    login(client, representative, company)
    representative_page = client.get("/entegrasyonlar/")
    assert representative_page.status_code == 200
    assert "Anahtar Oluştur" in representative_page.get_data(as_text=True)

    login(client, management, company)
    management_page = client.get("/entegrasyonlar/")
    management_body = management_page.get_data(as_text=True)
    assert management_page.status_code == 200
    assert "API Anahtarları" in management_body
    assert "Anahtar Oluştur" not in management_body

    for user in (department_manager, staff):
        login(client, user, company)
        assert client.get("/entegrasyonlar/").status_code == 403
