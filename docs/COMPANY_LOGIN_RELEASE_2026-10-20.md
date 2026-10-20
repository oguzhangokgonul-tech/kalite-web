# Company-Code Login and Public Landing

## Approved Scope

- Anonymous visitors at the configured platform host (and local preview) see
  the approved dark dynamic landing at `/`. Authenticated `/` remains the
  existing dashboard. Tenant-host `/` retains its login redirect.
- Login offers active company codes only, preserving leading zeroes. Names,
  personnel and contact information are not exposed in the selector.
- Tenant-host login is fixed to that company. Posted conflicting codes and
  unknown host selections are rejected server-side.
- System Management (empty code) preserves the global super-admin login.
  Empty code does not grant a company user platform privileges.
- Existing password, CSRF, remember-me, safe-next, locale and legal-acceptance
  behavior remains. Authentication lookup, rate limits and attempts use the
  same company scope, separate from trusted host tenancy.
- Existing sessions of ordinary users are revoked when their company is
  deactivated. Company IDs in the session cannot override user ownership.
- No model/migration changes. Existing unique `Company.code` is reused.

## Verification

- Expanded new authentication suite: 31 passed.
- Independent tenant/session/logout/security suite: 47 passed.
- Six-role and cross-company direct-document access checks are included in the
  expanded authentication suite. User-password regression tests passed.
- Workflow security: 10 passed after updating the anonymous root expectation to
  public landing and retaining a protected-document redirect assertion.
- Landing server tests: 8 passed. Independent localization tests: 8 passed.
- Legal policy suite: 6 passed, 2 failed. Both failures reproduce identically at
  baseline `62860104` in a clean detached worktree: admin access and revision
  publishing expect 200 but receive 403. These are pre-existing test/authorization
  issues, not newly introduced regressions; their root cause remains open.
- Browser flow passed at 390, 768 and 1440px: public landing, login link,
  company selector, wrong-company rejection, cleared password, retained code,
  remember-me and successful dashboard redirect.
- Original landing checks: ten viewport configurations and both story scroll
  directions passed; see `LANDING_REVIEW_2026-10-19.md`.
- Full repository suite not claimed; scoped authentication/tenant regression
  coverage is broader than the changed routes.

## Release Gates

Live preflight confirmed base `62860104f97127c3fcc6a5efd6d5e30d4960a9fc`,
clean tracked worktree, active app/reminder/webhook timers and adequate storage.
Credentials must never be stored in repository, deploy scripts or reports.

1. Explicit file allowlist, scoped commit and Git bundle.
2. Detached candidate worktree; preserve existing service configuration.
3. Pause background timers, wait for workers and stop the application.
4. Full database/uploads backup, archive validation and isolated restore.
5. Candidate-code migration upgrade must be a no-op: identical schema/rows.
6. Authenticate against the restored copy, never change live user passwords.
7. Copy backup off-host and verify SHA-256 before activating the candidate.
8. Fast-forward, restart, HTTPS landing/login/protected-route checks and logs.
9. Resume timers and confirm service health.

No live schema downgrade or destructive Git operation is permitted. A failed
post-merge release stays stopped until a reviewed code-only revert commit is
applied and health checks pass; do not restore old data over newer records.

## Status

Implementation and scoped verification completed. Deployment and live
verification results pending; do not treat this document as proof of deployment.
