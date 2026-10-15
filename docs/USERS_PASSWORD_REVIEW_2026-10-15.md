# Users and Password Review - 2026-10-15

## Scope and Reproduction

- Report: password changes appeared to do nothing without a visible error.
- Reproduced: a short password blocks native browser submission (zero POST requests),
  but the edit form did not explain the minimum length or retain an inline error.
- A valid password saved and authenticated successfully in isolated tests. No evidence
  of a failed database password write was found. The user's exact password was not requested.

## Changes

- Create and edit show the configured minimum and maximum password lengths.
- Passwords use `autocomplete="new-password"`; an accessible show/hide button is available.
- Invalid fields have persistent inline messages and a linked error summary beside Save.
- Blank edit passwords remain unchanged. Passwords are never repopulated after failed POSTs.
- Successful password edits explicitly confirm the password changed.
- Password edits record `User/password_changed` with actor, target and company in the
  same transaction, without passwords or hashes. Rejected edits do not record success.
- No schema migration, permission expansion or existing credential reset is included.

## Verification

- Password management suite: 42 passed, including real login using the old/new passwords,
  create/edit length boundaries, empty/omitted values, roles, active/inactive, deletion,
  duplicate usernames, CSRF, tenant isolation and atomic rollback/audit checks.
- Root password audit retains platform ownership even with a company selected.
- Server validation errors appear inline and in a linked summary; unsuccessful
  requests never refill the submitted password.
- Related regression suite: 167 passed (profile synchronization, company admin,
  company-admin release checks, logout, tenant sessions and audit logging).
- Browser workflow at 390, 768 and 1440 px: create, real login, rejected short password,
  visible validation, show/hide, successful password change, old login rejected,
  new login accepted, blank password preserved, delete then login rejected.
- Browser workflows reported no page JavaScript errors or horizontal document overflow.
- Tests use disposable users and databases, never customer accounts.

## Agent Review and Limits

- Planner/security review identified hidden policy, missing persistent feedback and
  missing explicit password audit; an independent QA agent added the regression suite.
- Existing authenticated sessions are not revoked by a password change in this release.
  This remains a separate session-security hardening item; changing a password does
  reject the old password for new logins. Deactivation blocks existing session use.
- No claim is made that every possible account/device condition is defect-free.

## Release Gates

- Require clean live base `0483bc144313cc4866d61641952624728299b34e`, exact file allowlist,
  passing tests, full database/uploads backup and matching off-host SHA-256.
- Restore the real backup only into an isolated temporary database/uploads tree;
  compare every table and schema, and verify upgrading to head changes neither.
- Exercise CSRF-protected password edits and real old/new logins on synthetic accounts
  inside the restored copy using HTTPS and a matching Referer.
- After deployment verify service/timers, login pages and protected Users redirects on
  the platform and both company domains, and inspect startup errors.
- No migration rollback is necessary. A failed release must not discard live customer
  data; keep the verified backup and revert code through a reviewed follow-up commit.
