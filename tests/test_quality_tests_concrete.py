from datetime import date

from app.extensions import db
from app.models import COMPANY_MODULE_KEYS, QualityTestRecord
from app.routes import QUALITY_TEST_CONCRETE_CLASS_OPTIONS, QUALITY_TEST_ELEMENT_OPTIONS

from .helpers import create_company, create_user, login


def concrete_payload(**overrides):
    data = {
        "project_number": "PRJ-2026-001",
        "title": "Bergama Plastik",
        "record_date": date.today().isoformat(),
        "sample_name": QUALITY_TEST_ELEMENT_OPTIONS[0],
        "concrete_class": QUALITY_TEST_CONCRETE_CLASS_OPTIONS[0],
        "air_temperature": "13",
        "description": "Aciklama girilmemis.",
    }
    data.update(overrides)
    return data


def test_concrete_quality_record_measurement_edit_and_clear_flow(client):
    company = create_company("351")
    user = create_user("quality-user", company=company, permissions=("quality.create",))
    login(client, user)

    response = client.post("/kalite-deneyleri/beton-deneyi/yeni", data=concrete_payload())

    assert response.status_code == 302
    record = QualityTestRecord.query.one()
    assert record.number_label.startswith("BET-")
    assert record.project_number == "PRJ-2026-001"
    assert record.current_measurement_day == 2

    response = client.post(
        f"/kalite-deneyleri/beton-deneyi/{record.id}/olcum",
        data={"strength_value": "17,4"},
    )

    assert response.status_code == 302
    db.session.refresh(record)
    assert record.strength_2_day == 17.4
    assert record.current_measurement_day == 7

    response = client.post(
        f"/kalite-deneyleri/beton-deneyi/{record.id}/olcum-duzenle",
        data={
            "strength_2_day": "34",
            "strength_7_day": "",
            "strength_28_day": "45",
        },
    )

    assert response.status_code == 302
    db.session.refresh(record)
    assert record.strength_2_day == 34
    assert record.strength_7_day is None
    assert record.strength_28_day == 45
    assert record.current_measurement_day == 7

    response = client.post(
        f"/kalite-deneyleri/beton-deneyi/{record.id}/olcum-duzenle",
        data={
            "strength_2_day": "34",
            "strength_7_day": "40",
            "strength_28_day": "45",
        },
    )

    assert response.status_code == 302
    db.session.refresh(record)
    assert record.current_measurement_day is None


def test_disabled_quality_test_module_blocks_all_direct_concrete_urls(client):
    enabled_modules = set(COMPANY_MODULE_KEYS) - {
        "quality_tests",
        "quality_test_concrete",
    }
    company = create_company("352", module_keys=enabled_modules, package_key="custom")
    user = create_user("disabled-quality-user", company=company, permissions=("quality.create",))
    record = QualityTestRecord(
        company_id=company.id,
        test_type="beton-deneyi",
        record_number=1,
        title="Kapali modullu deney",
    )
    db.session.add(record)
    db.session.commit()
    login(client, user)

    assert client.get("/kalite-deneyleri/beton-deneyi").status_code == 403
    assert client.get("/kalite-deneyleri/beton-deneyi/yeni").status_code == 403
    assert client.get(
        f"/kalite-deneyleri/beton-deneyi/{record.id}/olcum-duzenle"
    ).status_code == 403
