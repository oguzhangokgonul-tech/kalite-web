from functools import wraps
from datetime import date, datetime, UTC
import re
import unicodedata
from uuid import UUID, uuid4

from flask import Blueprint, abort, flash, g, redirect, render_template, request, send_file, url_for
from sqlalchemy import or_, false
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload
from sqlalchemy.orm.exc import StaleDataError

from .extensions import db
from .models import PersonnelContact, User
from .custody_models import CustodyRecord, custody_today
from .tenant import scoped_query, current_company_id, assign_current_company
from .audit import record_audit_event
from .notifications import add_user_notification

bp = Blueprint('custody', __name__, url_prefix='/zimmet-yonetimi')


def allowed(permission):
    return bool(g.current_user.is_active and g.current_user.has_permission(permission))


@bp.before_request
def guard():
    if not getattr(g, 'current_user', None):
        return redirect(url_for('main.login', next=request.full_path))
    if not current_company_id() or not any(allowed(p) for p in ('custody.view', 'custody.view_all', 'custody.manage')):
        abort(403)
    if not g.company_module_enabled('custody_management'):
        abort(403)


def records():
    query = scoped_query(CustodyRecord.query, CustodyRecord).filter_by(company_id=current_company_id())
    if not (allowed('custody.view_all') or allowed('custody.manage')):
        person_id = g.current_user.personnel_contact_id
        if person_id and not unambiguous_person_link(current_company_id(), person_id):
            person_id = None
        query = query.filter(CustodyRecord.personnel_contact_id == person_id if person_id else false())
    return query.options(joinedload(CustodyRecord.personnel))


def unambiguous_person_link(company_id, person_id):
    from .routes import normalize_personnel_name
    cache = request.environ.setdefault('custody.person_links', {})
    key = (company_id, person_id)
    if key not in cache:
        person = PersonnelContact.query.filter_by(company_id=company_id, id=person_id).first()
        valid = bool(person and person.is_active)
        if valid:
            # Legacy name-based linking must not expose records for ambiguous identities.
            name = normalize_personnel_name(person.full_name)
            names = db.session.query(PersonnelContact.full_name).filter_by(company_id=company_id).all()
            valid = bool(name) and sum(normalize_personnel_name(row[0]) == name for row in names) == 1
            valid = valid and User.query.filter_by(company_id=company_id, personnel_contact_id=person_id, is_active=True).count() == 1
        cache[key] = valid
    return cache[key]


def get_record(record_id):
    if record_id >= 2**63:
        abort(404)
    return records().filter_by(id=record_id).first_or_404()


def manage():
    if not allowed('custody.manage'):
        abort(403)


def atomic(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        try:
            return view(*args, **kwargs)
        except (IntegrityError, StaleDataError):
            db.session.rollback()
            abort(409, description='Kayıt değişti veya seri numarası halen zimmette. Listeyi yenileyip kontrol edin.')
        except Exception:
            db.session.rollback()
            raise
    return wrapped


def audit(record, action, old=None):
    db.session.flush()
    record_audit_event('CustodyRecord', action, record.record_no, entity_id=record.id,
                      company_id=record.company_id, old_values=old, new_values=snapshot(record), commit=False)


def snapshot(record):
    return {c.name: getattr(record, c.name) for c in CustodyRecord.__table__.columns}


def text(name, limit, required=False):
    value = request.form.get(name, '').strip()
    if (required and not value) or len(value) > limit or re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff]', value):
        raise ValueError('Zorunlu alanları ve metin uzunluklarını kontrol edin.')
    return value or None


def form_date(name, required=False):
    value = request.form.get(name, '').strip()
    if not value and not required:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError('Geçerli bir tarih girin.') from None


def values_from_form():
    assigned = form_date('assigned_date', True)
    due = form_date('expected_return_date')
    try:
        quantity = int(request.form.get('quantity', '1'))
    except ValueError:
        raise ValueError('Adet 1 ile 9999 arasında olmalıdır.') from None
    serial = text('serial_no', 100)
    serial_key = unicodedata.normalize('NFKC', serial).casefold() if serial else None
    if serial_key and len(serial_key) > 200:
        raise ValueError('Seri numarası çok uzun.')
    if not 1 <= quantity <= 9999 or (serial and quantity != 1):
        raise ValueError('Adet 1 ile 9999 arasında olmalıdır. Seri numaralı cihazlarda adet 1 olmalıdır.')
    if assigned > custody_today() or (due and due < assigned):
        raise ValueError('Teslim tarihi gelecekte, beklenen iade tarihi teslimden önce olamaz.')
    return dict(item_name=text('item_name', 180, True), serial_no=serial,
                serial_key=serial_key,
                quantity=quantity, assigned_date=assigned, expected_return_date=due, notes=text('notes', 2000))


def form_context(record=None):
    people = scoped_query(PersonnelContact.query, PersonnelContact).filter_by(company_id=current_company_id()).filter(
        or_(PersonnelContact.is_active.is_(True), PersonnelContact.id == record.personnel_contact_id) if record else PersonnelContact.is_active.is_(True)
    ).order_by(PersonnelContact.full_name, PersonnelContact.id).all()
    values = request.form if request.method == 'POST' else snapshot(record) if record else {'quantity': 1, 'assigned_date': custody_today().isoformat()}
    return dict(record=record, personnel=people, values=values, today=custody_today(),
                request_token=request.form.get('request_token') or str(uuid4()))


def notify(record, returned=False):
    if not unambiguous_person_link(record.company_id, record.personnel_contact_id):
        return
    users = User.query.filter_by(company_id=record.company_id, personnel_contact_id=record.personnel_contact_id, is_active=True).all()
    if len(users) != 1:
        return
    for user in users:
        if any(user.has_permission(p) for p in ('custody.view', 'custody.view_all', 'custody.manage')):
            add_user_notification(user, f'{record.record_no}: {record.item_name} ' + ('iade alındı.' if returned else 'adınıza zimmetlendi.'),
                company_id=record.company_id, source_key=f'custody:{record.id}:{"returned" if returned else "assigned"}:{user.id}',
                target_url=url_for('custody.detail', record_id=record.id))


def filtered():
    query = records()
    status = request.args.get('status', 'all')
    if status not in ('active', 'returned', 'all'):
        abort(400)
    if status != 'all':
        query = query.filter(CustodyRecord.returned_date.is_(None) if status == 'active' else CustodyRecord.returned_date.is_not(None))
    q = request.args.get('q', '').strip()[:180]
    if q:
        escaped = q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
        query = query.join(CustodyRecord.personnel).filter(or_(CustodyRecord.item_name.ilike(f'%{escaped}%', escape='\\'),
            CustodyRecord.serial_no.ilike(f'%{escaped}%', escape='\\'), PersonnelContact.full_name.ilike(f'%{escaped}%', escape='\\')))
    return query, q, status


@bp.get('')
def dashboard():
    query, q, status = filtered()
    pagination = query.order_by(CustodyRecord.assigned_date.desc(), CustodyRecord.id.desc()).paginate(per_page=20, error_out=False)
    stats = {'active': records().filter(CustodyRecord.returned_date.is_(None)).count(),
             'returned': records().filter(CustodyRecord.returned_date.is_not(None)).count()}
    return render_template('custody/dashboard.html', pagination=pagination, stats=stats, q=q, status=status,
                           can_manage=allowed('custody.manage'), can_export=allowed('custody.export'), today=custody_today())


@bp.route('/yeni', methods=['GET', 'POST'])
@atomic
def create():
    manage()
    if request.method == 'POST':
        try:
            try:
                token = str(UUID(request.form.get('request_token', '')))
            except ValueError:
                raise ValueError('Formu yenileyip tekrar deneyin.') from None
            existing = records().filter_by(request_token=token).first()
            if existing:
                return redirect(url_for('custody.detail', record_id=existing.id))
            person_id = int(request.form.get('personnel_contact_id', ''))
            if not 0 < person_id < 2**63:
                raise ValueError('Personel seçin.')
            person = scoped_query(PersonnelContact.query, PersonnelContact).filter_by(id=person_id, company_id=current_company_id(), is_active=True).first()
            if not person:
                raise ValueError('Şirketinize ait aktif bir personel seçin.')
            record = CustodyRecord(personnel_contact_id=person.id, created_by_user_id=g.current_user.id,
                                   request_token=token, **values_from_form())
            assign_current_company(record)
            db.session.add(record)
            audit(record, 'created')
            notify(record)
            db.session.commit()
            flash('Zimmet kaydedildi.', 'success')
            return redirect(url_for('custody.detail', record_id=record.id))
        except ValueError as error:
            db.session.rollback()
            flash(str(error) or 'Formu yenileyip tekrar deneyin.', 'danger')
            return render_template('custody/form.html', **form_context()), 400
    return render_template('custody/form.html', **form_context())


def version(record):
    if request.form.get('version_id') != str(record.version_id) or record.returned_date:
        abort(409, description='Bu kayıt güncellendi veya iade alındı. Sayfayı yenileyin.')


@bp.get('/<int:record_id>')
def detail(record_id):
    return render_template('custody/detail.html', record=get_record(record_id), can_manage=allowed('custody.manage'),
                           today=custody_today(), values={})


@bp.route('/<int:record_id>/duzenle', methods=['GET', 'POST'])
@atomic
def edit(record_id):
    manage()
    record = get_record(record_id)
    if record.returned_date:
        abort(409)
    if request.method == 'POST':
        version(record)
        old = snapshot(record)
        try:
            values = values_from_form()
            person_id = int(request.form.get('personnel_contact_id', ''))
            if not 0 < person_id < 2**63:
                raise ValueError('Personel seçin.')
            if person_id != record.personnel_contact_id:
                person = scoped_query(PersonnelContact.query, PersonnelContact).filter_by(id=person_id, company_id=current_company_id(), is_active=True).first()
                if not person:
                    raise ValueError('Şirketinize ait aktif bir personel seçin.')
                values['personnel_contact_id'] = person_id
        except ValueError as error:
            flash(str(error), 'danger')
            return render_template('custody/form.html', **form_context(record)), 400
        for key, value in values.items():
            setattr(record, key, value)
        record.updated_at = datetime.now(UTC).replace(tzinfo=None)
        audit(record, 'updated', old)
        if old['personnel_contact_id'] != record.personnel_contact_id:
            from .models import Notification
            Notification.query.filter_by(company_id=record.company_id).filter(Notification.source_key.like(f'custody:{record.id}:%')).delete(synchronize_session=False)
            notify(record)
        db.session.commit()
        return redirect(url_for('custody.detail', record_id=record.id))
    return render_template('custody/form.html', **form_context(record))


@bp.post('/<int:record_id>/iade')
@atomic
def return_record(record_id):
    manage()
    record = get_record(record_id)
    version(record)
    old = snapshot(record)
    try:
        returned = form_date('returned_date', True)
        note = text('return_note', 2000)
        if returned < record.assigned_date or returned > custody_today():
            raise ValueError('İade tarihi teslim tarihi ile bugün arasında olmalıdır.')
    except ValueError as error:
        flash(str(error), 'danger')
        return render_template('custody/detail.html', record=record, can_manage=True, today=custody_today(), values=request.form), 400
    record.returned_date, record.return_note, record.returned_by_user_id = returned, note, g.current_user.id
    audit(record, 'returned', old)
    notify(record, True)
    db.session.commit()
    flash('Zimmet iade alındı.', 'success')
    return redirect(url_for('custody.detail', record_id=record.id))


@bp.get('/rapor')
def export():
    if not allowed('custody.export'):
        abort(403)
    from .routes import build_simple_xlsx
    query, _, status = filtered()
    rows = [(r.record_no, r.item_name, r.serial_no or '', r.quantity, r.personnel.full_name,
             r.assigned_date.isoformat(), r.expected_return_date.isoformat() if r.expected_return_date else '',
             r.returned_date.isoformat() if r.returned_date else '', 'İade Edildi' if r.returned_date else 'Zimmette') for r in query.order_by(CustodyRecord.id).all()]
    rows = [tuple(re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]', '\ufffd', value) if isinstance(value, str) else value for value in row) for row in rows]
    workbook = build_simple_xlsx(('Zimmet No', 'Malzeme', 'Seri No', 'Adet', 'Personel', 'Teslim Tarihi', 'Beklenen İade', 'İade Tarihi', 'Durum'), rows, sheet_name='Zimmetler')
    record_audit_event('CustodyRecord', 'exported', 'Zimmet raporu', company_id=current_company_id(),
                       details={'row_count': len(rows), 'status': status})
    return send_file(workbook, as_attachment=True, download_name=f'zimmetler-{custody_today():%Y%m%d}.xlsx', mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
