# Changelog

Both ChatGPT/Codex and Claude Code must update this file and TASKS.md after every change.
Entries describe the final change, task IDs, validation and limitations. New entries go first.
The containing Git commit identifies an entry; do not invent its own SHA before committing.

## 2026-10-14 — Shared assistant handoff package

- Author: ChatGPT/Codex. Task: HANDOFF-01.
- Added PROJECT.md, ARCHITECTURE.md, AGENTS.md and TASKS.md as shared product context,
  implementation map, working agreement and prioritized release checklist.
- Added CLAUDE.md to direct Claude Code to the shared instructions, and this changelog.
- Consolidated the original roadmap and later owner changes, distinguishing implemented,
  partially verified and pending work. Corrected outdated README/preview descriptions.
- Required both assistants to update tasks and changelog with every change and hand off
  by exact canonical GitHub commit. Documented the old local/remote SHA divergence.
- Validation: inspected tracked source/configuration, migrations, tests and verification
  records; checked documentation links and diff whitespace. No application/schema changes.
- Limitations: this does not complete any pending production feature or back up household data.

## 2026-10-14 — AI assistant preview (historical baseline)

- Author: ChatGPT/Codex. Tasks: AI-01–03; AI-04 partial; AI-05 pending.
- Real OpenAI proposals, clarification, editable approval/dismissal history, atomic linked
  record creation, duplicate prevention, search review and saved reminder preferences.
- Clarified birthday attendee versus gift recipient; API key stored privately with approval.
- Canonical commits: da819bdcbeac24ffeea7699209cb3dda564c216e and
  704938dbdc96dab72a29c15e2780d192af60dd0f. CI 38568649471 passed. Real hosted generation,
  revision, edit and dismissal verified; no test activities/tasks approved in the real household.
- Limitations: no reminder delivery, recurrence, Google writes or integrated research.

## 2026-10-12–14 — Organizer and deployment preview (historical summary)

- Author: ChatGPT/Codex. Tasks: FND-01–02/04, FAM-01, CAL-01, TSK-01, UX-01,
  GGL-01, LUN-01–02, DASH-01–02; remaining live/release verification tracked in TASKS.md.
- Separate private GitHub/Render foundation, owner sign-in, PostgreSQL migrations and
  notes-only recovery; family/calendar/tasks/lunch workflows; inline quick forms and
  priority; parent invitations, read-only Google connections and unified events.
- Key verification: PostgreSQL CI 38313660452, 38462765334, 38499169193; real owner
  persistence, reversible lunch test and Chris's Google event verified in the preview.
- Limits: notes-only export, free expiring database, no unattended scheduler or delivery.
  See docs/verification.md and Git history for detailed evidence; this is not a release certification.
