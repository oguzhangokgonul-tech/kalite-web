# Organization Context Release

Work started October 5; final release verification continued October 7, 2026 (Europe/Istanbul).

## Scope

- Extend the existing stakeholder-management package with organization context records. Do not duplicate stakeholder/requirement tables or expand their row permissions.
- Shared workspace tabs: organization context and existing interested-party matrix. Separate `context.*` permissions; unchanged company module switches.
- Scope, internal/external issues, evidence sources, strategy, climate relevance and its rationale; owner and analysis/review dates.
- Drafts can be incomplete. Review requires complete text, a decided climate relevance, review note, authorized reviewer and timestamp.
- Reviewed content is locked; reasoned reopen/archive, inactive-owner recovery, optimistic locking and atomic audit/notification behavior.
- In-app assignments and review tasks, direct Excel and period/custom Report Center exports. No new automatic email schedule.
- Existing stakeholder routes now require a selected company; helpers cannot return all-company rows to an unscoped global admin.
- No automatic certification or legal-compliance claim. Context and party records are independently maintained; no fabricated record linkage.

## Agent Checks

- Planner/KYS/workflow: confirmed reuse of the stakeholder workspace with separate context lifecycle.
- Coding agent delivered scoped backend, model, guards, migration and tests, but reached its usage limit before its final report. Coordinator and independent QA verify the resulting files.
- Independent role/security review found the existing unscoped stakeholder access issue; fixed at blueprint/query boundaries and regression-tested.
- Independent data/migration/release review found no code blocker. Warned that production downgrade deletes new-module records; it must not be used for normal rollback.
- Independent QA/security and browser checks are release gates, not inferred from implementation completion.

## Release Gates

- [x] Final core tests and independent QA review
- [x] Shared regression/integration tests: 74 passed, seven existing `utcnow()` deprecation warnings
- [x] Browser flows and inspected screenshots at 390/768/1440 px
- [x] Fresh full backup, verify, restore dry-run and off-host checksum match
- [x] Migration rehearsal: minimal, populated runtime table and production backup (3 passed)
- [x] Commit/push and verified production migration
- [x] Tenant/role, public HTTPS/static asset and service/log checks
- [x] Audited single-key checklist completion

## Backup And Recovery

Final backup: `/var/data/aksiyon-takip/backups/context-20261007/volkaportal-backup-20261007-085704.zip`.
Size: 59,333,737 bytes; 204 uploads.
SHA-256: `a73c7d67d2aebb038217734daaaba0e03e8054b086dd2c5326bf6f767c5fb33e`.
Verification and restore dry-run succeeded; off-host copy checksum matched.

Migration `202610050004` follows `202610050003`. Rehearsals preserve existing data/schema objects and compare all new-table fields across repeated upgrade. Downgrade intentionally drops the new table and is tested only on disposable copies. Production recovery retains the expanded schema for code rollback; restoring business data needs a separate decision accounting for records created after backup.

## Verification Boundary

Browser checks include creation, review, export, reopening, archiving, cross-workspace tabs and keyboard focus with CSRF enabled. Chrome screenshot capture required `--disable-gpu` on this Windows test host; no application rendering setting was changed. Role switching in the test navigates to `about:blank` first to prevent outstanding page requests from overwriting the test session.

Independent QA initially passed 127 core tests and identified a SQLite whitespace-only required-text gap (HTTP validation already rejected it). Runtime and migration guards now reject Unicode whitespace-only titles, reviewed required fields and archive reasons; final tests and the three migration rehearsals are rerun after that change.

Independent recheck verified the whitespace fix, runtime/migration parity and FK-off protections. Two additional guards increased the expected trigger count from seven to nine; the corresponding two migration tests were updated and passed.

Final focused run: 143 passed and two stale trigger-count assertions failed. Those assertions were corrected, and their targeted rerun passed (2 tests). Subsequent combined rerun of migration compatibility, integration and whitespace guards passed all 27 tests. Final independent staged-diff review found no new critical regression; it did not replace the production release gates.

Production smoke initially reached its final unscoped-access check but returned login redirects: its default localhost client did not send the configured `.volkaportal.com` session cookie. The release script now uses the tenant base HTTPS host for both session and requests, confirms that host does not select a company, and still requires strict HTTP 403. Added host-only/shared-domain cookie regression cases; the updated integration suite passed 19 tests. Application authentication settings were not weakened.

Only focused and shared regressions are claimed. A full-repository green run is not claimed; earlier release notes list unresolved failures outside this scope. Live test-client smoke is separate from real HTTPS/service checks. Missing live-role users are reported as partial coverage; no fake production users are created.

## Production Proof (October 7)

- Feature commit `674e6ff`; release-script cookie correction `f74e881`. Both pushed and deployed by verified fast-forward; tracked live files clean.
- Verified backup above was copied off-host and rehearsed successfully: 3/3 migration tests, including populated production-copy preservation.
- Production revision `202610050004`, SQLite integrity `ok`, all nine context triggers present. No synthetic business records created (context table: zero rows).
- Default role grants configured idempotently (second run: no changes); tenant-health passed.
- Live smoke passed 11 role/company checks, cross-company session rejection and unscoped global-admin denials. Live role coverage is partial: company 1 lacks management representative, management, staff and viewer users; company 3 lacks department manager, staff and viewer users. Local role tests cover the six-role matrix independently.
- HTTPS login returned 200 on `volkaportal.com`, `erprefabrik.volkaportal.com` and `sagiroglucelik.volkaportal.com`. New CSS response checksums matched the deployed file on all three hosts.
- App and reminder/webhook timers active. Post-start application log has no errors; earlier SIGTERM messages correspond to deliberate service stops for backup/deployment.
- `sales_readiness:module_context_stakeholders=1`, with one `ContextRelease/checklist_completed` audit record. No other checklist item marked.
- Existing module switches preserved: company 1 enabled, companies 2 and 3 disabled. For those companies the stakeholder package must be deliberately enabled before this workspace is offered.
- Next uncompleted planned item: `module_risk_opportunity_portfolio` (Riskler ve Firsatlar Portfoyu).
