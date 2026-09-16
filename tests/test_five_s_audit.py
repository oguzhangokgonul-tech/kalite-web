from datetime import date, timedelta
from io import BytesIO

from app.extensions import db
from app.five_s import CATEGORIES
from app.models import AppSetting, AuditLog, FiveSAudit, FiveSAuditFile, FiveSAuditItem, Notification
from app.seed import ensure_runtime_schema
from .helpers import create_company, create_user, login


ALL_PERMISSIONS = ("five_s.view", "five_s.view_all", "five_s.create", "five_s.manage", "five_s.perform", "five_s.review", "five_s.resolve", "five_s.archive", "five_s.file_download")


def create_payload(auditor, reviewer, **overrides):
    values = {"title": "Aylık Üretim 5S", "area": "Kaynak Hattı", "department": "Üretim", "auditor_user_id": str(auditor.id), "reviewer_user_id": str(reviewer.id), "planned_date": date.today().isoformat(), "due_date": (date.today() + timedelta(days=7)).isoformat(), "summary": "Standart aylık kontrol"}
    values.update(overrides); return values


def perform_payload(audit, responsible, low_score=True, intent="submit"):
    values = {"intent": intent}
    for index, item in enumerate(audit.items):
        score = 2 if low_score and index == 0 else 4
        values[f"score_{item.id}"] = str(score)
        values[f"observation_{item.id}"] = "Gereksiz malzeme bulundu." if score < 3 else "Uygun."
        if score < 3:
            values[f"responsible_{item.id}"] = str(responsible.id)
            values[f"due_{item.id}"] = (date.today() + timedelta(days=3)).isoformat()
    return values


def test_five_s_full_workflow_scoring_tasks_review_findings_and_archive(app, client):
    company = create_company("711"); foreign_company = create_company("712")
    manager = create_user("5s-manager", company=company, permissions=ALL_PERMISSIONS)
    auditor = create_user("5s-auditor", company=company, permissions=("five_s.view", "five_s.perform", "five_s.file_download"))
    reviewer = create_user("5s-reviewer", company=company, permissions=("five_s.view", "five_s.review"))
    responsible = create_user("5s-responsible", company=company, permissions=("five_s.view", "five_s.resolve", "five_s.file_download"))
    outsider = create_user("5s-outsider", company=company, permissions=("five_s.view",))
    foreign = create_user("5s-foreign", company=foreign_company, permissions=ALL_PERMISSIONS)
    login(client, manager)
    response = client.post("/5s-denetim/yeni", data=create_payload(auditor, reviewer, attachment=(BytesIO(b"start"), "saha.jpg")), content_type="multipart/form-data", follow_redirects=True)
    assert response.status_code == 200 and "5S-2026-0001" in response.get_data(as_text=True)
    audit = FiveSAudit.query.one()
    assert client.get("/5s-denetim").status_code == 200
    assert len(audit.items) == sum(len(criteria) for _, _, criteria in CATEGORIES) == 15
    assert FiveSAuditFile.query.one().sha256_hash
    assert Notification.query.filter_by(source_key=f"five-s:assigned:{audit.id}:{auditor.id}").one()
    login(client, outsider); assert client.get(f"/5s-denetim/{audit.id}").status_code == 404
    login(client, foreign); assert client.get(f"/5s-denetim/{audit.id}").status_code == 404

    login(client, auditor)
    assert audit.audit_no in client.get("/uzerime-atananlar?module=five_s").get_data(as_text=True)
    assert client.post(f"/5s-denetim/{audit.id}/uygula", data=perform_payload(audit, responsible)).status_code == 302
    db.session.refresh(audit)
    assert audit.status == "review_pending" and audit.score_percent == 77.3
    finding = FiveSAuditItem.query.filter(FiveSAuditItem.score < 3).one()
    assert finding.responsible_user_id == responsible.id and not finding.is_resolved
    assert Notification.query.filter_by(source_key=f"five-s:review:{audit.id}:{reviewer.id}").one()

    login(client, reviewer)
    assert client.post(f"/5s-denetim/{audit.id}/incele", data={"decision": "approve", "review_note": "Puanlar doğrulandı."}).status_code == 302
    db.session.refresh(audit); assert audit.status == "completed"
    login(client, manager)
    client.post(f"/5s-denetim/{audit.id}/arsivle", follow_redirects=True); assert audit.archived_at is None

    login(client, responsible)
    assert audit.audit_no in client.get("/uzerime-atananlar?module=five_s").get_data(as_text=True)
    assert client.post(f"/5s-denetim/bulgu/{finding.id}/kapat", data={"resolution_note": "Alan temizlendi.", "attachment": (BytesIO(b"closed"), "sonra.jpg")}, content_type="multipart/form-data").status_code == 302
    db.session.refresh(finding); assert finding.is_resolved
    login(client, manager); assert client.post(f"/5s-denetim/{audit.id}/arsivle").status_code == 302
    db.session.refresh(audit); assert audit.status == "archived" and audit.archived_at is not None
    assert AuditLog.query.filter_by(entity_type="FiveSAudit").count() >= 1
    assert AuditLog.query.filter_by(entity_type="FiveSAuditItem").count() >= 1


def test_five_s_validation_sequence_and_server_side_score(client):
    company = create_company("713")
    manager = create_user("5s-validation", company=company, permissions=ALL_PERMISSIONS)
    reviewer = create_user("5s-validation-reviewer", company=company, permissions=ALL_PERMISSIONS)
    login(client, manager)
    invalid = client.post("/5s-denetim/yeni", data=create_payload(manager, manager), follow_redirects=True)
    assert invalid.status_code == 200 and FiveSAudit.query.count() == 0
    for title in ("Bir", "İki"):
        assert client.post("/5s-denetim/yeni", data=create_payload(manager, reviewer, title=title)).status_code == 302
    assert [row.audit_no for row in FiveSAudit.query.order_by(FiveSAudit.id)] == ["5S-2026-0001", "5S-2026-0002"]
    audit = FiveSAudit.query.first()
    bad = perform_payload(audit, reviewer, low_score=False); bad[f"score_{audit.items[0].id}"] = "6"
    client.post(f"/5s-denetim/{audit.id}/uygula", data=bad, follow_redirects=True)
    db.session.refresh(audit); assert audit.status == "planned" and audit.score_percent is None


def test_runtime_schema_marks_five_s_done(app):
    AppSetting.query.filter_by(key="sales_readiness:competitor_five_s_audit").delete(); db.session.commit()
    ensure_runtime_schema()
    setting = db.session.get(AppSetting, "sales_readiness:competitor_five_s_audit")
    assert setting and setting.value == "1"
