from datetime import UTC, datetime, timedelta
from io import BytesIO

from app.extensions import db
from app.models import AppSetting, AuditLog, Notification, WorkPermit, WorkPermitControl, WorkPermitFile
from app.seed import ensure_runtime_schema
from .helpers import create_company, create_user, login


ALL_PERMISSIONS = (
    "work_permits.view", "work_permits.view_all", "work_permits.create", "work_permits.update",
    "work_permits.confirm", "work_permits.approve", "work_permits.activate", "work_permits.close",
    "work_permits.manage", "work_permits.archive", "work_permits.file_download",
)


def date_value(value):
    return value.strftime("%Y-%m-%dT%H:%M")


def payload(responsible, approver, **overrides):
    now = datetime.now(UTC).replace(tzinfo=None)
    values = {
        "permit_type": "Sıcak Çalışma",
        "title": "Kaynak ile platform onarımı",
        "location": "Üretim Holü A",
        "department": "Üretim",
        "contractor": "Bakım Ekibi",
        "requested_start_at": date_value(now - timedelta(minutes=5)),
        "requested_end_at": date_value(now + timedelta(hours=2)),
        "responsible_user_id": str(responsible.id),
        "approver_user_id": str(approver.id),
        "description": "Platform bağlantı noktaları kaynakla onarılacak.",
        "hazards": "Yangın, sıcak yüzey ve duman.",
        "precautions": "Alan çevrilecek ve yangın gözcüsü bulunacak.",
        "ppe_requirements": "Kaynak maskesi, eldiven ve alev geciktirici kıyafet.",
        "emergency_plan": "Yangında işi durdurup 112 ve acil durum ekibi aranacak.",
    }
    values.update(overrides)
    return values


def test_full_work_permit_flow_tasks_audit_and_tenant_isolation(app, client):
    company = create_company("751")
    other = create_company("752")
    requester = create_user("permit-requester", company=company, permissions=("work_permits.view", "work_permits.create", "work_permits.update", "work_permits.file_download"))
    responsible = create_user("permit-responsible", company=company, permissions=("work_permits.view", "work_permits.confirm", "work_permits.activate", "work_permits.close", "work_permits.file_download"))
    approver = create_user("permit-approver", company=company, permissions=("work_permits.view", "work_permits.approve", "work_permits.file_download"))
    outsider = create_user("permit-outsider", company=company, permissions=("work_permits.view",))
    foreign = create_user("permit-foreign", company=other, permissions=ALL_PERMISSIONS)

    login(client, requester)
    response = client.post(
        "/is-izinleri/yeni",
        data=payload(responsible, approver, attachment=(BytesIO(b"permit evidence"), "alan.jpg")),
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    body = response.get_data(as_text=True)
    assert response.status_code == 200 and "IZIN-2026-0001" in body
    row = WorkPermit.query.one()
    assert row.status == "Taslak" and WorkPermitControl.query.count() == 6
    assert WorkPermitFile.query.one().sha256_hash

    login(client, outsider)
    assert client.get(f"/is-izinleri/{row.id}").status_code == 404
    login(client, foreign)
    assert client.get(f"/is-izinleri/{row.id}").status_code == 404

    login(client, responsible)
    assert row.permit_no in client.get("/uzerime-atananlar?module=work_permit").get_data(as_text=True)
    control_ids = [str(item.id) for item in row.controls]
    assert client.post(f"/is-izinleri/{row.id}/kontroller", data={"control_id": control_ids}).status_code == 302
    assert all(item.is_confirmed and item.confirmed_by_user_id == responsible.id for item in row.controls)

    login(client, requester)
    assert client.post(f"/is-izinleri/{row.id}/onaya-gonder").status_code == 302
    db.session.refresh(row)
    assert row.status == "Onay Bekliyor"
    assert Notification.query.filter(Notification.source_key.like(f"work-permit:review-%:{row.id}:{approver.id}")).count() == 1

    login(client, approver)
    assert client.post(f"/is-izinleri/{row.id}/degerlendir", data={"decision": "approve", "note": "Saha önlemleri uygun."}).status_code == 302
    db.session.refresh(row)
    assert row.status == "Onaylandı" and row.approved_by_user_id == approver.id

    login(client, responsible)
    assert client.post(f"/is-izinleri/{row.id}/etkinlestir").status_code == 302
    db.session.refresh(row)
    assert row.status == "Aktif" and row.activated_at
    invalid_close = client.post(
        f"/is-izinleri/{row.id}/kapat",
        data={"closure_note": "Geçersiz kanıt", "attachment": (BytesIO(b"x"), "script.exe")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    db.session.refresh(row)
    assert invalid_close.status_code == 200 and row.status == "Aktif"
    assert client.post(f"/is-izinleri/{row.id}/kapat", data={"closure_note": "İş güvenli biçimde tamamlandı."}).status_code == 302
    db.session.refresh(row)
    assert row.status == "Kapatıldı" and row.closed_at

    login(client, approver)
    assert client.post(f"/is-izinleri/{row.id}/arsivle").status_code == 403
    manager = create_user("permit-manager", company=company, permissions=ALL_PERMISSIONS)
    login(client, manager)
    assert client.post(f"/is-izinleri/{row.id}/arsivle").status_code == 302
    db.session.refresh(row)
    assert row.status == "Arşiv" and row.archived_at
    assert AuditLog.query.filter_by(entity_type="WorkPermit").count() >= 1
    assert AuditLog.query.filter_by(entity_type="WorkPermitControl").count() >= 1


def test_work_permit_validation_revision_and_transition_gates(client):
    company = create_company("753")
    requester = create_user("permit-gates-requester", company=company, permissions=("work_permits.view", "work_permits.create", "work_permits.update"))
    responsible = create_user("permit-gates-responsible", company=company, permissions=("work_permits.view", "work_permits.confirm", "work_permits.activate"))
    approver = create_user("permit-gates-approver", company=company, permissions=("work_permits.view", "work_permits.approve"))

    login(client, requester)
    own_approval = client.post("/is-izinleri/yeni", data=payload(responsible, requester), follow_redirects=True)
    assert own_approval.status_code == 200 and WorkPermit.query.count() == 0
    assert client.post("/is-izinleri/yeni", data=payload(responsible, approver)).status_code == 302
    row = WorkPermit.query.one()
    assert client.post(f"/is-izinleri/{row.id}/onaya-gonder").status_code == 409

    login(client, responsible)
    ids = [str(item.id) for item in row.controls]
    client.post(f"/is-izinleri/{row.id}/kontroller", data={"control_id": ids})
    login(client, requester)
    client.post(f"/is-izinleri/{row.id}/onaya-gonder")
    login(client, approver)
    missing_note = client.post(f"/is-izinleri/{row.id}/degerlendir", data={"decision": "revision", "note": ""}, follow_redirects=True)
    assert "gerekçesi zorunludur" in missing_note.get_data(as_text=True)
    client.post(f"/is-izinleri/{row.id}/degerlendir", data={"decision": "revision", "note": "Ek alan kontrolü gerekli."})
    db.session.refresh(row)
    assert row.status == "Revizyon Bekliyor"

    login(client, requester)
    client.post(f"/is-izinleri/{row.id}/duzenle", data=payload(responsible, approver, title="Revize kaynak işi"))
    db.session.refresh(row)
    assert row.status == "Taslak" and not any(item.is_confirmed for item in row.controls)


def test_invalid_file_foreign_user_and_expired_status_filter(client):
    company = create_company("754")
    other = create_company("755")
    manager = create_user("permit-validation-manager", company=company, permissions=ALL_PERMISSIONS)
    responsible = create_user("permit-validation-responsible", company=company, permissions=ALL_PERMISSIONS)
    approver = create_user("permit-validation-approver", company=company, permissions=ALL_PERMISSIONS)
    foreign = create_user("permit-validation-foreign", company=other, permissions=ALL_PERMISSIONS)
    login(client, manager)
    bad = client.post("/is-izinleri/yeni", data=payload(responsible, approver, attachment=(BytesIO(b"x"), "script.exe")), content_type="multipart/form-data", follow_redirects=True)
    assert bad.status_code == 200 and WorkPermit.query.count() == 0
    invalid_user = client.post("/is-izinleri/yeni", data=payload(foreign, approver), follow_redirects=True)
    assert invalid_user.status_code == 200 and WorkPermit.query.count() == 0

    row = WorkPermit(
        company_id=company.id, permit_no="IZIN-2026-0099", permit_type="Kazı", title="Geçmiş kazı",
        location="Saha", description="Deneme", hazards="Göçük", precautions="İksa", ppe_requirements="Baret",
        requester_user_id=manager.id, responsible_user_id=responsible.id, approver_user_id=approver.id,
        requested_start_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=2),
        requested_end_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=1), status="Aktif",
    )
    db.session.add(row)
    db.session.commit()
    response = client.get("/is-izinleri?status=Süresi+Geçti")
    assert row.permit_no in response.get_data(as_text=True)
    login(client, responsible)
    assert client.post(f"/is-izinleri/{row.id}/etkinlestir").status_code == 403


def test_runtime_schema_marks_work_permits_done(app):
    AppSetting.query.filter_by(key="sales_readiness:competitor_work_permits").delete()
    db.session.commit()
    ensure_runtime_schema()
    setting = db.session.get(AppSetting, "sales_readiness:competitor_work_permits")
    assert setting and setting.value == "1"
