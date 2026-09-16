from datetime import date, timedelta
from io import BytesIO

from app.extensions import db
from app.models import (
    AppSetting,
    AuditLog,
    Notification,
    OfficialCorrespondence,
    OfficialCorrespondenceDistribution,
    OfficialCorrespondenceFile,
)
from app.seed import ensure_runtime_schema

from .helpers import create_company, create_user, login


ALL_PERMISSIONS = (
    "ebys.view", "ebys.view_all", "ebys.create", "ebys.manage",
    "ebys.archive", "ebys.file_download", "ebys.confidential",
    "ebys.export",
)


def correspondence_payload(**overrides):
    values = {
        "direction": "incoming",
        "document_date": date.today().isoformat(),
        "external_reference_no": "KURUM-2026/18",
        "subject": "Kalite sistemi resmî yazısı",
        "sender": "Tedarikçi Kurum",
        "recipient": "Örnek Fabrika",
        "department": "Kalite",
        "security_level": "Normal",
        "status": "Kayıtlı",
        "due_date": (date.today() + timedelta(days=5)).isoformat(),
        "notes": "Termin içinde cevaplanacak.",
    }
    values.update(overrides)
    return values


def test_ebys_full_distribution_archive_and_company_isolation(app, client):
    company_a = create_company("451")
    company_b = create_company("452")
    manager = create_user(
        "ebys-manager", company=company_a, permissions=ALL_PERMISSIONS
    )
    recipient = create_user(
        "ebys-recipient",
        company=company_a,
        permissions=("ebys.view", "ebys.file_download"),
    )
    outsider = create_user(
        "ebys-outsider", company=company_a, permissions=("ebys.view",)
    )
    foreign_manager = create_user(
        "ebys-foreign", company=company_b, permissions=ALL_PERMISSIONS
    )

    login(client, manager)
    payload = correspondence_payload(
        assigned_user_ids=str(recipient.id),
        attachment=(BytesIO(b"official correspondence"), "resmi-yazi.pdf"),
    )
    response = client.post(
        "/resmi-yazismalar/yeni",
        data=payload,
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "EBYS-2026-0001" in response.get_data(as_text=True)

    record = OfficialCorrespondence.query.one()
    assert record.company_id == company_a.id
    assert record.status == "Dağıtıldı"
    assert len(record.files) == 1
    assert record.files[0].sha256_hash
    assignment = OfficialCorrespondenceDistribution.query.one()
    assert assignment.user_id == recipient.id
    assert Notification.query.filter_by(
        source_key=f"ebys-distribution:{record.id}:{recipient.id}"
    ).one()
    report = client.get("/resmi-yazismalar/rapor/excel")
    assert report.status_code == 200
    assert report.data.startswith(b"PK")

    login(client, outsider)
    assert client.get(f"/resmi-yazismalar/{record.id}").status_code == 404

    login(client, foreign_manager)
    assert client.get(f"/resmi-yazismalar/{record.id}").status_code == 404
    assert client.get(
        f"/resmi-yazismalar/dosya/{record.files[0].id}"
    ).status_code == 404

    login(client, recipient)
    task_response = client.get("/uzerime-atananlar?module=ebys")
    assert task_response.status_code == 200
    assert record.registration_no in task_response.get_data(as_text=True)
    assert client.post(
        f"/resmi-yazismalar/{record.id}/teslim-al"
    ).status_code == 302
    db.session.refresh(assignment)
    assert assignment.status == "Okundu"
    assert assignment.read_at is not None
    assert client.post(
        f"/resmi-yazismalar/{record.id}/tamamla"
    ).status_code == 302
    db.session.refresh(record)
    assert record.status == "Sonuçlandırıldı"

    login(client, manager)
    assert client.post(
        f"/resmi-yazismalar/{record.id}/arsivle"
    ).status_code == 302
    db.session.refresh(record)
    assert record.archived_at is not None
    assert record.archived_by_user_id == manager.id

    entity_types = {
        row.entity_type
        for row in AuditLog.query.filter(
            AuditLog.entity_type.in_(
                [
                    "OfficialCorrespondence",
                    "OfficialCorrespondenceFile",
                    "OfficialCorrespondenceDistribution",
                ]
            )
        )
    }
    assert "OfficialCorrespondence" in entity_types
    assert "OfficialCorrespondenceDistribution" in entity_types


def test_ebys_confidential_visibility_and_sequential_numbers(client):
    company = create_company("453")
    creator = create_user(
        "ebys-creator", company=company, permissions=ALL_PERMISSIONS
    )
    viewer = create_user(
        "ebys-viewer",
        company=company,
        permissions=("ebys.view", "ebys.view_all"),
    )
    login(client, creator)
    for subject in ("Gizli yönetim yazısı", "Normal yönetim yazısı"):
        payload = correspondence_payload(
            subject=subject,
            security_level="Gizli" if subject.startswith("Gizli") else "Normal",
        )
        assert client.post("/resmi-yazismalar/yeni", data=payload).status_code == 302

    records = OfficialCorrespondence.query.order_by(
        OfficialCorrespondence.id.asc()
    ).all()
    assert [row.registration_no for row in records] == [
        "EBYS-2026-0001", "EBYS-2026-0002"
    ]

    login(client, viewer)
    body = client.get("/resmi-yazismalar").get_data(as_text=True)
    assert "Normal yönetim yazısı" in body
    assert "Gizli yönetim yazısı" not in body
    assert client.get(f"/resmi-yazismalar/{records[0].id}").status_code == 404


def test_ebys_rejects_invalid_file_and_incomplete_archive(client):
    company = create_company("454")
    manager = create_user(
        "ebys-validation", company=company, permissions=ALL_PERMISSIONS
    )
    login(client, manager)
    payload = correspondence_payload(
        attachment=(BytesIO(b"binary"), "zararli.exe")
    )
    response = client.post(
        "/resmi-yazismalar/yeni",
        data=payload,
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "Yalnızca PDF" in response.get_data(as_text=True)
    assert OfficialCorrespondence.query.count() == 0
    assert OfficialCorrespondenceFile.query.count() == 0

    assert client.post(
        "/resmi-yazismalar/yeni", data=correspondence_payload()
    ).status_code == 302
    record = OfficialCorrespondence.query.one()
    response = client.post(
        f"/resmi-yazismalar/{record.id}/arsivle", follow_redirects=True
    )
    assert response.status_code == 200
    assert "Yalnızca sonuçlandırılmış" in response.get_data(as_text=True)
    assert record.archived_at is None


def test_runtime_schema_marks_ebys_sales_readiness_done(app):
    AppSetting.query.filter_by(
        key="sales_readiness:competitor_ebys"
    ).delete()
    db.session.commit()

    ensure_runtime_schema()

    setting = db.session.get(AppSetting, "sales_readiness:competitor_ebys")
    assert setting is not None
    assert setting.value == "1"
