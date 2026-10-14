from app.extensions import db
from app.models import ActionSubTask, CompanyModule, Notification
from app.notifications import add_user_notification
from .helpers import create_company, create_user, login
from .test_action_management import make_action


def test_disabled_module_hides_legacy_and_related_notifications_everywhere(client):
    company = create_company('ohs-notification')
    owner = create_user('ohs-owner', company=company, role_key='department_staff')
    action = make_action(company, owner, action_category='ohs', title='Hidden safety record')
    general = make_action(company, owner, action_number=2, title='General visible record')
    sub = ActionSubTask(company_id=company.id, parent_action=action, title='Hidden sub action',
                        responsible_id=owner.id, created_by_user_id=owner.id)
    db.session.add(sub)
    db.session.flush()
    hidden = []
    for target in (f'/actions/{action.id}', f'/actions/{action.id}?source=email',
                   f'/actions/{action.id}#closure-request', f'/sub-actions/{sub.id}',
                   f'/sub-actions/{sub.id}#evidence'):
        item = Notification(company_id=company.id, user_id=owner.id, target_url=target,
                            message='Hidden ISG notification')
        db.session.add(item)
        hidden.append(item)
    hidden.append(add_user_notification(owner, 'Hidden ISG relationship', action=action))
    visible = add_user_notification(owner, 'General notification', action=general)
    db.session.commit()
    login(client, owner)
    assert client.get('/notifications/count').get_json()['count'] == len(hidden) + 1
    setting = CompanyModule.query.filter_by(company_id=company.id, module_key='ohs_actions').one()
    setting.is_enabled = False
    db.session.commit()
    assert client.get('/notifications/count').get_json()['count'] == 1
    for path in ('/notifications', '/', '/mobil', '/uzerime-atananlar?tab=actions'):
        response = client.get(path)
        assert response.status_code == 200
        body = response.get_data(as_text=True)
        assert 'Hidden ISG' not in body and 'Hidden safety record' not in body
    for item in hidden:
        assert client.get(f'/notifications/{item.id}/open').status_code == 404
        assert client.post(f'/notifications/{item.id}/read').status_code == 404
    assert client.post('/notifications/read-all').status_code == 302
    db.session.refresh(visible)
    assert visible.is_read
    for item in hidden:
        db.session.refresh(item)
        assert not item.is_read
    setting.is_enabled = True
    db.session.commit()
    assert client.get('/notifications/count').get_json()['count'] == len(hidden)


def test_disabled_action_cannot_create_in_app_notification(client):
    company = create_company('ohs-block-notification')
    owner = create_user('ohs-owner', company=company)
    action = make_action(company, owner, action_category='ohs')
    CompanyModule.query.filter_by(company_id=company.id, module_key='ohs_actions').one().is_enabled = False
    db.session.commit()
    assert add_user_notification(owner, 'Blocked', action=action, email_event='assignment') is None
    db.session.commit()
    assert Notification.query.count() == 0
