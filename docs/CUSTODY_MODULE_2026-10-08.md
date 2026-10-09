# Zimmet Yonetimi - 2026-10-08

## Scope

Standalone, mobile-first personnel custody register at `/zimmet-yonetimi`.
The existing equipment lifecycle assignments are unchanged and are not copied
or synchronized into this register. No deployment has been performed for this change.

- Independent sidebar entry and permission-gated Mobile Center shortcut.
- Create with personnel, item, quantity, delivery date, optional serial,
  expected return date and note.
- Edit open records, including correction of an incorrect recipient.
- Receive the full quantity; returned records are read-only.
- Search, active/returned/all filters, 20-record pagination and scoped Excel export.
- No inventory, partial returns, signatures, attachments or purchase workflow.
- In-app assignment/return notifications only; no new email schedule.

## Access And Integrity

Permissions: `custody.view`, `custody.view_all`, `custody.manage`, `custody.export`.
Module flag: `custody_management`.

| Role | Default access |
| --- | --- |
| Super Admin | Manage/report within explicitly selected company |
| Management Representative | Company-wide manage/report |
| Management | Company-wide read/report |
| Department Manager, Staff, Viewer | Own linked personnel records only |

Own access never falls back to names. Ambiguous account links and duplicate
normalized personnel names fail closed; inactive personnel cannot receive new
assignments. Administrators can still receive their existing assignments back.
This defensive check does not certify the accuracy of legacy personnel identity
links; the user/personnel registry remains responsible for correct identity mapping.

Creation, editing, return and export are audited. Mutation and audit commit in one
transaction. UUID submission tokens suppress repeat saves, version checks reject
stale edits/returns, and normalized serial numbers cannot have two open assignments
in one company. The reference number uses creation year, not editable delivery date.

SQLite guards protect company/person/actor references, immutable identity and closed
records. Cross-company actors are permitted only for Super Admin; historical
creator authorization is not rechecked after a role change. Changed guard definitions
are refreshed in a savepoint. Existing soft-deletion administration paths remain usable.

## Local Verification

- Focused regression suite: **31 passed**, covering custody, migration, PWA,
  personnel/organization, existing equipment lifecycle and template CSRF coverage.
- Two SQLAlchemy legacy `Query.get()` warnings in existing personnel tests.
- Migration recheck after guard refresh change: **1 passed**.
- Custody route recheck against the final guards: **15 passed**.
- Browser workflow passed at **360, 768 and 1440 px**: create, edit, own-personnel
  read, return, filter, Excel download, no horizontal overflow, minimum 44 px
  form/button targets and no page JavaScript errors.
- Screenshot review identified excess header spacing and stretched icon buttons;
  the custody-only stylesheet was adjusted. The full browser workflow was repeated
  successfully at all three viewport sizes against the final code.
- Full repository suite and production smoke tests were not run.
- Planner review and independent security/QA static review identified actor scope
  and stale-trigger defects, which were corrected. Other initial agents reached
  usage limits; their incomplete work is not represented as verification.

Repeatable commands:

```powershell
.\venv\Scripts\python.exe -m pytest tests/test_custody.py tests/test_custody_migration.py tests/test_pwa.py tests/test_organization_personnel.py tests/test_equipment_lifecycle.py tests/test_security_hardening.py::test_server_rendered_post_forms_include_csrf_token -q
$env:PLAYWRIGHT_MODULE_PATH = (Resolve-Path '.tmp-playwright/node_modules/playwright').Path
node tests/ui/custody.mjs
```

The browser harness expects the isolated local preview on port 5100 with
`/__preview/login/management_representative` and `/__preview/login/department_staff`.
Those routes exist only in the temporary preview launcher, never the production app.
Screenshots and local test databases are under ignored Graphify input prefixes
`.tmp-*`; do not commit or deploy them. Graphify watches code saves locally and
has incorporated the custody files. Its graph is not evidence of test coverage.

## Migration And Release

Revision `202610080001`, parent `202610070001`; new `custody_records` table.
Runtime schema initialization follows the existing application convention. Migration
tests cover upgrade/downgrade/upgrade, metadata parity, preservation of legacy rows,
runtime-created rows and replacement of old guards.

Before an approved production release: take and verify a backup, rehearse the
migration on a protected copy, rerun the relevant tests, review the exact diff,
then verify the service and role/company-scoped HTTP workflows. Prefer roll-forward
after records exist. Downgrade drops custody records and must not be used as a
routine rollback. No production backup or deployment is claimed here.

## October 9 Release Preparation

- Leader explicitly approved production deployment.
- Independent QA rerun: 30 passed, two existing Query.get warnings.
- Production-backup migration rehearsal: 2 passed, no skips. Legacy schema/data
  fingerprints and foreign-key baseline preserved across upgrade/repeat-upgrade/
  downgrade/upgrade on the disposable copy; source backup unchanged.
- Preflight backup: `custody-20261009-preflight/volkaportal-backup-20261009-054320.zip`,
  59,345,422 bytes, 204 uploads, 206 checksums. Verify and restore dry-run passed.
  Off-host SHA-256 matched `a34d34591f2bded85cd12558d54aa14fabb9a25ae22d1fbdb11f8f65361202ba`.
- Compilation and pip dependency checks passed.
- Release helper grants the four scoped custody permissions idempotently and
  runs existing-account, company/role-scoped read-only smoke checks. Missing live
  roles are reported rather than creating synthetic production users.
- Final stopped-writer backup and external HTTPS checks remain mandatory. No
  checklist item or company module switch is changed by this release.
