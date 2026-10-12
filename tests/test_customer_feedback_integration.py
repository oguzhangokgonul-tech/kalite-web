from datetime import date, datetime, timedelta

from flask import g

from app.extensions import db
from app.models import ComplaintRecord, INTERNAL_FEEDBACK_SOURCE
from app.reminder_sources import customer_portal_recipients
from app.routes import complaint_query, customer_feedback_query, assigned_customer_feedback_tasks
from .test_customer_feedback_portal import app, client, company, create_user, login


def test_internal_feedback_is_in_tasks_but_not_legacy_complaints(app, client):
    user = create_user('customer_portal.view', 'customer_portal.create', 'customer_portal.respond')
    record = ComplaintRecord(company_id=company().id, complaint_no='MGB-INT-1',
        source=INTERNAL_FEEDBACK_SOURCE, customer_name='Customer', subject='Feedback',
        description='Content', received_date=date.today() - timedelta(days=3),
        due_date=date.today() - timedelta(days=1),
        resolution_due_at=datetime.now() - timedelta(days=1),
        responsible_user_id=user.id, created_by_user_id=user.id, status='Yeni')
    db.session.add(record)
    db.session.commit()
    with app.test_request_context('/'):
        g.current_user = user
        g.current_company = company()
        assert complaint_query().filter_by(id=record.id).count() == 0
        assert customer_feedback_query().filter_by(id=record.id).count() == 1
        for scope in ('created', 'assigned'):
            rows = assigned_customer_feedback_tasks(scope)
            assert len(rows) == 1
            assert rows[0]['status_key'] == 'delayed'
        assert user.id in [recipient.id for recipient in customer_portal_recipients(record)]
        record.status = 'Kapatıldı'
        db.session.commit()
        assert customer_portal_recipients(record) == []
        assert assigned_customer_feedback_tasks('created')[0]['status_key'] == 'completed'
