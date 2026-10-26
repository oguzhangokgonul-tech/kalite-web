"""Request-level QA for the private, company-scoped contract register."""

from io import BytesIO
from base64 import b64decode
import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from PIL import Image
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm.exc import StaleDataError

from app.contract_models import ContractFile, ContractRecord, utc_now
from app.extensions import db
from app.models import AuditLog, CompanyModule

from .helpers import create_company, create_user, login


BASE = "/sozlesmeler"
PDF = b"%PDF-1.4\n1 0 obj <<>> endobj\n%%EOF\n"


def upload(content=PDF, name="signed.pdf"):
    return BytesIO(content), name


def jpeg_upload():
    stream = BytesIO()
    Image.new("RGB", (2, 2), "white").save(stream, format="JPEG")
    stream.seek(0)
    return stream, "scan.jpeg"


def create_contract(client, *, title="Supply agreement", documents=None):
    return client.post(
        f"{BASE}/yeni",
        data={
            "title": title,
            "counterparty": "Acme Ltd",
            "contract_no": "AGR-1",
            "signed_on": "2026-10-01",
            "starts_on": "2026-10-01",
            "ends_on": "2027-10-01",
            "documents": documents if documents is not None else upload(),
        },
        content_type="multipart/form-data",
    )


@pytest.fixture()
def users():
    company = create_company("contracts-a")
    other = create_company("contracts-b")
    manager = create_user("contracts-manager", company=company, permissions=("contracts.manage",))
    viewer = create_user("contracts-viewer", company=company, permissions=("contracts.view",))
    plain = create_user("contracts-plain", company=company)
    other_manager = create_user("contracts-other-manager", company=other, permissions=("contracts.manage",))
    return company, other, manager, viewer, plain, other_manager


def test_permission_and_module_gates(client, users):
    company, _, manager, viewer, plain, _ = users
    assert client.get(BASE).status_code == 302

    login(client, plain)
    assert client.get(BASE).status_code == 403
    assert create_contract(client).status_code == 403

    login(client, viewer)
    assert client.get(BASE).status_code == 200
    assert client.get(f"{BASE}/yeni").status_code == 403
    assert create_contract(client).status_code == 403

    login(client, manager)
    assert client.get(f"{BASE}/yeni").status_code == 200
    module = CompanyModule.query.filter_by(company_id=company.id, module_key="contracts").one()
    module.is_enabled = False
    db.session.commit()
    assert client.get(BASE).status_code == 403
    assert create_contract(client).status_code == 403
    assert ContractRecord.query.count() == 0


@pytest.mark.parametrize("role_key", ["super_admin", "company_admin", "management_representative", "management"])
def test_default_management_roles_can_open_contracts(client, role_key):
    company = create_company("contracts-role")
    user = create_user(f"contracts-{role_key}", company=None if role_key == "super_admin" else company, role_key=role_key)
    login(client, user, company)
    assert client.get(BASE).status_code == 200
    assert client.get(f"{BASE}/yeni").status_code == 200


def test_create_pdf_jpeg_view_download_and_audit(app, client, users):
    company, _, manager, viewer, _, _ = users
    login(client, manager)
    response = create_contract(client, documents=[upload(), jpeg_upload()])
    assert response.status_code == 302

    record = ContractRecord.query.one()
    assert record.company_id == company.id
    assert record.created_by_user_id == manager.id
    assert record.title == "Supply agreement"
    assert len(record.files) == 2
    assert {row.mime_type for row in record.files} == {"application/pdf", "image/jpeg"}
    for row in record.files:
        assert row.company_id == company.id
        assert row.uploaded_by_user_id == manager.id
        assert (Path(app.config["UPLOAD_FOLDER"]) / row.stored_path).is_file()
    assert client.get(BASE).status_code == 200
    assert client.get(f"{BASE}/{record.id}").status_code == 200

    login(client, viewer)
    assert client.get(f"{BASE}/{record.id}").status_code == 200
    for row in record.files:
        expected = PDF if row.mime_type == "application/pdf" else None
        inline = client.get(f"{BASE}/{record.id}/belge/{row.id}")
        downloaded = client.get(f"{BASE}/{record.id}/belge/{row.id}/indir")
        assert inline.status_code == downloaded.status_code == 200
        assert inline.mimetype == downloaded.mimetype == row.mime_type
        assert inline.data == downloaded.data
        if expected is not None:
            assert inline.data == expected
        else:
            assert inline.data.startswith(b"\xff\xd8")
        assert inline.headers["Content-Disposition"].startswith("inline;")
        assert downloaded.headers["Content-Disposition"].startswith("attachment;")
        for served in (inline, downloaded):
            assert {part.strip() for part in served.headers["Cache-Control"].split(",")} == {"private", "no-store"}
            assert served.headers["X-Content-Type-Options"] == "nosniff"
            assert served.headers["Content-Security-Policy"] == "sandbox"

    events = AuditLog.query.filter(AuditLog.entity_type.in_(("ContractRecord", "ContractFile"))).all()
    assert [(event.entity_type, event.action) for event in events].count(("ContractRecord", "created")) == 1
    assert sum(event.action == "viewed" for event in events) == 2
    assert sum(event.action == "downloaded" for event in events) == 2
    assert all(event.company_id == company.id for event in events)
    assert all(event.user_id in (manager.id, viewer.id) for event in events)


@pytest.mark.parametrize("document", [
    lambda: upload(b"not a pdf", "wrong.pdf"),
    lambda: upload(PDF, "wrong.txt"),
    lambda: upload(b"not a jpeg", "wrong.jpg"),
    lambda: upload(b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScL/nwAAAABJRU5ErkJggg=="), "broken.png"),
    lambda: upload(PDF + b"x" * (10 * 1024 * 1024), "oversized.pdf"),
])
def test_invalid_or_oversized_file_does_not_create_record(client, users, document):
    _, _, manager, _, _, _ = users
    login(client, manager)
    response = create_contract(client, documents=document())
    assert response.status_code == 400
    assert ContractRecord.query.count() == 0
    assert ContractFile.query.count() == 0
    assert AuditLog.query.filter_by(entity_type="ContractRecord", action="created").count() == 0


def test_tenant_isolation_on_read_and_mutation(client, users):
    company, other, manager, _, _, other_manager = users
    login(client, manager)
    assert create_contract(client, title="Private agreement").status_code == 302
    record = ContractRecord.query.one()
    file_id = record.files[0].id

    login(client, other_manager)
    assert client.get(BASE).status_code == 200
    assert b"Private agreement" not in client.get(BASE).data
    assert client.get(f"{BASE}/{record.id}").status_code == 404
    assert client.get(f"{BASE}/{record.id}/belge/{file_id}").status_code == 404
    assert client.get(f"{BASE}/{record.id}/belge/{file_id}/indir").status_code == 404
    assert client.post(f"{BASE}/{record.id}/arsivle").status_code == 404
    assert client.post(f"{BASE}/{record.id}/belge", data={"documents": upload()}, content_type="multipart/form-data").status_code == 404
    assert client.post(f"{BASE}/{record.id}/belge/{file_id}/kaldir").status_code == 404
    assert client.post(f"{BASE}/{record.id}/duzenle", data={"title": "Stolen"}).status_code == 404
    db.session.refresh(record)
    assert record.company_id == company.id != other.id
    assert record.archived_at is None
    assert record.files[0].is_active
    assert AuditLog.query.filter_by(entity_type="ContractRecord", company_id=other.id).count() == 0


def test_file_removal_preserves_last_document_and_audit(client, users):
    company, _, manager, viewer, _, _ = users
    login(client, manager)
    assert create_contract(client, documents=[upload(), jpeg_upload()]).status_code == 302
    record = ContractRecord.query.one()
    first, last = record.files
    version_before_removal = record.version_id

    login(client, viewer)
    assert client.get(f"{BASE}/{record.id}/duzenle").status_code == 403
    assert client.post(f"{BASE}/{record.id}/belge", data={"documents": upload()}, content_type="multipart/form-data").status_code == 403
    assert client.post(f"{BASE}/{record.id}/belge/{first.id}/kaldir").status_code == 403
    login(client, manager)
    assert client.post(f"{BASE}/{record.id}/belge/{first.id}/kaldir").status_code == 302
    db.session.refresh(first)
    db.session.refresh(record)
    assert record.version_id > version_before_removal
    assert not first.is_active
    assert last.is_active
    assert client.get(f"{BASE}/{record.id}/belge/{first.id}").status_code == 404
    assert client.get(f"{BASE}/{record.id}/belge/{first.id}/indir").status_code == 404
    assert client.post(f"{BASE}/{record.id}/belge/{last.id}/kaldir").status_code == 409
    assert ContractFile.query.filter_by(record_id=record.id, is_active=True).count() == 1
    event = AuditLog.query.filter_by(entity_type="ContractRecord", action="document_removed").one()
    assert event.entity_id == str(record.id)
    assert event.company_id == company.id
    assert event.user_id == manager.id


def test_upload_changes_record_version_before_archive(client, users):
    _, _, manager, _, _, _ = users
    login(client, manager)
    assert create_contract(client).status_code == 302
    record = ContractRecord.query.one()
    previous_version = record.version_id
    response = client.post(
        f"{BASE}/{record.id}/belge",
        data={"documents": jpeg_upload()},
        content_type="multipart/form-data",
    )
    assert response.status_code == 302
    db.session.refresh(record)
    assert record.version_id > previous_version
    assert ContractFile.query.filter_by(record_id=record.id, is_active=True).count() == 2


def test_concurrent_file_removals_cannot_leave_record_without_document(tmp_path):
    engine = sa.create_engine("sqlite:///" + (tmp_path / "concurrent-contracts.db").as_posix())
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE companies (id INTEGER PRIMARY KEY)"))
        connection.execute(sa.text("CREATE TABLE users (id INTEGER PRIMARY KEY)"))
        connection.execute(sa.text("INSERT INTO companies (id) VALUES (1)"))
        connection.execute(sa.text("INSERT INTO users (id) VALUES (1)"))
    ContractRecord.__table__.create(engine)
    ContractFile.__table__.create(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session() as setup:
        record = ContractRecord(company_id=1, title="Concurrent", counterparty="Firm", created_by_user_id=1)
        setup.add(record)
        setup.flush()
        setup.add_all([
            ContractFile(company_id=1, record_id=record.id, original_name=f"scan-{index}.pdf",
                         stored_path=f"company-001/contracts/{index}.pdf", mime_type="application/pdf",
                         size_bytes=10, uploaded_by_user_id=1)
            for index in (1, 2)
        ])
        setup.commit()
        record_id = record.id
    with Session() as first, Session() as second:
        first_record = first.get(ContractRecord, record_id)
        second_record = second.get(ContractRecord, record_id)
        first_record.files[0].is_active = False
        first_record.updated_at = utc_now()
        second_record.files[1].is_active = False
        second_record.updated_at = utc_now()
        first.commit()
        with pytest.raises(StaleDataError):
            second.commit()
        second.rollback()
    with Session() as check:
        assert sum(file.is_active for file in check.get(ContractRecord, record_id).files) == 1
    engine.dispose()


def test_archive_is_readable_but_immutable(client, users):
    company, _, manager, viewer, _, _ = users
    login(client, manager)
    assert create_contract(client).status_code == 302
    record = ContractRecord.query.one()
    file_id = record.files[0].id

    login(client, viewer)
    assert client.post(f"{BASE}/{record.id}/arsivle").status_code == 403
    login(client, manager)
    assert client.post(f"{BASE}/{record.id}/arsivle").status_code == 302
    db.session.refresh(record)
    assert record.archived_at is not None
    assert b"Supply agreement" not in client.get(BASE).data
    assert b"Supply agreement" in client.get(f"{BASE}?archive=1").data
    assert client.get(f"{BASE}/{record.id}").status_code == 200
    assert client.get(f"{BASE}/{record.id}/belge/{file_id}").status_code == 200
    assert client.get(f"{BASE}/{record.id}/duzenle").status_code == 409
    assert client.post(f"{BASE}/{record.id}/belge", data={"documents": upload()}, content_type="multipart/form-data").status_code == 409
    assert client.post(f"{BASE}/{record.id}/belge/{file_id}/kaldir").status_code == 409
    assert client.post(f"{BASE}/{record.id}/arsivle").status_code == 409
    assert ContractFile.query.filter_by(record_id=record.id).count() == 1
    event = AuditLog.query.filter_by(entity_type="ContractRecord", action="archived").one()
    assert event.entity_id == str(record.id)
    assert event.company_id == company.id
    assert event.user_id == manager.id


def test_contract_migration_upgrade_downgrade_reupgrade(tmp_path):
    path = Path(__file__).resolve().parents[1] / "migrations/versions/202610260002_contract_register.py"
    spec = importlib.util.spec_from_file_location("contract_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine("sqlite:///" + (tmp_path / "contracts.db").as_posix())
    try:
        with engine.begin() as connection:
            connection.execute(sa.text("CREATE TABLE companies (id INTEGER PRIMARY KEY)"))
            connection.execute(sa.text("CREATE TABLE users (id INTEGER PRIMARY KEY)"))
            connection.execute(sa.text("INSERT INTO companies (id) VALUES (1)"))
            connection.execute(sa.text("INSERT INTO users (id) VALUES (1)"))
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
                migration.upgrade()
                inspector = sa.inspect(connection)
                assert {"contract_records", "contract_files"} <= set(inspector.get_table_names())
                assert {"company_id", "ends_on", "version_id"} <= {
                    column["name"] for column in inspector.get_columns("contract_records")
                }
                assert {"company_id", "record_id", "is_active"} <= {
                    column["name"] for column in inspector.get_columns("contract_files")
                }
                assert {"ix_contract_records_company_id", "ix_contract_records_ends_on"} <= {
                    index["name"] for index in inspector.get_indexes("contract_records")
                }
                assert {"ix_contract_files_company_id", "ix_contract_files_record_id"} <= {
                    index["name"] for index in inspector.get_indexes("contract_files")
                }

                connection.execute(sa.text(
                    "INSERT INTO contract_records (id, company_id, title, counterparty, created_by_user_id) "
                    "VALUES (1, 1, 'Signed agreement', 'Acme Ltd', 1)"
                ))
                connection.execute(sa.text(
                    "INSERT INTO contract_files (company_id, record_id, original_name, stored_path, "
                    "mime_type, size_bytes, uploaded_by_user_id) "
                    "VALUES (1, 1, 'signed.pdf', 'company-001/contracts/signed.pdf', 'application/pdf', 10, 1)"
                ))
                with pytest.raises(RuntimeError):
                    migration.downgrade()
                assert "contract_records" in sa.inspect(connection).get_table_names()

                connection.execute(sa.text("DELETE FROM contract_files"))
                connection.execute(sa.text("DELETE FROM contract_records"))
                migration.downgrade()
                assert not {"contract_records", "contract_files"} & set(sa.inspect(connection).get_table_names())
                migration.upgrade()
                assert {"contract_records", "contract_files"} <= set(sa.inspect(connection).get_table_names())
    finally:
        engine.dispose()
