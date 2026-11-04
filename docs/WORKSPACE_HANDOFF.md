# VolkaPortal cross-device handoff

Updated: 2026-11-04. This is a sanitized working summary, not a chat transcript,
credential store, database backup, or proof that a release is live.

## Project and decision record

- VolkaPortal is a multi-company Flask/SQLAlchemy ISO 9001 and factory-management
  application with a Windows desktop wrapper and installer.
- Product owner Oguzhan Gokgonul approves scope and production releases. Follow
  `AGENTS.md` for agent roles, tests, migration, backup, and release gates.
- Existing work spans actions, IF/DOF, documents, audits, calibration, people,
  OHS, purchasing, payments, contracts, feedback, mobile workflows, and other
  modules. Verify behavior in source/tests; prior chat requests do not prove a
  feature is finished or live.
- Sales-readiness and security progress are tracked in project docs. In
  particular, continue from `docs/SECURITY_VERIFICATION_CHECKLIST_2026-10-27.md`.
- Do not push raw conversations, customer data, local databases, backups,
  passwords, API keys, signing keys, or certificate PINs to Git.

## Current work

- Document revision publishing now requires a reason in both direct revision
  and request approval. Each `Document` version stores its own reason, and the
  archive copy retains the previous version's reason. Commit `9ac40aa` was
  deployed on 2026-11-04 with Alembic revision `202611040002`. The full backup
  `volkaportal-backup-20261104-164214.zip` (DB and 205 uploads) passed package
  verification and was copied off-host with matching SHA-256. Upgrade,
  downgrade, and upgrade passed on a live DB copy; 78 document rows remained.
  Focused document, upload, report, and training tests passed (36), followed by
  14 document tests after the final change. Production tenant-health, SQLite
  quick check, service status, logs, and unauthenticated HTTPS smoke passed.
  Authenticated production revision publishing was not exercised. Existing
  metadata edit can replace a file or revision number without using the
  archival revision flow; treat that as a separate document-control follow-up.
- OHS notes now accept multiple JPEG/PNG images on create and edit. Images are
  company-scoped, served only through authenticated note routes, validated and
  re-encoded to remove metadata, and individually removable. Commit `514d59c`
  was deployed on 2026-11-04 with Alembic revision `202611040001`. The full
  backup `volkaportal-backup-20261104-141427.zip` passed verification and was
  copied off-host with matching SHA-256. Migration rehearsal on a copy of the
  live DB, production tenant-health, service status, and unauthenticated HTTP
  smoke checks passed. On 2026-11-04 an actual HTTPS login on the `000` demo
  tenant uploaded two synthetic PNGs, read them in-session, denied anonymous
  image access, replaced one image, then removed all images and soft-deleted
  test note 5. The temporary least-privilege user 36 was deactivated. DB
  confirmed zero active images and no image files remained; service/log checks
  passed. Audit and soft-deleted metadata remain by design. Local 390/768/1440
  browser flows and 125 targeted/regression tests passed.
  Soft-deleted notes retain image files for now; agree a retention policy
  before automated cleanup.
- Action creation/edit forms no longer show the CAPA type selector. Existing
  action classifications are preserved on edit; new risk and IF/DOF actions
  receive their existing automatic classification. The application change was
  deployed as commit `896c59f` on 2026-11-04. Action/IF/DOF/risk regression
  tests passed (73), plus four focused tests and QA's OHS/tenant selection
  (44). The production full backup was verified and copied off-host before
  deployment; tenant-health, service status, and unauthenticated HTTP smoke
  checks passed. Authenticated production form use was not exercised.
- Desktop installer 0.1.6 is currently unsigned. Signing preparation is in
  commit `3a2e501`; it was not deployed as a signed release. See
  `desktop/README.md` for the build and verification sequence.
- A personally validated OV code-signing certificate was chosen first because
  a VolkaPortal business registration does not yet exist. The verified Windows
  publisher would use the owner's legal name, while the application may remain
  branded VolkaPortal. No certificate has been purchased or issued.
- The owner plans to obtain `admin@volkaportal.com`. Confirm the mailbox can
  receive an external test message before certificate application. The owner
  must personally handle purchase, terms, and identity verification. Never
  request certificate private keys or PINs in chat.
- Once a certificate is issued: bump desktop version, sign app/installer/
  uninstaller with timestamp, verify signatures and release manifest, test on
  a clean Windows machine, then request explicit production approval.
- Previous conversation included a server credential. It must be rotated
  through a secure channel; do not repeat or copy its value into this repo.

## Working from another computer

1. Sign in to the same ChatGPT account and workspace. Chat visibility and
   remote-control availability depend on account and feature settings; do not
   assume this existing task is synchronized automatically.
2. Clone the GitHub repository, check out `main`, then read `AGENTS.md`, this
   file, the relevant checklist, and `git status` before editing.
3. Install project dependencies using `README.md` and `desktop/README.md`.
   Local `.env`, databases, uploads, signing keys, tokens, and credentials are
   intentionally excluded from Git and require separate secure provisioning.
4. For each completed task, update the relevant checklist and this handoff
   with verified state only. Commit and push the intended files; on the other
   computer, pull before starting new edits. Never force-push or overwrite
   local changes to solve a sync conflict.
5. Do not equate `git push` with production deployment. Production needs its
   own backup, migration, tests, owner approval, service check, and rollback.

## Next session prompt

"Read AGENTS.md, docs/WORKSPACE_HANDOFF.md, and the current checklist. Check
git status and origin/main. Continue the requested task from verified code
state; preserve unrelated local changes and never expose secrets."

This file is a concise index. For exact historical conversation text, use the
chat history in the original account if available; do not commit an unreviewed
export because past messages may contain credentials and personal data.
