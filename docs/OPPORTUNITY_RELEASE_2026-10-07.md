# Risk And Opportunity Portfolio

## Scope And Decisions

- Checklist: `module_risk_opportunity_portfolio`.
- Keep existing RiskRecord, OHS assessments and action workflows unchanged. Add opportunities under the existing risk-management package; preserve company module switches.
- Portfolio reads risks and opportunities using independent permissions and row visibility. Risk severity and opportunity benefit scores are not combined.
- Opportunity: owner, source reference, description, expected benefit, likelihood/benefit scores, plan, success criteria, target/review dates and optional existing action.
- Draft -> active -> realized/not realized. Activation requires a plan and success criteria. Result evaluation requires notes and evidence sources. Closed records are locked; reopening and archive require reasons.
- Review permission does not imply company-wide visibility. Authorized reviewers/managers may assess their own records; independent dual approval is not claimed. Prior results remain in atomic audit snapshots when reopening.
- Action linkage grants no access to that action and never automatically changes either workflow. Hidden action identifiers/titles must not appear in output.
- In-app notifications and My Tasks only; no new email schedule. Excel and period/custom Report Center exports use the same visibility policy.
- No certification claim. Automatic SWOT/PESTLE/context conversion, multiple linked actions and independent approval assignment are outside this step.

## Agent Work

- Planner/KYS/workflow: recommended separate opportunity lifecycle and preserving legacy risk semantics; highlighted success criteria, review dates, result history, action visibility and stale writes.
- Coordinator: accepted success criteria/review dates and explicit source reference; retained audit snapshots rather than a second evaluation-history store. Separate assigned reviewer/dual approval is not a requirement of this release.
- Coding agent: delivered model, schema, migration, blueprint, UI and core tests, then hit its usage limit. Coordinator completed verification and corrections; agent completion is not inferred.
- Coordinator: shared permissions, menu, registration, reports/tasks and release orchestration.
- [x] Independent QA, role/security and workflow review: final static review found no remaining blockers after corrections.
- [x] Independent data/migration review; production release checks remain pending.
- [x] UX/mobile/tablet/desktop verification: Playwright create/activate/roles/evaluate/export/reopen/archive passed at 390/768/1440 px, CSRF enabled; screenshots inspected for mobile portfolio and desktop result view.

## Release Gates

- [x] Focused and shared regression tests (scope and reruns below)
- [x] Populated-copy upgrade/downgrade/upgrade rehearsal (3 passed; never downgrade live)
- [x] Verified full backup and off-host checksum
- [ ] Clean scoped diff, commit and push
- [ ] Production migration, tenant/role smoke and HTTPS/service health
- [ ] Audited single-key checklist completion

## Recovery

Keep the additive schema and all business records. Do NOT redeploy the unmodified
baseline `e6cf404`: its action deletion removes evidence before the retained
opportunity reference guard rejects the database delete.

The available containment path keeps the tested release code and disables the
existing `risk_management` module switch only for affected companies, with a
recorded prior state and explicit operational approval. This hides legacy risk
management as well as the portfolio; it is not an opportunity-only switch.
The retained-schema/module-disabled regression verifies linked action evidence
remains protected even while portfolio routes are disabled. Restore the recorded
switch states after a forward fix; do not change other companies.

Any future code rollback build MUST retain both the opportunity reference guard
and commit-before-filesystem-cleanup action deletion fix, and pass the retained
schema deletion tests before use. No such baseline-compatible rollback build is
claimed here. A database restore can discard post-backup business changes and
requires a separate decision; never downgrade production as a rollback shortcut.

## Backup

- `/var/data/aksiyon-takip/backups/opportunity-20261007/volkaportal-backup-20261007-113511.zip`
- 59,338,921 bytes, 204 uploads; backup verification and restore dry-run passed.
- SHA-256: `27d0c3557f4c8730503c766b10997a8da8d2decc0980f1595aff1f54971a6d6d`. Off-host copy matched.
- Production baseline: `e6cf404`, migration `202610050004`, tracked files clean. Existing company 1 risk module uses the default enabled state (no explicit row); companies 2 and 3 explicitly disabled. Preserve these settings.

## Findings And Corrections

- Data reviewer found action deletion could remove evidence before a new opportunity FK guard rejected database deletion. Coordinator added an early link guard and, after independent QA identified a concurrent-link race, changed this endpoint to commit database deletion before filesystem cleanup. Failure preserves all attachments, legacy closure files, closure files and subtask evidence. Targeted fail/success cleanup tests passed (2); pre-existing-link preservation passed (1).
- Action choices, submitted links and linked-action display/export also check `can_view_action`. Existing shared risk-linked-action visibility policy is unchanged; this is not a new department-scoping claim. Targeted no-disclosure regression passed (1).
- Initial integration suite passed 18 tests; independent schema reviewer verified model/runtime/migration parity, 11 triggers and reference guards. Final broader regressions and release gates remain below.
- Focused combined suite passed 71 tests (opportunities, integration, legacy risk management), with four existing SQLAlchemy Query.get deprecation warnings. Subsequent targeted additions passed: no-disclosure (1), deletion commit/failure ordering (2), unavailable risk-archive filter (1).
- Independent QA also caught a misleading legacy risk archive filter; removed that option while retaining opportunity archive filtering. Existing risk/archive behavior is unchanged.
- No full-repository green claim. Existing unrelated deprecations or failures must be reported separately from this scope.

## Resumed Verification (October 8)

- Shared regression: 104 passed; one static CSRF check initially failed because
  it could not resolve tokens rendered through a Jinja macro. Hidden CSRF inputs
  are now explicit in each transition form. Final combined opportunities,
  integration and static CSRF suite: 70 passed, six legacy Query.get warnings.
- Recovery/module-disabled and commit-before-cleanup checks: four passed.
- Latest production-copy migration rehearsal: three passed, zero skips; an
  independent data reviewer verified archive CRC, 206 payload hashes, legacy
  schema/data preservation, seven indexes and 11 opportunity guards.
- Refreshed backup: `/var/data/aksiyon-takip/backups/opportunity-20261008/volkaportal-backup-20261008-062820.zip`.
  59,339,503 bytes, 204 uploads; backup verification and restore dry-run passed.
  Off-host SHA-256 matched: `bc219b982ff9e10eea48013ba6183aa9d75cf79e5f5c7383f2210fa05ee2322e`.
- Browser workflow rerun passed at 390/768/1440 px with CSRF enabled. Compilation
  and pip dependency checks passed. Independent QA confirmed staged corrections.
- Graphify is a local developer-only watcher (eight-second debounce, two workers,
  duplicate-instance mutex); IDE folder-open task requires workspace trust and
  automatic-task permission. Generated graphs are excluded from Git/deployment.
- DevOps review corrected release abort conditions and failure handling: active
  workers cause an explicit abort; failed post-mutation verification leaves
  writers stopped. Module/checklist baseline is captured after writers stop.
