from datetime import date, timedelta
from io import BytesIO

from app.extensions import db
from app.models import AppSetting, AuditLog, HazardousSubstance, HazardousSubstanceFile, HazardousSubstanceTransaction, Notification
from app.reminders import generate_due_reminders
from app.seed import ensure_runtime_schema
from .helpers import create_company, create_user, login


ALL_PERMISSIONS = (
    "hazardous_substances.view", "hazardous_substances.view_all", "hazardous_substances.create",
    "hazardous_substances.update", "hazardous_substances.approve", "hazardous_substances.stock",
    "hazardous_substances.quarantine", "hazardous_substances.dispose", "hazardous_substances.manage",
    "hazardous_substances.archive", "hazardous_substances.file_download",
)


def payload(responsible, reviewer, **overrides):
    today = date.today()
    values = {
        "name": "Aseton",
        "product_code": "AST-01",
        "manufacturer": "Kimya AŞ",
        "supplier": "Tedarik Kimya",
        "cas_no": "67-64-1",
        "ec_no": "200-662-2",
        "un_no": "UN1090",
        "physical_state": "Sıvı",
        "signal_word": "Tehlike",
        "hazard_classes": ["Alevlenir", "Tahriş edici"],
        "pictogram_codes": ["GHS02", "GHS07"],
        "department": "Üretim",
        "usage_area": "Boya hazırlama",
        "storage_location": "Kimyasal Dolap A",
        "storage_group": "Yanıcı",
        "incompatible_materials": "Oksitleyiciler",
        "precautions": "Ateş ve kıvılcım kaynaklarından uzak tutun.",
        "ppe_requirements": "Kimyasal eldiven ve gözlük.",
        "first_aid": "Temasta bol suyla yıkayın.",
        "spill_response": "Alanı havalandırın ve inert emici kullanın.",
        "initial_quantity": "10",
        "unit": "L",
        "minimum_stock": "2",
        "maximum_stock": "20",
        "expiry_date": (today + timedelta(days=90)).isoformat(),
        "sds_revision_date": today.isoformat(),
        "sds_review_due_date": (today + timedelta(days=365)).isoformat(),
        "responsible_user_id": str(responsible.id),
        "reviewer_user_id": str(reviewer.id),
        "sds_revision_no": "R1",
        "sds_language": "Türkçe",
    }
    values.update(overrides)
    return values


def create_record(client, responsible, reviewer, **overrides):
    data = payload(responsible, reviewer, **overrides)
    data["sds_file"] = (BytesIO(b"%PDF-1.4 test sds"), "gbf.pdf")
    return client.post("/tehlikeli-maddeler/yeni", data=data, content_type="multipart/form-data", follow_redirects=True)


def test_full_hazardous_substance_workflow_stock_files_audit_and_isolation(app, client):
    company = create_company("761")
    other = create_company("762")
    creator = create_user("chemical-creator", company=company, permissions=("hazardous_substances.view", "hazardous_substances.create", "hazardous_substances.file_download"))
    responsible = create_user("chemical-responsible", company=company, permissions=("hazardous_substances.view", "hazardous_substances.update", "hazardous_substances.stock", "hazardous_substances.quarantine", "hazardous_substances.dispose", "hazardous_substances.file_download"))
    reviewer = create_user("chemical-reviewer", company=company, permissions=("hazardous_substances.view", "hazardous_substances.approve", "hazardous_substances.file_download"))
    outsider = create_user("chemical-outsider", company=other, permissions=ALL_PERMISSIONS)

    login(client, creator)
    response = create_record(client, responsible, reviewer)
    assert response.status_code == 200 and "KIM-2026-0001" in response.get_data(as_text=True)
    row = HazardousSubstance.query.one()
    assert row.status == "Taslak" and row.quantity == 10
    assert HazardousSubstanceTransaction.query.one().balance_after == 10
    sds = HazardousSubstanceFile.query.one()
    assert sds.is_current and sds.revision_no == "R1" and sds.sha256_hash

    login(client, outsider)
    assert client.get(f"/tehlikeli-maddeler/{row.id}").status_code == 404
    assert client.get(f"/tehlikeli-maddeler/dosya/{sds.id}").status_code == 404

    login(client, responsible)
    assert row.inventory_no in client.get("/uzerime-atananlar?module=hazardous_substance").get_data(as_text=True)
    assert client.post(f"/tehlikeli-maddeler/{row.id}/onaya-gonder").status_code == 302
    db.session.refresh(row)
    assert row.status == "Onay Bekliyor"

    login(client, reviewer)
    assert client.post(f"/tehlikeli-maddeler/{row.id}/degerlendir", data={"decision": "approve", "note": "SDS ve depolama uygun."}).status_code == 302
    db.session.refresh(row)
    assert row.status == "Aktif" and row.approved_by_user_id == reviewer.id

    login(client, responsible)
    client.post(f"/tehlikeli-maddeler/{row.id}/stok-hareketi", data={"movement_type": "Tüketim", "quantity": "3", "direction": "decrease", "note": "Üretimde kullanıldı."})
    db.session.refresh(row)
    assert row.quantity == 7 and HazardousSubstanceTransaction.query.count() == 2
    client.post(f"/tehlikeli-maddeler/{row.id}/stok-hareketi", data={"movement_type": "Tüketim", "quantity": "99", "note": "Hatalı çıkış"})
    db.session.refresh(row)
    assert row.quantity == 7 and HazardousSubstanceTransaction.query.count() == 2
    client.post(f"/tehlikeli-maddeler/{row.id}/karantinaya-al", data={"note": "Ambalaj hasarı."})
    db.session.refresh(row)
    assert row.status == "Karantina"
    assert client.post(f"/tehlikeli-maddeler/{row.id}/stok-hareketi", data={"movement_type": "Giriş", "quantity": "1", "note": "Engellenmeli"}).status_code == 409
    client.post(f"/tehlikeli-maddeler/{row.id}/bertaraf", data={"note": "Lisanslı firmaya teslim edildi."})
    db.session.refresh(row)
    assert row.status == "Bertaraf" and row.quantity == 0

    manager = create_user("chemical-manager", company=company, permissions=ALL_PERMISSIONS)
    login(client, manager)
    client.post(f"/tehlikeli-maddeler/{row.id}/arsivle")
    db.session.refresh(row)
    assert row.status == "Arşiv"
    assert AuditLog.query.filter_by(entity_type="HazardousSubstance").count() >= 1
    assert AuditLog.query.filter_by(entity_type="HazardousSubstanceTransaction").count() >= 1


def test_sds_required_creator_cannot_review_and_revision_preserves_history(client):
    company = create_company("763")
    creator = create_user("chemical-sds-creator", company=company, permissions=ALL_PERMISSIONS)
    responsible = create_user("chemical-sds-owner", company=company, permissions=ALL_PERMISSIONS)
    reviewer = create_user("chemical-sds-reviewer", company=company, permissions=ALL_PERMISSIONS)
    login(client, creator)
    missing = client.post("/tehlikeli-maddeler/yeni", data=payload(responsible, reviewer), follow_redirects=True)
    assert missing.status_code == 200 and HazardousSubstance.query.count() == 0
    self_review = create_record(client, responsible, creator)
    assert self_review.status_code == 200 and HazardousSubstance.query.count() == 0
    create_record(client, responsible, reviewer)
    row = HazardousSubstance.query.one()
    login(client, responsible)
    client.post(f"/tehlikeli-maddeler/{row.id}/onaya-gonder")
    login(client, reviewer)
    client.post(f"/tehlikeli-maddeler/{row.id}/degerlendir", data={"decision": "approve"})
    db.session.refresh(row)
    assert row.status == "Aktif"

    login(client, responsible)
    next_revision_date = (date.today() + timedelta(days=1)).isoformat()
    next_review_date = (date.today() + timedelta(days=400)).isoformat()
    metadata_only = payload(responsible, reviewer, sds_revision_date=next_revision_date, sds_review_due_date=next_review_date)
    metadata_only.pop("initial_quantity")
    client.post(f"/tehlikeli-maddeler/{row.id}/duzenle", data=metadata_only)
    blocked = client.post(f"/tehlikeli-maddeler/{row.id}/onaya-gonder", follow_redirects=True)
    db.session.refresh(row)
    assert row.status == "Taslak" and "yeni PDF" in blocked.get_data(as_text=True)

    edit_data = payload(responsible, reviewer, signal_word="Dikkat", sds_revision_no="R2", sds_revision_date=next_revision_date, sds_review_due_date=next_review_date)
    edit_data.pop("initial_quantity")
    edit_data["sds_file"] = (BytesIO(b"%PDF-1.4 revision two"), "gbf-r2.pdf")
    response = client.post(f"/tehlikeli-maddeler/{row.id}/duzenle", data=edit_data, content_type="multipart/form-data", follow_redirects=True)
    db.session.refresh(row)
    assert response.status_code == 200 and row.status == "Taslak" and row.approved_at is None
    files = HazardousSubstanceFile.query.order_by(HazardousSubstanceFile.id).all()
    assert len(files) == 2 and not files[0].is_current and files[0].archived_at and files[1].is_current


def test_storage_compatibility_blocks_submission_and_validation(client):
    company = create_company("764")
    creator = create_user("chemical-compat-creator", company=company, permissions=ALL_PERMISSIONS)
    responsible = create_user("chemical-compat-owner", company=company, permissions=ALL_PERMISSIONS)
    reviewer = create_user("chemical-compat-reviewer", company=company, permissions=ALL_PERMISSIONS)
    login(client, creator)
    create_record(client, responsible, reviewer, name="Oksitleyici A", storage_group="Oksitleyici", hazard_classes=["Oksitleyici"], pictogram_codes=["GHS03"])
    first = HazardousSubstance.query.one()
    first.status = "Aktif"
    db.session.commit()
    create_record(client, responsible, reviewer, name="Yanıcı B", cas_no="64-17-5")
    second = HazardousSubstance.query.order_by(HazardousSubstance.id.desc()).first()
    login(client, responsible)
    response = client.post(f"/tehlikeli-maddeler/{second.id}/onaya-gonder", follow_redirects=True)
    db.session.refresh(second)
    assert second.status == "Taslak" and "uyumsuz depolama" in response.get_data(as_text=True).lower()


def test_due_reminders_include_sds_expiry_and_low_stock(app, client):
    company = create_company("765")
    manager = create_user("chemical-reminder-manager", company=company, permissions=ALL_PERMISSIONS)
    reviewer = create_user("chemical-reminder-reviewer", company=company, permissions=ALL_PERMISSIONS)
    manager.email = "chemical@example.com"
    reviewer.email = "reviewer@example.com"
    row = HazardousSubstance(
        company_id=company.id, inventory_no="KIM-2026-0099", name="Süreli Kimyasal", physical_state="Sıvı",
        signal_word="Tehlike", hazard_classes="Alevlenir", pictogram_codes="GHS02", usage_area="Üretim",
        storage_location="Dolap B", storage_group="Yanıcı", precautions="Önlem", ppe_requirements="Eldiven",
        first_aid="Yıka", spill_response="Emici kullan", quantity=1, unit="L", minimum_stock=2,
        expiry_date=date.today() + timedelta(days=5), sds_revision_date=date.today() - timedelta(days=300),
        sds_review_due_date=date.today() + timedelta(days=10), responsible_user_id=manager.id,
        reviewer_user_id=reviewer.id, created_by_user_id=manager.id, status="Aktif",
    )
    db.session.add(row)
    db.session.commit()
    stats = generate_due_reminders(company_id=company.id, run_date=date.today())
    db.session.commit()
    assert stats["notifications"] >= 6
    keys = {item.source_key.split(":", 1)[0] for item in Notification.query.filter_by(company_id=company.id).all()}
    assert {"hazardous-sds", "hazardous-expiry", "hazardous-low-stock"}.issubset(keys)


def test_invalid_file_foreign_link_and_runtime_checklist(client, app):
    company = create_company("766")
    other = create_company("767")
    manager = create_user("chemical-validation", company=company, permissions=ALL_PERMISSIONS)
    reviewer = create_user("chemical-validation-reviewer", company=company, permissions=ALL_PERMISSIONS)
    foreign = create_user("chemical-validation-foreign", company=other, permissions=ALL_PERMISSIONS)
    login(client, manager)
    data = payload(manager, reviewer, responsible_user_id=str(foreign.id))
    data["sds_file"] = (BytesIO(b"x"), "not-pdf.exe")
    response = client.post("/tehlikeli-maddeler/yeni", data=data, content_type="multipart/form-data", follow_redirects=True)
    assert response.status_code == 200 and HazardousSubstance.query.count() == 0
    AppSetting.query.filter_by(key="sales_readiness:competitor_hazardous_substances").delete()
    db.session.commit()
    ensure_runtime_schema()
    setting = db.session.get(AppSetting, "sales_readiness:competitor_hazardous_substances")
    assert setting and setting.value == "1"
