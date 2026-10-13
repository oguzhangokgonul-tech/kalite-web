from datetime import date, datetime, timezone
from functools import wraps
import re
from uuid import UUID, uuid4

from flask import Blueprint, abort, flash, g, redirect, render_template, request, send_file, url_for
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload
from sqlalchemy.orm.exc import StaleDataError

from .audit import record_audit_event
from .extensions import db
from .models import CompanyDepartment, User
from .notifications import add_user_notification
from .reporting import REPORT_PERIOD_CHOICES, report_period_metadata, resolve_report_period
from .shift_handover_models import ShiftHandover, handover_today
from .tenant import assign_current_company, current_company_id, scoped_query

bp = Blueprint('shift_handover', __name__, url_prefix='/vardiya-devir-teslimi')
UTC = timezone.utc
STATUS_LABELS = {'draft': 'Taslak', 'sent': 'Gönderildi', 'received': 'Teslim alındı', 'cancelled': 'İptal edildi'}
NOTE_FIELDS = (('summary', 'Vardiya özeti'), ('pending_work', 'Bekleyen işler'),
               ('safety_notes', 'İş güvenliği notları'), ('quality_notes', 'Kalite notları'),
               ('equipment_notes', 'Ekipman notları'))
REPORT_HEADERS = ('Kayıt No', 'Vardiya Tarihi', 'Vardiya', 'Departman', 'Alan', 'Başlık',
                  'Teslim Eden', 'Teslim Alan', 'Durum', *(label for _, label in NOTE_FIELDS),
                  'Gönderim (UTC)', 'Teslim Alma (UTC)', 'Arşiv (UTC)', 'İptal Gerekçesi')


def user_allowed(user, permission):
    if not user or not user.is_active:
        return False
    if permission in ('create', 'receive', 'manage') and user.role_keys == {'viewer'}:
        return False
    return user.has_permission(f'shift_handover.{permission}')


def allowed(permission):
    return user_allowed(getattr(g, 'current_user', None), permission)


def require_read():
    if not current_company_id() or not any(allowed(p) for p in ('view', 'view_all', 'manage')):
        abort(403)
    if not g.company_module_enabled('shift_handover'):
        abort(403)


@bp.before_request
def guard():
    if not getattr(g, 'current_user', None):
        return redirect(url_for('main.login', next=request.full_path))
    require_read()


@bp.context_processor
def template_context():
    return dict(handover_statuses=STATUS_LABELS, handover_notes=NOTE_FIELDS)


def records():
    require_read()
    query = scoped_query(ShiftHandover.query, ShiftHandover).filter_by(company_id=current_company_id())
    if not (allowed('view_all') or allowed('manage')):
        query = query.filter(or_(ShiftHandover.sender_user_id == g.current_user.id,
                                 ShiftHandover.receiver_user_id == g.current_user.id))
    return query.options(joinedload(ShiftHandover.sender), joinedload(ShiftHandover.receiver),
                         joinedload(ShiftHandover.department))


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
            abort(409, description='Kayıt değişti veya aynı istek daha önce işlendi. Sayfayı yenileyin.')
        except Exception:
            db.session.rollback()
            raise
    return wrapped


def snapshot(record):
    return {column.name: getattr(record, column.name) for column in ShiftHandover.__table__.columns}


def audit(record, action, old=None):
    db.session.flush()
    record_audit_event('ShiftHandover', action, record.record_no, entity_id=record.id,
                       company_id=record.company_id, old_values=old,
                       new_values=snapshot(record), commit=False)


def version(record):
    if request.form.get('version_id') != str(record.version_id) or record.archived_at:
        abort(409, description='Kayıt değişti veya arşivlendi. Sayfayı yenileyin.')


def can_edit(record):
    return bool(not record.archived_at and record.status == 'draft' and
                (record.sender_user_id == g.current_user.id and allowed('create') or allowed('manage')))


def require_draft(record):
    if not (record.sender_user_id == g.current_user.id and allowed('create') or allowed('manage')):
        abort(403)
    if record.status != 'draft' or record.archived_at:
        abort(409, description='Yalnızca arşivlenmemiş taslaklar değiştirilebilir.')


def form_text(name, limit, required=False):
    value = request.form.get(name, '').strip()
    if (required and not value) or len(value) > limit or re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]', value):
        raise ValueError('Zorunlu alanları ve metin uzunluklarını kontrol edin.')
    return value or None


def form_id(name):
    try:
        value = int(request.form.get(name, ''))
    except ValueError:
        raise ValueError('Departman ve teslim alacak kullanıcı seçin.') from None
    if not 0 < value < 2**63:
        raise ValueError('Geçerli bir departman ve kullanıcı seçin.')
    return value


def validate_assignment(department_id, receiver_id):
    department = scoped_query(CompanyDepartment.query, CompanyDepartment).filter_by(
        company_id=current_company_id(), id=department_id, is_active=True).first()
    receiver = scoped_query(User.query, User).filter_by(
        company_id=current_company_id(), id=receiver_id, is_active=True).first()
    if not department:
        raise ValueError('Şirketinize ait aktif bir departman seçin.')
    if not all(user_allowed(receiver, p) for p in ('view', 'receive')):
        raise ValueError('Şirketinize ait aktif, vardiya görüntüleme ve teslim alma yetkili bir kullanıcı seçin.')
    return receiver


def values_from_form():
    try:
        handover_date = date.fromisoformat(request.form.get('handover_date', ''))
    except ValueError:
        raise ValueError('Geçerli bir vardiya tarihi girin.') from None
    department_id, receiver_id = form_id('department_id'), form_id('receiver_user_id')
    validate_assignment(department_id, receiver_id)
    return dict(handover_date=handover_date, shift_name=form_text('shift_name', 80, True),
                department_id=department_id, receiver_user_id=receiver_id, area=form_text('area', 120),
                title=form_text('title', 180, True),
                **{name: form_text(name, 5000, name == 'summary') for name, _ in NOTE_FIELDS})


def form_context(record=None):
    departments = scoped_query(CompanyDepartment.query, CompanyDepartment).filter_by(
        company_id=current_company_id(), is_active=True).order_by(CompanyDepartment.sort_order, CompanyDepartment.name).all()
    users = scoped_query(User.query, User).filter_by(company_id=current_company_id(), is_active=True).order_by(User.full_name, User.id).all()
    receivers = [user for user in users if all(user_allowed(user, p) for p in ('view', 'receive'))]
    values = request.form if request.method == 'POST' else snapshot(record) if record else {'handover_date': handover_today().isoformat()}
    return dict(record=record, departments=departments, receivers=receivers, values=values,
                request_token=request.form.get('request_token') or str(uuid4()))


def filtered():
    query = records()
    status = request.args.get('status', 'all')
    archive_filter = request.args.get('archive', 'active')
    if status not in ('all', *STATUS_LABELS) or archive_filter not in ('active', 'archived', 'all'):
        abort(400)
    if status != 'all':
        query = query.filter_by(status=status)
    if archive_filter != 'all':
        query = query.filter(ShiftHandover.archived_at.is_(None) if archive_filter == 'active' else ShiftHandover.archived_at.is_not(None))
    q = request.args.get('q', '').strip()[:180]
    if q:
        escaped = q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
        query = query.filter(or_(*(column.ilike(f'%{escaped}%', escape='\\') for column in
                                  (ShiftHandover.title, ShiftHandover.shift_name, ShiftHandover.area))))
    try:
        period = resolve_report_period(request.args.get('period'), request.args.get('anchor'), today=handover_today())
    except ValueError:
        abort(400, description='Geçerli bir rapor dönemi ve tarih seçin.')
    if period:
        query = query.filter(ShiftHandover.handover_date.between(period.start_date, period.end_date))
    filters = dict(q=q, status=status, archive=archive_filter, period=period.key if period else '',
                   anchor=period.anchor_date.isoformat() if period else '')
    return query, filters, period


@bp.get('')
def dashboard():
    query, filters, period = filtered()
    pagination = query.order_by(ShiftHandover.handover_date.desc(), ShiftHandover.id.desc()).paginate(per_page=20, error_out=False)
    return render_template('shift_handover/dashboard.html', pagination=pagination, filters=filters,
                           period=period, period_choices=REPORT_PERIOD_CHOICES, today=handover_today(),
                           can_create=allowed('create'), can_export=allowed('export'))


@bp.route('/yeni', methods=['GET', 'POST'])
@atomic
def create():
    if not allowed('create'):
        abort(403)
    if request.method == 'POST':
        if request.form.get('version_id') != '1':
            abort(409, description='Formu yenileyin.')
        try:
            try:
                token = str(UUID(request.form.get('request_token', '')))
            except ValueError:
                raise ValueError('Formu yenileyip tekrar deneyin.') from None
            existing = scoped_query(ShiftHandover.query, ShiftHandover).filter_by(
                company_id=current_company_id(), request_token=token).first()
            if existing:
                if existing.sender_user_id != g.current_user.id:
                    abort(409)
                return redirect(url_for('shift_handover.detail', record_id=existing.id))
            record = ShiftHandover(sender_user_id=g.current_user.id, request_token=token, **values_from_form())
            assign_current_company(record)
            db.session.add(record)
            audit(record, 'created')
            db.session.commit()
        except ValueError as error:
            db.session.rollback()
            flash(str(error), 'danger')
            return render_template('shift_handover/form.html', **form_context()), 400
        flash('Vardiya devir teslim taslağı kaydedildi.', 'success')
        return redirect(url_for('shift_handover.detail', record_id=record.id))
    return render_template('shift_handover/form.html', **form_context())


@bp.get('/<int:record_id>')
def detail(record_id):
    record = get_record(record_id)
    return render_template('shift_handover/detail.html', record=record, can_edit=can_edit(record),
                           can_receive=not record.archived_at and record.status == 'sent' and record.receiver_user_id == g.current_user.id and allowed('view') and allowed('receive'),
                           can_archive=not record.archived_at and record.status in ('received', 'cancelled') and allowed('manage'),
                           can_cancel=not record.archived_at and (can_edit(record) or record.status == 'sent' and allowed('manage')))


@bp.route('/<int:record_id>/duzenle', methods=['GET', 'POST'])
@atomic
def edit(record_id):
    record = get_record(record_id)
    require_draft(record)
    if request.method == 'POST':
        version(record)
        try:
            values = values_from_form()
        except ValueError as error:
            flash(str(error), 'danger')
            return render_template('shift_handover/form.html', **form_context(record)), 400
        old = snapshot(record)
        for key, value in values.items():
            setattr(record, key, value)
        record.updated_at = datetime.now(UTC).replace(tzinfo=None)
        audit(record, 'updated', old)
        db.session.commit()
        flash('Taslak güncellendi.', 'success')
        return redirect(url_for('shift_handover.detail', record_id=record.id))
    return render_template('shift_handover/form.html', **form_context(record))


@bp.post('/<int:record_id>/gonder')
@atomic
def send(record_id):
    record = get_record(record_id)
    require_draft(record)
    version(record)
    try:
        receiver = validate_assignment(record.department_id, record.receiver_user_id)
    except ValueError as error:
        abort(400, description=str(error))
    old = snapshot(record)
    record.status, record.sent_by_user_id = 'sent', g.current_user.id
    record.sent_at = datetime.now(UTC).replace(tzinfo=None)
    audit(record, 'sent', old)
    notification = add_user_notification(receiver, f'{record.record_no}: {record.title} vardiya devir teslimi sizi bekliyor.',
                          company_id=record.company_id, source_key=f'shift_handover:{record.id}:sent:{receiver.id}',
                          target_url=url_for('shift_handover.detail', record_id=record.id))
    if notification is None:
        abort(409, description='Teslim alma bildirimi oluşturulamadı. Sayfayı yenileyin.')
    db.session.commit()
    flash('Vardiya devir teslimi gönderildi.', 'success')
    return redirect(url_for('shift_handover.detail', record_id=record.id))


@bp.post('/<int:record_id>/teslim-al')
@atomic
def receive(record_id):
    record = get_record(record_id)
    if record.receiver_user_id != g.current_user.id or not allowed('view') or not allowed('receive'):
        abort(403)
    version(record)
    if record.status != 'sent':
        abort(409)
    old = snapshot(record)
    record.status, record.received_by_user_id = 'received', g.current_user.id
    record.received_at = datetime.now(UTC).replace(tzinfo=None)
    audit(record, 'received', old)
    if record.sender.is_active and record.sender.company_id == record.company_id:
        notification = add_user_notification(
            record.sender, f'{record.record_no}: Vardiya devir teslimi teslim alındı.',
            company_id=record.company_id, source_key=f'shift_handover:{record.id}:received:{record.sender_user_id}',
            target_url=url_for('shift_handover.detail', record_id=record.id))
        if notification is None:
            abort(409, description='Teslim alma bildirimi oluşturulamadı. Sayfayı yenileyin.')
    db.session.commit()
    flash('Vardiya teslim alındı.', 'success')
    return redirect(url_for('shift_handover.detail', record_id=record.id))


@bp.post('/<int:record_id>/arsivle')
@atomic
def archive(record_id):
    if not allowed('manage'):
        abort(403)
    record = get_record(record_id)
    version(record)
    if record.status not in ('received', 'cancelled'):
        abort(409, description='Yalnızca teslim alınan veya iptal edilen kayıtlar arşivlenebilir.')
    old = snapshot(record)
    record.archived_at, record.archived_by_user_id = datetime.now(UTC).replace(tzinfo=None), g.current_user.id
    audit(record, 'archived', old)
    db.session.commit()
    flash('Kayıt arşivlendi.', 'success')
    return redirect(url_for('shift_handover.detail', record_id=record.id))


@bp.post('/<int:record_id>/iptal')
@atomic
def cancel(record_id):
    record = get_record(record_id)
    if not (allowed('manage') or record.status == 'draft' and record.sender_user_id == g.current_user.id and allowed('create')):
        abort(403)
    version(record)
    if record.status not in ('draft', 'sent'):
        abort(409)
    try:
        reason = form_text('cancel_reason', 1000, True)
    except ValueError as error:
        abort(400, description=str(error))
    old = snapshot(record)
    record.status, record.cancel_reason = 'cancelled', reason
    record.cancelled_at, record.cancelled_by_user_id = datetime.now(UTC).replace(tzinfo=None), g.current_user.id
    audit(record, 'cancelled', old)
    db.session.commit()
    flash('Vardiya devir teslimi iptal edildi.', 'success')
    return redirect(url_for('shift_handover.detail', record_id=record.id))


def report_rows(query):
    rows = []
    for record in query.order_by(ShiftHandover.handover_date, ShiftHandover.id).all():
        rows.append((record.record_no, record.handover_date.isoformat(), record.shift_name,
                     record.department.name, record.area or '', record.title,
                     record.sender.full_name or record.sender.username,
                     record.receiver.full_name or record.receiver.username, STATUS_LABELS[record.status],
                     *(getattr(record, field) or '' for field, _ in NOTE_FIELDS),
                     record.sent_at.isoformat(sep=' ') if record.sent_at else '',
                     record.received_at.isoformat(sep=' ') if record.received_at else '',
                     record.archived_at.isoformat(sep=' ') if record.archived_at else '', record.cancel_reason or ''))
    return [tuple(re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]', '\ufffd', value)
                  if isinstance(value, str) else value for value in row) for row in rows]


def report_data():
    # The report center applies its period filter; visibility is enforced here by IDs.
    return dict(key='shift_handover', title='Vardiya Devir Teslimi', module_key='shift_handover',
                headers=REPORT_HEADERS, rows=report_rows(records()), sheet_name='Vardiya Devir Teslimi')


@bp.get('/excel')
@atomic
def export_excel():
    if not allowed('export'):
        abort(403)
    from .routes import build_simple_xlsx
    query, filters, period = filtered()
    rows = report_rows(query)
    metadata = report_period_metadata(dict(title='Vardiya Devir Teslimi', module_key='shift_handover',
                                           rows=rows, period=period, date_basis='Vardiya tarihi'),
                                      scope_label=getattr(getattr(g, 'current_company', None), 'name', str(current_company_id())),
                                      generated_by=g.current_user.full_name or g.current_user.username,
                                      generated_at=datetime.now(UTC))
    workbook = build_simple_xlsx(REPORT_HEADERS, rows, sheet_name='Vardiya Devir Teslimi', metadata=metadata)
    record_audit_event('ShiftHandover', 'exported', 'Vardiya devir teslim raporu',
                       company_id=current_company_id(), details=dict(row_count=len(rows), **filters), commit=False)
    db.session.commit()
    return send_file(workbook, as_attachment=True,
                     download_name=f'vardiya-devir-teslimi-{period.code if period else handover_today().isoformat()}.xlsx',
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


def assigned_task_rows(scope, row_builder):
    if (scope == 'created' or not current_company_id() or not allowed('view') or not allowed('receive')
            or not g.company_module_enabled('shift_handover')):
        return []
    items = records().filter_by(receiver_user_id=g.current_user.id, status='sent', archived_at=None).order_by(
        ShiftHandover.handover_date, ShiftHandover.id).all()
    return [row_builder(module_key='shift_handover', module_label='Vardiya Devir Teslimi',
                        module_icon='arrow-left-right', module_tone='quality', title=item.title,
                        description=item.summary, reference_no=item.record_no, department=item.department.name,
                        due_date=item.handover_date, date_label='Vardiya tarihi', due_is_deadline=False,
                        status='Teslim alma bekliyor', status_key='pending',
                        priority='Orta', detail_url=url_for('shift_handover.detail', record_id=item.id),
                        created_at=item.created_at, sort_id=item.id) for item in items]
