from datetime import date, timedelta
from io import BytesIO

from app.extensions import db
from app.models import (
    AppSetting, AuditLog, CalibrationRecord, EquipmentAsset,
    EquipmentAssetFile, EquipmentLifecycleEvent, MaintenanceMachine, Notification,
)
from app.seed import ensure_runtime_schema
from .helpers import create_company, create_user, login


ALL_PERMISSIONS = (
    "equipment.view", "equipment.view_all", "equipment.create", "equipment.manage",
    "equipment.event", "equipment.archive", "equipment.file_download",
)


def payload(**overrides):
    values = {
        "name": "Dijital Kumpas",
        "category": "Ölçüm Cihazı",
        "manufacturer": "Mitutoyo",
        "brand_model": "CD-15",
        "serial_no": "SN-1001",
        "purchase_date": date.today().isoformat(),
        "commissioning_date": date.today().isoformat(),
        "warranty_end_date": (date.today() + timedelta(days=300)).isoformat(),
        "location": "Kalite Laboratuvarı",
        "department": "Kalite",
        "criticality": "Yüksek",
        "status": "Aktif",
        "next_maintenance_date": (date.today() + timedelta(days=10)).isoformat(),
        "next_inspection_date": (date.today() + timedelta(days=20)).isoformat(),
        "notes": "Kontrollü ölçüm cihazı.",
    }
    values.update(overrides)
    return values


def test_equipment_full_lifecycle_links_tasks_archive_and_isolation(app, client):
    company_a = create_company("461")
    company_b = create_company("462")
    manager = create_user("equipment-manager", company=company_a, permissions=ALL_PERMISSIONS)
    custodian = create_user(
        "equipment-custodian",
        company=company_a,
        permissions=("equipment.view", "equipment.event", "equipment.file_download"),
    )
    outsider = create_user("equipment-outsider", company=company_a, permissions=("equipment.view",))
    foreign = create_user("equipment-foreign", company=company_b, permissions=ALL_PERMISSIONS)
    machine = MaintenanceMachine(
        company_id=company_a.id, code="MAK-01", machine_name="Kumpas Bakım Kartı",
        is_active=True, created_by_user_id=manager.id,
    )
    calibration = CalibrationRecord(
        company_id=company_a.id, device_code="KAL-01", device_name="Kumpas Kalibrasyonu",
        is_active=True, created_by_user_id=manager.id,
    )
    db.session.add_all([machine, calibration])
    db.session.commit()

    login(client, manager)
    response = client.post(
        "/ekipman-yasam-dongusu/yeni",
        data=payload(
            custodian_user_id=str(custodian.id),
            maintenance_machine_id=str(machine.id),
            calibration_record_id=str(calibration.id),
            attachment=(BytesIO(b"technical manual"), "kilavuz.pdf"),
        ),
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "EKP-2026-0001" in response.get_data(as_text=True)
    asset = EquipmentAsset.query.one()
    assert asset.maintenance_machine_id == machine.id
    assert asset.calibration_record_id == calibration.id
    assert EquipmentLifecycleEvent.query.filter_by(event_type="Kabul").one()
    assert EquipmentAssetFile.query.one().sha256_hash
    assert Notification.query.filter_by(
        source_key=f"equipment-custodian:{asset.id}:{custodian.id}"
    ).one()

    login(client, outsider)
    assert client.get(f"/ekipman-yasam-dongusu/{asset.id}").status_code == 404
    login(client, foreign)
    assert client.get(f"/ekipman-yasam-dongusu/{asset.id}").status_code == 404

    login(client, custodian)
    task_body = client.get("/uzerime-atananlar?module=equipment").get_data(as_text=True)
    assert asset.asset_code in task_body
    event_response = client.post(
        f"/ekipman-yasam-dongusu/{asset.id}/olay",
        data={
            "event_type": "Transfer",
            "event_date": date.today().isoformat(),
            "description": "Laboratuvardan ölçüm odasına transfer edildi.",
            "new_location": "Ölçüm Odası",
            "new_status": "Kullanım Dışı",
        },
    )
    assert event_response.status_code == 302
    db.session.refresh(asset)
    assert asset.location == "Ölçüm Odası"
    assert asset.status == "Kullanım Dışı"

    login(client, manager)
    assert client.post(f"/ekipman-yasam-dongusu/{asset.id}/arsivle").status_code == 302
    db.session.refresh(asset)
    assert asset.archived_at is not None
    assert EquipmentLifecycleEvent.query.filter_by(event_type="Kullanım Dışı").count() == 1
    assert AuditLog.query.filter_by(entity_type="EquipmentAsset").count() >= 1
    assert AuditLog.query.filter_by(entity_type="EquipmentLifecycleEvent").count() >= 1


def test_equipment_validation_and_company_sequence(client):
    company = create_company("463")
    manager = create_user("equipment-validation", company=company, permissions=ALL_PERMISSIONS)
    login(client, manager)
    for name in ("Kumpas", "Mikrometre"):
        assert client.post(
            "/ekipman-yasam-dongusu/yeni", data=payload(name=name)
        ).status_code == 302
    assert [row.asset_code for row in EquipmentAsset.query.order_by(EquipmentAsset.id).all()] == [
        "EKP-2026-0001", "EKP-2026-0002"
    ]
    bad = client.post(
        "/ekipman-yasam-dongusu/yeni",
        data=payload(name="", attachment=(BytesIO(b"x"), "zararli.exe")),
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert bad.status_code == 200
    assert EquipmentAsset.query.count() == 2


def test_runtime_schema_marks_equipment_lifecycle_done(app):
    AppSetting.query.filter_by(
        key="sales_readiness:competitor_equipment_lifecycle"
    ).delete()
    db.session.commit()
    ensure_runtime_schema()
    setting = db.session.get(AppSetting, "sales_readiness:competitor_equipment_lifecycle")
    assert setting is not None
    assert setting.value == "1"
