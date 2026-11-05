import json

from app.company_onboarding import company_workspace_status, initialize_company_document_categories
from app.extensions import db
from app.models import AuditLog, Document, DocumentCategory
from app.routes import ensure_document_categories

from .helpers import create_company, create_user, first_document_category, login, make_document


def category_payload(**overrides):
    data = {
        "code": "09",
        "name": "Teknik Şartnameler",
        "sort_order": "9",
        "color": "cyan",
        "icon": "folder",
    }
    data.update(overrides)
    return data


def test_category_create_edit_and_default_changes_survive_seeding(app, client):
    company = create_company("CAT01")
    manager = create_user("category-manager", company=company, role_key="management_representative")
    login(client, manager)

    assert client.get("/documents").status_code == 200
    assert client.get("/documents/categories/new").status_code == 200
    assert client.post("/documents/categories/new", data=category_payload()).status_code == 302
    category = DocumentCategory.query.filter_by(company_id=company.id, code="09").one()
    assert category.slug == "teknik-sartnameler"
    assert AuditLog.query.filter_by(entity_type="DocumentCategory", entity_id=str(category.id), action="created").count() == 1
    assert client.post(
        f"/documents/categories/{category.id}/edit",
        data=category_payload(name="Güncel Şartnameler", sort_order="2", icon="book"),
    ).status_code == 302
    db.session.refresh(category)
    assert category.name == "Güncel Şartnameler"
    assert category.slug == "teknik-sartnameler"
    assert category.sort_order == 2
    assert category.icon == "book"
    assert AuditLog.query.filter_by(entity_type="DocumentCategory", entity_id=str(category.id), action="updated").count() >= 1

    default_category = first_document_category(company)
    assert client.post(
        f"/documents/categories/{default_category.id}/edit",
        data=category_payload(code=default_category.code, name="Özelleştirilmiş Klasör"),
    ).status_code == 302
    ensure_document_categories()
    initialize_company_document_categories(company)
    db.session.commit()
    db.session.refresh(default_category)
    assert default_category.name == "Özelleştirilmiş Klasör"


def test_category_delete_moves_documents_and_requires_case_insensitive_confirmation(app, client):
    company = create_company("CAT02")
    manager = create_user("category-delete-manager", company=company, role_key="management_representative")
    category = first_document_category(company)
    destination = DocumentCategory.query.filter(
        DocumentCategory.company_id == company.id, DocumentCategory.id != category.id,
    ).first()
    documents = [
        make_document(app, company, category=category, document_code=f"CAT.{index}", file_name=f"cat-{index}.pdf")
        for index in (1, 2)
    ]
    original_paths = [document.file_path for document in documents]
    login(client, manager)

    response = client.post(
        f"/documents/categories/{category.id}/delete",
        data={"destination_id": str(destination.id)},
    )
    assert response.status_code == 400
    assert "evet yazın" in response.get_data(as_text=True)
    assert db.session.get(DocumentCategory, category.id).is_active
    assert all(db.session.get(Document, document.id).category_id == category.id for document in documents)

    response = client.post(
        f"/documents/categories/{category.id}/delete",
        data={"destination_id": str(destination.id), "confirmation": "  EVET  "},
    )
    assert response.status_code == 302
    assert not db.session.get(DocumentCategory, category.id).is_active
    for document, original_path in zip(documents, original_paths):
        db.session.refresh(document)
        assert document.category_id == destination.id
        assert document.file_path == original_path
        assert client.get(f"/documents/{document.id}/download").status_code == 200
        audit = AuditLog.query.filter_by(entity_type="Document", entity_id=str(document.id), action="updated").order_by(AuditLog.id.desc()).first()
        assert json.loads(audit.old_values)["category_id"] == category.id
        assert json.loads(audit.new_values)["category_id"] == destination.id
    assert AuditLog.query.filter_by(entity_type="DocumentCategory", entity_id=str(category.id)).count() > 0
    ensure_document_categories()
    assert not db.session.get(DocumentCategory, category.id).is_active
    assert company_workspace_status(company)["document_categories_ready"]


def test_category_delete_empty_or_one_document_needs_no_word(app, client):
    company = create_company("CAT03")
    manager = create_user("category-simple-delete", company=company, role_key="management_representative")
    categories = DocumentCategory.query.filter_by(company_id=company.id).order_by(DocumentCategory.id).all()
    login(client, manager)
    assert client.post(f"/documents/categories/{categories[0].id}/delete").status_code == 302
    document = make_document(app, company, category=categories[1])
    response = client.post(
        f"/documents/categories/{categories[1].id}/delete",
        data={"destination_id": str(categories[2].id)},
    )
    assert response.status_code == 302
    db.session.refresh(document)
    assert document.category_id == categories[2].id


def test_category_management_is_tenant_scoped_and_permission_guarded(app, client):
    company = create_company("CAT04")
    other = create_company("CAT05")
    manager = create_user("category-tenant-manager", company=company, role_key="management_representative")
    viewer = create_user("category-viewer", company=company, permissions=("documents.view",))
    foreign = first_document_category(other)
    login(client, viewer)
    assert client.get("/documents/categories/new").status_code == 403
    assert client.post("/documents/categories/new", data=category_payload()).status_code == 403
    login(client, manager)
    assert client.get(f"/documents/categories/{foreign.id}/edit").status_code == 404
    assert client.post(f"/documents/categories/{foreign.id}/delete").status_code == 404
    assert client.post(
        "/documents/categories/new", data=category_payload(code="01"),
    ).status_code == 400
    own_category = first_document_category(company)
    document = make_document(app, company, category=own_category)
    assert client.post(
        f"/documents/categories/{own_category.id}/delete",
        data={"destination_id": str(foreign.id)},
    ).status_code == 400
    db.session.refresh(document)
    assert document.category_id == own_category.id
    assert own_category.is_active


def test_onboarding_detects_missing_default_but_accepts_archived_default(app):
    company = create_company("CAT06")
    categories = DocumentCategory.query.filter_by(company_id=company.id).order_by(DocumentCategory.id).all()
    categories[0].is_active = False
    db.session.commit()
    assert company_workspace_status(company)["document_categories_ready"]

    db.session.delete(categories[-1])
    db.session.commit()
    assert not company_workspace_status(company)["document_categories_ready"]
    initialize_company_document_categories(company)
    db.session.commit()
    assert company_workspace_status(company)["document_categories_ready"]
