# Shared working agreement: ChatGPT/Codex and Claude Code

Applies to every assistant changing this repository. Explicit owner instructions take
precedence. Do not rely on private assistant memory for requirements or handoffs.

## Start each work session

1. Read PROJECT.md, ARCHITECTURE.md, TASKS.md, CHANGELOG.md and relevant docs/verification.md.
2. Inspect git status and recent commits. Fetch the canonical private repository and verify
   the incoming handoff commit. Preserve uncommitted work; never reset or overwrite it.
3. Work from the handed-off commit on a short-lived branch when practical. Take one usable
   increment from TASKS.md in dependency order; record its ID/owner/status before changes.
   Explicit user requests can reprioritize work; record the decision in TASKS.md.
4. Verify deployment/configuration constraints before selecting new services or dependencies.

## Required after EVERY change

- Update TASKS.md in the same handoff: progress, evidence, unfinished work, blockers and
  the next concrete step. Never mark an untested feature done or hide a partial implementation.
- Update CHANGELOG.md in the same handoff, including documentation-only changes: what
  changed, affected task IDs, validation and known limitations. Name the assistant responsible.
- Update PROJECT.md/ARCHITECTURE.md when product decisions or architecture change.
- Record meaningful verification in docs/verification.md. Run checks appropriate to the
  change; do not claim unrun checks passed. Documentation-only changes need link/content
  checks; application changes need relevant tests and CI. Migrations must be committed.
- Review the diff for credentials, personal data, unintended files and destructive changes.
- Commit source and documentation together. Push to the private repository, verify the
  remote commit and CI, then report the canonical full commit SHA as the handoff point.
  If push/checks are blocked, report that explicitly; do not present a local-only commit
  as an available GitHub handoff. Leave a clean worktree or list remaining changes.

These are mandatory repository instructions for both assistants, not a claim that a
particular tool enforces them. The owner/reviewer should reject handoffs missing updates.

## Handoff format

Report: repository, branch, full remote commit SHA, task IDs completed/partial, checks
run/results, deployment state, blockers and next task. Use the committed documents as
shared memory. The incoming assistant checks out that commit, reads the documents and
continues; no manual source-file copying between assistants. Never force-push shared history.
Do not have both assistants edit the same branch/worktree concurrently. Separate branches
and review/merge are required if parallel work is explicitly requested.

Historical note: this Windows workspace initially used the GitHub connector to publish
because a helper's Git subprocess hit EPERM. Its local commits have different SHAs from
GitHub despite matching source. **GitHub SHAs are canonical.** For a new assistant use a
fresh clone of GitHub; do not merge the historical local mirror or force-push it. When a
connector fallback is needed, use the current remote parent plus an expected-head lease,
verify the result, and record the canonical remote SHA in the handoff message. Document
entries reference earlier commits or their own commit via git log, never fabricated self-SHAs.

## Product and safety invariants

- Keep the separate Home Headquarters project; preserve previous apps, backups and grants.
  Any parent workspace sources/ folder is read-only synced reference material.
- No hard-coded family identities; no cross-household access; validate server inputs and AI
  output. Preserve CSRF/authentication and stale-edit protection on every write workflow.
- Models propose; users approve. No AI-triggered writes, invitations, messages or purchases.
- Real provider integration when configured; honestly label unavailable functionality.
  A saved reminder or heartbeat is not notification delivery. A search link is not research.
- No secrets in commits, source archives, screenshots, logs, chats or exports. Do not copy
  the real database to test environments. Fixtures belong in isolated test databases only.
- Stay on approved free preview hosting. Ask before incurring new recurring charges.
  Respect applicable consent/credential requirements without repeating existing approvals.
- Use PostgreSQL locally and hosted. Prefer the current simple server-rendered architecture.
- Never delete/regenerate applied migrations; add migrations. Verify recovery before any
  replacement of real household data. Source backups and database backups are different.
- Maintain the accepted compact Overview, inline quick forms and monthly lunch experience.

## Standard checks

Use the repository Python environment and an isolated PostgreSQL 17 database:

```sh
python manage.py check --deploy
python manage.py makemigrations --check --dry-run
python manage.py collectstatic --noinput
python manage.py test organizer --noinput
git diff --check
git status --short
```

See README.md for setup. A successful build is not evidence of real sign-in, calendar
consent, notification delivery or restore. Verify each relevant release gate separately.
