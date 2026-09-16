from datetime import UTC, datetime
from io import BytesIO

from app.extensions import db
from app.models import AppSetting, AuditLog, HelpDeskComment, HelpDeskFile, HelpDeskTicket, Notification
from app.seed import ensure_runtime_schema
from .helpers import create_company, create_user, login


ALL_PERMISSIONS = ("helpdesk.view", "helpdesk.view_all", "helpdesk.create", "helpdesk.assign", "helpdesk.work", "helpdesk.comment", "helpdesk.manage", "helpdesk.archive", "helpdesk.file_download")


def payload(**overrides):
    values = {"title": "Yazıcı bağlantı sorunu", "description": "Kalite ofisindeki ağ yazıcısına erişilemiyor.", "category": "Bilgi Teknolojileri", "department": "Bilgi Teknolojileri", "priority": "Yüksek"}
    values.update(overrides)
    return values


def test_full_assignment_resolution_reopen_close_archive_and_isolation(app, client):
    company = create_company("741")
    other = create_company("742")
    requester = create_user("help-requester", company=company, permissions=("helpdesk.view", "helpdesk.create", "helpdesk.comment", "helpdesk.file_download"))
    assignee = create_user("help-assignee", company=company, permissions=("helpdesk.view", "helpdesk.work", "helpdesk.comment", "helpdesk.file_download"))
    manager = create_user("help-manager", company=company, permissions=ALL_PERMISSIONS)
    outsider = create_user("help-outsider", company=company, permissions=("helpdesk.view",))
    foreign = create_user("help-foreign", company=other, permissions=ALL_PERMISSIONS)

    login(client, requester)
    before = datetime.now(UTC).replace(tzinfo=None)
    response = client.post("/ic-talepler/yeni", data=payload(attachment=(BytesIO(b"screen"), "ekran.png")), content_type="multipart/form-data", follow_redirects=True)
    assert response.status_code == 200 and "TLP-2026-0001" in response.get_data(as_text=True)
    row = HelpDeskTicket.query.one()
    assert row.status == "Yeni" and 7.9 <= (row.sla_due_at - before).total_seconds() / 3600 <= 8.1
    assert HelpDeskFile.query.one().sha256_hash

    login(client, outsider)
    assert client.get(f"/ic-talepler/{row.id}").status_code == 404
    login(client, foreign)
    assert client.get(f"/ic-talepler/{row.id}").status_code == 404

    login(client, manager)
    assert client.post(f"/ic-talepler/{row.id}/ata", data={"assignee_user_id": assignee.id}).status_code == 302
    db.session.refresh(row)
    assert row.status == "Atandı" and row.assignee_user_id == assignee.id
    assert Notification.query.filter(Notification.source_key.like(f"helpdesk:assigned-%:{row.id}:{assignee.id}")).count() == 1

    login(client, assignee)
    assert row.ticket_no in client.get("/uzerime-atananlar?module=helpdesk").get_data(as_text=True)
    client.post(f"/ic-talepler/{row.id}/isleme-al")
    client.post(f"/ic-talepler/{row.id}/yorum", data={"body": "Ağ bağlantısı kontrol ediliyor.", "attachment": (BytesIO(b"log"), "ag-log.txt")}, content_type="multipart/form-data")
    client.post(f"/ic-talepler/{row.id}/cozumle", data={"resolution": "Yazıcı IP kaydı yenilendi."})
    db.session.refresh(row)
    assert row.status == "Çözüm Bekliyor" and HelpDeskComment.query.count() == 1

    login(client, requester)
    client.post(f"/ic-talepler/{row.id}/sonuclandir", data={"decision": "reopen", "note": "Renkli çıktı alınamıyor."})
    db.session.refresh(row)
    assert row.status == "Yeniden Açıldı" and row.reopened_at and HelpDeskComment.query.count() == 2
    login(client, assignee)
    client.post(f"/ic-talepler/{row.id}/isleme-al")
    client.post(f"/ic-talepler/{row.id}/cozumle", data={"resolution": "Renk profili yeniden kuruldu."})
    login(client, requester)
    client.post(f"/ic-talepler/{row.id}/sonuclandir", data={"decision": "accept"})
    db.session.refresh(row)
    assert row.status == "Kapatıldı" and row.closed_at

    login(client, manager)
    client.post(f"/ic-talepler/{row.id}/arsivle")
    db.session.refresh(row)
    assert row.status == "Arşiv" and row.archived_at
    assert AuditLog.query.filter_by(entity_type="HelpDeskTicket").count() >= 1
    assert AuditLog.query.filter_by(entity_type="HelpDeskComment").count() >= 1


def test_validation_foreign_assignment_invalid_file_and_search(client):
    company = create_company("743")
    other = create_company("744")
    manager = create_user("help-validation", company=company, permissions=ALL_PERMISSIONS)
    foreign = create_user("help-validation-foreign", company=other, permissions=ALL_PERMISSIONS)
    login(client, manager)
    bad = client.post("/ic-talepler/yeni", data=payload(attachment=(BytesIO(b"x"), "zararli.exe")), content_type="multipart/form-data", follow_redirects=True)
    assert bad.status_code == 200 and HelpDeskTicket.query.count() == 0
    assert client.post("/ic-talepler/yeni", data=payload()).status_code == 302
    row = HelpDeskTicket.query.one()
    client.post(f"/ic-talepler/{row.id}/ata", data={"assignee_user_id": foreign.id})
    db.session.refresh(row)
    assert row.assignee_user_id is None and row.status == "Yeni"
    assert row.ticket_no in client.get("/ic-talepler?q=Yazıcı&priority=Yüksek").get_data(as_text=True)


def test_runtime_schema_marks_help_desk_done(app):
    AppSetting.query.filter_by(key="sales_readiness:competitor_help_desk").delete()
    db.session.commit()
    ensure_runtime_schema()
    setting = db.session.get(AppSetting, "sales_readiness:competitor_help_desk")
    assert setting and setting.value == "1"
