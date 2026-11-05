"""Standards index backed by the current Document records."""

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for
from sqlalchemy import and_, or_
from sqlalchemy.orm import joinedload

from .extensions import db
from .models import DOCUMENT_STATUSES, Document
from .standard_documentation_models import StandardDocumentationHeading, StandardDocumentationLink
from .tenant import assign_current_company, current_company_id, scoped_query


bp = Blueprint("standard_documentation", __name__, url_prefix="/standart-dokumantasyon")


def can_view():
    user = getattr(g, "current_user", None)
    return bool(
        user and current_company_id()
        and g.company_module_enabled("standard_documentation")
        and g.company_module_enabled("documents")
        and (user.has_permission("standard_documentation.view") or user.has_permission("standard_documentation.manage"))
        and (user.has_permission("documents.view") or user.has_permission("documents.manage"))
    )


def can_manage():
    return can_view() and g.current_user.has_permission("standard_documentation.manage")


@bp.before_request
def guard():
    if getattr(g, "current_user", None) is None:
        return redirect(url_for("main.login", next=request.full_path))
    if not can_view():
        abort(403)


def headings_query():
    return scoped_query(StandardDocumentationHeading.query, StandardDocumentationHeading).filter_by(
        company_id=current_company_id()
    )


def heading_or_404(heading_id):
    return headings_query().filter_by(id=heading_id).first_or_404()


def available_documents(heading=None):
    linked_ids = [link.document_id for link in heading.links] if heading else []
    return scoped_query(Document.query, Document).filter(
        Document.company_id == current_company_id(),
        or_(
            and_(Document.archived_at.is_(None), Document.status.in_(DOCUMENT_STATUSES[:2])),
            Document.id.in_(linked_ids),
        ),
    ).order_by(Document.document_code.asc(), Document.id.asc()).all()


def parse_form(heading=None):
    values = {}
    for key, limit, required in (
        ("title", 200, True),
        ("related_standard", 200, False),
        ("technical_heading_no", 80, False),
    ):
        value = request.form.get(key, "").strip()
        if len(value) > limit or (required and not value) or any(ord(char) < 32 for char in value):
            raise ValueError("Başlık alanlarını ve metin uzunluklarını kontrol edin.")
        values[key] = value or None

    raw_ids = request.form.getlist("document_ids")
    if len(raw_ids) > 100 or any(
        len(raw) > 20 or not raw.isascii() or not raw.isdecimal() or int(raw) < 1
        for raw in raw_ids
    ):
        raise ValueError("En fazla 100 geçerli doküman seçin.")
    document_ids = list(dict.fromkeys(int(raw) for raw in raw_ids))
    linked_ids = [link.document_id for link in heading.links] if heading else []
    documents = Document.query.filter(
        Document.company_id == current_company_id(),
        or_(
            and_(Document.archived_at.is_(None), Document.status.in_(DOCUMENT_STATUSES[:2])),
            Document.id.in_(linked_ids),
        ),
        Document.id.in_(document_ids),
    ).all() if document_ids else []
    if len(documents) != len(document_ids):
        raise ValueError("Seçilen dokümanlardan biri bu şirkete ait değil veya arşivde.")
    return values, document_ids


@bp.get("")
def dashboard():
    headings = headings_query().options(
        joinedload(StandardDocumentationHeading.links).joinedload(StandardDocumentationLink.document)
    ).order_by(StandardDocumentationHeading.sort_order, StandardDocumentationHeading.id).all()
    return render_template("standard_documentation/dashboard.html", headings=headings, can_manage=can_manage())


def form_response(heading=None, error=None, status=200):
    selected = [link.document_id for link in heading.links] if heading else []
    if request.method == "POST":
        selected = [int(raw) for raw in request.form.getlist("document_ids")
                    if len(raw) <= 20 and raw.isascii() and raw.isdecimal()]
    return render_template(
        "standard_documentation/form.html", heading=heading, documents=available_documents(heading),
        selected=selected, values=request.form if request.method == "POST" else None, error=error,
    ), status


@bp.route("/yeni", methods=["GET", "POST"])
def create():
    if not can_manage():
        abort(403)
    if request.method == "POST":
        try:
            values, document_ids = parse_form()
        except ValueError as error:
            return form_response(error=str(error), status=400)
        heading = assign_current_company(StandardDocumentationHeading(
            **values, created_by_user_id=g.current_user.id,
        ))
        db.session.add(heading)
        db.session.flush()
        for position, document_id in enumerate(document_ids):
            heading.links.append(StandardDocumentationLink(
                company_id=heading.company_id, document_id=document_id, sort_order=position,
            ))
        db.session.commit()
        flash("Standart ana başlığı oluşturuldu.", "success")
        return redirect(url_for("standard_documentation.dashboard") + f"#heading-{heading.id}")
    return form_response()


@bp.route("/<int:heading_id>/duzenle", methods=["GET", "POST"])
def edit(heading_id):
    if not can_manage():
        abort(403)
    heading = heading_or_404(heading_id)
    if request.method == "POST":
        try:
            values, document_ids = parse_form(heading)
        except ValueError as error:
            return form_response(heading, str(error), 400)
        for key, value in values.items():
            setattr(heading, key, value)
        existing = {link.document_id: link for link in heading.links}
        for link in tuple(heading.links):
            if link.document_id not in document_ids:
                heading.links.remove(link)
        for position, document_id in enumerate(document_ids):
            if document_id in existing:
                existing[document_id].sort_order = position
            else:
                heading.links.append(StandardDocumentationLink(
                    company_id=heading.company_id, document_id=document_id, sort_order=position,
                ))
        db.session.commit()
        flash("Standart ana başlığı güncellendi.", "success")
        return redirect(url_for("standard_documentation.dashboard") + f"#heading-{heading.id}")
    return form_response(heading)
