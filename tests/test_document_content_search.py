import importlib.util
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
import sqlalchemy as sa

from app.document_search import extract_text_bounded
from app.extensions import db
from app.models import AuditLog, Document, DocumentSearchIndex

from .helpers import create_company, create_user, first_document_category, login, make_document, stored_upload_path, upload_tuple
from .test_documents_management import document_payload


def _pdf_with_text(value):
    stream = f"BT /F1 12 Tf 72 720 Td ({value}) Tj ET".encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    result = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, body in enumerate(objects, 1):
        offsets.append(len(result))
        result.extend(f"{number} 0 obj\n".encode() + body + b"\nendobj\n")
    xref = len(result)
    result.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        result.extend(f"{offset:010d} 00000 n \n".encode())
    result.extend(f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode())
    return bytes(result)


def _office_file(name, xml):
    stream = BytesIO()
    with ZipFile(stream, "w") as archive:
        archive.writestr(name, xml)
    return stream.getvalue()


@pytest.mark.parametrize(
    "extension,name,xml,needle",
    [
        ("docx", "word/document.xml", '<w:document xmlns:w="urn:w"><w:body><w:p><w:r><w:t>Kontrol listesi örneği</w:t></w:r></w:p></w:body></w:document>', "kontrol listesi"),
        ("xlsx", "xl/worksheets/sheet2.xml", '<worksheet><sheetData><row><c t="inlineStr"><is><t>Malzeme uygunluğu</t></is></c></row></sheetData></worksheet>', "malzeme uygunlugu"),
        ("pptx", "ppt/slides/slide2.xml", '<p:sld xmlns:p="urn:p" xmlns:a="urn:a"><p:sp><a:p><a:r><a:t>Denetim sunumu</a:t></a:r></a:p></p:sp></p:sld>', "denetim sunumu"),
    ],
)
def test_office_text_extraction(tmp_path, extension, name, xml, needle):
    path = tmp_path / f"sample.{extension}"
    path.write_bytes(_office_file(name, xml))
    status, text = extract_text_bounded(path, extension)
    assert status == "ready"
    assert needle in text


def test_document_content_search_tenant_revision_and_backfill(app, client):
    company = create_company("921")
    foreign_company = create_company("922")
    manager = create_user("search-manager", company=company, role_key="management_representative")
    viewer = create_user("search-viewer", company=company, permissions=("documents.view",))
    foreign_viewer = create_user("foreign-search-viewer", company=foreign_company, permissions=("documents.view",))
    category = first_document_category(company)
    login(client, manager)

    upload = client.post("/documents/upload", data={
        **document_payload(category, title="Genel Prosedur", description="Standart kayıt"),
        "document_file": upload_tuple(_pdf_with_text("benzersizkalite belge metni"), "belge.pdf"),
    })
    assert upload.status_code == 302
    document = Document.query.filter_by(company_id=company.id).one()
    assert document.search_index.status == "ready"
    assert "benzersizkalite" in document.search_index.search_text
    assert all(
        "benzersizkalite" not in (entry.old_values or "") + (entry.new_values or "")
        for entry in AuditLog.query.filter_by(entity_type="Document").all()
    )

    login(client, viewer)
    response = client.get("/documents/list?search=benzersizkalite")
    assert response.status_code == 200
    assert "Genel Prosedur" in response.get_data(as_text=True)

    foreign = make_document(app, foreign_company, title="Yabancı Belge", content=_pdf_with_text("benzersizkalite"))
    runner = app.test_cli_runner()
    assert runner.invoke(args=["reindex-documents"]).exit_code == 0
    assert DocumentSearchIndex.query.filter_by(document_id=foreign.id).count() == 0
    result = runner.invoke(args=["reindex-documents", "--apply"])
    assert result.exit_code == 0, result.output
    assert runner.invoke(args=["reindex-documents", "--apply"]).exit_code == 0

    login(client, foreign_viewer)
    foreign_body = client.get("/documents/list?search=benzersizkalite").get_data(as_text=True)
    assert "Yabancı Belge" in foreign_body
    assert "Genel Prosedur" not in foreign_body

    login(client, manager)
    revise = client.post(f"/documents/{document.id}/revise", data={
        "revision_no": "1", "revision_reason": "Yeni sürüm",
        "document_file": upload_tuple(_pdf_with_text("yenicerik"), "yeni.pdf"),
    })
    assert revise.status_code == 302
    db.session.expire_all()
    assert "yenicerik" in Document.query.get(document.id).search_index.search_text
    assert "benzersizkalite" not in Document.query.get(document.id).search_index.search_text
    archive = Document.query.filter(Document.id != document.id, Document.company_id == company.id).one()
    assert "benzersizkalite" in archive.search_index.search_text

    login(client, viewer)
    response = client.get("/documents/list?search=benzersizkalite&status=Arşiv")
    assert response.status_code == 200
    assert "Genel Prosedur" in response.get_data(as_text=True)
    response = client.get("/documents/list?search=yenicerik&status=Arşiv")
    assert "Genel Prosedur" not in response.get_data(as_text=True)


def test_broken_document_does_not_break_upload_or_match_content(app, client):
    company = create_company("923")
    manager = create_user("broken-manager", company=company, role_key="management_representative")
    category = first_document_category(company)
    login(client, manager)
    response = client.post("/documents/upload", data={
        **document_payload(category, title="Bozuk Dosya"),
        "document_file": upload_tuple(b"not a real pdf", "broken.pdf"),
    })
    assert response.status_code == 302
    document = Document.query.one()
    assert document.search_index.status == "error"
    assert document.search_index.search_text == ""


def test_reindex_detects_replaced_and_missing_source(app):
    company = create_company("924")
    document = make_document(app, company, content=_pdf_with_text("eskiicerik"))
    runner = app.test_cli_runner()
    assert runner.invoke(args=["reindex-documents", "--apply"]).exit_code == 0
    assert "eskiicerik" in document.search_index.search_text

    source = stored_upload_path(app, document.file_path)
    source.write_bytes(_pdf_with_text("yeniicerik"))
    assert runner.invoke(args=["reindex-documents", "--apply"]).exit_code == 0
    db.session.expire_all()
    assert "yeniicerik" in document.search_index.search_text
    assert "eskiicerik" not in document.search_index.search_text

    source.unlink()
    assert runner.invoke(args=["reindex-documents", "--apply"]).exit_code == 0
    db.session.expire_all()
    assert document.search_index.status == "missing"
    assert document.search_index.search_text == ""


def test_document_search_migration_round_trip(tmp_path):
    path = Path(__file__).resolve().parents[1] / "migrations/versions/202611040003_document_search_indexes.py"
    spec = importlib.util.spec_from_file_location("document_search_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine("sqlite:///" + (tmp_path / "documents.db").as_posix())
    try:
        with engine.begin() as connection:
            connection.execute(sa.text("CREATE TABLE companies (id INTEGER PRIMARY KEY)"))
            connection.execute(sa.text("CREATE TABLE documents (id INTEGER PRIMARY KEY)"))
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
                migration.upgrade()
                assert "document_search_indexes" in sa.inspect(connection).get_table_names()
                migration.downgrade()
                assert "document_search_indexes" not in sa.inspect(connection).get_table_names()
                migration.upgrade()
                assert "document_search_indexes" in sa.inspect(connection).get_table_names()
    finally:
        engine.dispose()
