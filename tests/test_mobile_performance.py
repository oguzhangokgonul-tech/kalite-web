from sqlalchemy import event

from app.extensions import db
from app.models import Notification
from tests.helpers import create_company, create_user, login


def test_static_assets_do_not_load_user_or_query_database(app, client, monkeypatch):
    from app import routes
    company = create_company('perf')
    user = create_user('perf-user', company=company, role_key='management_representative')
    login(client, user)
    def forbidden():
        raise AssertionError('Static assets must not initialize application schema')
    monkeypatch.setattr(routes, 'ensure_personnel_identity_columns', forbidden)
    statements = []
    def count(*args):
        statements.append(args[2])
    event.listen(db.engine, 'before_cursor_execute', count)
    try:
        first = client.get('/static/css/styles.css')
        assert first.status_code == 200
        assert first.cache_control.public and first.cache_control.max_age == 300
        assert 'Cookie' not in first.headers.get('Vary', '')
        assert 'Set-Cookie' not in first.headers
        assert client.head('/static/css/styles.css').status_code == 200
        assert client.get('/static/css/styles.css', headers={'If-None-Match': first.headers['ETag']}).status_code == 304
        assert client.get('/static/missing-asset.css').status_code == 404
        assert statements == []
    finally:
        event.remove(db.engine, 'before_cursor_execute', count)


def test_navigation_counts_only_on_html_and_auth_stays_live(app, client, monkeypatch):
    from app import routes
    company = create_company('perf-count')
    user = create_user('perf-user', company=company, role_key='management_representative')
    login(client, user)
    calls = []
    def badge():
        calls.append(True)
        return 7
    monkeypatch.setattr(routes, 'assigned_tasks_badge_count', badge)
    for path in ('/manifest.webmanifest', '/service-worker.js', '/notifications/count', '/mobil/qr.svg'):
        response = client.get(path)
        assert response.status_code == 200
        assert 'private' in response.headers['Cache-Control']
        assert calls == []
    response = client.get('/mobil')
    assert response.status_code == 200 and len(calls) == 1
    assert 'assigned-count-badge">7<' in response.get_data(as_text=True)
    assert response.cache_control.no_store and response.cache_control.private
    user.is_active = False
    db.session.commit()
    assert client.get('/mobil').status_code == 302
    assert len(calls) == 1


def test_foreign_tenant_denial_and_notification_count_are_preserved(client):
    company = create_company('perf-a')
    other = create_company('perf-b')
    user = create_user('perf-staff', company=company, role_key='department_staff')
    foreign_user = create_user('other-staff', company=other, role_key='department_staff')
    db.session.add(Notification(company_id=company.id, user_id=user.id, message='own', is_read=False))
    db.session.add(Notification(company_id=other.id, user_id=foreign_user.id, message='foreign', is_read=False))
    db.session.commit()
    login(client, user)
    assert client.get('/notifications/count').json['count'] == 1
    base = f'https://{other.slug}.volkaportal.com'
    with client.session_transaction(base_url=base) as session:
        session['user_id'] = user.id
        session['company_id'] = company.id
    response = client.get('/mobil', base_url=base)
    assert response.status_code == 302 and '/login' in response.location


def test_core_resources_are_same_origin(client):
    response = client.get('/login')
    html = response.get_data(as_text=True)
    assert 'https://cdn.jsdelivr.net/npm/bootstrap' not in html
    for path in ('vendor/bootstrap-5.3.3/bootstrap.min.css', 'vendor/bootstrap-5.3.3/bootstrap.bundle.min.js',
                 'vendor/bootstrap-icons-1.11.3/bootstrap-icons.min.css', 'vendor/bootstrap-icons-1.11.3/fonts/bootstrap-icons.woff2'):
        assert client.get('/static/' + path).status_code == 200
