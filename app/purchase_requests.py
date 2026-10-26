"""Purchase request workflow. Register bp and import purchase_models in app setup."""
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from functools import wraps
import re
from uuid import UUID, uuid4

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for
from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload
from sqlalchemy.orm.exc import StaleDataError

from .audit import record_audit_event
from .extensions import db
from .models import User
from .notifications import add_user_notification
from .purchase_models import PurchaseDecision, PurchaseRequest, PurchaseRequestItem
from .tenant import assign_current_company, current_company_id, scoped_query

bp = Blueprint('purchase_requests', __name__, url_prefix='/satin-alma-talepleri')
STATUS_LABELS = {
    'draft': 'Taslak', 'pending_purchase': 'Satın alma onayında',
    'pending_admin': 'Şirket yöneticisi onayında', 'returned': 'İade edildi',
    'rejected': 'Reddedildi', 'closed': 'Kapatıldı',
}
KIND_LABELS = {'material': 'Malzeme', 'service': 'Hizmet'}
ACTION_LABELS = {
    'submitted': 'Gönderildi', 'resubmitted': 'Yeniden gönderildi',
    'purchasing_approved': 'Satın alma onayı', 'admin_approved': 'Şirket yöneticisi onayı',
    'returned': 'İade edildi', 'rejected': 'Reddedildi',
}
INVALID_TEXT = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]')


def active_company_user(user):
    return bool(user and user.is_active and user.company_id == current_company_id())


def can_create():
    user = g.current_user
    return bool(user and user.is_active and current_company_id() and
                (active_company_user(user) or
                 (user.company_id is None and getattr(g, 'current_user_is_super_admin', False) and
                  user.has_role('super_admin'))) and user.has_permission('purchase.create'))


def can_purchase_approve(user):
    return active_company_user(user) and user.has_role('purchasing_approver') and user.has_permission('purchase.approve')


def can_admin_approve(user):
    return active_company_user(user) and user.has_role('company_admin')


def can_read():
    user = g.current_user
    if (user and user.is_active and current_company_id() and
            getattr(g, 'current_user_is_super_admin', False) and user.has_role('super_admin')):
        return True
    return active_company_user(user) and (
        user.has_permission('purchase.view') or user.has_permission('purchase.view_all') or can_create() or
        can_purchase_approve(user) or can_admin_approve(user))


@bp.before_request
def guard():
    if not getattr(g, 'current_user', None):
        return redirect(url_for('main.login', next=request.full_path))
    if not current_company_id() or not g.company_module_enabled('purchase_requests') or not can_read():
        abort(403)


@bp.context_processor
def template_context():
    return dict(purchase_statuses=STATUS_LABELS, purchase_kinds=KIND_LABELS,
                purchase_actions=ACTION_LABELS)


def records():
    user = g.current_user
    query = scoped_query(PurchaseRequest.query, PurchaseRequest).filter_by(company_id=current_company_id())
    if not (can_admin_approve(user) or
            (user.has_permission('purchase.view_all') and active_company_user(user)) or
            (getattr(g, 'current_user_is_super_admin', False) and user.has_role('super_admin'))):
        clauses = [PurchaseRequest.requester_id == user.id,
                   PurchaseRequest.purchasing_approver_id == user.id,
                   PurchaseRequest.id.in_(select(PurchaseDecision.request_id).where(
                       PurchaseDecision.company_id == current_company_id(),
                       PurchaseDecision.actor_id == user.id))]
        if can_purchase_approve(user):
            clauses.append(PurchaseRequest.status == 'pending_purchase')
        query = query.filter(or_(*clauses))
    return query.options(joinedload(PurchaseRequest.requester),
                         joinedload(PurchaseRequest.purchasing_approver),
                         joinedload(PurchaseRequest.admin_approver))


def get_record(record_id):
    if not 0 < record_id < 2**63:
        abort(404)
    return records().filter_by(id=record_id).first_or_404()


def atomic(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        try:
            return view(*args, **kwargs)
        except (IntegrityError, StaleDataError):
            db.session.rollback()
            abort(409, description='Kayıt değişti veya işlem daha önce tamamlandı. Sayfayı yenileyin.')
        except Exception:
            db.session.rollback()
            raise
    return wrapped


def snapshot(record):
    return {column.name: getattr(record, column.name) for column in PurchaseRequest.__table__.columns}


def audit(record, action, old=None):
    db.session.flush()
    record_audit_event('PurchaseRequest', action, record.record_no, entity_id=record.id,
                       company_id=record.company_id, old_values=old,
                       new_values=snapshot(record), commit=False)


def check_version(record):
    if request.form.get('version_id') != str(record.version_id):
        abort(409, description='Kayıt değişti. Sayfayı yenileyin.')


def text_field(name, limit, required=False):
    value = request.form.get(name, '').strip()
    if (required and not value) or len(value) > limit or INVALID_TEXT.search(value):
        raise ValueError('Zorunlu alanları ve metin uzunluklarını kontrol edin.')
    return value or None


def form_values():
    kind = request.form.get('kind', '')
    currency = request.form.get('currency', 'TRY')
    if kind not in KIND_LABELS or currency not in ('TRY', 'USD', 'EUR'):
        raise ValueError('Geçerli bir talep türü ve para birimi seçin.')
    try:
        quantity = Decimal(request.form.get('quantity', ''))
        estimate = request.form.get('estimated_total', '').strip()
        estimated_total = Decimal(estimate) if estimate else None
    except InvalidOperation:
        raise ValueError('Miktar ve tahmini tutarı kontrol edin.') from None
    if (not quantity.is_finite() or quantity <= 0 or quantity.as_tuple().exponent < -3 or
            quantity >= Decimal('1000000000') or
            estimated_total is not None and
            (not estimated_total.is_finite() or estimated_total < 0 or
             estimated_total.as_tuple().exponent < -2 or estimated_total >= Decimal('1000000000000'))):
        raise ValueError('Miktar veya tahmini tutar geçersiz.')
    needed_by = request.form.get('needed_by', '').strip()
    try:
        needed_by = date.fromisoformat(needed_by) if needed_by else None
    except ValueError:
        raise ValueError('İhtiyaç tarihini kontrol edin.') from None
    return dict(kind=kind, title=text_field('title', 180, True),
                description=text_field('description', 5000, True),
                justification=text_field('justification', 3000, True),
                quantity=quantity, unit=text_field('unit', 40, True),
                estimated_total=estimated_total, currency=currency, needed_by=needed_by)


def form_context(record=None):
    values = request.form if request.method == 'POST' else snapshot(record) if record else {'quantity': '1', 'currency': 'TRY'}
    return dict(record=record, values=values,
                request_token=request.form.get('request_token') or str(uuid4()))


def eligible_reviewers(stage, record):
    users = scoped_query(User.query, User).filter_by(
        company_id=record.company_id, is_active=True).order_by(User.id).all()
    if stage == 'purchase':
        return [user for user in users if user.id != record.requester_id and can_purchase_approve(user)]
    return [user for user in users if user.id not in (record.requester_id, record.purchasing_approver_id)
            and can_admin_approve(user)]


def _admins_for_reviewer(record, reviewer_id):
    users = scoped_query(User.query, User).filter_by(
        company_id=record.company_id, is_active=True).all()
    return [user for user in users if user.id not in (record.requester_id, reviewer_id)
            and can_admin_approve(user)]


def notify(users, record, event, message):
    for user in users:
        if user.company_id is None and (not user.is_active or not user.has_role('super_admin')):
            continue
        notification = add_user_notification(
            user, f'{record.record_no}: {message}', company_id=record.company_id,
            source_key=f'purchase:{record.id}:{record.version_id}:{event}:{user.id}',
            target_url=url_for('purchase_requests.detail', record_id=record.id),
            allow_platform_admin=user.company_id is None)
        if notification is None:
            abort(409, description='Bildirim oluşturulamadı. İşlemi tekrar deneyin.')


def transition(record, action, status, *, reason=None, old=None):
    if old is None:
        old = snapshot(record)
    prior = record.status
    record.status = status
    record.decision_reason = reason
    db.session.add(PurchaseDecision(company_id=record.company_id, request_id=record.id,
                                    actor_id=g.current_user.id, action=action,
                                    from_status=prior, to_status=status, reason=reason))
    audit(record, action, old)


@bp.get('')
def dashboard():
    status = request.args.get('status', 'all')
    if status not in ('all', *STATUS_LABELS):
        abort(400)
    query = records()
    if status != 'all':
        query = query.filter_by(status=status)
    pagination = query.order_by(PurchaseRequest.created_at.desc(), PurchaseRequest.id.desc()).paginate(
        per_page=20, error_out=False)
    has_purchasing_approver = any(
        can_purchase_approve(user) for user in scoped_query(User.query, User).filter_by(
            company_id=current_company_id(), is_active=True).all()
    )
    return render_template('purchase_requests/dashboard.html', pagination=pagination,
                           status=status, can_create=can_create(),
                           show_setup_notice=can_admin_approve(g.current_user) and not has_purchasing_approver)


@bp.route('/yeni', methods=['GET', 'POST'])
@atomic
def create():
    if not can_create():
        abort(403)
    if request.method == 'POST':
        if request.form.get('version_id') != '1':
            abort(409)
        try:
            token = str(UUID(request.form.get('request_token', '')))
            existing = scoped_query(PurchaseRequest.query, PurchaseRequest).filter_by(
                company_id=current_company_id(), request_token=token).first()
            if existing:
                if existing.requester_id != g.current_user.id:
                    abort(409)
                return redirect(url_for('purchase_requests.detail', record_id=existing.id))
            record = PurchaseRequest(requester_id=g.current_user.id, request_token=token,
                                     **form_values())
            assign_current_company(record)
            db.session.add(record)
            db.session.flush()
            db.session.add(PurchaseRequestItem(
                company_id=record.company_id, request_id=record.id, line_no=1,
                description=record.description, quantity=record.quantity, unit=record.unit,
                estimated_total=record.estimated_total))
            audit(record, 'created')
            db.session.commit()
        except ValueError as error:
            db.session.rollback()
            flash(str(error), 'danger')
            return render_template('purchase_requests/form.html', **form_context()), 400
        flash('Satın alma talebi taslağı kaydedildi.', 'success')
        return redirect(url_for('purchase_requests.detail', record_id=record.id))
    return render_template('purchase_requests/form.html', **form_context())


@bp.get('/<int:record_id>')
def detail(record_id):
    record = get_record(record_id)
    user = g.current_user
    can_edit = record.requester_id == user.id and can_create() and record.status in ('draft', 'returned')
    can_purchase = record.status == 'pending_purchase' and record.requester_id != user.id and can_purchase_approve(user)
    can_admin = record.status == 'pending_admin' and user.id not in (record.requester_id, record.purchasing_approver_id) and can_admin_approve(user)
    return render_template('purchase_requests/detail.html', record=record,
                           can_edit=can_edit, can_purchase=can_purchase, can_admin=can_admin)


@bp.route('/<int:record_id>/duzenle', methods=['GET', 'POST'])
@atomic
def edit(record_id):
    record = get_record(record_id)
    if record.requester_id != g.current_user.id or not can_create():
        abort(403)
    if record.status not in ('draft', 'returned'):
        abort(409)
    if request.method == 'POST':
        check_version(record)
        try:
            values = form_values()
        except ValueError as error:
            flash(str(error), 'danger')
            return render_template('purchase_requests/form.html', **form_context(record)), 400
        old = snapshot(record)
        for key, value in values.items():
            setattr(record, key, value)
        item = scoped_query(PurchaseRequestItem.query, PurchaseRequestItem).filter_by(
            company_id=record.company_id, request_id=record.id, line_no=1).first()
        if item is None:
            abort(409, description='Talep kalemi bulunamadı.')
        for key in ('description', 'quantity', 'unit', 'estimated_total'):
            setattr(item, key, getattr(record, key))
        audit(record, 'updated', old)
        db.session.commit()
        flash('Talep güncellendi.', 'success')
        return redirect(url_for('purchase_requests.detail', record_id=record.id))
    return render_template('purchase_requests/form.html', **form_context(record))


@bp.post('/<int:record_id>/gonder')
@atomic
def submit(record_id):
    record = get_record(record_id)
    if record.requester_id != g.current_user.id or not can_create():
        abort(403)
    check_version(record)
    if record.status not in ('draft', 'returned'):
        abort(409)
    reviewers = eligible_reviewers('purchase', record)
    if not reviewers:
        flash('Şirketinizde satın alma onaylayıcısı yok. Şirket admini bir kullanıcıya Satın Alma Onaylayıcısı rolünü atamalı.', 'warning')
        return redirect(url_for('purchase_requests.detail', record_id=record.id))
    reviewers = [reviewer for reviewer in reviewers if _admins_for_reviewer(record, reviewer.id)]
    if not reviewers:
        flash('Talep sahibi ve satın alma onaylayıcısından farklı bir şirket admini bulunamadı.', 'warning')
        return redirect(url_for('purchase_requests.detail', record_id=record.id))
    action = 'resubmitted' if record.status == 'returned' else 'submitted'
    record.purchasing_approver_id = None
    record.admin_approver_id = None
    record.submitted_at = datetime.now(timezone.utc).replace(tzinfo=None)
    transition(record, action, 'pending_purchase')
    notify(reviewers, record, action, 'Satın alma onayınız bekleniyor.')
    db.session.commit()
    flash('Talep satın alma onayına gönderildi.', 'success')
    return redirect(url_for('purchase_requests.detail', record_id=record.id))


@bp.post('/<int:record_id>/satin-alma-onayla')
@atomic
def approve_purchase(record_id):
    record = get_record(record_id)
    user = g.current_user
    if not can_purchase_approve(user) or user.id == record.requester_id:
        abort(403)
    check_version(record)
    if record.status != 'pending_purchase':
        abort(409)
    old = snapshot(record)
    record.purchasing_approver_id = user.id
    admins = eligible_reviewers('admin', record)
    if not admins:
        abort(409, description='Farklı bir şirket yöneticisi onaycısı bulunamadı.')
    transition(record, 'purchasing_approved', 'pending_admin', old=old)
    notify(admins, record, 'purchasing_approved', 'Şirket yöneticisi onayınız bekleniyor.')
    notify([record.requester], record, 'purchasing_approved_requester', 'Talep satın alma tarafından onaylandı.')
    db.session.commit()
    flash('Satın alma onayı kaydedildi.', 'success')
    return redirect(url_for('purchase_requests.detail', record_id=record.id))


@bp.post('/<int:record_id>/yonetici-onayla')
@atomic
def approve_admin(record_id):
    record = get_record(record_id)
    user = g.current_user
    if not can_admin_approve(user) or user.id in (record.requester_id, record.purchasing_approver_id):
        abort(403)
    check_version(record)
    if record.status != 'pending_admin':
        abort(409)
    old = snapshot(record)
    record.admin_approver_id = user.id
    record.closed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    transition(record, 'admin_approved', 'closed', old=old)
    notify([record.requester, record.purchasing_approver], record,
           'admin_approved', 'Talep şirket yöneticisi tarafından onaylanıp kapatıldı.')
    db.session.commit()
    flash('Talep onaylanıp kapatıldı.', 'success')
    return redirect(url_for('purchase_requests.detail', record_id=record.id))


@bp.post('/<int:record_id>/karar')
@atomic
def decide(record_id):
    record = get_record(record_id)
    user = g.current_user
    if record.status == 'pending_purchase':
        authorized = can_purchase_approve(user) and user.id != record.requester_id
    elif record.status == 'pending_admin':
        authorized = can_admin_approve(user) and user.id not in (record.requester_id, record.purchasing_approver_id)
    else:
        abort(409)
    if not authorized:
        abort(403)
    check_version(record)
    action = request.form.get('action')
    if action not in ('returned', 'rejected'):
        abort(400)
    try:
        reason = text_field('reason', 1000, True)
    except ValueError as error:
        abort(400, description=str(error))
    was_admin_stage = record.status == 'pending_admin'
    transition(record, action, action, reason=reason)
    notify([record.requester], record, action, f'Talep {"iade edildi" if action == "returned" else "reddedildi"}. Gerekçe: {reason}')
    if was_admin_stage:
        notify([record.purchasing_approver], record, f'{action}_purchasing',
               f'Şirket yöneticisi talebi {"iade etti" if action == "returned" else "reddetti"}.')
    db.session.commit()
    flash('Karar kaydedildi.', 'success')
    return redirect(url_for('purchase_requests.detail', record_id=record.id))


def assigned_task_rows(scope, row_builder):
    if (not getattr(g, 'current_user', None) or not current_company_id() or
            not g.company_module_enabled('purchase_requests') or not can_read()):
        return []
    user = g.current_user
    if scope == 'created':
        if not can_create():
            return []
        query = records().filter_by(requester_id=user.id, status='returned')
    else:
        conditions = []
        if can_purchase_approve(user):
            conditions.append(and_(PurchaseRequest.status == 'pending_purchase',
                                   PurchaseRequest.requester_id != user.id))
        if can_admin_approve(user):
            conditions.append(and_(PurchaseRequest.status == 'pending_admin',
                                   PurchaseRequest.requester_id != user.id,
                                   PurchaseRequest.purchasing_approver_id != user.id))
        if can_create():
            conditions.append(and_(PurchaseRequest.status == 'returned',
                                   PurchaseRequest.requester_id == user.id))
        if not conditions:
            return []
        query = records().filter(or_(*conditions))
    items = query.order_by(PurchaseRequest.created_at, PurchaseRequest.id).all()
    rows = []
    for item in items:
        status = ('Düzeltme bekliyor' if item.status == 'returned' else
                  'Satın alma onayı bekliyor' if item.status == 'pending_purchase' else
                  'Şirket yöneticisi onayı bekliyor')
        rows.append(row_builder(
            module_key='purchase_requests', module_label='Satın Alma Talepleri',
            module_icon='cart-check', module_tone='quality', title=item.title,
            description=item.description, reference_no=item.record_no,
            department='-', due_date=item.needed_by, date_label='İhtiyaç tarihi',
            due_is_deadline=False, status=status, status_key='pending', priority='Orta',
            detail_url=url_for('purchase_requests.detail', record_id=item.id),
            created_at=item.created_at, sort_id=item.id))
    return rows
