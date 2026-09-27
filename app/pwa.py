from functools import wraps
from io import BytesIO
import json
import re

from flask import Blueprint, Response, abort, current_app, g, redirect, render_template, request, url_for
import qrcode
from qrcode.image.svg import SvgPathImage

from .tenant import tenant_url_for_company


bp = Blueprint("pwa", __name__)
HEX_COLOR_PATTERN = re.compile(r"^#[0-9a-fA-F]{6}$")
DEFAULT_THEME_COLOR = "#0d6efd"


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if getattr(g, "current_user", None) is None:
            return redirect(url_for("main.login", next=request.full_path))
        return view(*args, **kwargs)

    return wrapped


def _company():
    return getattr(g, "current_company", None) or getattr(g, "tenant_company", None)


def _theme_color(company):
    value = str(getattr(company, "brand_primary_color", "") or "").strip()
    return value if HEX_COLOR_PATTERN.fullmatch(value) else DEFAULT_THEME_COLOR


def _has_permission(permission):
    user = getattr(g, "current_user", None)
    return bool(user and user.has_permission(permission))


def _module_enabled(module_key):
    checker = getattr(g, "company_module_enabled", None)
    return bool(checker(module_key)) if checker else True


def _quick_actions():
    actions = []
    if _has_permission("actions.create"):
        actions.append(
            {
                "label": "Yeni Aksiyon",
                "description": "Sorumlu, termin ve takip bilgileriyle aksiyon oluşturun.",
                "icon": "bi-plus-circle",
                "url": url_for("main.create_action"),
            }
        )
    if _module_enabled("if_management"):
        actions.append(
            {
                "label": "Yeni İF / DÖF",
                "description": "Uygunsuzluk veya düzeltici faaliyet kaydı açın.",
                "icon": "bi-shield-exclamation",
                "url": url_for("main.create_dof"),
            }
        )
    if _module_enabled("suggestions"):
        actions.append(
            {
                "label": "Yeni Öneri",
                "description": "İyileştirme önerinizi hızlıca kaydedin.",
                "icon": "bi-lightbulb",
                "url": url_for("main.create_suggestion"),
            }
        )
        if _has_permission("complaints.manage"):
            actions.append(
                {
                    "label": "Yeni Şikayet",
                    "description": "Şikayet kaydını ilgili iş akışına gönderin.",
                    "icon": "bi-chat-left-dots",
                    "url": url_for("main.create_complaint"),
                }
            )
    if _module_enabled("help_desk") and (
        _has_permission("helpdesk.create") or _has_permission("helpdesk.manage")
    ):
        actions.append(
            {
                "label": "Yeni İç Talep",
                "description": "Şirket içi destek veya hizmet talebi oluşturun.",
                "icon": "bi-headset",
                "url": url_for("help_desk.create"),
            }
        )
    return actions


@bp.get("/manifest.webmanifest")
def manifest():
    company = _company()
    company_name = str(getattr(company, "name", "") or "").strip()
    site_name = current_app.config.get("SITE_NAME", "VolkaPortal")
    name = f"{company_name} | VolkaPortal" if company_name else site_name
    payload = {
        "id": "/mobil",
        "name": name,
        "short_name": company_name[:24] if company_name else "VolkaPortal",
        "description": "Kalite ve kurumsal süreç yönetimi mobil merkezi",
        "lang": "tr",
        "dir": "ltr",
        "start_url": "/mobil",
        "scope": "/",
        "display": "standalone",
        "orientation": "any",
        "background_color": "#f5f8fc",
        "theme_color": _theme_color(company),
        "icons": [
            {
                "src": url_for("static", filename="brand/favicon/favicon-192x192.png"),
                "sizes": "192x192",
                "type": "image/png",
                "purpose": "any",
            },
            {
                "src": url_for("static", filename="brand/favicon/favicon-512x512.png"),
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "any",
            },
        ],
        "shortcuts": [
            {"name": "Mobil Merkez", "short_name": "Mobil", "url": url_for("pwa.mobile_hub")},
            {"name": "Görevlerim", "short_name": "Görevler", "url": url_for("main.assigned_tasks")},
            {"name": "Bildirimler", "short_name": "Bildirimler", "url": url_for("main.notifications")},
        ],
    }
    response = Response(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        content_type="application/manifest+json; charset=utf-8",
    )
    response.headers["Cache-Control"] = "no-cache, max-age=0"
    return response


@bp.get("/service-worker.js")
def service_worker():
    version = re.sub(r"[^a-zA-Z0-9._-]", "-", str(current_app.config.get("ASSET_VERSION", "1")))
    offline_url = url_for("pwa.offline")
    allowed_assets = [
        offline_url,
        url_for("static", filename="css/pwa.css"),
        url_for("static", filename="js/pwa.js"),
        url_for("static", filename="brand/favicon/favicon-192x192.png"),
        url_for("static", filename="brand/favicon/favicon-512x512.png"),
    ]
    script = f"""'use strict';
const CACHE_NAME = 'volkaportal-shell-{version}';
const OFFLINE_URL = {json.dumps(offline_url)};
const ALLOWED_ASSETS = Object.freeze({json.dumps(allowed_assets)});
const ALLOWED_PATHS = new Set(ALLOWED_ASSETS);

self.addEventListener('install', (event) => {{
  event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(ALLOWED_ASSETS)));
  self.skipWaiting();
}});

self.addEventListener('activate', (event) => {{
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((key) => key.startsWith('volkaportal-shell-') && key !== CACHE_NAME).map((key) => caches.delete(key))))
      .then(() => self.clients.claim())
  );
}});

self.addEventListener('fetch', (event) => {{
  const request = event.request;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  if (request.mode === 'navigate') {{
    event.respondWith(fetch(request).catch(() => caches.match(OFFLINE_URL)));
    return;
  }}

  if (!ALLOWED_PATHS.has(url.pathname)) return;
  event.respondWith(caches.match(request).then((cached) => cached || fetch(request)));
}});
"""
    response = Response(script, content_type="text/javascript; charset=utf-8")
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Service-Worker-Allowed"] = "/"
    return response


@bp.get("/offline")
def offline():
    response = Response(render_template("pwa/offline.html"), content_type="text/html; charset=utf-8")
    response.headers["Cache-Control"] = "public, max-age=300"
    return response


@bp.get("/mobil")
@login_required
def mobile_hub():
    return render_template(
        "pwa/mobile.html",
        quick_actions=_quick_actions(),
        company=_company(),
    )


@bp.get("/mobil/qr.svg")
@login_required
def mobile_qr():
    company = _company()
    if company is None:
        abort(404)
    target_url = tenant_url_for_company(company, url_for("pwa.mobile_hub"))
    if not target_url.startswith(("https://", "http://")):
        abort(503)

    image = qrcode.make(
        target_url,
        image_factory=SvgPathImage,
        box_size=8,
        border=3,
    )
    output = BytesIO()
    image.save(output)
    response = Response(output.getvalue(), content_type="image/svg+xml; charset=utf-8")
    response.headers["Cache-Control"] = "no-store, private"
    response.headers["Content-Disposition"] = "inline; filename=volkaportal-mobil-qr.svg"
    response.headers["X-QR-Target"] = target_url
    return response
