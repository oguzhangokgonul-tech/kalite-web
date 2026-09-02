from io import BytesIO
from pathlib import Path
import zipfile
from xml.etree import ElementTree as ET

from app.extensions import db
from app.models import (
    COMPANY_MODULE_KEYS,
    DOCUMENT_CATEGORY_DEFAULTS,
    DOCUMENT_STATUSES,
    Company,
    CompanyModule,
    Document,
    DocumentCategory,
    Role,
    User,
    UserPermission,
)


def create_company(code="101", name=None, module_keys=None, package_key="production_plus"):
    selected_modules = set(COMPANY_MODULE_KEYS if module_keys is None else module_keys)
    company = Company(
        code=code,
        name=name or f"Firma {code}",
        slug=f"firma-{code}",
        package_key=package_key,
        is_active=True,
    )
    db.session.add(company)
    db.session.flush()
    for module_key in COMPANY_MODULE_KEYS:
        db.session.add(
            CompanyModule(
                company_id=company.id,
                module_key=module_key,
                is_enabled=module_key in selected_modules,
            )
        )
    for category_data in DOCUMENT_CATEGORY_DEFAULTS:
        db.session.add(
            DocumentCategory(
                company_id=company.id,
                code=category_data["code"],
                name=category_data["name"],
                slug=category_data["slug"],
                sort_order=category_data["sort_order"],
                color=category_data.get("color"),
                icon=category_data.get("icon"),
                is_active=True,
            )
        )
    db.session.commit()
    return company


def create_user(username, *, company=None, role_key=None, permissions=(), full_name=None, title=None):
    user = User(
        company_id=company.id if company else None,
        username=username,
        full_name=full_name or username.replace("-", " ").title(),
        title=title,
        password_hash="not-used",
        is_active=True,
    )
    if role_key:
        user.roles.append(Role.query.filter_by(key=role_key).one())
    for permission_key in permissions:
        user.extra_permissions.append(UserPermission(permission_key=permission_key))
    db.session.add(user)
    db.session.commit()
    return user


def login(client, user, company=None):
    with client.session_transaction() as session:
        session["user_id"] = user.id
        if company is not None:
            session["company_id"] = company.id
        else:
            session.pop("company_id", None)


def first_document_category(company):
    return (
        DocumentCategory.query.filter_by(company_id=company.id, is_active=True)
        .order_by(DocumentCategory.sort_order.asc(), DocumentCategory.id.asc())
        .first()
    )


def upload_tuple(content=b"test file", filename="file.pdf"):
    return (BytesIO(content), filename)


def stored_upload_path(app, relative_path):
    return Path(app.config["UPLOAD_FOLDER"]) / relative_path


def write_stored_upload(app, relative_path, content=b"test file"):
    path = stored_upload_path(app, relative_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def make_document(app, company, category=None, uploader=None, **overrides):
    category = category or first_document_category(company)
    file_name = overrides.pop("file_name", "document-test.pdf")
    file_path = overrides.pop(
        "file_path",
        f"company-{company.id:03d}/documents/originals/{category.slug}/{file_name}",
    )
    content = overrides.pop("content", b"%PDF-1.4\n% document\n")
    write_stored_upload(app, file_path, content)
    document = Document(
        company_id=company.id,
        category_id=category.id,
        document_code=overrides.pop("document_code", "PR.01"),
        title=overrides.pop("title", "Test Dokuman"),
        revision_no=overrides.pop("revision_no", "0"),
        publish_date=overrides.pop("publish_date", None),
        revision_date=overrides.pop("revision_date", None),
        department=overrides.pop("department", None),
        description=overrides.pop("description", None),
        status=overrides.pop("status", DOCUMENT_STATUSES[0]),
        file_name=file_name,
        original_file_name=overrides.pop("original_file_name", file_name),
        file_path=file_path,
        file_type=overrides.pop("file_type", "pdf"),
        file_size=len(content),
        uploaded_by=uploader.id if uploader else None,
        **overrides,
    )
    db.session.add(document)
    db.session.commit()
    return document


def assert_xlsx_response(response):
    assert response.status_code == 200
    assert response.mimetype == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    with zipfile.ZipFile(BytesIO(response.data)) as archive:
        names = set(archive.namelist())
    assert "[Content_Types].xml" in names
    assert "xl/workbook.xml" in names
    assert "xl/worksheets/sheet1.xml" in names


def sheet_values(xlsx_bytes):
    namespace = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(BytesIO(xlsx_bytes)) as archive:
        sheet = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
    rows = []
    for row in sheet.findall(".//m:row", namespace):
        values = []
        for cell in row.findall("m:c", namespace):
            text = cell.find("m:is/m:t", namespace)
            values.append(text.text if text is not None and text.text is not None else "")
        rows.append(values)
    return rows
