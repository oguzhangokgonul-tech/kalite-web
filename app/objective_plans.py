"""Explicit, transactional execution plans originating from quality objectives."""
import hashlib
import json
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation

from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, url_for
from itsdangerous import BadSignature, URLSafeSerializer
from sqlalchemy import String, cast, select, update

from .audit import record_audit_event
from .extensions import db
from .models import Action, QualityObjective, User
from .objective_plan_models import ObjectivePlanLink
from .project_models import ProjectRecord, ProjectTask
from .projects import atomic
from .tenant import assign_current_company, current_company_id, scoped_query

bp = Blueprint('objective_plans', __name__, url_prefix='/kalite-hedefleri')
KINDS = {'project': 'Proje Planı Oluştur', 'action': 'Aksiyon Oluştur'}


def enabled(module):
    return bool(getattr(g, 'company_module_enabled', lambda key: False)(module))


def source_query():
    return scoped_query(QualityObjective.query, QualityObjective).filter_by(company_id=current_company_id())


def links(objective):
    return scoped_query(ObjectivePlanLink.query, ObjectivePlanLink).filter_by(
        company_id=current_company_id(), objective_id=objective.id)


def can_generate(objective, kind):
    from .routes import can_manage_quality_objective, can_view_quality_objectives, current_user_can
    from .projects import READ_PERMISSIONS
    if not (current_company_id() and objective.company_id == current_company_id()
            and enabled('quality_objectives') and can_view_quality_objectives()
            and can_manage_quality_objective(objective)):
        return False
    if kind == 'project':
        return (enabled('projects') and current_user_can('projects.create')
                and any(current_user_can(key) for key in READ_PERMISSIONS))
    return kind == 'action' and current_user_can('actions.create')


def objective_plans_context(objective):
    from .projects import READ_PERMISSIONS, STATUSES, has_permission, visible_projects
    from .routes import action_task_status, can_view_action
    existing = {link.kind: link for link in links(objective).all()}
    entries = []
    for kind, link in existing.items():
        entry = {'kind': kind, 'label': 'Proje Planı' if kind == 'project' else 'Aksiyon', 'url': None}
        if kind == 'project' and enabled('projects') and any(has_permission(key) for key in READ_PERMISSIONS):
            project = visible_projects().filter_by(id=link.project_id).first()
            if project:
                entry.update(url=url_for('projects.detail', project_id=project.id), number=project.project_no,
                             title=project.title, status=STATUSES[project.status], progress=project.progress)
        elif kind == 'action':
            action = scoped_query(Action.query, Action).filter_by(id=link.action_id, company_id=objective.company_id).first()
            if action and can_view_action(action):
                entry.update(url=url_for('main.action_detail', action_id=action.id), number=action.number_label,
                             title=action.title, status=action_task_status(action)[0])
        entries.append(entry)
    return {'execution_plans': entries,
            'plan_commands': [(kind, label) for kind, label in KINDS.items() if kind not in existing and can_generate(objective, kind)]}


def visible_source(target, kind):
    from .routes import can_view_quality_objectives
    if (not current_company_id() or target.company_id != current_company_id()
            or not enabled('quality_objectives') or not can_view_quality_objectives()):
        return None
    query = scoped_query(ObjectivePlanLink.query, ObjectivePlanLink).filter_by(company_id=current_company_id(), kind=kind)
    query = query.filter_by(project_id=target.id) if kind == 'project' else query.filter_by(action_id=target.id)
    link = query.first()
    return source_query().filter_by(id=link.objective_id).first() if link else None


def snapshot(objective):
    return {column.name: getattr(objective, column.name) for column in QualityObjective.__table__.columns}


def fingerprint(objective):
    return hashlib.sha256(json.dumps(snapshot(objective), sort_keys=True, default=str).encode()).hexdigest()


def reviewed_conditions(objective):
    values = snapshot(objective)
    conditions = []
    # SQLite server defaults omit fractional seconds, unlike ORM datetime binds.
    # Preserve the exact stored spelling without accepting a changed timestamp.
    timestamp_keys = [key for key, value in values.items() if isinstance(value, datetime)]
    raw = {}
    if db.session.get_bind().dialect.name == 'sqlite' and timestamp_keys:
        row = db.session.execute(select(*[
            cast(getattr(QualityObjective, key), String) for key in timestamp_keys
        ]).where(QualityObjective.id == objective.id,
                 QualityObjective.company_id == objective.company_id)).first()
        if row is None:
            abort(409, description='Hedef değişti. Formu yenileyin.')
        raw = dict(zip(timestamp_keys, row))
        for key, value in raw.items():
            if value is None or datetime.fromisoformat(value) != values[key]:
                abort(409, description='Hedef değişti. Formu yenileyin.')
    for key, value in values.items():
        column = getattr(QualityObjective, key)
        conditions.append(cast(column, String) == raw[key] if key in raw else column == value)
    return conditions


def serializer():
    return URLSafeSerializer(current_app.secret_key, salt='quality-objective-plan-v1')


def token_for(objective, kind):
    return serializer().dumps([current_company_id(), g.current_user.id, objective.id, kind, fingerprint(objective)])


def owners(kind, task=False):
    from .projects import READ_PERMISSIONS
    users = scoped_query(User.query, User).filter_by(company_id=current_company_id(), is_active=True).order_by(User.full_name, User.id).all()
    if kind == 'project':
        permission = 'projects.update' if task else 'projects.create'
        return [user for user in users if any(user.has_permission(key) for key in READ_PERMISSIONS)
                and (user.has_permission(permission) or user.has_permission('projects.manage'))]
    return [user for user in users if user.has_permission('actions.request_close_assigned')
            and not user.has_role('management_representative') and not user.has_permission('roles.manage')]


def field(name, limit, required=True):
    value = request.form.get(name, '').strip()
    if (required and not value) or len(value) > limit or any(ord(c) < 32 and c not in '\n\r\t' for c in value):
        raise ValueError('Zorunlu alanları ve metin uzunluklarını kontrol edin.')
    return value


def selected_user(name, users):
    try:
        user_id = int(request.form.get(name, ''))
    except ValueError:
        raise ValueError('Geçerli bir sorumlu seçin.') from None
    user = next((user for user in users if user.id == user_id), None)
    if not user:
        raise ValueError('Bu şirkette ilgili işlemi yapabilen aktif bir sorumlu seçin.')
    return user


@bp.route('/<int:objective_id>/plan/<kind>', methods=['GET', 'POST'])
@atomic
def create(objective_id, kind):
    from .projects import audit as project_audit
    from .routes import can_manage_quality_objective, can_view_quality_objectives, company_department_choices, reserve_action_number, add_action_history
    from .notifications import add_user_notification
    if not getattr(g, 'current_user', None):
        return redirect(url_for('main.login', next=request.full_path))
    if kind not in KINDS:
        abort(404)
    if not current_company_id() or not enabled('quality_objectives') or not can_view_quality_objectives():
        abort(403)
    objective = source_query().filter_by(id=objective_id).first_or_404()
    if objective.is_closed:
        abort(409, description='Tamamlanan veya arşivlenen hedef için yeni plan oluşturulamaz.')
    if not can_manage_quality_objective(objective) or not can_generate(objective, kind):
        abort(403)
    if links(objective).filter_by(kind=kind).first():
        return redirect(url_for('main.quality_objective_detail', objective_id=objective.id))
    eligible = owners(kind)
    task_owners = owners('project', task=True) if kind == 'project' else []
    departments = company_department_choices() if kind == 'action' else []
    values = request.form if request.method == 'POST' else {
        'title': objective.title[:160] if kind == 'action' else objective.title,
        'description': objective.description or '', 'owner_user_id': objective.owner_user_id or '',
        'task_owner_user_id': objective.owner_user_id or '', 'task_title': objective.title,
        'start_date': objective.period_start or min(date.today(), objective.period_end),
        'due_date': objective.period_end, 'department': objective.department or '',
    }
    if request.method == 'POST':
        try:
            payload = serializer().loads(request.form.get('objective_token', ''))
        except BadSignature:
            abort(409, description='Hedef formunu yenileyin.')
        if payload != [current_company_id(), g.current_user.id, objective.id, kind, fingerprint(objective)]:
            abort(409, description='Hedef bilgileri değişti. Formu yenileyin.')
        try:
            title = field('title', 160 if kind == 'action' else 240)
            description = field('description', 18000)
            owner = selected_user('owner_user_id', eligible)
            try:
                start, due = (date.fromisoformat(request.form.get(key, '')) for key in ('start_date', 'due_date'))
            except ValueError:
                raise ValueError('Geçerli başlangıç ve termin tarihi girin.') from None
            if due < start or due > objective.period_end or (objective.period_start and start < objective.period_start):
                raise ValueError('Plan tarihleri kalite hedefinin dönem aralığında olmalıdır.')
            if kind == 'project':
                task_owner = selected_user('task_owner_user_id', task_owners)
                task_title = field('task_title', 240)
                raw_hours = field('estimated_hours', 20, required=False)
                hours = None
                if raw_hours:
                    try:
                        hours = Decimal(raw_hours)
                    except InvalidOperation:
                        raise ValueError('Tahmini efor için geçerli bir sayı girin.') from None
                    if not hours.is_finite() or not Decimal('0.1') <= hours <= Decimal('10000') or hours != hours.quantize(Decimal('0.1')):
                        raise ValueError('Tahmini efor 0,1 ile 10000 saat arasında ve en fazla bir ondalık basamaklı olmalıdır.')
            else:
                department = field('department', 80)
                if department not in departments:
                    raise ValueError('Bu şirkete ait aktif bir departman seçin.')
        except ValueError as error:
            flash(str(error), 'danger')
            return render_template('quality_objectives/plan_form.html', objective=objective, kind=kind,
                label=KINDS[kind], values=values, users=eligible, task_users=task_owners, departments=departments,
                objective_token=token_for(objective, kind)), 400
        # Compare the reviewed source and lock it before allocating any target records.
        result = db.session.execute(update(QualityObjective).where(*reviewed_conditions(objective))
            .values(updated_at=datetime.now(UTC).replace(tzinfo=None)).execution_options(synchronize_session=False))
        if result.rowcount != 1:
            abort(409, description='Hedef değişti. Formu yenileyin.')
        source_text = f'{objective.objective_no}: {objective.title}\n{objective.metric_name}: {objective.target_direction} {objective.target_value} {objective.unit}\nDönem: {objective.period_start or "-"} - {objective.period_end}'
        full_description = f'{source_text}\nPlan Başlangıcı: {start}\nPlan Termini: {due}\n\n{description}'
        if kind == 'project':
            project = assign_current_company(ProjectRecord(title=title, description=full_description,
                owner_user_id=owner.id, created_by_user_id=g.current_user.id, start_date=start, due_date=due, status='draft'))
            db.session.add(project)
            db.session.flush()
            task = assign_current_company(ProjectTask(project_id=project.id, title=task_title, owner_user_id=task_owner.id,
                start_date=start, due_date=due, estimated_hours=hours, status='pending'))
            db.session.add(task)
            db.session.flush()
            project_audit(project, 'created')
            project_audit(task, 'created')
            link = assign_current_company(ObjectivePlanLink(objective_id=objective.id, kind=kind,
                project_id=project.id, created_by_user_id=g.current_user.id))
        else:
            action = assign_current_company(Action(action_number=reserve_action_number(company_id=objective.company_id),
                title=title, description=full_description, responsible_user_id=owner.id, responsible_owner=owner.full_name,
                department=department, termin_date=due))
            action.refresh_delay()
            db.session.add(action)
            db.session.flush()
            add_action_history(action, 'objective_linked', f'{objective.objective_no} kalite hedefinden oluşturuldu.', actor=g.current_user)
            link = assign_current_company(ObjectivePlanLink(objective_id=objective.id, kind=kind,
                action_id=action.id, created_by_user_id=g.current_user.id))
            add_user_notification(owner, f'{action.number_label} {action.title} kalite hedefi aksiyonu size atandı.',
                action=action, company_id=objective.company_id, source_key=f'objective:{objective.id}:action', due_date=due)
        db.session.add(link)
        db.session.flush()
        record_audit_event('ObjectivePlanLink', 'created', f'{objective.objective_no} uygulama planı',
            entity_id=link.id, company_id=objective.company_id,
            new_values={'objective_id': objective.id, 'kind': kind, 'project_id': link.project_id, 'action_id': link.action_id,
                        'source_fingerprint': payload[-1], 'source_snapshot': snapshot(objective),
                        'plan_start_date': start, 'plan_due_date': due}, commit=False)
        db.session.commit()
        flash('Proje ve ilk görev taslak olarak oluşturuldu.' if kind == 'project' else 'Hedeften aksiyon oluşturuldu.', 'success')
        return redirect(url_for('main.quality_objective_detail', objective_id=objective.id))
    return render_template('quality_objectives/plan_form.html', objective=objective, kind=kind,
        label=KINDS[kind], values=values, users=eligible, task_users=task_owners, departments=departments,
        objective_token=token_for(objective, kind))
