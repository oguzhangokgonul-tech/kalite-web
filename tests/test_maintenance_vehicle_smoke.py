from datetime import date

from app.extensions import db
from app.models import (
    COMPANY_MODULE_KEYS,
    DEPARTMENTS,
    MAINTENANCE_MACHINE_STATUSES,
    MaintenanceFault,
    MaintenanceMachine,
    Vehicle,
    VehicleOperation,
)

from .helpers import create_company, create_user, login


def machine_payload(**overrides):
    data = {
        "code": "MKN-01",
        "machine_name": "Kompresor",
        "brand_model": "Atlas",
        "serial_no": "SN-MKN-01",
        "status": MAINTENANCE_MACHINE_STATUSES[0],
        "location": "Uretim",
        "notes": "",
    }
    data.update(overrides)
    return data


def test_maintenance_machine_fault_and_passive_delete_flow(client):
    company = create_company("361")
    manager = create_user(
        "maintenance-manager",
        company=company,
        permissions=("maintenance.inventory_manage", "maintenance.fault_manage"),
    )
    login(client, manager)

    response = client.post("/bakim/makine/yeni", data=machine_payload())

    assert response.status_code == 302
    machine = MaintenanceMachine.query.filter_by(code="MKN-01").one()

    response = client.post(
        "/bakim/ariza/yeni",
        data={
            "machine_id": str(machine.id),
            "title": "Basinc dusuk",
            "description": "Periyodik kontrol gerekli",
            "responsible_user_id": str(manager.id),
            "reporting_department": "Kalite" if "Kalite" in DEPARTMENTS else DEPARTMENTS[0],
            "reported_date": date.today().isoformat(),
        },
    )

    assert response.status_code == 302
    fault = MaintenanceFault.query.one()
    db.session.refresh(machine)
    assert fault.fault_number == 1
    assert machine.status == "ARIZALI"

    response = client.post(f"/bakim/makine/{machine.id}/sil")

    assert response.status_code == 302
    db.session.refresh(machine)
    assert machine.is_active is False


def test_vehicle_create_operation_delete_flow(client):
    company = create_company("362")
    manager = create_user(
        "vehicle-manager",
        company=company,
        permissions=("vehicles.view", "vehicles.manage"),
    )
    login(client, manager)

    response = client.post(
        "/arac-yonetimi/arac/yeni",
        data={
            "plate": "35 ABC 123",
            "brand": "Ford",
            "model": "Transit",
            "owner": "Sevkiyat",
        },
    )

    assert response.status_code == 302
    vehicle = Vehicle.query.one()
    assert vehicle.plate == "35 ABC 123"

    response = client.post(
        f"/arac-yonetimi/arac/{vehicle.id}/islem-ekle",
        data={
            "operation_date": date.today().isoformat(),
            "description": "Bakim islemi",
            "amount_tl": "1250,50",
        },
    )

    assert response.status_code == 302
    operation = VehicleOperation.query.one()
    assert float(operation.amount_tl) == 1250.50

    assert client.post(f"/arac-yonetimi/islem/{operation.id}/sil").status_code == 302
    assert VehicleOperation.query.count() == 0

    assert client.post(f"/arac-yonetimi/arac/{vehicle.id}/sil").status_code == 302
    assert Vehicle.query.count() == 0


def test_maintenance_and_vehicle_permissions_and_module_blocks(client):
    company = create_company("363")
    viewer = create_user("production-viewer", company=company)
    login(client, viewer)

    assert client.get("/bakim/makine/yeni").status_code == 403
    assert client.get("/arac-yonetimi").status_code == 403

    enabled_modules = set(COMPANY_MODULE_KEYS) - {"maintenance", "vehicles"}
    disabled_company = create_company("364", module_keys=enabled_modules, package_key="custom")
    manager = create_user(
        "disabled-production-manager",
        company=disabled_company,
        permissions=(
            "maintenance.inventory_manage",
            "maintenance.fault_manage",
            "vehicles.view",
            "vehicles.manage",
        ),
    )
    login(client, manager)

    assert client.get("/bakim").status_code == 403
    assert client.get("/arac-yonetimi").status_code == 403
