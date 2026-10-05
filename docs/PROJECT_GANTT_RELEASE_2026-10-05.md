# Project Gantt Release - 2026-10-05

## Scope

- Added a project timeline with task bars, dated milestones, a today marker and year filtering.
- Added required milestone acceptance criteria, completion evidence, audited reopen, and project completion blocking until all milestones and active tasks are complete.
- Added optional task effort estimates and a per-owner summary. The summary does not calculate staff capacity; overlap counts use open tasks only.
- Added milestones and estimates to each project's Excel export.
- Added tenant-scoped routes, optimistic concurrency checks, SQLite guards and migration `202610050001`.
- Included project progress from both non-cancelled tasks and milestones.

## Verification

- Focused Python regression: 34 passed, 1 skipped. The skipped test needs a production backup archive.
- Backup migration rehearsal: 2 passed against the final off-host production backup copy. Existing project/task fields were compared across upgrade; the archive hash stayed unchanged.
- Responsive Playwright workflow: passed at 390, 768 and 1440 px, including milestone creation/acceptance, Gantt view, completion, Excel download and archive.
- `git diff --check`, Python compile and `pip check`: passed.
- Full suite before the final CSRF template-helper rename: 794 passed, 5 failed, 2 skipped. Four remaining failures are in company onboarding/environmental reminders/hazardous substances/quality objective reminders; they are outside this change and also failed when isolated. The fifth was the static CSRF source check; it passed in the focused run after the helper rename. The full suite was not rerun after that final fix.

## Production Proof

- Application commit: `80c2d0393e9c321436ced12cd5559d33ebafcd37`.
- Previous database revision: `202610030001`; deployed revision: `202610050001`.
- `tenant-health`: all reported checks passed.
- Project role smoke: 6 checks passed. Some active companies do not have every smoke-test role configured; the script reports these roles without live users rather than creating accounts.
- `volkaportal.com`, `erprefabrik.volkaportal.com`, and `sagiroglucelik.volkaportal.com` login routes returned HTTP 200.
- `aksiyon-takip.service`, `volkaportal-reminders.timer`, and `volkaportal-webhooks.timer` are active.
- Sales readiness flags: `module_project_planning=1`, `module_project_gantt=1`.

## Backup and Recovery

- Full backup: `/var/data/aksiyon-takip/backups/project-gantt-final-20261005/volkaportal-backup-20261005-082832.zip`.
- Off-host SHA-256: `ff2bc7b5ec556d9e6408bf107c89259c49a1cc73eeeb360b07e91b4a07d93392`; matches the server copy.
- `backup-verify`, restore dry-run, SQLite `quick_check` and `integrity_check`: passed.
- Migration test on the off-host copy: 2 passed; the source archive was not modified.
- Do not run `flask db downgrade` in production. This migration removes milestone data and task effort values. If application rollback is needed, retain the expanded database schema and roll back code only; restore data only with an explicit recovery decision.
