from datetime import date, timedelta
from io import BytesIO
from pathlib import Path

import pytest
from werkzeug.datastructures import FileStorage

from app.extensions import db
from app.models import Action, AppSetting, DEPARTMENTS, Document, Suggestion
from app.routes import (
    existing_uploaded_file_path,
    safe_original_filename,
    store_uploaded_file,
    uploaded_file_path,
)
from app.seed import ensure_runtime_schema

from .helpers import create_company, create_user, first_document_category, login, upload_tuple


def action_payload(responsible):
    return {
        "title": "Dosya guvenligi aksiyonu",
        "responsible_user_id": str(responsible.id),
        "related_user_1_id": "",
        "related_user_2_id": "",
        "department": "Kalite" if "Kalite" in DEPARTMENTS else DEPARTMENTS[0],
        "description": "Turkce dosya adi kontrolu",
        "termin_date": (date.today() + timedelta(days=7)).isoformat(),
        "sub_action_indexes": "",
    }


def document_payload(category):
    return {
        "category_id": str(category.id),
        "document_code": "PR.99",
        "title": "Kalite Plani",
        "revision_no": "0",
        "publish_date": date.today().isoformat(),
        "revision_date": "",
        "department": "",
        "description": "Turkce dokuman dosya adi kontrolu",
        "status": "Yayında",
    }


def suggestion_payload():
    return {
        "suggestion_date": date.today().isoformat(),
        "department": "",
        "owner_name": "Öneri Sahibi",
        "definition": "Dosya adı Türkçe karakterle korunmalı.",
    }


def test_safe_original_filename_preserves_turkish_and_strips_path():
    assert (
        safe_original_filename(r"C:\fakepath\şantiye ölçüm kanıtı.pdf")
        == "şantiye ölçüm kanıtı.pdf"
    )
    assert safe_original_filename("../gizli?.pdf") == "gizli.pdf"


def test_uploaded_file_path_rejects_escape_absolute_and_null_paths(app):
    with app.app_context():
        upload_root = Path(app.config["UPLOAD_FOLDER"]).resolve()

        assert uploaded_file_path("../secret.pdf") is None
        assert uploaded_file_path(str(upload_root.parent / "secret.pdf")) is None
        assert uploaded_file_path("company-001/actions/\x00secret.pdf") is None

        safe_path = uploaded_file_path("company-001/actions/files/kanit.pdf")
        assert safe_path is not None
        safe_path.resolve().relative_to(upload_root)


def test_existing_uploaded_file_path_legacy_fallback_stays_inside_upload_root(app):
    with app.app_context():
        upload_root = Path(app.config["UPLOAD_FOLDER"]).resolve()
        legacy_path = upload_root / "legacy.pdf"
        legacy_path.write_bytes(b"legacy")

        assert existing_uploaded_file_path("../legacy.pdf") == legacy_path
        assert uploaded_file_path("../legacy.pdf") is None


def test_store_uploaded_file_rejects_oversized_file_and_removes_temp_file(app):
    app.config["MAX_CONTENT_LENGTH"] = 4

    with app.app_context():
        with pytest.raises(ValueError, match="file_too_large"):
            store_uploaded_file(
                FileStorage(stream=BytesIO(b"12345"), filename="kanıt.pdf"),
                folder="actions/files",
                company_id=42,
            )

    upload_root = Path(app.config["UPLOAD_FOLDER"])
    assert list(upload_root.rglob("*.pdf")) == []


def test_action_upload_preserves_turkish_original_filename(client):
    company = create_company("351")
    responsible = create_user(
        "action-upload-owner",
        company=company,
        permissions=("actions.create",),
    )
    login(client, responsible)

    response = client.post(
        "/actions/new",
        data={
            **action_payload(responsible),
            "action_file": upload_tuple(b"turkish-action", "şantiye ölçüm kanıtı.pdf"),
        },
    )

    assert response.status_code == 302
    action = Action.query.one()
    assert action.file_original_name == "şantiye ölçüm kanıtı.pdf"
    assert action.file_stored_name.startswith(f"company-{company.id:03d}/")
    assert client.get(f"/actions/{action.id}/download").data == b"turkish-action"


def test_document_upload_preserves_turkish_original_filename(client):
    company = create_company("352")
    manager = create_user(
        "document-upload-manager",
        company=company,
        role_key="management_representative",
    )
    category = first_document_category(company)
    login(client, manager)

    response = client.post(
        "/documents/upload",
        data={
            **document_payload(category),
            "document_file": upload_tuple(b"%PDF-1.4\n", "şantiye kalite planı.pdf"),
        },
    )

    assert response.status_code == 302
    document = Document.query.one()
    assert document.original_file_name == "şantiye kalite planı.pdf"
    assert document.file_path.startswith(f"company-{company.id:03d}/")
    assert client.get(f"/documents/{document.id}/download").data == b"%PDF-1.4\n"


def test_suggestion_attachment_preserves_turkish_original_filename(client):
    company = create_company("353")
    user = create_user("suggestion-owner", company=company)
    login(client, user)

    response = client.post(
        "/oneri-sikayet/oneri/yeni",
        data={
            **suggestion_payload(),
            "attachment": upload_tuple(b"suggestion-file", "öneri görseli.png"),
        },
    )

    assert response.status_code == 302
    suggestion = Suggestion.query.one()
    assert suggestion.attachment_original_name == "öneri görseli.png"
    assert suggestion.attachment_stored_name.startswith(f"company-{company.id:03d}/")
    download_response = client.get(f"/oneri-sikayet/oneri/{suggestion.id}/ek/indir")
    assert download_response.status_code == 200
    assert download_response.data == b"suggestion-file"


def test_runtime_schema_marks_sales_readiness_bugfix_done(app):
    AppSetting.query.delete()
    db.session.commit()

    ensure_runtime_schema()

    setting = db.session.get(AppSetting, "sales_readiness:month1_bugfix")
    assert setting is not None
    assert setting.value == "1"
