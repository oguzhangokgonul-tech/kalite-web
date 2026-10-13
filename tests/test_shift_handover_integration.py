from flask import g

from app.extensions import db
from app.models import CompanyModule, Notification
from app.routes import (report_center_export_data, assigned_task_row,
                        report_definition_access_allowed, REPORT_CENTER_REPORTS)
from app.shift_handover import assigned_task_rows
from tests.helpers import login
from tests.test_shift_handover import people, create_record, transition


def test_mobile_and_tasks_receive_lifecycle(client, people):
    record = create_record(client, people)
    assert 'href="/vardiya-devir-teslimi"' in client.get('/mobil').get_data(as_text=True)
    assert transition(client, record, 'send').status_code == 302
    login(client, people['receiver'])
    with client.application.test_request_context('/vardiya-devir-teslimi'):
        g.current_user = people['receiver']
        g.current_company = people['company']
        g.company_module_enabled = lambda key: True
        rows = assigned_task_rows('assigned', assigned_task_row)
        assert [r['reference_no'] for r in rows] == [record.record_no]
        assert assigned_task_rows('created', assigned_task_row) == []
    assert transition(client, record, 'receive').status_code == 302
    assert Notification.query.filter_by(user_id=people['sender'].id, company_id=people['company'].id).count() == 1
    with client.application.test_request_context('/vardiya-devir-teslimi'):
        g.current_user = people['receiver']
        g.current_company = people['company']
        g.company_module_enabled = lambda key: True
        assert assigned_task_rows('assigned', assigned_task_row) == []
    CompanyModule.query.filter_by(company_id=people['company'].id, module_key='shift_handover').one().is_enabled = False
    db.session.commit()
    assert 'href="/vardiya-devir-teslimi"' not in client.get('/mobil').get_data(as_text=True)


def test_report_center_uses_identity_scope_and_export_permission(client, people):
    record = create_record(client, people)
    definition = next(d for d in REPORT_CENTER_REPORTS if d['key'] == 'shift_handover')
    for user_key, expected_count in [('sender', 1), ('receiver', 1), ('stranger', 0), ('foreign', 0)]:
        with client.application.test_request_context('/raporlar'):
            g.current_user = people[user_key]
            g.current_company = people['foreign_company'] if user_key == 'foreign' else people['company']
            g.company_module_enabled = lambda key: True
            data = report_center_export_data('shift_handover')
            assert data is not None
            assert len(data['rows']) == expected_count
            if expected_count:
                assert record.record_no in data['rows'][0]
    with client.application.test_request_context('/raporlar'):
        g.current_user = people['reader']
        g.current_company = people['company']
        g.company_module_enabled = lambda key: True
        assert report_definition_access_allowed(definition)
        assert report_center_export_data('shift_handover') is None


def test_record_number_survives_draft_date_change(client, people):
    from tests.test_shift_handover import form_data
    record = create_record(client, people)
    number = record.record_no
    response = client.post(f'/vardiya-devir-teslimi/{record.id}/duzenle', data=form_data(
        people, version_id=str(record.version_id), handover_date='2025-01-01'))
    assert response.status_code == 302
    assert record.record_no == number
