from datetime import date, datetime, timedelta
import hashlib
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from unittest.mock import Mock

from flask import url_for
from PIL import Image
import pytest

from app import customer_portal
from app.extensions import db
from app.models import (
    AuditLog,
    CompanyDepartment,
    ComplaintFile,
    ComplaintMessage,
    ComplaintRecord,
    ComplaintStatusHistory,
    CustomerPortalAttempt,
    CustomerPortalToken,
)

from .helpers import create_user
from .test_customer_feedback_portal import app, client, company, login


HEADERS = {"Host": "portal-firma.volkaportal.com"}
BASE = "/musteri-geri-bildirimleri"
LEGACY_SOURCE = "\u0130\u00e7 Kay\u0131t"
PUBLIC_SOURCE = "M\u00fc\u015fteri Portal\u0131"
CLOSED_STATUS = "Kapat\u0131ld\u0131"


class FeedbackCells(HTMLParser):
    def __init__(self, body):
        super().__init__()
        self.cells = {}
        self.label = None
        self.feed(body)

    def handle_starttag(self, tag, attrs):
        if tag == "td":
            self.label = dict(attrs).get("data-label")
            if self.label:
                self.cells.setdefault(self.label, [])

    def handle_endtag(self, tag):
        if tag == "td":
            self.label = None

    def handle_data(self, data):
        if self.label:
            self.cells[self.label].append(data)

    def text(self, label):
        return " ".join(" ".join(self.cells[label]).split())


@pytest.fixture()
def staff(app):
    target = company()
    users = {
        "creator": create_user("internal-creator", company=target, permissions=(
            "customer_portal.view", "customer_portal.create",
            "customer_portal.assign",
            "customer_portal.file_download", "customer_portal.respond",
            "customer_portal.close", "customer_portal.archive",
        )),
        "owner": create_user("internal-owner", company=target, permissions=(
            "customer_portal.view", "customer_portal.respond",
            "customer_portal.file_download",
        )),
        "stranger": create_user("internal-stranger", company=target, permissions=(
            "customer_portal.view", "customer_portal.file_download",
            "customer_portal.respond",
        )),
        "foreign": create_user("foreign-owner", company=company("102"), permissions=(
            "customer_portal.view", "customer_portal.assign",
            "customer_portal.file_download", "customer_portal.respond",
        )),
        "inactive": create_user("inactive-owner", company=target),
    }
    users["inactive"].is_active = False
    db.session.add_all([
        CompanyDepartment(company_id=target.id, name="Internal Quality", is_active=True),
        CompanyDepartment(company_id=target.id, name="Inactive Department", is_active=False),
        CompanyDepartment(company_id=company("102").id, name="Foreign Department", is_active=True),
    ])
    db.session.commit()
    return users


def form_data(staff, **overrides):
    values = {
        "customer_name": "Internal Customer AS",
        "customer_reference": "PROJECT-INT-42",
        "received_date": (date.today() - timedelta(days=2)).isoformat(),
        "subject": "Surface damage reported by phone",
        "description": "Customer reported damaged panels in the delivered batch.",
        "department": "Internal Quality",
        "responsible_user_id": str(staff["owner"].id),
        "due_date": (date.today() + timedelta(days=7)).isoformat(),
        "corrective_action": "Replace affected panels and inspect the next batch.",
    }
    values.update(overrides)
    return values


def image_upload(filename="evidence.png", image_format="PNG"):
    stream = BytesIO()
    Image.new("RGB", (8, 8), (35, 140, 90)).save(stream, format=image_format)
    stream.seek(0)
    return stream, filename


def stored_files(app):
    return {
        path.relative_to(Path(app.config["UPLOAD_FOLDER"])): path.read_bytes()
        for path in Path(app.config["UPLOAD_FOLDER"]).rglob("*")
        if path.is_file()
    }


def endpoint(app, name, **values):
    with app.test_request_context():
        return url_for(f"customer_portal.{name}", **values)


def create_record(client, staff, **overrides):
    login(client, staff["creator"])
    response = client.post(f"{BASE}/yeni", data=form_data(staff, **overrides), headers=HEADERS)
    assert response.status_code == 302
    record = ComplaintRecord.query.order_by(ComplaintRecord.id.desc()).first()
    assert record is not None
    assert response.headers["Location"].endswith(f"{BASE}/{record.id}")
    return record


def test_create_internal_record_without_customer_verification_or_tracking(app, client, staff, monkeypatch):
    send_email = Mock()
    monkeypatch.setattr(customer_portal, "send_recipient_email", send_email)
    values = form_data(staff)

    record = create_record(client, staff)

    assert record.company_id == company().id
    assert record.created_by_user_id == staff["creator"].id
    assert record.responsible_user_id == staff["owner"].id
    assert record.source not in {LEGACY_SOURCE, PUBLIC_SOURCE}
    assert record.email_verified_at is None
    assert record.contact_email is None
    assert record.status != "E-posta Do\u011frulamas\u0131 Bekleniyor"
    assert record.received_date == date.fromisoformat(values["received_date"])
    assert record.due_date == date.fromisoformat(values["due_date"])
    for field in ("customer_name", "customer_reference", "subject", "description", "department", "corrective_action"):
        assert getattr(record, field) == values[field]
    assert CustomerPortalToken.query.count() == 0
    assert CustomerPortalAttempt.query.count() == 0
    send_email.assert_not_called()
    history = ComplaintStatusHistory.query.filter_by(complaint_id=record.id).one()
    assert history.company_id == record.company_id
    assert history.changed_by_user_id == staff["creator"].id
    assert AuditLog.query.filter_by(entity_type="CustomerFeedbackPortal", entity_id=record.id).count() >= 1


def test_creator_sees_record_title_project_and_dates_without_assignment(app, client, staff):
    record = create_record(client, staff)
    assert record.responsible_user_id != staff["creator"].id
    for permission in list(staff["creator"].extra_permissions):
        if permission.permission_key == "customer_portal.assign":
            staff["creator"].extra_permissions.remove(permission)
    db.session.commit()
    assert not staff["creator"].has_permission("customer_portal.assign")

    dashboard = client.get(BASE, headers=HEADERS)
    detail = client.get(f"{BASE}/{record.id}", headers=HEADERS)

    assert dashboard.status_code == detail.status_code == 200
    for response in (dashboard, detail):
        body = response.get_data(as_text=True)
        for value in (record.complaint_no, record.subject, record.customer_reference,
                      record.received_date.strftime("%d.%m.%Y")):
            assert value in body
    assert record.due_date.strftime("%d.%m.%Y") in dashboard.get_data(as_text=True)
    detail_body = detail.get_data(as_text=True)
    assert (record.due_date.strftime("%d.%m.%Y") in detail_body
            or f'value="{record.due_date.isoformat()}"' in detail_body)


def test_internal_source_does_not_expose_legacy_complaints(app, client, staff):
    record = create_record(client, staff)
    legacy = ComplaintRecord(
        company_id=company().id, complaint_no="LEGACY-PRIVATE-42", customer_name="Legacy",
        subject="Legacy complaint", source=LEGACY_SOURCE, created_by_user_id=staff["creator"].id,
        responsible_user_id=staff["creator"].id, status="Yeni",
    )
    db.session.add(legacy)
    db.session.commit()

    response = client.get(BASE, headers=HEADERS)

    assert response.status_code == 200
    assert record.complaint_no in response.get_data(as_text=True)
    assert legacy.complaint_no not in response.get_data(as_text=True)
    assert client.get(f"{BASE}/{legacy.id}", headers=HEADERS).status_code == 404


def test_new_form_scopes_active_departments_and_responsible_users(app, client, staff):
    login(client, staff["creator"])
    response = client.get(f"{BASE}/yeni", headers=HEADERS)
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Internal Quality" in body
    assert staff["owner"].full_name in body
    for name in ("Inactive Department", "Foreign Department", staff["foreign"].full_name, staff["inactive"].full_name):
        assert name not in body


def test_creator_without_assign_cannot_assign_another_user(app, client, staff):
    creator = create_user("creator-no-assign", company=company(), permissions=(
        "customer_portal.view", "customer_portal.create",
    ))
    login(client, creator)
    response = client.post(f"{BASE}/yeni", data=form_data(staff,
        before_images=[image_upload()],
    ), headers=HEADERS)
    assert response.status_code == 403
    assert ComplaintRecord.query.count() == 0
    assert ComplaintFile.query.count() == 0
    assert ComplaintStatusHistory.query.count() == 0
    assert CustomerPortalToken.query.count() == 0
    assert AuditLog.query.filter_by(entity_type="CustomerFeedbackPortal").count() == 0
    assert not stored_files(app)


@pytest.mark.parametrize("self_assign", [False, True])
def test_creator_without_assign_can_create_and_access_own_record(app, client, staff, self_assign):
    creator = create_user("creator-no-assign", company=company(), permissions=(
        "customer_portal.view", "customer_portal.create",
    ))
    login(client, creator)
    response = client.post(f"{BASE}/yeni", data=form_data(staff,
        department="",
        responsible_user_id=str(creator.id) if self_assign else "",
    ), headers=HEADERS)
    assert response.status_code == 302
    record = ComplaintRecord.query.one()
    assert record.created_by_user_id == creator.id
    assert record.responsible_user_id == (creator.id if self_assign else None)
    assert client.get(response.headers["Location"], headers=HEADERS).status_code == 200
    assert record.complaint_no in client.get(BASE, headers=HEADERS).get_data(as_text=True)


def test_creator_without_assign_cannot_forge_department_assignment(app, client, staff):
    creator = create_user("creator-no-assign", company=company(), permissions=(
        "customer_portal.view", "customer_portal.create",
    ))
    login(client, creator)
    response = client.post(f"{BASE}/yeni", data=form_data(staff,
        responsible_user_id="",
    ), headers=HEADERS)
    assert response.status_code == 403
    assert ComplaintRecord.query.count() == 0


@pytest.mark.parametrize("invalid_choice", ["foreign_user", "inactive_user", "foreign_department", "inactive_department"])
def test_create_rejects_out_of_scope_choices_without_partial_record(app, client, staff, invalid_choice):
    overrides = {
        "foreign_user": {"responsible_user_id": str(staff["foreign"].id)},
        "inactive_user": {"responsible_user_id": str(staff["inactive"].id)},
        "foreign_department": {"department": "Foreign Department"},
        "inactive_department": {"department": "Inactive Department"},
    }[invalid_choice]
    login(client, staff["creator"])
    response = client.post(f"{BASE}/yeni", data=form_data(staff, **overrides), headers=HEADERS)
    assert response.status_code == 400
    assert ComplaintRecord.query.count() == 0
    assert ComplaintFile.query.count() == 0
    assert CustomerPortalToken.query.count() == 0
    assert not stored_files(app)


@pytest.mark.parametrize("role_key,permissions", [
    (None, ("customer_portal.view",)),
    ("viewer", ("customer_portal.view",)),
])
def test_readonly_user_cannot_open_or_submit_new_record(app, client, staff, role_key, permissions):
    viewer = create_user("readonly", company=company(), role_key=role_key, permissions=permissions)
    login(client, viewer)
    assert client.get(f"{BASE}/yeni", headers=HEADERS).status_code == 403
    assert client.post(f"{BASE}/yeni", data=form_data(staff), headers=HEADERS).status_code == 403
    assert ComplaintRecord.query.count() == 0


@pytest.mark.parametrize("overrides", [
    {"received_date": "not-a-date"},
    {"received_date": "2026-02-30"},
    {"due_date": "not-a-date"},
    {"received_date": "2026-10-12", "due_date": "2026-10-11"},
    {"responsible_user_id": "not-an-id"},
    {"customer_name": ""},
    {"subject": ""},
    {"description": ""},
])
def test_invalid_fields_do_not_create_partial_records(app, client, staff, overrides):
    login(client, staff["creator"])
    response = client.post(f"{BASE}/yeni", data=form_data(staff, **overrides), headers=HEADERS)
    assert response.status_code == 400
    assert ComplaintRecord.query.count() == 0
    assert ComplaintStatusHistory.query.count() == 0
    assert CustomerPortalToken.query.count() == 0


def test_create_ignores_forged_company_source_and_creator(app, client, staff):
    record = create_record(client, staff,
        company_id=str(company("102").id), created_by_user_id=str(staff["foreign"].id),
        source=PUBLIC_SOURCE, email_verified_at="2026-01-01T12:00:00",
    )
    assert record.company_id == company().id
    assert record.created_by_user_id == staff["creator"].id
    assert record.source not in {LEGACY_SOURCE, PUBLIC_SOURCE}
    assert record.email_verified_at is None


def test_search_matches_project_reference(app, client, staff):
    record = create_record(client, staff)
    matching = client.get(BASE, query_string={"search": record.customer_reference}, headers=HEADERS)
    missing = client.get(BASE, query_string={"search": "UNRELATED-PROJECT"}, headers=HEADERS)
    assert matching.status_code == missing.status_code == 200
    assert record.complaint_no in matching.get_data(as_text=True)
    assert record.complaint_no not in missing.get_data(as_text=True)


def test_multiple_before_after_images_are_internal_and_privately_previewed(app, client, staff):
    record = create_record(client, staff,
        before_images=[image_upload("before-one.png"), image_upload("before-two.jpeg", "JPEG")],
        after_images=[image_upload("after-one.jpg", "JPEG"), image_upload("after-two.png")],
    )
    rows = ComplaintFile.query.filter_by(complaint_id=record.id).order_by(ComplaintFile.id).all()
    assert len(rows) == 4
    assert sorted(row.evidence_stage for row in rows) == ["after", "after", "before", "before"]
    assert len(stored_files(app)) == 4

    for row in rows:
        assert row.company_id == record.company_id
        assert row.visibility == "internal"
        assert row.uploaded_by_user_id == staff["creator"].id
        assert row.uploaded_by_customer is False
        path = Path(app.config["UPLOAD_FOLDER"]) / row.stored_path
        assert path.is_file()
        assert row.file_size == path.stat().st_size
        assert row.sha256_hash == hashlib.sha256(path.read_bytes()).hexdigest()
        response = client.get(endpoint(app, "preview_file", record_id=record.id, file_id=row.id), headers=HEADERS)
        assert response.status_code == 200
        assert response.mimetype in {"image/png", "image/jpeg"}
        assert response.data == path.read_bytes()
        assert not response.headers.get("Content-Disposition", "").startswith("attachment")
        assert "private" in response.headers.get("Cache-Control", "")
        assert "no-store" in response.headers.get("Cache-Control", "")
        assert response.headers.get("X-Content-Type-Options") == "nosniff"
        response.close()


@pytest.mark.parametrize("image_format,extension", [("JPEG", "jpg"), ("PNG", "png")])
def test_evidence_normalizes_orientation_and_strips_metadata_and_trailing_payload(app, client, staff, image_format, extension):
    stream = BytesIO()
    exif = Image.Exif()
    exif[274] = 6
    exif[315] = "PRIVATE-CAMERA-OWNER"
    with Image.new("RGB", (8, 4), (35, 140, 90)) as picture:
        picture.save(stream, format=image_format, exif=exif)
    stream.write(b"TRAILING-PRIVATE-PAYLOAD")
    stream.seek(0)
    with Image.open(stream) as picture:
        assert picture.getexif()[315] == "PRIVATE-CAMERA-OWNER"
    stream.seek(0)
    record = create_record(client, staff, before_images=[(stream, f"metadata.{extension}")])
    row = ComplaintFile.query.filter_by(complaint_id=record.id).one()
    path = Path(app.config["UPLOAD_FOLDER"]) / row.stored_path
    with Image.open(path) as picture:
        assert picture.size == (4, 8)
        assert not picture.getexif()
    payload = path.read_bytes()
    assert b"PRIVATE-CAMERA-OWNER" not in payload
    assert b"TRAILING-PRIVATE-PAYLOAD" not in payload
    assert row.file_size == len(payload)
    assert row.sha256_hash == hashlib.sha256(payload).hexdigest()


def test_evidence_above_twenty_megapixels_rolls_back_batch(app, client, staff):
    stream = BytesIO()
    with Image.new("1", (5000, 4001)) as picture:
        picture.save(stream, format="PNG")
    stream.seek(0)
    login(client, staff["creator"])
    response = client.post(f"{BASE}/yeni", data=form_data(staff,
        before_images=[image_upload()], after_images=[(stream, "too-large.png")],
    ), headers=HEADERS)
    assert response.status_code == 400
    assert ComplaintRecord.query.count() == 0
    assert ComplaintFile.query.count() == 0
    assert not stored_files(app)


@pytest.mark.parametrize("image_count", [12, 13])
def test_evidence_batch_limit_counts_both_stages(app, client, staff, image_count):
    login(client, staff["creator"])
    response = client.post(f"{BASE}/yeni", data=form_data(staff,
        before_images=[image_upload(f"before-{index}.png") for index in range(6)],
        after_images=[image_upload(f"after-{index}.png") for index in range(image_count - 6)],
    ), headers=HEADERS)
    assert response.status_code == (302 if image_count == 12 else 400)
    assert ComplaintRecord.query.count() == (1 if image_count == 12 else 0)
    assert ComplaintFile.query.count() == (12 if image_count == 12 else 0)
    assert len(stored_files(app)) == (12 if image_count == 12 else 0)


@pytest.mark.parametrize("actor", ["anonymous", "stranger", "foreign"])
def test_image_preview_requires_record_and_tenant_access(app, client, staff, actor):
    record = create_record(client, staff, before_images=[image_upload()])
    row = ComplaintFile.query.one()
    preview_url = endpoint(app, "preview_file", record_id=record.id, file_id=row.id)
    isolated_client = app.test_client()
    headers = HEADERS
    if actor == "foreign":
        headers = {"Host": "diger-firma.volkaportal.com"}
        with isolated_client.session_transaction(base_url="https://diger-firma.volkaportal.com") as session:
            session["user_id"] = staff["foreign"].id
    elif actor != "anonymous":
        login(isolated_client, staff[actor])
    response = isolated_client.get(preview_url, headers=headers)
    assert response.status_code == {"anonymous": 302, "stranger": 403, "foreign": 404}[actor]
    assert response.mimetype not in {"image/png", "image/jpeg"}


def test_internal_evidence_is_not_available_through_customer_tracking(app, client, staff):
    record = create_record(client, staff, before_images=[image_upload()])
    row = ComplaintFile.query.one()
    raw_token = "test-internal-record-tracking-token"
    db.session.add(CustomerPortalToken(
        company_id=record.company_id, complaint_id=record.id, purpose="tracking",
        token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
        expires_at=datetime.now() + timedelta(days=1),
    ))
    db.session.commit()
    response = app.test_client().get(
        f"/musteri-portali/takip/{raw_token}/dosya/{row.id}", headers=HEADERS,
    )
    assert response.status_code == 404


def test_evidence_preview_and_download_require_file_permission(app, client, staff):
    record = create_record(client, staff, before_images=[image_upload()])
    row = ComplaintFile.query.one()
    reader = create_user("reader-no-download", company=company(), permissions=(
        "customer_portal.view",
    ))
    record.responsible_user_id = reader.id
    db.session.commit()
    login(client, reader)
    assert client.get(f"{BASE}/{record.id}", headers=HEADERS).status_code == 200
    for name in ("preview_file", "internal_file"):
        response = client.get(endpoint(app, name, record_id=record.id, file_id=row.id), headers=HEADERS)
        assert response.status_code == 403
        assert response.mimetype not in {"image/png", "image/jpeg"}


def test_evidence_preview_and_download_reject_another_records_file(app, client, staff):
    first = create_record(client, staff, before_images=[image_upload()])
    row = ComplaintFile.query.filter_by(complaint_id=first.id).one()
    second = create_record(client, staff)
    for name in ("preview_file", "internal_file"):
        response = client.get(endpoint(app, name, record_id=second.id, file_id=row.id), headers=HEADERS)
        assert response.status_code == 404
        assert response.mimetype not in {"image/png", "image/jpeg"}


@pytest.mark.parametrize("operation", ["create", "evidence"])
def test_internal_writes_require_csrf_token(app, client, staff, operation):
    if operation == "evidence":
        record = create_record(client, staff)
        url = endpoint(app, "upload_evidence", record_id=record.id)
        data = {"before_images": [image_upload()]}
    else:
        login(client, staff["creator"])
        url = f"{BASE}/yeni"
        data = form_data(staff, before_images=[image_upload()])
    existing_records = ComplaintRecord.query.count()
    existing_audits = AuditLog.query.filter_by(entity_type="CustomerFeedbackPortal").count()
    app.config["WTF_CSRF_ENABLED"] = True
    response = client.post(url, data=data, headers={**HEADERS, "Accept": "application/json"})
    assert response.status_code == 400
    assert response.json["ok"] is False
    assert ComplaintRecord.query.count() == existing_records
    assert ComplaintFile.query.count() == 0
    assert AuditLog.query.filter_by(entity_type="CustomerFeedbackPortal").count() == existing_audits
    assert not stored_files(app)


@pytest.mark.parametrize("filename,payload", [
    ("fake.png", b"not an image"),
    ("document.pdf", b"%PDF-1.4\nnot an image"),
    ("truncated.png", b"\x89PNG\r\n\x1a\n"),
    ("truncated.jpg", b"\xff\xd8\xff"),
])
def test_invalid_image_rolls_back_record_and_cleans_preceding_images(app, client, staff, filename, payload):
    login(client, staff["creator"])
    data = form_data(staff,
        before_images=[image_upload("valid-first.png")],
        after_images=[(BytesIO(payload), filename)],
    )
    response = client.post(f"{BASE}/yeni", data=data, headers=HEADERS)
    assert response.status_code == 400
    assert ComplaintRecord.query.count() == 0
    assert ComplaintFile.query.count() == 0
    assert ComplaintMessage.query.count() == 0
    assert ComplaintStatusHistory.query.count() == 0
    assert CustomerPortalToken.query.count() == 0
    assert AuditLog.query.filter_by(entity_type="CustomerFeedbackPortal").count() == 0
    assert not stored_files(app)


def test_add_evidence_preserves_stages_and_invalid_batch_preserves_existing_files(app, client, staff):
    record = create_record(client, staff, before_images=[image_upload("original.png")])
    upload_url = endpoint(app, "upload_evidence", record_id=record.id)
    response = client.post(upload_url, data={
        "after_images": [image_upload("after.png"), image_upload("after.jpg", "JPEG")],
    }, headers=HEADERS)
    assert response.status_code == 302
    assert sorted(row.evidence_stage for row in ComplaintFile.query.all()) == ["after", "after", "before"]
    existing_files = stored_files(app)
    existing_ids = {row.id for row in ComplaintFile.query.all()}

    response = client.post(upload_url, data={
        "before_images": [image_upload("valid-new.png")],
        "after_images": [(BytesIO(b"invalid"), "invalid.png")],
    }, headers=HEADERS)
    assert response.status_code == 302
    assert {row.id for row in ComplaintFile.query.all()} == existing_ids
    assert stored_files(app) == existing_files
    assert ComplaintRecord.query.count() == 1


def test_internal_message_defaults_to_private_without_tracking_email(app, client, staff, monkeypatch):
    record = create_record(client, staff)
    send_email = Mock()
    monkeypatch.setattr(customer_portal, "send_recipient_email", send_email)
    response = client.post(f"{BASE}/{record.id}/mesaj", data={
        "message": "Internal progress note", "visibility": "public",
        "attachment": image_upload("message.png"),
    }, headers=HEADERS)
    assert response.status_code == 302
    assert ComplaintMessage.query.one().visibility == "internal"
    row = ComplaintFile.query.one()
    assert row.visibility == "internal"
    assert row.evidence_stage == "general"
    assert CustomerPortalToken.query.count() == 0
    send_email.assert_not_called()


def test_closing_internal_record_does_not_issue_customer_token_or_email(app, client, staff, monkeypatch):
    record = create_record(client, staff)
    send_email = Mock()
    monkeypatch.setattr(customer_portal, "send_recipient_email", send_email)
    response = client.post(f"{BASE}/{record.id}/guncelle", data={
        "status": CLOSED_STATUS, "customer_solution_summary": "Replacement inspected and accepted.",
    }, headers=HEADERS)
    assert response.status_code == 302
    db.session.refresh(record)
    assert record.status == CLOSED_STATUS
    assert record.is_closed
    assert record.closed_at is not None
    assert CustomerPortalToken.query.count() == 0
    send_email.assert_not_called()


@pytest.mark.parametrize("status", [CLOSED_STATUS, "Kapand\u0131", "Reddedildi", "Ar\u015fiv"])
def test_closed_status_is_not_overdue_without_closed_timestamp(app, client, staff, status):
    record = create_record(client, staff)
    record.status = status
    record.closed_at = None
    record.due_date = date.today() - timedelta(days=5)
    db.session.commit()
    assert record.is_closed
    assert record.delay_days == 0
    response = client.get(BASE, headers=HEADERS)
    assert response.status_code == 200
    cells = FeedbackCells(response.get_data(as_text=True))
    assert cells.text("Kalan S\u00fcre") == "Kapand\u0131"
    assert cells.text("Sonu\u00e7") == status


def test_archived_record_rejects_new_evidence_without_changing_files(app, client, staff):
    record = create_record(client, staff, before_images=[image_upload("original.png")])
    record.status = CLOSED_STATUS
    record.closed_at = datetime.now()
    db.session.commit()
    assert client.post(f"{BASE}/{record.id}/arsivle", headers=HEADERS).status_code == 302
    db.session.refresh(record)
    assert record.is_archived
    existing_files = stored_files(app)
    response = client.post(endpoint(app, "upload_evidence", record_id=record.id), data={
        "after_images": [image_upload("too-late.png")],
    }, headers=HEADERS)
    assert response.status_code == 400
    assert ComplaintFile.query.count() == 1
    assert stored_files(app) == existing_files


def test_readonly_assignee_cannot_upload_evidence(app, client, staff):
    record = create_record(client, staff)
    viewer = create_user("readonly-owner", company=company(), role_key="viewer", permissions=(
        "customer_portal.view", "customer_portal.file_download",
    ))
    record.responsible_user_id = viewer.id
    db.session.commit()
    login(client, viewer)
    response = client.post(endpoint(app, "upload_evidence", record_id=record.id), data={
        "before_images": [image_upload()],
    }, headers=HEADERS)
    assert response.status_code == 403
    assert ComplaintFile.query.count() == 0
    assert not stored_files(app)
