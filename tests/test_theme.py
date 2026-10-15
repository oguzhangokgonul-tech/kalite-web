"""Server-rendered theme contract; browser behavior is in test_theme_js.cjs."""

from html.parser import HTMLParser
from urllib.parse import parse_qs, urlsplit

import pytest

from app.extensions import db
from tests.helpers import create_company, create_user, login
from tests.test_pwa import create_company as create_tenant_company


class Page(HTMLParser):
    def __init__(self, response):
        super().__init__(convert_charrefs=True)
        assert response.status_code == 200
        self.tags = []
        self.feed(response.get_data(as_text=True))

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

    def select(self, tag=None, attribute=None):
        return [
            attrs for name, attrs in self.tags
            if (tag is None or name == tag)
            and (attribute is None or attribute in attrs)
        ]

    @property
    def key(self):
        roots = self.select("html")
        assert len(roots) == 1
        assert roots[0]["data-bs-theme"] == "light"
        return roots[0]["data-theme-key"]


def assert_toggle(page):
    toggles = page.select(attribute="data-theme-toggle")
    assert len(toggles) == 1
    button = toggles[0]
    assert button in page.select("button")
    assert button["type"] == "button"
    assert "hidden" in button  # No inactive control when JavaScript is disabled.
    assert button["aria-pressed"] == "false"
    assert button["aria-label"]
    assert button["title"] == button["data-dark-label"]
    assert button["data-light-label"] != button["data-dark-label"]
    assert not any(name.startswith("on") for name in button)
    icons = page.select(attribute="data-theme-icon")
    assert len(icons) == 1
    assert "bi-moon" in icons[0]["class"].split()
    assert icons[0]["aria-hidden"] == "true"


def assert_assets(page):
    scripts = [
        (index, attrs) for index, (tag, attrs) in enumerate(page.tags)
        if tag == "script"
        and urlsplit(attrs.get("src", "")).path == "/static/js/theme.js"
    ]
    assert len(scripts) == 1
    script_index, script = scripts[0]
    assert not {"defer", "async"}.intersection(script)
    assert script.get("type", "text/javascript") == "text/javascript"
    styles = [
        (index, attrs) for index, (tag, attrs) in enumerate(page.tags)
        if tag == "style" or (tag == "link" and "stylesheet" in attrs.get("rel", "").split())
    ]
    assert styles
    assert script_index < min(index for index, _ in styles)
    body_index = next(index for index, (tag, _) in enumerate(page.tags) if tag == "body")
    assert script_index < body_index
    assert styles[-1][0] < body_index
    assert urlsplit(styles[-1][1]["href"]).path == "/static/css/theme.css"
    assert sum(
        urlsplit(attrs.get("href", "")).path == "/static/css/theme.css"
        for _, attrs in styles
    ) == 1
    for url in (script["src"], styles[-1][1]["href"]):
        parsed = urlsplit(url)
        assert parsed.scheme == parsed.netloc == parsed.fragment == ""
        assert url.startswith("/static/")
        assert parse_qs(parsed.query) == {"v": ["20261015-1"]}


@pytest.mark.parametrize("authenticated", [False, True], ids=["login", "app-shell"])
def test_theme_render_contract(app, client, authenticated):
    app.config["ASSET_VERSION"] = "unrelated-environment-version"
    company = create_company("theme")
    company.brand_primary_color = "#1248aa"
    db.session.commit()
    if authenticated:
        user = create_user("theme-user", company=company, role_key="department_staff")
        login(client, user)
        page = Page(client.get("/mobil"))
        assert page.key == f"vp-theme:{company.id}:{user.id}"
    else:
        page = Page(client.get("/login"))
        assert page.key == "vp-theme:public:guest"
    assert_toggle(page)
    assert_assets(page)
    colors = [meta["content"] for meta in page.select("meta") if meta.get("name") == "theme-color"]
    assert colors == (["#1248aa"] if authenticated else ["#0d6efd"])


def test_base_navbar_also_renders_one_toggle(app, client):
    from flask import render_template_string

    @app.get("/_theme_base_test")
    def theme_base_test():
        return render_template_string(
            '{% extends "base.html" %}{% block head_extra %}'
            '<style id="page-specific-style">body { color: inherit; }</style>'
            '{% endblock %}'
        )

    page = Page(client.get("/_theme_base_test"))
    assert page.key == "vp-theme:public:guest"
    assert any(style.get("id") == "page-specific-style" for style in page.select("style"))
    assert_toggle(page)
    assert_assets(page)


def test_same_origin_accounts_and_guest_have_separate_keys(client):
    company_a = create_company("theme-a")
    company_b = create_company("theme-b")
    guest_key = Page(client.get("/login")).key
    keys = [guest_key]
    for username, company in (("theme-a1", company_a), ("theme-a2", company_a), ("theme-b1", company_b)):
        user = create_user(username, company=company, role_key="department_staff")
        login(client, user)
        key = Page(client.get("/mobil")).key
        assert key == f"vp-theme:{company.id}:{user.id}"
        assert Page(client.get("/mobil")).key == key
        keys.append(key)
    assert len(set(keys)) == 4
    with client.session_transaction() as session:
        session.clear()
    assert Page(client.get("/login")).key == guest_key


def test_same_admin_switching_company_changes_key(client):
    company_a = create_company("theme-admin-a")
    company_b = create_company("theme-admin-b")
    user = create_user("theme-admin", role_key="super_admin")
    keys = []
    for company in (company_a, company_b, company_a):
        login(client, user, company=company)
        key = Page(client.get("/mobil")).key
        assert key == f"vp-theme:{company.id}:{user.id}"
        keys.append(key)
    assert keys[0] != keys[1]
    assert keys[0] == keys[2]


def test_tenant_guest_keys_use_ids_not_host_or_display_names(client):
    keys = []
    for code, slug in (("THA", "theme-a"), ("THB", "theme-b")):
        company = create_tenant_company(code, '\"><script>alert("theme")</script>', slug)
        page = Page(client.get("/login", base_url=f"https://{company.primary_domain}"))
        assert page.key == f"vp-theme:{company.id}:guest"
        assert "onload" not in page.select("html")[0]
        assert_toggle(page)
        keys.append(page.key)
    assert keys[0] != keys[1]
    page = Page(client.get("/login", base_url="https://untrusted.example"))
    assert page.key == "vp-theme:public:guest"


def test_user_display_data_and_forged_company_cannot_control_key(client):
    company = create_company("theme-safe")
    foreign = create_company("theme-foreign")
    user = create_user(
        'theme-"-user', company=company, role_key="department_staff",
        full_name='\"><script>alert("theme")</script>',
    )
    login(client, user, company=foreign)
    page = Page(client.get("/mobil?theme=dark&theme_key=attacker"))
    assert page.key == f"vp-theme:{company.id}:{user.id}"
    assert set(page.select("html")[0]) == {"lang", "data-bs-theme", "data-theme-key"}


@pytest.mark.parametrize("asset,mimetypes", [
    ("js/theme.js", {"text/javascript", "application/javascript"}),
    ("css/theme.css", {"text/css"}),
])
def test_theme_assets_are_served_locally_without_authentication(client, asset, mimetypes):
    response = client.get(f"/static/{asset}?v=20261015-1")
    assert response.status_code == 200
    assert response.mimetype in mimetypes
    assert "Set-Cookie" not in response.headers
    assert response.data
