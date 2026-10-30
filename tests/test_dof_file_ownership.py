from app.extensions import db
from app.models import AuditLog, Dof, DofFile

from .helpers import create_company, create_user, login, write_stored_upload
from .test_dof_management import make_dof


def opening_file(dof, stored_name):
    file_record = DofFile(
        company_id=dof.company_id,
        dof_id=dof.id,
        original_name="finding.jpg",
        stored_name=stored_name,
        file_type="opening",
    )
    db.session.add(file_record)
    db.session.commit()
    return file_record


def test_dof_opening_download_rejects_foreign_company_path(app, client):
    company_a = create_company("851")
    company_b = create_company("852")
    manager = create_user("dof-owner-manager", company=company_a, role_key="management_representative")
    dof = make_dof(company_a, manager)
    stored_name = f"company-{company_b.id:03d}/dof/opening/dof-opening-{'a' * 32}.jpg"
    write_stored_upload(app, stored_name, b"foreign-company-file")
    file_record = opening_file(dof, stored_name)

    login(client, manager)
    response = client.get(f"/dofs/{dof.id}/files/{file_record.id}/download")

    assert response.status_code == 404
    assert AuditLog.query.filter_by(entity_type="DofFile", action="downloaded").count() == 0


def test_dof_opening_download_rejects_other_record_metadata(app, client):
    company = create_company("853")
    manager = create_user("dof-record-manager", company=company, role_key="management_representative")
    dof_a = make_dof(company, manager, dof_no="IF-2026-0853")
    dof_b = make_dof(company, manager, dof_no="IF-2026-0854")
    stored_name = f"company-{company.id:03d}/dof/opening/dof-opening-{'b' * 32}.jpg"
    write_stored_upload(app, stored_name, b"other-record-file")
    opening_file(dof_b, stored_name)
    wrong_file = opening_file(dof_a, stored_name)

    login(client, manager)
    response = client.get(f"/dofs/{dof_a.id}/files/{wrong_file.id}/download")

    assert response.status_code == 404


def test_dof_legacy_opening_file_remains_downloadable(app, client):
    company = create_company("855")
    manager = create_user("dof-legacy-manager", company=company, role_key="management_representative")
    dof = make_dof(company, manager)
    stored_name = f"dof-opening-{'c' * 32}.jpg"
    write_stored_upload(app, stored_name, b"legacy-finding")
    file_record = opening_file(dof, stored_name)

    login(client, manager)
    response = client.get(f"/dofs/{dof.id}/files/{file_record.id}/download")

    assert response.status_code == 200
    assert response.data == b"legacy-finding"


def test_dof_opening_download_rejects_mismatched_file_company(app, client):
    company_a = create_company("860")
    company_b = create_company("861")
    manager = create_user("dof-metadata-manager", company=company_a, role_key="management_representative")
    dof = make_dof(company_a, manager)
    stored_name = f"company-{company_a.id:03d}/dof/opening/dof-opening-{'f' * 32}.jpg"
    write_stored_upload(app, stored_name, b"mismatched-metadata")
    file_record = opening_file(dof, stored_name)
    file_record.company_id = company_b.id
    db.session.commit()

    login(client, manager)
    assert client.get(f"/dofs/{dof.id}/files/{file_record.id}/download").status_code == 404


def test_dof_download_does_not_fall_back_to_flat_root(app, client):
    company = create_company("862")
    manager = create_user("dof-fallback-manager", company=company, role_key="management_representative")
    dof = make_dof(company, manager)
    file_name = f"dof-opening-{'0' * 32}.jpg"
    write_stored_upload(app, file_name, b"unrelated-flat-file")
    stored_name = f"company-{company.id:03d}/dof/opening/{file_name}"
    file_record = opening_file(dof, stored_name)

    login(client, manager)
    assert client.get(f"/dofs/{dof.id}/files/{file_record.id}/download").status_code == 404


def test_dof_company_files_download_and_delete_with_legacy_separator(app, client):
    company = create_company("863")
    manager = create_user("dof-valid-manager", company=company, role_key="management_representative")
    dof = make_dof(company, manager)
    opening_name = f"company-{company.id:03d}/dof/opening/dof-opening-{'1' * 32}.jpg"
    evidence_name = f"company-{company.id:03d}/dof/evidence/dof-{'2' * 32}.pdf"
    opening_path = write_stored_upload(app, opening_name, b"valid-opening")
    evidence_path = write_stored_upload(app, evidence_name, b"valid-evidence")
    opening = opening_file(dof, opening_name.replace("/", "\\"))
    dof.evidence_stored_name = evidence_name
    dof.evidence_original_name = "evidence.pdf"
    db.session.commit()

    login(client, manager)
    assert client.get(f"/dofs/{dof.id}/files/{opening.id}/download").data == b"valid-opening"
    assert client.get(f"/dofs/{dof.id}/evidence/download").data == b"valid-evidence"
    assert client.post(f"/dofs/{dof.id}/delete").status_code == 302
    assert not opening_path.exists()
    assert not evidence_path.exists()


def test_dof_evidence_download_rejects_foreign_company_path(app, client):
    company_a = create_company("856")
    company_b = create_company("857")
    manager = create_user("dof-evidence-manager", company=company_a, role_key="management_representative")
    dof = make_dof(company_a, manager)
    stored_name = f"company-{company_b.id:03d}/dof/evidence/dof-{'d' * 32}.pdf"
    write_stored_upload(app, stored_name, b"foreign-evidence")
    dof.evidence_stored_name = stored_name
    dof.evidence_original_name = "evidence.pdf"
    db.session.commit()

    login(client, manager)
    response = client.get(f"/dofs/{dof.id}/evidence/download")

    assert response.status_code == 404
    assert AuditLog.query.filter_by(entity_type="Dof", action="downloaded").count() == 0


def test_dof_legacy_evidence_download_and_delete(app, client):
    company = create_company("866")
    manager = create_user("dof-legacy-evidence-manager", company=company, role_key="management_representative")
    dof = make_dof(company, manager)
    stored_name = f"dof-{'4' * 32}.pdf"
    file_path = write_stored_upload(app, stored_name, b"legacy-evidence")
    dof.evidence_stored_name = stored_name
    dof.evidence_original_name = "evidence.pdf"
    db.session.commit()

    login(client, manager)
    assert client.get(f"/dofs/{dof.id}/evidence/download").data == b"legacy-evidence"
    assert client.post(f"/dofs/{dof.id}/delete").status_code == 302
    assert not file_path.exists()


def test_dof_delete_does_not_remove_foreign_file(app, client):
    company_a = create_company("858")
    company_b = create_company("859")
    manager = create_user("dof-delete-manager", company=company_a, role_key="management_representative")
    dof = make_dof(company_a, manager)
    stored_name = f"company-{company_b.id:03d}/dof/opening/dof-opening-{'e' * 32}.jpg"
    file_path = write_stored_upload(app, stored_name, b"keep-foreign-file")
    opening_file(dof, stored_name)

    login(client, manager)
    response = client.post(f"/dofs/{dof.id}/delete")

    assert response.status_code == 409
    assert Dof.query.filter_by(id=dof.id).first() is not None
    assert file_path.read_bytes() == b"keep-foreign-file"


def test_dof_delete_does_not_remove_foreign_evidence(app, client):
    company_a = create_company("864")
    company_b = create_company("865")
    manager = create_user("dof-evidence-delete-manager", company=company_a, role_key="management_representative")
    dof = make_dof(company_a, manager)
    stored_name = f"company-{company_b.id:03d}/dof/evidence/dof-{'3' * 32}.pdf"
    file_path = write_stored_upload(app, stored_name, b"keep-foreign-evidence")
    dof.evidence_stored_name = stored_name
    db.session.commit()

    login(client, manager)
    assert client.post(f"/dofs/{dof.id}/delete").status_code == 409
    assert Dof.query.filter_by(id=dof.id).first() is not None
    assert file_path.read_bytes() == b"keep-foreign-evidence"


def test_dof_shared_legacy_file_blocks_download_and_delete(app, client):
    company = create_company("867")
    manager = create_user("dof-shared-legacy-manager", company=company, role_key="management_representative")
    first_dof = make_dof(company, manager, dof_no="IF-2026-0867")
    second_dof = make_dof(company, manager, dof_no="IF-2026-0868")
    stored_name = f"dof-opening-{'5' * 32}.jpg"
    file_path = write_stored_upload(app, stored_name, b"shared-legacy")
    first_file = opening_file(first_dof, stored_name)
    opening_file(second_dof, stored_name)

    login(client, manager)
    assert client.get(f"/dofs/{first_dof.id}/files/{first_file.id}/download").status_code == 404
    assert client.post(f"/dofs/{first_dof.id}/delete").status_code == 409
    assert Dof.query.filter_by(id=first_dof.id).first() is not None
    assert file_path.read_bytes() == b"shared-legacy"


def test_dof_duplicate_opening_file_blocks_delete_without_unlink(app, client):
    company = create_company("868")
    manager = create_user("dof-duplicate-manager", company=company, role_key="management_representative")
    dof = make_dof(company, manager)
    stored_name = f"dof-opening-{'6' * 32}.jpg"
    file_path = write_stored_upload(app, stored_name, b"duplicate-opening")
    opening_file(dof, stored_name)
    opening_file(dof, stored_name)

    login(client, manager)
    assert client.post(f"/dofs/{dof.id}/delete").status_code == 409
    assert Dof.query.filter_by(id=dof.id).first() is not None
    assert file_path.read_bytes() == b"duplicate-opening"
