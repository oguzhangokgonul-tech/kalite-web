from html.parser import HTMLParser
from urllib.parse import urlsplit

import pytest

from tests.helpers import create_company, create_user, login


class _SidebarLinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_sidebar = False
        self.sidebar_depth = 0
        self.links = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "aside" and attributes.get("id") == "dashboardSidebar":
            self.in_sidebar = True
            self.sidebar_depth = 1
            return
        if not self.in_sidebar:
            return
        if tag == "aside":
            self.sidebar_depth += 1
        if tag == "a" and attributes.get("href"):
            self.links.append(attributes["href"])

    def handle_endtag(self, tag):
        if self.in_sidebar and tag == "aside":
            self.sidebar_depth -= 1
            if self.sidebar_depth == 0:
                self.in_sidebar = False


@pytest.mark.parametrize(
    ("role_key", "username"),
    (
        ("super_admin", "superadmin"),
        ("management_representative", "nav-management-representative"),
        ("management", "nav-management"),
        ("department_manager", "nav-department-manager"),
        ("department_staff", "nav-department-staff"),
        ("viewer", "nav-viewer"),
    ),
)
def test_each_role_can_open_every_visible_sidebar_link(client, role_key, username):
    company = create_company(f"NAV-{role_key}")
    user = create_user(username, company=None if role_key == "super_admin" else company,
                       role_key=role_key, title="Kalite")
    login(client, user, company)

    dashboard = client.get("/")
    assert dashboard.status_code == 200
    parser = _SidebarLinkParser()
    parser.feed(dashboard.get_data(as_text=True))
    paths = {
        urlsplit(link).path + (f"?{urlsplit(link).query}" if urlsplit(link).query else "")
        for link in parser.links
        if link.startswith("/")
    }

    assert paths
    for path in sorted(paths):
        response = client.get(path)
        assert response.status_code == 200, (role_key, path, response.status_code)
