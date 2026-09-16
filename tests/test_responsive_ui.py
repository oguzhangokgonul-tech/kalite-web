from app.extensions import db
from app.models import QualityTestRecord
from tests.helpers import create_company, create_user, login


def test_device_assets_and_tablet_menu_are_available(client):
    company = create_company("RESP")
    user = create_user("responsive-manager", company=company, role_key="management_representative")
    login(client, user, company)
    body = client.get("/").get_data(as_text=True)
    assert "css/responsive.css" in body
    assert "js/responsive.js" in body
    assert 'dashboard-sidebar offcanvas-xl offcanvas-start' in body
    assert 'dashboard-mobile-menu-button btn btn-icon d-xl-none' in body
    assert client.get("/static/css/responsive.css").status_code == 200
    script = client.get("/static/js/responsive.js")
    assert script.status_code == 200
    assert script.mimetype in {"text/javascript", "application/javascript"}


def test_concrete_viewer_sees_results_but_not_measurement_actions(client):
    company = create_company("RESP-Q")
    viewer = create_user("responsive-viewer", company=company, role_key="viewer")
    record = QualityTestRecord(company_id=company.id, test_type="beton-deneyi",
                               record_number=1, title="Deney", strength_2_day=17.4)
    db.session.add(record)
    db.session.commit()
    login(client, viewer, company)
    body = client.get("/kalite-deneyleri/beton-deneyi").get_data(as_text=True)
    assert f'quality_record_extra_{record.id}' in body
    assert f'/{record.id}/olcum"' not in body
    assert f'/{record.id}/olcum-duzenle"' not in body
    editor = create_user("responsive-editor", company=company, permissions=("quality.create",))
    login(client, editor, company)
    body = client.get("/kalite-deneyleri/beton-deneyi").get_data(as_text=True)
    assert f'/{record.id}/olcum"' in body
    assert f'/{record.id}/olcum-duzenle"' in body
