from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import CustodyRecord, PersonnelContact, AuditLog, CompanyModule, EquipmentAsset
from app.custody_models import custody_today
from tests.helpers import create_company, create_user, login, sheet_values


def setup_people():
    company = create_company('CUST')
    manager = create_user('cust-manager', company=company, role_key='management_representative')
    person = PersonnelContact(company_id=company.id, full_name='Çağrı Öztürk', is_active=True)
    db.session.add(person)
    db.session.commit()
    return company, manager, person


def payload(person, **overrides):
    data = dict(personnel_contact_id=str(person.id), item_name='Dizüstü Bilgisayar', serial_no='PC-001',
                quantity='1', assigned_date=custody_today().isoformat(), request_token=str(uuid4()))
    data.update(overrides)
    return data


def test_full_mobile_workflow_audit_duplicate_edit_return_report(client):
    company, manager, person = setup_people()
    login(client, manager)
    assert 'href="/zimmet-yonetimi"' in client.get('/mobil').get_data(as_text=True)
    data = payload(person)
    response = client.post('/zimmet-yonetimi/yeni', data=data)
    assert response.status_code == 302
    record = CustodyRecord.query.one()
    assert record.company_id == company.id
    assert client.post('/zimmet-yonetimi/yeni', data=data).location == response.location
    assert CustodyRecord.query.count() == 1
    assert client.get(response.location).status_code == 200
    data.update(version_id=str(record.version_id), item_name='İş Bilgisayarı')
    assert client.post(f'/zimmet-yonetimi/{record.id}/duzenle', data=data).status_code == 302
    assert record.item_name == 'İş Bilgisayarı'
    assert client.post(f'/zimmet-yonetimi/{record.id}/duzenle', data=data).status_code == 409
    returned = dict(version_id=str(record.version_id), returned_date=custody_today().isoformat(), return_note='Sağlam teslim alındı')
    assert client.post(f'/zimmet-yonetimi/{record.id}/iade', data=returned).status_code == 302
    assert client.post(f'/zimmet-yonetimi/{record.id}/iade', data=returned).status_code == 409
    assert client.get(f'/zimmet-yonetimi/{record.id}/duzenle').status_code == 409
    report = client.get('/zimmet-yonetimi/rapor?status=returned')
    assert report.status_code == 200
    assert person.full_name in sheet_values(report.data)[1]
    assert {a.action for a in AuditLog.query.filter_by(entity_type='CustodyRecord')} >= {'created', 'updated', 'returned'}
    assert EquipmentAsset.query.count() == 0


def test_person_link_visibility_tenant_forgery_and_inactive(client):
    company, manager, person = setup_people()
    other_company = create_company('OTHER')
    foreign = PersonnelContact(company_id=other_company.id, full_name='Foreign', is_active=True)
    db.session.add(foreign)
    db.session.commit()
    login(client, manager)
    assert client.post('/zimmet-yonetimi/yeni', data=payload(foreign)).status_code == 400
    client.post('/zimmet-yonetimi/yeni', data=payload(person))
    record = CustodyRecord.query.one()
    staff = create_user('staff', company=company, role_key='department_staff')
    login(client, staff)
    assert client.get(f'/zimmet-yonetimi/{record.id}').status_code == 404
    staff.personnel_contact_id = person.id
    db.session.commit()
    assert client.get(f'/zimmet-yonetimi/{record.id}').status_code == 200
    assert client.get('/zimmet-yonetimi/yeni').status_code == 403
    assert client.get('/zimmet-yonetimi/rapor').status_code == 403
    outsider = create_user('othermanager', company=other_company, role_key='management_representative')
    login(client, outsider)
    assert client.get(f'/zimmet-yonetimi/{record.id}').status_code == 404
    login(client, manager)
    person.is_active = False
    db.session.commit()
    assert client.post('/zimmet-yonetimi/yeni', data=payload(person, serial_no='NEW')).status_code == 400
    assert client.post(f'/zimmet-yonetimi/{record.id}/iade', data={'version_id': record.version_id, 'returned_date':custody_today().isoformat()}).status_code == 302


@pytest.mark.parametrize('role,write', [('super_admin',True),('management_representative',True),('management',False),('department_manager',False),('department_staff',False),('viewer',False)])
def test_six_role_and_module_controls(client, role, write):
    company = create_company('roles')
    user = create_user('role-user', company=None if role=='super_admin' else company, role_key=role)
    login(client, user, company=company)
    assert client.get('/zimmet-yonetimi').status_code == 200
    assert client.get('/zimmet-yonetimi/yeni').status_code == (200 if write else 403)
    CompanyModule.query.filter_by(company_id=company.id, module_key='custody_management').one().is_enabled = False
    db.session.commit()
    assert client.get('/zimmet-yonetimi').status_code == 403
    assert 'href="/zimmet-yonetimi"' not in client.get('/mobil').get_data(as_text=True)


def test_bad_input_serial_conflicts_and_serial_reuse(client):
    company, manager, person = setup_people()
    login(client, manager)
    bad = [dict(quantity='0'), dict(quantity='2'), dict(assigned_date=(custody_today()+timedelta(days=1)).isoformat()),
           dict(expected_return_date=(custody_today()-timedelta(days=1)).isoformat()), dict(item_name=' '),
           dict(personnel_contact_id=str(2**100)), dict(item_name='a'*181), dict(request_token='bad')]
    for override in bad:
        assert client.post('/zimmet-yonetimi/yeni', data=payload(person, **override)).status_code == 400
    assert CustodyRecord.query.count() == 0
    assert client.post('/zimmet-yonetimi/yeni', data=payload(person)).status_code == 302
    assert client.post('/zimmet-yonetimi/yeni', data=payload(person, serial_no='pc-001')).status_code == 409
    record = CustodyRecord.query.one()
    assert client.post(f'/zimmet-yonetimi/{record.id}/iade',data={'version_id':record.version_id,'returned_date':(custody_today()-timedelta(days=1)).isoformat()}).status_code == 400
    client.post(f'/zimmet-yonetimi/{record.id}/iade', data={'version_id':record.version_id,'returned_date':custody_today().isoformat()})
    assert client.post('/zimmet-yonetimi/yeni', data=payload(person)).status_code == 302


def test_csrf_and_unscoped_admin(app, client):
    _, manager, person = setup_people()
    login(client, manager)
    app.config['WTF_CSRF_ENABLED'] = True
    assert client.post('/zimmet-yonetimi/yeni', data=payload(person)).status_code == 302
    assert CustodyRecord.query.count() == 0
    assert client.post('/zimmet-yonetimi/yeni', data=payload(person), headers={'Accept': 'application/json'}).status_code == 400
    assert CustodyRecord.query.count() == 0
    admin = create_user('superadmin', role_key='super_admin')
    login(client, admin)
    assert client.get('/zimmet-yonetimi').status_code == 403


def test_guard_rejects_cross_company_and_audit_failure_rolls_back(client, monkeypatch):
    from app import custody
    company, manager, person = setup_people()
    login(client, manager)
    def broken(*args, **kwargs):
        raise RuntimeError('audit unavailable')
    monkeypatch.setattr(custody, 'record_audit_event', broken)
    response = client.post('/zimmet-yonetimi/yeni', data=payload(person))
    assert response.status_code == 500
    assert CustodyRecord.query.count() == 0
    other = create_company('guard')
    record = CustodyRecord(company_id=other.id, personnel_contact_id=person.id, created_by_user_id=manager.id,
                          request_token=str(uuid4()), item_name='Test', assigned_date=custody_today())
    db.session.add(record)
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_person_correction_duplicate_link_and_stable_reference(client):
    company, manager, person = setup_people()
    login(client, manager)
    client.post('/zimmet-yonetimi/yeni', data=payload(person))
    record = CustodyRecord.query.one()
    number = record.record_no
    corrected = PersonnelContact(company_id=company.id, full_name='Doğru Personel', is_active=True)
    db.session.add(corrected)
    db.session.commit()
    data = payload(corrected, version_id=record.version_id, assigned_date='2025-10-08')
    assert client.post(f'/zimmet-yonetimi/{record.id}/duzenle', data=data).status_code == 302
    assert record.personnel_contact_id == corrected.id
    assert record.record_no == number
    person_a = create_user('ambiguous-a', company=company, role_key='department_staff')
    person_b = create_user('ambiguous-b', company=company, role_key='department_staff')
    person_a.personnel_contact_id = person_b.personnel_contact_id = corrected.id
    db.session.commit()
    login(client, person_a)
    assert client.get(f'/zimmet-yonetimi/{record.id}').status_code == 404
    assert record.item_name not in client.get('/zimmet-yonetimi').get_data(as_text=True)


def test_own_export_does_not_expand_visibility_and_formula_is_text(client):
    from io import BytesIO
    import zipfile
    from xml.etree import ElementTree as ET
    company, manager, person = setup_people()
    login(client, manager)
    client.post('/zimmet-yonetimi/yeni', data=payload(person, item_name='=SUM(1,2)'))
    other = PersonnelContact(company_id=company.id, full_name='Hidden', is_active=True)
    db.session.add(other)
    db.session.commit()
    client.post('/zimmet-yonetimi/yeni', data=payload(other, item_name='HIDDEN-ITEM', serial_no='OTHER'))
    user = create_user('report-own', company=company, permissions=('custody.view','custody.export'))
    user.personnel_contact_id = person.id
    db.session.commit()
    login(client, user)
    response = client.get('/zimmet-yonetimi/rapor?status=all')
    rows = sheet_values(response.data)
    assert len(rows) == 2 and '=SUM(1,2)' in rows[1] and 'HIDDEN-ITEM' not in str(rows)
    with zipfile.ZipFile(BytesIO(response.data)) as archive:
        root = ET.fromstring(archive.read('xl/worksheets/sheet1.xml'))
        assert not root.findall('.//{http://schemas.openxmlformats.org/spreadsheetml/2006/main}f')
    assert AuditLog.query.filter_by(entity_type='CustodyRecord', action='exported').count() == 1


def test_ambiguous_names_do_not_expose_own_records(client):
    company, manager, person = setup_people()
    login(client, manager)
    client.post('/zimmet-yonetimi/yeni', data=payload(person))
    record = CustodyRecord.query.one()
    staff = create_user('same-name-staff', company=company, role_key='department_staff')
    staff.personnel_contact_id = person.id
    db.session.add(PersonnelContact(company_id=company.id, full_name=person.full_name, is_active=True))
    db.session.commit()
    login(client, staff)
    assert client.get(f'/zimmet-yonetimi/{record.id}').status_code == 404


def test_company_bound_superadmin_can_switch_and_historical_role_change(client):
    from app.models import Role
    company, manager, person = setup_people()
    home = create_company('ADMIN-HOME')
    admin = create_user('company-admin', company=home, role_key='super_admin')
    login(client, admin, company=company)
    assert client.post('/zimmet-yonetimi/yeni', data=payload(person)).status_code == 302
    record = CustodyRecord.query.one()
    assert record.company_id == company.id and record.created_by_user_id == admin.id
    assert client.post(f'/zimmet-yonetimi/{record.id}/iade', data={
        'version_id': record.version_id, 'returned_date': custody_today().isoformat()
    }).status_code == 302
    assert client.post('/zimmet-yonetimi/yeni', data=payload(person, serial_no='SECOND')).status_code == 302
    open_record = CustodyRecord.query.filter_by(returned_date=None).one()
    admin.roles = [Role.query.filter_by(key='department_staff').one()]
    db.session.commit()
    login(client, manager)
    assert client.post(f'/zimmet-yonetimi/{open_record.id}/iade', data={
        'version_id': open_record.version_id, 'returned_date': custody_today().isoformat()
    }).status_code == 302
