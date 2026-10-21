from html.parser import HTMLParser

import pytest

from app.extensions import db
from app.models import CompanyModule
from .helpers import create_company, create_user, login
from .test_action_management import make_action


class MenuParser(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.elements = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))

    def find(self, tag, key, value):
        return [attrs for kind, attrs in self.elements if kind == tag and attrs.get(key) == value]


@pytest.fixture()
def scenario(app, client):
    company = create_company('874')
    user = create_user('ohs-navigation', company=company, role_key='management_representative')
    login(client, user)
    return company, user


@pytest.mark.parametrize('path,active', [('/', None), ('/isg-notlari', '/isg-notlari'),
    ('/isg-notlari/yeni', '/isg-notlari'), ('/isg-aksiyonlari', '/isg-aksiyonlari'),
    ('/isg-aksiyonlari/yeni', '/isg-aksiyonlari')])
def test_group_and_active_state(client, scenario, path, active):
    response = client.get(path)
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'İş Sağlığı' in html
    parsed = MenuParser(html)
    toggle, = parsed.find('button', 'data-bs-target', '#occupationalHealthNav')
    panel, = parsed.find('div', 'id', 'occupationalHealthNav')
    assert toggle['aria-controls'] == 'occupationalHealthNav'
    assert toggle['aria-expanded'] == ('true' if active else 'false')
    assert ('show' in panel['class'].split()) == bool(active)
    for href in ['/isg-notlari', '/isg-aksiyonlari']:
        links = [a for a in parsed.find('a', 'href', href) if 'dashboard-subnav-item' in a.get('class', '')]
        assert len(links) == 1
        assert ('active' in links[0]['class'].split()) == (href == active)
    home = [a for a in parsed.find('a', 'href', '/') if 'dashboard-nav-item' in a.get('class', '')][0]
    assert ('active' in home['class'].split()) == (path == '/')


def test_shared_action_detail_selects_correct_group(client, scenario):
    company, user = scenario
    for number, category in [(1, 'ohs'), (2, 'general')]:
        action = make_action(company, user, action_number=number, action_category=category)
        response = client.get(f'/actions/{action.id}')
        assert response.status_code == 200
        parsed = MenuParser(response.get_data(as_text=True))
        toggle, = parsed.find('button', 'data-bs-target', '#occupationalHealthNav')
        assert toggle['aria-expanded'] == ('true' if category == 'ohs' else 'false')
        home = [a for a in parsed.find('a', 'href', '/') if 'dashboard-nav-item' in a.get('class', '')][0]
        assert ('active' in home['class'].split()) == (category == 'general')


def test_module_disabled_hides_whole_group(client, scenario):
    company, _ = scenario
    CompanyModule.query.filter_by(company_id=company.id, module_key='ohs_actions').one().is_enabled = False
    db.session.commit()
    html = client.get('/').get_data(as_text=True)
    assert 'occupationalHealthNav' not in html
    assert 'href="/isg-notlari"' not in html
    assert 'href="/isg-aksiyonlari"' not in html
