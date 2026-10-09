# Zimmet Yonetimi - 2026-10-08

## Scope

Standalone, mobile-first personnel custody register at `/zimmet-yonetimi`.
The existing equipment lifecycle assignments are unchanged and are not copied
or synchronized into this register. Deployed October 9; production proof is below.

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
routine rollback. The completed production backup and deployment are recorded below.

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

## Production Proof - October 9

- Feature commit: `880b49d83062b6120467d9a754e1478aaf16c8e1`, pushed to GitHub
  and deployed by pinned fast-forward bundle. Production tracked worktree clean.
- Migration: `202610080001`; integrity OK, nine custody guards, zero synthetic
  custody records. Permission configuration audited and second invocation made
  no changes. Company module rows and sales checklist values unchanged.
- Stopped-writer backup:
  `/var/data/aksiyon-takip/backups/custody-20261009-deploy/volkaportal-backup-20261009-054741.zip`.
  59,345,841 bytes, 204 uploads, 206 checksums; verification and restore dry-run
  passed. No live restore was performed.
- Off-host restricted-access copy: `C:\Users\Asus\VolkaPortalBackups\20261009-custody`.
  SHA-256: `c99f420a30727132a11c5248c0b9449bcec968fb04dd58cc585e70d8a3940298`.
  Matching acknowledgment was required before code/database mutation.
- Application restarted at 08:48:53 Europe/Istanbul; application and reminder/
  webhook timers individually active. Post-start journal showed INFO startup
  entries only. SIGTERM worker messages occurred during the intentional stop,
  not after the new service started.
- Eleven existing-user/company smoke checks passed: dashboard, create-form
  permissions, Mobile Center shortcut, foreign-tenant session denial and
  unscoped-admin denial. No business records created or edited.
- Live role coverage is partial: company 1 lacks management-representative,
  management, staff and viewer accounts; company 3 lacks department-manager,
  staff and viewer accounts. Local six-role tests cover those scenarios.
- External HTTPS verified on `volkaportal.com`, `erprefabrik.volkaportal.com`
  and `sagiroglucelik.volkaportal.com`: login 200; unauthenticated custody page
  redirects to login; custody CSS 200 and exact feature-commit SHA-256 match.
- Release helper test: 1 passed; independent regression 30 passed; migration
  tests with production-copy rehearsal 2 passed. Prior browser verification
  covered 360/768/1440 px. No full-repository or physical-device guarantee.
- Initial deployment attempt stopped before mutation on Git ownership checks;
  Git operations were changed to run as the repository owner `aksiyon`. No
  global safe-directory exemption or force/reset operation was used.

Recovery: retain additive custody schema and data. Prefer forward fixes. If
containment is needed, explicitly disable `custody_management` only for affected
companies while recording their previous states; this leaves equipment lifecycle
unchanged. Database restore or downgrade is not an automatic rollback and can
discard post-backup business changes. No containment switch was changed here.
