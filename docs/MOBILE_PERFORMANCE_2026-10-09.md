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

Deployed application commit `305eee27d67d7d379063fe4de3bb695dc7ba6f7a`, followed by nginx compression scope fix `b69257b08204363cf13967085222886c31292654`. The existing global nginx setting also compressed HTML; the include now explicitly disables inherited compression at server scope, enabling it only in `/static/`.

- Stopped-writer backup: `mobile-performance-release.JjACuRIH/archive/volkaportal-backup-20261009-061804.zip`, 59,349,016 bytes, 204 uploads. Checksum verification, database integrity and restore dry-run passed.
- Off-host copy SHA-256 matched: `c2c81503fcfafe95cc93dd1dc85a5befd0714d7f5f60c61d020c6ec9853998d1`.
- Existing migration head `202610080001`, company module flags, sales checklist values and custody row count preserved. Tenant health checks passed.
- Live authenticated smoke exercised 11 available company/role combinations, including mobile hub and custody access. Seven role/company combinations had no live users; production role coverage is partial, with synthetic role coverage in the Python suite.
- nginx configuration backed up and validated before reload. Application, nginx and both reminder/webhook timers individually verified active. Warning/error journal check since release start returned no entries.
- External HTTPS checks passed on `volkaportal.com`, `erprefabrik.volkaportal.com` and `sagiroglucelik.volkaportal.com`: login 200, protected mobile route redirects to login, six local assets 200, five-minute public asset cache, no asset cookies, icon font signature correct. Login remains no-store and uncompressed.
- Same-server warm CSS probe changed from 58 SELECTs / approximately 48 ms to zero SQL / approximately 2 ms. Manifest and service-worker requests now use two SELECTs / approximately 3-4 ms. These measure server request handling, not complete mobile page rendering.
- Live gzip transfer: main CSS 286,033 -> 43,837 bytes; Bootstrap CSS 232,803 -> 31,840 bytes; Bootstrap JS 80,721 -> 23,995 bytes; icon CSS 85,875 -> 13,690 bytes; navigation JS 6,923 -> 2,296 bytes. Fonts retain their existing compressed format.
- Graphify local AST map refreshed; generated graph, private backups, temporary scripts and logs excluded from commits.

No schema rollback is needed. On a regression, restore the saved nginx configuration, validate/reload it, and deploy a reviewed revert commit for the application changes; preserve business data. Static cache freshness is bounded to five minutes.
