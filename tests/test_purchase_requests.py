"""Regression coverage for tenant-scoped purchase request decisions."""
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import AuditLog, Notification, Role
from app.purchase_models import PurchaseDecision, PurchaseRequest, PurchaseRequestItem
from tests.helpers import create_company, create_user, login


BASE = "/satin-alma-talepleri"


@pytest.fixture()
def actors(client):
    company = create_company("PURCHASE-A")
    other_company = create_company("PURCHASE-B")
    requester = create_user("purchase-requester", company=company, role_key="department_staff")
    purchaser = create_user("purchase-reviewer", company=company, role_key="purchasing_approver")
    admin = create_user("purchase-admin", company=company, role_key="company_admin")
    viewer = create_user("purchase-viewer", company=company, role_key="viewer")
    foreign = create_user("purchase-foreign", company=other_company, role_key="company_admin")
    login(client, requester, company)
    return SimpleNamespace(company=company, other_company=other_company, requester=requester,
                           purchaser=purchaser, admin=admin, viewer=viewer, foreign=foreign)


def form_data(kind="material", **changes):
    values = {
        "version_id": "1",
        "request_token": str(uuid4()),
        "kind": kind,
        "title": "Workshop supply" if kind == "material" else "Equipment calibration",
        "description": "Needed for the scheduled maintenance window",
        "justification": "Approved maintenance plan requires this purchase",
        "quantity": "2.500",
        "unit": "piece" if kind == "material" else "hour",
        "estimated_total": "1250.75",
        "currency": "EUR",
        "needed_by": "2026-12-15",
    }
    values.update(changes)
    return values


def create_request(client, actors, kind="material", **changes):
    login(client, actors.requester, actors.company)
    response = client.post(f"{BASE}/yeni", data=form_data(kind, **changes))
    assert response.status_code == 302, response.get_data(as_text=True)
    record = PurchaseRequest.query.order_by(PurchaseRequest.id.desc()).first()
    assert response.headers["Location"].endswith(f"{BASE}/{record.id}")
    return record


def act(client, actors, user, record, route, **data):
    db.session.expire_all()
    version = db.session.get(PurchaseRequest, record.id).version_id
    login(client, user, actors.company)
    return client.post(f"{BASE}/{record.id}/{route}", data={"version_id": str(version), **data})


def decisions(record):
    return PurchaseDecision.query.filter_by(request_id=record.id).order_by(PurchaseDecision.id).all()


def notifications(record):
    return Notification.query.filter_by(company_id=record.company_id).filter(
        Notification.source_key.like(f"purchase:{record.id}:%")
    ).all()


def audits(record):
    return AuditLog.query.filter_by(entity_type="PurchaseRequest", entity_id=str(record.id)).all()


@pytest.mark.parametrize("role_name,can_create", [
    ("requester", True), ("admin", True), ("viewer", False),
])
def test_dashboard_create_button_matches_form_permission(client, actors, role_name, can_create):
    login(client, getattr(actors, role_name), actors.company)
    response = client.get(BASE)
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert ("Satın Alma Talebi Oluştur" in html) is can_create
    assert (f'href="{BASE}/yeni"' in html) is can_create
    assert client.get(f"{BASE}/yeni").status_code == (200 if can_create else 403)


def test_scoped_superadmin_can_create_and_submit_without_cross_tenant_leak(client, actors):
    platform_admin = create_user("purchase-platform-admin", role_key="super_admin")
    login(client, platform_admin, actors.company)
    response = client.get(BASE)
    assert response.status_code == 200
    assert "Satın Alma Talebi Oluştur" in response.get_data(as_text=True)
    assert client.get(f"{BASE}/yeni").status_code == 200

    response = client.post(f"{BASE}/yeni", data=form_data())
    assert response.status_code == 302
    record = PurchaseRequest.query.order_by(PurchaseRequest.id.desc()).first()
    assert (record.company_id, record.requester_id) == (actors.company.id, platform_admin.id)
    assert client.post(f"{BASE}/{record.id}/gonder", data={
        "version_id": str(record.version_id)}).status_code == 302
    db.session.refresh(record)
    assert record.status == "pending_purchase"

    assert act(client, actors, actors.purchaser, record, "satin-alma-onayla").status_code == 302
    assert act(client, actors, actors.admin, record, "yonetici-onayla").status_code == 302
    db.session.refresh(record)
    assert record.status == "closed"
    assert {entry.user_id for entry in notifications(record)} == {
        actors.purchaser.id, actors.admin.id, platform_admin.id}
    assert [entry.actor_id for entry in decisions(record)] == [
        platform_admin.id, actors.purchaser.id, actors.admin.id]

    login(client, platform_admin, actors.other_company)
    assert client.get(f"{BASE}/{record.id}").status_code == 404
    login(client, platform_admin)
    assert client.get(f"{BASE}/yeni").status_code == 403


def test_superadmin_role_revocation_does_not_block_company_approvals(client, actors):
    platform_admin = create_user("purchase-revoked-admin", role_key="super_admin")
    login(client, platform_admin, actors.company)
    assert client.post(f"{BASE}/yeni", data=form_data()).status_code == 302
    record = PurchaseRequest.query.order_by(PurchaseRequest.id.desc()).first()
    assert client.post(f"{BASE}/{record.id}/gonder", data={
        "version_id": str(record.version_id)}).status_code == 302

    platform_admin.roles.clear()
    db.session.commit()
    assert act(client, actors, actors.purchaser, record, "satin-alma-onayla").status_code == 302
    assert act(client, actors, actors.admin, record, "yonetici-onayla").status_code == 302
    db.session.refresh(record)
    assert record.status == "closed"
    assert platform_admin.id not in {entry.user_id for entry in notifications(record)}


@pytest.mark.parametrize("kind", ["material", "service"])
def test_form_creates_tenant_owned_draft_and_single_item(client, actors, kind):
    assert client.get(f"{BASE}/yeni").status_code == 200
    record = create_request(client, actors, kind)
    item = PurchaseRequestItem.query.filter_by(request_id=record.id).one()

    assert (record.company_id, record.requester_id, record.kind, record.status) == (
        actors.company.id, actors.requester.id, kind, "draft")
    assert record.record_no.startswith("SAT-")
    assert (record.quantity, record.estimated_total, record.currency) == (
        Decimal("2.500"), Decimal("1250.75"), "EUR")
    assert (item.company_id, item.line_no, item.description, item.quantity) == (
        actors.company.id, 1, record.description, record.quantity)
    assert client.get(f"{BASE}/{record.id}").status_code == 200
    assert [(entry.action, entry.user_id) for entry in audits(record)] == [
        ("created", actors.requester.id)]


def test_two_distinct_approvals_close_with_decisions_notifications_and_audit(client, actors):
    record = create_request(client, actors)
    assert act(client, actors, actors.requester, record, "gonder").status_code == 302
    db.session.refresh(record)
    assert record.status == "pending_purchase"
    assert {notice.user_id for notice in notifications(record)} == {actors.purchaser.id}

    assert act(client, actors, actors.purchaser, record, "satin-alma-onayla").status_code == 302
    db.session.refresh(record)
    assert record.status == "pending_admin"
    assert record.purchasing_approver_id == actors.purchaser.id
    assert {notice.user_id for notice in notifications(record)} == {
        actors.purchaser.id, actors.admin.id, actors.requester.id}

    assert act(client, actors, actors.admin, record, "yonetici-onayla").status_code == 302
    db.session.refresh(record)
    assert (record.status, record.admin_approver_id) == ("closed", actors.admin.id)
    assert record.closed_at is not None
    assert [(entry.action, entry.from_status, entry.to_status, entry.actor_id) for entry in decisions(record)] == [
        ("submitted", "draft", "pending_purchase", actors.requester.id),
        ("purchasing_approved", "pending_purchase", "pending_admin", actors.purchaser.id),
        ("admin_approved", "pending_admin", "closed", actors.admin.id),
    ]
    assert [(entry.action, entry.user_id) for entry in audits(record)] == [
        ("created", actors.requester.id), ("submitted", actors.requester.id),
        ("purchasing_approved", actors.purchaser.id), ("admin_approved", actors.admin.id)]
    assert len(notifications(record)) == 5
    assert all(note.target_url == f"{BASE}/{record.id}" for note in notifications(record))
    assert all(note.company_id == actors.company.id for note in notifications(record))


def test_sqlite_guards_reject_foreign_approver_and_closed_item(client, actors):
    with pytest.raises(IntegrityError):
        db.session.execute(text("""
            INSERT INTO purchase_requests
                (company_id, requester_id, kind, title, description, justification,
                 quantity, unit, currency, status, purchasing_approver_id,
                 request_token, version_id)
            VALUES (:company_id, :requester_id, 'material', 'Guard test',
                    'Material', 'Required', 1, 'piece', 'TRY', 'draft',
                    :foreign_id, :token, 1)
        """), dict(company_id=actors.company.id, requester_id=actors.requester.id,
                   foreign_id=actors.foreign.id, token=str(uuid4())))
        db.session.commit()
    db.session.rollback()

    record = create_request(client, actors)
    assert act(client, actors, actors.requester, record, "gonder").status_code == 302
    assert act(client, actors, actors.purchaser, record, "satin-alma-onayla").status_code == 302
    assert act(client, actors, actors.admin, record, "yonetici-onayla").status_code == 302
    with pytest.raises(IntegrityError):
        db.session.add(PurchaseRequestItem(
            company_id=actors.company.id, request_id=record.id, line_no=2,
            description="Late item", quantity=1, unit="piece"))
        db.session.commit()
    db.session.rollback()


def test_submission_stays_draft_without_distinct_approvers(client, actors):
    record = create_request(client, actors)
    actors.purchaser.is_active = False
    db.session.commit()
    response = act(client, actors, actors.requester, record, "gonder")
    assert response.status_code == 302
    db.session.refresh(record)
    assert record.status == "draft"
    assert not decisions(record)
    assert not notifications(record)


def test_purchase_forms_require_csrf(client, app, actors):
    app.config["WTF_CSRF_ENABLED"] = True
    try:
        assert client.get(f"{BASE}/yeni").status_code == 200
        response = client.post(f"{BASE}/yeni", data=form_data())
        assert response.status_code == 302
        assert PurchaseRequest.query.count() == 0
    finally:
        app.config["WTF_CSRF_ENABLED"] = False


def test_role_stage_and_self_approval_bans(client, actors):
    record = create_request(client, actors)
    actors.requester.roles.extend([
        Role.query.filter_by(key="purchasing_approver").one(),
        Role.query.filter_by(key="company_admin").one(),
    ])
    actors.purchaser.roles.append(Role.query.filter_by(key="company_admin").one())
    db.session.commit()

    assert act(client, actors, actors.admin, record, "yonetici-onayla").status_code == 409
    assert act(client, actors, actors.requester, record, "gonder").status_code == 302
    assert act(client, actors, actors.requester, record, "satin-alma-onayla").status_code == 403
    assert act(client, actors, actors.viewer, record, "satin-alma-onayla").status_code == 404
    assert act(client, actors, actors.admin, record, "satin-alma-onayla").status_code == 403
    assert act(client, actors, actors.purchaser, record, "satin-alma-onayla").status_code == 302
    assert act(client, actors, actors.purchaser, record, "yonetici-onayla").status_code == 403
    assert act(client, actors, actors.requester, record, "yonetici-onayla").status_code == 403
    assert act(client, actors, actors.admin, record, "yonetici-onayla").status_code == 302
    assert act(client, actors, actors.purchaser, record, "satin-alma-onayla").status_code == 409
    assert len(decisions(record)) == 3


def test_return_edit_resubmit_then_admin_reject(client, actors):
    record = create_request(client, actors)
    assert act(client, actors, actors.requester, record, "gonder").status_code == 302
    assert act(client, actors, actors.purchaser, record, "karar",
               action="returned", reason="Specify the delivery location").status_code == 302
    db.session.refresh(record)
    assert (record.status, record.decision_reason) == ("returned", "Specify the delivery location")
    assert act(client, actors, actors.requester, record, "duzenle",
               **form_data(title="Revised supply")).status_code == 409
    db.session.refresh(record)
    values = form_data(title="Revised supply")
    values["version_id"] = str(record.version_id)
    login(client, actors.requester, actors.company)
    assert client.post(f"{BASE}/{record.id}/duzenle", data=values).status_code == 302
    db.session.refresh(record)
    assert record.title == "Revised supply"
    assert act(client, actors, actors.requester, record, "gonder").status_code == 302
    assert act(client, actors, actors.purchaser, record, "satin-alma-onayla").status_code == 302
    assert act(client, actors, actors.admin, record, "karar",
               action="rejected", reason="Budget not available").status_code == 302
    db.session.refresh(record)
    assert (record.status, record.decision_reason, record.closed_at) == (
        "rejected", "Budget not available", None)
    assert [entry.action for entry in decisions(record)] == [
        "submitted", "returned", "resubmitted", "purchasing_approved", "rejected"]
    assert [(entry.action, entry.reason) for entry in decisions(record) if entry.reason] == [
        ("returned", "Specify the delivery location"), ("rejected", "Budget not available")]
    assert {entry.action for entry in audits(record)} == {
        "created", "submitted", "returned", "updated", "resubmitted",
        "purchasing_approved", "rejected"}
    assert {note.user_id for note in notifications(record)} == {
        actors.requester.id, actors.purchaser.id, actors.admin.id}


@pytest.mark.parametrize("action", ["returned", "rejected"])
def test_decision_requires_reason_and_correct_stage(client, actors, action):
    record = create_request(client, actors)
    assert act(client, actors, actors.requester, record, "gonder").status_code == 302
    assert act(client, actors, actors.purchaser, record, "karar",
               action=action, reason=" ").status_code == 400
    assert act(client, actors, actors.admin, record, "karar",
               action=action, reason="Unauthorized stage").status_code == 403
    assert act(client, actors, actors.purchaser, record, "karar",
               action=action, reason="Review decision").status_code == 302
    db.session.refresh(record)
    assert (record.status, record.decision_reason) == (action, "Review decision")
    assert act(client, actors, actors.purchaser, record, "karar",
               action=action, reason="Duplicate").status_code == 409
    assert [entry.action for entry in decisions(record)] == ["submitted", action]


def test_cross_tenant_list_detail_and_transition_are_scoped(client, actors):
    local = create_request(client, actors)
    login(client, actors.foreign, actors.other_company)
    response = client.post(f"{BASE}/yeni", data=form_data(title="Foreign private request"))
    assert response.status_code == 302
    foreign = PurchaseRequest.query.filter_by(company_id=actors.other_company.id).one()

    login(client, actors.admin, actors.company)
    listing = client.get(BASE)
    assert listing.status_code == 200
    assert local.title in listing.get_data(as_text=True)
    assert foreign.title not in listing.get_data(as_text=True)
    assert client.get(f"{BASE}/{foreign.id}").status_code == 404
    assert client.post(f"{BASE}/{foreign.id}/yonetici-onayla",
                       data={"version_id": str(foreign.version_id)}).status_code == 404
    login(client, actors.foreign, actors.other_company)
    assert client.get(f"{BASE}/{local.id}").status_code == 404
    assert PurchaseRequest.query.count() == 2
    assert not decisions(foreign)


def test_duplicate_create_token_and_stale_transition_have_no_extra_side_effects(client, actors):
    values = form_data()
    login(client, actors.requester, actors.company)
    assert client.post(f"{BASE}/yeni", data=values).status_code == 302
    record = PurchaseRequest.query.one()
    assert client.post(f"{BASE}/yeni", data=values).status_code == 302
    assert PurchaseRequest.query.count() == PurchaseRequestItem.query.count() == 1
    assert len(audits(record)) == 1

    stale_version = str(record.version_id)
    assert client.post(f"{BASE}/{record.id}/gonder",
                       data={"version_id": stale_version}).status_code == 302
    db.session.refresh(record)
    before = (len(decisions(record)), len(notifications(record)), len(audits(record)))
    assert client.post(f"{BASE}/{record.id}/gonder",
                       data={"version_id": stale_version}).status_code == 409
    assert (len(decisions(record)), len(notifications(record)), len(audits(record))) == before

    login(client, actors.purchaser, actors.company)
    stale_version = str(record.version_id)
    assert client.post(f"{BASE}/{record.id}/satin-alma-onayla",
                       data={"version_id": stale_version}).status_code == 302
    before = (len(decisions(record)), len(notifications(record)), len(audits(record)))
    assert client.post(f"{BASE}/{record.id}/satin-alma-onayla",
                       data={"version_id": stale_version}).status_code == 409
    assert (len(decisions(record)), len(notifications(record)), len(audits(record))) == before
