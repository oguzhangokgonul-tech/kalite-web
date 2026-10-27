"""Payment records stay internal, tenant-scoped, and auditable."""

from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO
from pathlib import Path

import pytest

from app.extensions import db
from app.models import AuditLog, CompanyModule, Notification
from app.notification_policy import POLICY_DEFAULTS
from app.payment_models import PaymentAttachment, PaymentInstallment, PaymentRecord, PaymentTransaction
from app.reminders import generate_due_reminders
from tests.helpers import create_company, create_user, login


BASE = "/odemeler"


@pytest.fixture()
def actors(client):
    company = create_company("PAY-A")
    other = create_company("PAY-B")
    manager = create_user("pay-manager", company=company, role_key="management_representative")
    viewer = create_user("pay-viewer", company=company, permissions=("payments.view",))
    staff = create_user("pay-staff", company=company, role_key="department_staff")
    foreign = create_user("pay-foreign", company=other, role_key="management_representative")
    return company, other, manager, viewer, staff, foreign


def data(**overrides):
    result = {
        "counterparty": "Örnek Müşteri",
        "description": "Proje hakedişi",
        "reference_no": "F-001",
        "project_no": "P-42",
        "amount": "1250.50",
        "currency": "TRY",
        "due_date": (date.today() + timedelta(days=1)).isoformat(),
        "note": "İç takip",
    }
    result.update(overrides)
    return result


def make(client, company, manager, direction="receivable", **changes):
    login(client, manager, company)
    response = client.post(f"{BASE}/{direction}/yeni", data=data(**changes))
    assert response.status_code == 302, response.get_data(as_text=True)
    record = PaymentRecord.query.order_by(PaymentRecord.id.desc()).first()
    assert response.headers["Location"].endswith(f"{BASE}/{direction}/{record.id}")
    return record


def test_menu_permissions_and_directional_pages(client, actors):
    company, _, manager, viewer, staff, _ = actors
    login(client, manager, company)
    for direction, label in (("receivable", "Alınacak Ödemeler"), ("payable", "Yapılacak Ödemeler")):
        response = client.get(f"{BASE}/{direction}")
        assert response.status_code == 200
        assert label in response.get_data(as_text=True)
        assert client.get(f"{BASE}/{direction}/yeni").status_code == 200
    login(client, viewer, company)
    assert client.get(f"{BASE}/receivable").status_code == 200
    assert client.get(f"{BASE}/receivable/yeni").status_code == 403
    login(client, staff, company)
    assert client.get(f"{BASE}/receivable").status_code == 403
    assert "Ödemeler" not in client.get("/dashboard").get_data(as_text=True)


def test_create_partial_close_correction_and_audit(client, actors):
    company, _, manager, _, _, _ = actors
    record = make(client, company, manager)
    assert (record.company_id, record.status, record.amount, record.remaining_amount) == (
        company.id, "open", Decimal("1250.50"), Decimal("1250.50"))
    response = client.post(f"{BASE}/receivable/{record.id}/gerceklesen", data={
        "version_id": str(record.version_id), "settled_amount": "250.50", "settled_on": date.today().isoformat()})
    assert response.status_code == 302
    db.session.refresh(record)
    assert (record.status, record.remaining_amount) == ("open", Decimal("1000.00"))
    response = client.post(f"{BASE}/receivable/{record.id}/gerceklesen", data={
        "version_id": str(record.version_id), "settled_amount": "200", "settled_on": date.today().isoformat()})
    assert response.status_code == 302
    db.session.refresh(record)
    assert record.settled_amount == Decimal("250.50")
    response = client.post(f"{BASE}/receivable/{record.id}/gerceklesen", data={
        "version_id": str(record.version_id), "settled_amount": "1250.50", "settled_on": date.today().isoformat()})
    assert response.status_code == 302
    db.session.refresh(record)
    assert (record.status, record.remaining_amount) == ("closed", Decimal("0"))
    assert AuditLog.query.filter_by(entity_type="PaymentRecord", entity_id=str(record.id)).count() >= 3


def test_pdf_upload_download_and_company_isolation(client, app, actors):
    company, other, manager, viewer, staff, foreign = actors
    record = make(client, company, manager, direction="payable")
    response = client.post(f"{BASE}/payable/{record.id}/belge", data={
        "pdf": (BytesIO(b"%PDF-1.4\ninternal evidence"), "fatura.pdf")},
        content_type="multipart/form-data")
    assert response.status_code == 302
    attachment = PaymentAttachment.query.filter_by(record_id=record.id).one()
    assert attachment.company_id == company.id
    login(client, viewer, company)
    response = client.get(f"{BASE}/payable/{record.id}/belge/{attachment.id}")
    assert response.status_code == 200
    assert response.headers["Content-Disposition"].startswith("attachment")
    assert {part.strip() for part in response.headers["Cache-Control"].split(",")} == {"private", "no-store"}
    assert client.post(f"{BASE}/payable/{record.id}/belge/{attachment.id}/kaldir").status_code == 403
    login(client, staff, company)
    assert client.get(f"{BASE}/payable/{record.id}/belge/{attachment.id}").status_code == 403
    login(client, foreign, other)
    assert client.get(f"{BASE}/payable/{record.id}").status_code == 404
    assert client.get(f"{BASE}/payable/{record.id}/belge/{attachment.id}").status_code == 404
    login(client, manager, company)
    response = client.post(f"{BASE}/payable/{record.id}/belge/{attachment.id}/kaldir")
    assert response.status_code == 302
    assert client.get(f"{BASE}/payable/{record.id}/belge/{attachment.id}").status_code == 404
    db.session.refresh(attachment)
    assert attachment.is_active is False


def test_payment_document_rejects_foreign_company_storage_path(client, app, actors):
    company, other, manager, _, _, _ = actors
    record = make(client, company, manager)
    response = client.post(f"{BASE}/receivable/{record.id}/belge", data={
        "pdf": (BytesIO(b"%PDF-1.4\nlocal evidence"), "fatura.pdf")},
        content_type="multipart/form-data")
    assert response.status_code == 302
    attachment = PaymentAttachment.query.filter_by(record_id=record.id).one()

    foreign_path = Path(app.config["UPLOAD_FOLDER"]) / (
        f"company-{other.id:03d}/payments/foreign.pdf"
    )
    foreign_path.parent.mkdir(parents=True, exist_ok=True)
    foreign_path.write_bytes(b"%PDF-1.4\nforeign evidence")
    attachment.stored_path = foreign_path.relative_to(app.config["UPLOAD_FOLDER"]).as_posix()
    db.session.commit()

    response = client.get(f"{BASE}/receivable/{record.id}/belge/{attachment.id}")
    assert response.status_code == 404
    assert b"foreign evidence" not in response.data
    assert AuditLog.query.filter_by(
        entity_type="PaymentAttachment", entity_id=str(attachment.id), action="downloaded"
    ).count() == 0

    unrelated_path = Path(app.config["UPLOAD_FOLDER"]) / (
        f"company-{company.id:03d}/contracts/unrelated.pdf"
    )
    unrelated_path.parent.mkdir(parents=True, exist_ok=True)
    unrelated_path.write_bytes(b"%PDF-1.4\nunrelated evidence")
    attachment.stored_path = unrelated_path.relative_to(app.config["UPLOAD_FOLDER"]).as_posix()
    db.session.commit()
    assert client.get(f"{BASE}/receivable/{record.id}/belge/{attachment.id}").status_code == 404


@pytest.mark.parametrize("direction", ("receivable", "payable"))
def test_payment_mutations_require_manager_and_matching_company(client, actors, direction):
    company, other, manager, viewer, _, foreign = actors
    record = make(client, company, manager, direction=direction)
    installment_id = record.installments[0].id
    urls = (
        f"{BASE}/{direction}/{record.id}/duzenle",
        f"{BASE}/{direction}/{record.id}/gerceklesen",
        f"{BASE}/{direction}/{record.id}/iptal",
        f"{BASE}/{direction}/{record.id}/arsivle",
        f"{BASE}/{direction}/{record.id}/belge",
        f"{BASE}/{direction}/{record.id}/taksit/{installment_id}/islem",
        f"{BASE}/{direction}/{record.id}/islem/999/geri-al",
        f"{BASE}/{direction}/{record.id}/belge/999/kaldir",
    )

    for user, user_company, expected in (
        (viewer, company, 403),
        (foreign, other, 404),
    ):
        login(client, user, user_company)
        detail = client.get(f"{BASE}/{direction}/{record.id}")
        assert detail.status_code == (200 if user is viewer else 404)
        for url in urls:
            assert client.post(url, data={"version_id": str(record.version_id)}).status_code == expected, url

    db.session.refresh(record)
    assert record.status == "open"
    assert record.settled_amount == Decimal("0")
    assert PaymentAttachment.query.filter_by(record_id=record.id).count() == 0


def test_invalid_pdf_and_missing_tenant_do_not_create_records(client, actors):
    company, _, manager, _, _, _ = actors
    login(client, manager, company)
    response = client.post(f"{BASE}/receivable/yeni", data={
        **data(), "pdf": (BytesIO(b"not-a-pdf"), "wrong.pdf")},
        content_type="multipart/form-data")
    assert response.status_code == 400
    assert PaymentRecord.query.count() == 0
    assert client.get(f"{BASE}/receivable").status_code == 200


def test_payable_cancel_archive_and_module_disable(client, actors):
    company, _, manager, _, _, _ = actors
    record = make(client, company, manager, direction="payable")
    response = client.post(f"{BASE}/payable/{record.id}/iptal", data={
        "version_id": str(record.version_id), "reason": "Duplicate entry"})
    assert response.status_code == 302
    db.session.refresh(record)
    assert record.status == "cancelled"
    assert client.post(f"{BASE}/payable/{record.id}/gerceklesen", data={
        "version_id": str(record.version_id), "settled_amount": "100",
        "settled_on": date.today().isoformat()}).status_code == 409
    assert client.post(f"{BASE}/payable/{record.id}/arsivle", data={
        "version_id": str(record.version_id)}).status_code == 302
    db.session.refresh(record)
    assert record.archived_at is not None
    assert client.get(f"{BASE}/payable/{record.id}").status_code == 200
    module = CompanyModule.query.filter_by(company_id=company.id, module_key="payment_tracking").one()
    module.is_enabled = False
    db.session.commit()
    assert client.get(f"{BASE}/payable").status_code == 403
    assert client.get(f"{BASE}/payable/{record.id}").status_code == 403


def test_edit_and_stale_version_reject_cross_tenant_responsible(client, actors):
    company, other, manager, _, _, foreign = actors
    record = make(client, company, manager)
    response = client.post(f"{BASE}/receivable/{record.id}/duzenle", data={
        **data(counterparty="Güncel Müşteri", responsible_user_id=str(foreign.id)),
        "version_id": str(record.version_id)})
    assert response.status_code == 400
    db.session.refresh(record)
    assert record.counterparty == "Örnek Müşteri"
    version = record.version_id
    response = client.post(f"{BASE}/receivable/{record.id}/duzenle", data={
        **data(counterparty="Güncel Müşteri", responsible_user_id=str(manager.id)),
        "version_id": str(version)})
    assert response.status_code == 302
    db.session.refresh(record)
    assert (record.counterparty, record.responsible_user_id) == ("Güncel Müşteri", manager.id)
    assert client.post(f"{BASE}/receivable/{record.id}/duzenle", data={
        **data(), "version_id": str(version)}).status_code == 409


def test_due_reminders_are_internal_deduplicated_and_stop_on_close(client, actors):
    company, _, manager, _, _, _ = actors
    record = make(client, company, manager, due_date=date.today().isoformat(),
                  responsible_user_id=str(manager.id))
    assert POLICY_DEFAULTS["payment-receivable"]["email"] is False
    first = generate_due_reminders(company.id, run_date=date.today(), kinds={"payment-receivable"})
    db.session.commit()
    assert first["notifications"] == 1
    second = generate_due_reminders(company.id, run_date=date.today(), kinds={"payment-receivable"})
    assert second["notifications"] == 0
    notices = Notification.query.filter_by(company_id=company.id, user_id=manager.id).filter(
        Notification.source_key.like(f"payment-receivable:{record.id}:%")
    ).all()
    assert len(notices) == 1
    login(client, manager, company)
    client.post(f"{BASE}/receivable/{record.id}/gerceklesen", data={
        "version_id": str(record.version_id), "settled_amount": "1250.50",
        "settled_on": date.today().isoformat()})
    db.session.refresh(record)
    assert record.status == "closed"
    after_close = generate_due_reminders(company.id, run_date=date.today() + timedelta(days=1),
                                         kinds={"payment-receivable"})
    assert after_close["notifications"] == 0


@pytest.mark.parametrize("direction", ["receivable", "payable"])
def test_installment_partial_movements_only_close_when_every_installment_is_paid(client, actors, direction):
    company, _, manager, _, _, _ = actors
    due_dates = [(date.today() + timedelta(days=days)).isoformat() for days in (1, 30, 60)]
    record = make(client, company, manager, direction=direction,
                  amount="1200", payment_method="check", installment_count="3",
                  installment_due_date=due_dates,
                  installment_amount=["400", "300", "500"])
    assert record.payment_method == "check"
    assert [(item.amount, item.due_date) for item in record.installments] == [
        (Decimal("400"), date.fromisoformat(due_dates[0])),
        (Decimal("300"), date.fromisoformat(due_dates[1])),
        (Decimal("500"), date.fromisoformat(due_dates[2])),
    ]
    for index, amount in ((0, "150"), (0, "250"), (1, "300"), (2, "500")):
        db.session.refresh(record)
        item = record.installments[index]
        response = client.post(f"{BASE}/{direction}/{record.id}/taksit/{item.id}/islem", data={
            "version_id": str(record.version_id), "amount": amount,
            "occurred_on": date.today().isoformat(), "instrument_no": "CHK-1"})
        assert response.status_code == 302
        db.session.refresh(record)
        assert record.status == ("closed" if index == 2 else "open")
    assert record.settled_amount == Decimal("1200")
    assert PaymentTransaction.query.filter_by(record_id=record.id).count() == 4
    assert record.installments[0].settled_amount == Decimal("400")


def test_installment_overpayment_reversal_and_tenant_boundary(client, actors):
    company, other, manager, viewer, _, foreign = actors
    record = make(client, company, manager, amount="100", payment_method="promissory_note",
                  installment_count="2",
                  installment_due_date=[date.today().isoformat(),
                                        (date.today() + timedelta(days=30)).isoformat()],
                  installment_amount=["40", "60"])
    item = record.installments[0]
    url = f"{BASE}/receivable/{record.id}/taksit/{item.id}/islem"
    response = client.post(url, data={"version_id": str(record.version_id),
                                      "amount": "41", "occurred_on": date.today().isoformat()})
    assert response.status_code == 400
    db.session.refresh(record)
    assert record.settled_amount == 0
    login(client, viewer, company)
    assert client.post(url, data={}).status_code == 403
    login(client, foreign, other)
    assert client.get(url).status_code == 404
    login(client, manager, company)
    assert client.post(url, data={"version_id": str(record.version_id),
                                  "amount": "40", "occurred_on": date.today().isoformat()}).status_code == 302
    db.session.refresh(record)
    assert record.status == "open"
    movement = PaymentTransaction.query.filter_by(record_id=record.id, amount=Decimal("40")).one()
    reversal = f"{BASE}/receivable/{record.id}/islem/{movement.id}/geri-al"
    assert client.post(reversal, data={"version_id": str(record.version_id), "reason": "Test düzeltmesi"}).status_code == 302
    db.session.refresh(record)
    assert record.settled_amount == 0
    assert record.installments[0].settled_amount == 0
    assert client.post(reversal, data={"version_id": str(record.version_id), "reason": "Tekrar"}).status_code == 409


def test_installment_total_must_match_and_plan_locks_after_payment(client, actors):
    company, _, manager, _, _, _ = actors
    login(client, manager, company)
    invalid = client.post(f"{BASE}/payable/yeni", data=data(
        amount="100", installment_count="2",
        installment_due_date=[date.today().isoformat(), (date.today() + timedelta(days=2)).isoformat()],
        installment_amount=["50", "40"]))
    assert invalid.status_code == 400
    assert PaymentRecord.query.count() == 0
    record = make(client, company, manager, direction="payable")
    item = record.installments[0]
    assert client.post(f"{BASE}/payable/{record.id}/taksit/{item.id}/islem", data={
        "version_id": str(record.version_id), "amount": "100",
        "occurred_on": date.today().isoformat()}).status_code == 302
    db.session.refresh(record)
    response = client.post(f"{BASE}/payable/{record.id}/duzenle", data={
        **data(amount="1300", payment_method="cash"), "version_id": str(record.version_id)})
    assert response.status_code == 400
    db.session.refresh(record)
    assert (record.amount, record.payment_method) == (Decimal("1250.50"), "unspecified")


def test_reversal_restores_last_valid_payment_date(client, actors):
    company, _, manager, _, _, _ = actors
    record = make(client, company, manager, amount="100")
    item = record.installments[0]
    url = f"{BASE}/receivable/{record.id}/taksit/{item.id}/islem"
    first_day = date.today() - timedelta(days=3)
    second_day = date.today() - timedelta(days=1)
    for amount, day in (("40", first_day), ("60", second_day)):
        assert client.post(url, data={"version_id": str(record.version_id),
                                      "amount": amount, "occurred_on": day.isoformat()}).status_code == 302
        db.session.refresh(record)
    assert record.status == "closed" and record.settled_on == second_day
    movement = PaymentTransaction.query.filter_by(record_id=record.id, amount=Decimal("60")).one()
    assert client.post(f"{BASE}/receivable/{record.id}/islem/{movement.id}/geri-al", data={
        "version_id": str(record.version_id), "reason": "Yanlış işlem"}).status_code == 302
    db.session.refresh(record)
    assert (record.status, record.settled_on, record.settled_amount) == (
        "open", first_day, Decimal("40"))


def test_plan_edit_advances_version_and_dismisses_old_due_reminders(client, actors):
    company, _, manager, _, _, _ = actors
    old_due = date.today() + timedelta(days=1)
    new_due = date.today() + timedelta(days=4)
    record = make(client, company, manager, amount="100", responsible_user_id=str(manager.id),
                  installment_count="2", installment_due_date=[old_due.isoformat(), old_due.isoformat()],
                  installment_amount=["40", "60"])
    original_ids = [item.id for item in record.installments]
    original_version = record.version_id
    generate_due_reminders(company.id, run_date=date.today(), kinds={"payment-receivable"})
    db.session.commit()
    notices = Notification.query.filter(Notification.source_key.like("payment-receivable:%")).all()
    assert len(notices) == 2
    login(client, manager, company)
    edit_data = data(amount="100", responsible_user_id=str(manager.id), installment_count="2",
                     installment_due_date=[new_due.isoformat(), new_due.isoformat()],
                     installment_amount=["40", "60"], version_id=str(original_version))
    assert client.post(f"{BASE}/receivable/{record.id}/duzenle", data=edit_data).status_code == 302
    db.session.refresh(record)
    assert record.version_id > original_version
    assert [item.id for item in record.installments] == original_ids
    assert all(notice.is_read for notice in notices)
    assert client.post(f"{BASE}/receivable/{record.id}/duzenle", data=edit_data).status_code == 409
    edit_data.update(version_id=str(record.version_id),
                     installment_due_date=[old_due.isoformat(), old_due.isoformat()])
    assert client.post(f"{BASE}/receivable/{record.id}/duzenle", data=edit_data).status_code == 302
    db.session.expire_all()
    assert all(notice.is_read is False for notice in Notification.query.filter(
        Notification.source_key.like("payment-receivable:%")).all())
    record = db.session.get(PaymentRecord, record.id)
    edit_data.update(version_id=str(record.version_id),
                     installment_due_date=[new_due.isoformat(), new_due.isoformat()])
    assert client.post(f"{BASE}/receivable/{record.id}/duzenle", data=edit_data).status_code == 302
    generate_due_reminders(company.id, run_date=date.today(), kinds={"payment-receivable"})
    db.session.commit()
    db.session.refresh(record)
    first_installment = record.installments[0]
    assert client.post(f"{BASE}/receivable/{record.id}/taksit/{first_installment.id}/islem", data={
        "version_id": str(record.version_id), "amount": "40",
        "occurred_on": date.today().isoformat()}).status_code == 302
    db.session.refresh(record)
    movement = PaymentTransaction.query.filter_by(installment_id=first_installment.id).one()
    assert client.post(f"{BASE}/receivable/{record.id}/islem/{movement.id}/geri-al", data={
        "version_id": str(record.version_id), "reason": "Düzeltme"}).status_code == 302
    old_notice = Notification.query.filter(Notification.source_key.like(
        f"payment-receivable:{first_installment.id}:{old_due}:%")).one()
    current_notice = Notification.query.filter(Notification.source_key.like(
        f"payment-receivable:{first_installment.id}:{new_due}:%")).one()
    assert old_notice.is_read and not current_notice.is_read


def test_total_correction_uses_remaining_payment_date(client, actors):
    company, _, manager, _, _, _ = actors
    record = make(client, company, manager, amount="100")
    first_day = date.today() - timedelta(days=3)
    second_day = date.today() - timedelta(days=1)
    for total, day in (("40", first_day), ("100", second_day)):
        assert client.post(f"{BASE}/receivable/{record.id}/gerceklesen", data={
            "version_id": str(record.version_id), "settled_amount": total,
            "settled_on": day.isoformat()}).status_code == 302
        db.session.refresh(record)
    assert client.post(f"{BASE}/receivable/{record.id}/gerceklesen", data={
        "version_id": str(record.version_id), "settled_amount": "40",
        "settled_on": date.today().isoformat(), "reason": "Son işlem hatalı"}).status_code == 302
    db.session.refresh(record)
    assert (record.settled_amount, record.settled_on) == (Decimal("40"), first_day)
    assert client.post(f"{BASE}/receivable/{record.id}/gerceklesen", data={
        "version_id": str(record.version_id), "settled_amount": "0",
        "reason": "İlk işlem de hatalı"}).status_code == 302
    db.session.refresh(record)
    third_day = date.today()
    assert client.post(f"{BASE}/receivable/{record.id}/gerceklesen", data={
        "version_id": str(record.version_id), "settled_amount": "30",
        "settled_on": third_day.isoformat()}).status_code == 302
    db.session.refresh(record)
    assert (record.settled_amount, record.settled_on) == (Decimal("30"), third_day)


def test_reminders_track_each_unpaid_installment_even_with_same_due_date(client, actors):
    company, _, manager, _, _, _ = actors
    record = make(client, company, manager, amount="100", payment_method="cash",
                  responsible_user_id=str(manager.id), installment_count="2",
                  installment_due_date=[date.today().isoformat(), date.today().isoformat()],
                  installment_amount=["40", "60"])
    first = generate_due_reminders(company.id, run_date=date.today(), kinds={"payment-receivable"})
    db.session.commit()
    assert first["notifications"] == 2
    source_keys = {notice.source_key for notice in Notification.query.filter_by(
        company_id=company.id, user_id=manager.id).all() if notice.source_key.startswith("payment-receivable:")}
    assert len(source_keys) == 2
    item = record.installments[0]
    login(client, manager, company)
    assert client.post(f"{BASE}/receivable/{record.id}/taksit/{item.id}/islem", data={
        "version_id": str(record.version_id), "amount": "40",
        "occurred_on": date.today().isoformat()}).status_code == 302
    db.session.refresh(record)
    first_notice = Notification.query.filter(Notification.source_key.like(
        f"payment-receivable:{item.id}:%")).one()
    assert first_notice.is_read
    next_run = generate_due_reminders(company.id, run_date=date.today() + timedelta(days=1),
                                      kinds={"payment-receivable"}, persist_notifications=False)
    assert len(next_run["_collection"]["items"]) == 1
    movement = PaymentTransaction.query.filter_by(installment_id=item.id, amount=Decimal("40")).one()
    assert client.post(f"{BASE}/receivable/{record.id}/islem/{movement.id}/geri-al", data={
        "version_id": str(record.version_id), "reason": "Düzeltme"}).status_code == 302
    db.session.refresh(first_notice)
    assert not first_notice.is_read
