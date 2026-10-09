# Mobile performance release - 2026-10-09

## Scope and findings

- Static assets previously triggered tenant initialization and navigation task queries. Production profiling found 58 SELECTs for a warm authenticated styles.css request; HTML /mobil also used 58 SELECTs.
- PWA metadata and notification polling did not need HTML navigation counts, but calculated them anyway.
- Core Bootstrap resources used an external CDN. Sidebar tooltips were initialized eagerly on touch devices and every tooltip was visited on scroll.
- Server CPU and memory were not saturated during the baseline measurement. This does not exclude intermittent network or device bottlenecks.

## Changes

- Public static requests bypass application user/task initialization, with five-minute public caching and conditional responses. No customer files or authenticated pages are included.
- Navigation counts run when rendering HTML, once per request. Tenant, active-user and legal checks remain request-time checks. No cross-request permission or task cache is introduced.
- Bootstrap 5.3.3 and Bootstrap Icons 1.11.3 are served locally, unchanged, with their licenses. The versions are not upgraded.
- Sidebar tooltips initialize only for compact desktop navigation; scrolling hides only the visible tooltip. Hidden/offline tabs skip notification polling.
- Optional nginx include compresses public CSS/JS/SVG only. Private HTML remains private/no-store.
- No schema, company package, sales checklist or business workflow change.

## Verification

- 32 focused Python tests passed: performance, PWA, custody and role navigation.
- 26 further Python tests passed: assigned tasks, logout, tenant sessions and security hardening. Existing SQLite datetime deprecation warnings remain.
- Playwright at 360, 768 and 1440 pixels passed menu/search, submenu, compact desktop navigation, icon fonts, no horizontal overflow, fixture creation and logout checks. Mobile run used 4x CPU slowdown.
- Local mobile cold resource transfer was 1,040,882 bytes; a subsequent module navigation transferred 5,015 bytes, with common stylesheets served from browser cache. These are local uncompressed resource measurements, not a promise of equivalent production latency gains.
- Candidate production-copy profiling: static CSS zero SELECTs, PWA metadata two SELECTs. HTML counts remain current, with 58/62 SELECTs for the measured pages.
- Latest backup copied off-host, SHA-256 matched, ZIP CRC verified. No-op migration to existing 202610080001 on a disposable backup copy preserved the database file hash and integrity.
- Agent delegation was attempted, but three agents hit usage limits. Checks were completed by the coordinating agent; independent agent sign-off is not claimed.
- Full repository test suite and physical-device frame-rate profiling were not run. No 60/144 FPS guarantee is made.

## Deployment and recovery

Deployment pending at this commit. Require a fresh stopped-writer backup, restore dry-run, off-host checksum, pinned fast-forward release, nginx configuration backup and nginx -t before reload. Verify service, timers, all three company/public hosts and compressed assets afterwards.

No schema rollback is needed. On a regression, restore the saved nginx configuration, validate/reload it, and deploy a reviewed revert commit for the application changes; preserve business data. Static cache freshness is bounded to five minutes.
