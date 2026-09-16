from io import BytesIO

from app.extensions import db
from app.models import AppSetting, AuditLog, LessonLearned, LessonLearnedFile, Notification
from app.seed import ensure_runtime_schema
from .helpers import create_company, create_user, login


ALL_PERMISSIONS = ("lessons.view", "lessons.view_all", "lessons.create", "lessons.update", "lessons.review", "lessons.manage", "lessons.archive", "lessons.file_download")


def payload(owner, reviewer, **overrides):
    values = {
        "title": "Kaynak parametresi standardizasyonu",
        "category": "Üretim",
        "department": "Kaynak",
        "owner_user_id": str(owner.id),
        "reviewer_user_id": str(reviewer.id),
        "situation": "Üç vardiyada farklı kaynak parametreleri kullanıldı.",
        "lesson": "Parametre doğrulaması vardiya başlangıcında yapılmalıdır.",
        "recommendation": "Onaylı reçete kontrol listesine bağlanmalıdır.",
        "applicability": "Tüm kaynak hatları",
        "tags": "kaynak, standardizasyon, vardiya",
    }
    values.update(overrides)
    return values


def test_full_review_publish_search_reuse_archive_file_and_isolation(app, client):
    company = create_company("731")
    other = create_company("732")
    manager = create_user("lesson-manager", company=company, permissions=ALL_PERMISSIONS)
    owner = create_user("lesson-owner", company=company, permissions=("lessons.view", "lessons.update", "lessons.file_download"))
    reviewer = create_user("lesson-reviewer", company=company, permissions=("lessons.view", "lessons.review"))
    viewer = create_user("lesson-viewer", company=company, permissions=("lessons.view",))
    foreign = create_user("lesson-foreign", company=other, permissions=ALL_PERMISSIONS)

    login(client, manager)
    response = client.post("/alinan-dersler/yeni", data=payload(owner, reviewer, attachment=(BytesIO(b"lesson evidence"), "kanit.pdf")), content_type="multipart/form-data", follow_redirects=True)
    assert response.status_code == 200
    assert "DERS-2026-0001" in response.get_data(as_text=True)
    row = LessonLearned.query.one()
    assert row.status == "Taslak"
    assert LessonLearnedFile.query.one().sha256_hash

    login(client, viewer)
    assert client.get(f"/alinan-dersler/{row.id}").status_code == 404
    login(client, foreign)
    assert client.get(f"/alinan-dersler/{row.id}").status_code == 404

    login(client, owner)
    assert client.post(f"/alinan-dersler/{row.id}/incelemeye-gonder").status_code == 302
    db.session.refresh(row)
    assert row.status == "İnceleme Bekliyor"
    assert Notification.query.filter(Notification.source_key.like(f"lesson:review-%:{row.id}:{reviewer.id}")).count() == 1
    login(client, reviewer)
    assert row.lesson_no in client.get("/uzerime-atananlar?module=lessons").get_data(as_text=True)
    client.post(f"/alinan-dersler/{row.id}/incele", data={"decision": "return", "review_note": "Uygulama alanını netleştirin."})
    db.session.refresh(row)
    assert row.status == "Revizyon Bekliyor"
    login(client, owner)
    client.post(f"/alinan-dersler/{row.id}/guncelle", data=payload(owner, reviewer, applicability="Tüm robot kaynak hatları"))
    client.post(f"/alinan-dersler/{row.id}/incelemeye-gonder")
    login(client, reviewer)
    client.post(f"/alinan-dersler/{row.id}/incele", data={"decision": "publish", "review_note": "Doğrulandı."})
    db.session.refresh(row)
    assert row.status == "Yayınlandı" and row.published_at and row.published_by_user_id == reviewer.id

    login(client, viewer)
    page = client.get("/alinan-dersler?q=standardizasyon&category=Üretim")
    assert page.status_code == 200 and row.lesson_no in page.get_data(as_text=True)
    client.post(f"/alinan-dersler/{row.id}/yeniden-kullan")
    db.session.refresh(row)
    assert row.reuse_count == 1

    login(client, manager)
    client.post(f"/alinan-dersler/{row.id}/arsivle")
    db.session.refresh(row)
    assert row.status == "Arşiv" and row.archived_at
    assert AuditLog.query.filter_by(entity_type="LessonLearned").count() >= 1


def test_validation_bad_file_and_reviewer_separation(client):
    company = create_company("733")
    manager = create_user("lesson-validation", company=company, permissions=ALL_PERMISSIONS)
    reviewer = create_user("lesson-validation-review", company=company, permissions=ALL_PERMISSIONS)
    login(client, manager)
    assert client.post("/alinan-dersler/yeni", data=payload(manager, manager), follow_redirects=True).status_code == 200
    assert LessonLearned.query.count() == 0
    bad = client.post("/alinan-dersler/yeni", data=payload(manager, reviewer, attachment=(BytesIO(b"x"), "zararli.exe")), content_type="multipart/form-data", follow_redirects=True)
    assert bad.status_code == 200 and LessonLearned.query.count() == 0


def test_runtime_schema_marks_lessons_done(app):
    AppSetting.query.filter_by(key="sales_readiness:competitor_lessons_learned").delete()
    db.session.commit()
    ensure_runtime_schema()
    setting = db.session.get(AppSetting, "sales_readiness:competitor_lessons_learned")
    assert setting and setting.value == "1"
