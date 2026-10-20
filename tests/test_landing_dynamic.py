from html.parser import HTMLParser
from urllib.parse import urlsplit

import pytest
from flask import url_for

from tests.helpers import create_company, create_user, login


class LandingMarkup(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.elements = []
        self.text = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))

    def handle_data(self, text):
        self.text.append(text)


def landing(client):
    response = client.get('/landing-dynamic-preview')
    assert response.status_code == 200
    return LandingMarkup(response.get_data(as_text=True))


def test_public_landing_has_real_unique_fragment_targets(client):
    page = landing(client)
    ids = [attrs['id'] for _, attrs in page.elements if 'id' in attrs]
    assert len(ids) == len(set(ids))
    assert {'top', 'platform', 'flow', 'modules', 'demo'} <= set(ids)
    for tag, attrs in page.elements:
        href = attrs.get('href', '')
        if tag == 'a' and href.startswith('#'):
            assert href[1:] in ids
    assert len([tag for tag, _ in page.elements if tag == 'h1']) == 1


def test_public_landing_uses_honest_demo_contact_and_preview_labels(client):
    page = landing(client)
    text = ''.join(page.text)
    assert 'Temsili operasyon' in text
    assert 'Temsili ekran' in text
    assert 'Referanslar (\u00d6rnek g\u00f6sterim)' in text
    assert 'Canl\u0131 ekran' not in text
    assert '\ufffd' not in text
    assert not any(tag == 'form' for tag, _ in page.elements)
    assert any(tag == 'a' and attrs.get('href', '').startswith(
        'mailto:info@volkaportal.com?subject=') for tag, attrs in page.elements)


def test_public_landing_assets_exist_and_versioned(client):
    page = landing(client)
    assets = [attrs.get('src') or attrs.get('href') for tag, attrs in page.elements
              if tag in {'img', 'script', 'link'}]
    selected = [path for path in assets if path and (
        'landing_dynamic.' in path)]
    assert len(selected) == 2
    for path in selected:
        assert urlsplit(path).query
        response = client.get(path)
        assert response.status_code == 200
        assert response.data
    for tag, attrs in page.elements:
        if tag == 'img':
            assert attrs.get('alt') or attrs.get('aria-hidden') == 'true'
            assert client.get(attrs['src']).status_code == 200


def test_no_script_navigation_and_flow_content_are_present(client):
    page = landing(client)
    panels = [attrs for _, attrs in page.elements if 'data-scene' in attrs]
    steps = [attrs for _, attrs in page.elements if 'data-scene-trigger' in attrs]
    assert len(panels) == len(steps) == 5
    assert all('hidden' not in panel for panel in panels)
    assert [panel['data-scene'] for panel in panels] == [step['data-scene-trigger'] for step in steps]
    menu = next(attrs for tag, attrs in page.elements if tag == 'nav')
    assert 'hidden' not in menu
    assert not any('data-flow-tab' in attrs for _, attrs in page.elements)
    classes = ' '.join(attrs.get('class', '') for _, attrs in page.elements)
    assert 'vp-dynamic-product' in classes
    assert 'vp-dynamic-stage' in classes
    assert not any('landing-dashboard.png' in attrs.get('src', '') for _, attrs in page.elements)


@pytest.mark.parametrize('role', [None, 'department_staff', 'management_representative'])
def test_landing_account_link_respects_session(app, client, role):
    if role:
        company = create_company('landing')
        user = create_user('landing-test', company=company, role_key=role)
        login(client, user, company)
    page = landing(client)
    text = ''.join(page.text)
    assert ('Panele Git' in text) == bool(role)
    assert ('Giri\u015f Yap' in text) == (not role)
    with app.test_request_context():
        expected = url_for('main.dashboard' if role else 'main.login')
    assert any(tag == 'a' and attrs.get('href') == expected for tag, attrs in page.elements)


def test_landing_does_not_expose_company_user_names(client):
    company = create_company('landing-isolation', name='Private Company Sentinel')
    user = create_user('landing-secret', company=company, role_key='department_staff',
                       full_name='Private User Sentinel')
    login(client, user, company)
    page = landing(client)
    text = ''.join(page.text)
    assert 'Private Company Sentinel' not in text
    assert 'Private User Sentinel' not in text
