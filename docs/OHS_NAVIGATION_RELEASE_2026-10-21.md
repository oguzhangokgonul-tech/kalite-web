# Is Sagligi Navigation Release

## Scope

- Group ISG Notlari and ISG Aksiyonlari under the collapsible Is Sagligi sidebar heading.
- Preserve existing company/module visibility, routes and permissions.
- Open the group on related pages and highlight the current child; avoid also highlighting Home on shared OHS action details.
- Use existing navigation CSS/JS, including search, compact mode and mobile offcanvas.
- No model, schema, migration, dependency or business workflow changes.

## Verification

- Independent QA: `tests/test_ohs_navigation.py`: 7 passed. Two pre-existing SQLAlchemy Query.get deprecation warnings.
- Playwright at 390, 768 and 1440 pixels: collapse, keyboard, menu search, active links and compact/mobile navigation passed; no JS errors or horizontal overflow.
- Independent scoped QA/UX and Data/Migration/Release reviews completed.
- Graphify local code map updated; generated graph artifacts excluded from commit/deployment.

## Production Evidence

- User authorized deployment on 2026-10-21.
- Previous live commit: `278e95b90922979096b1624b0785dfcfe2b1802d`.
- Deployed commit: `895e6fad4585c6d62a0cd4418cdd47cbe6951609`.
- Exact-base, clean tracked tree, bundle ancestry and four-file allowlist verified before fast-forward. Unrelated local AGENTS/log/temp changes excluded.
- Fresh consistent full backup taken with app and scheduled writers stopped:
  `/var/data/aksiyon-takip/backups/ohs-nav.eeKAVi4D/archive/volkaportal-backup-20261021-061449.zip`.
- Off-host copy: `backups/ohs-navigation-20261021/volkaportal-backup-20261021-061449.zip` (not committed).
- Matching SHA-256: `bc0304601331407895c7a0685ed0f8cdf8a6e20dae8d649022d5dc1cc94f4dd6`.
- Backup package/integrity validation and isolated extraction passed; all 204 upload files verified. Restored SQLite integrity and revision `202610200001` verified; schema unchanged during authenticated rendering for companies 001 and 002.
- Authenticated tests used isolated restored data, not production user sessions. No synthetic production records or password changes.
- No migration or production restore executed.
- Platform and both company domains passed HTTPS landing/login and protected OHS route checks. Initial startup-only 502 cleared in the readiness retry; final checks passed.
- `aksiyon-takip.service`, `volkaportal-reminders.timer` and `volkaportal-webhooks.timer` active; new startup logs passed error scan. Temporary service environment file removed.
- Deployment helper returned `DEPLOY_OK` and exit 0.

## Rollback

If needed, revert only the navigation template change through a reviewed commit and restart the application. Do not restore old DB/uploads over newer customer records. No schema rollback is required.
