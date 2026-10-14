# Changelog

Both ChatGPT/Codex and Claude Code must update this file and TASKS.md after every change.
Entries describe the final change, task IDs, validation and limitations. New entries go first.
The containing Git commit identifies an entry; do not invent its own SHA before committing.

## 2026-10-14 — Add an activity on several dates

- Author: Claude Code. Task: CAL-03.
- New "Add on several dates" page (linked from Add activity): enter details once, tick dates on a
  calendar grid (weekday columns can be selected at once), review every date with any problems
  and other plans that day, then add them all together. If any date has a problem, none are added.
- Migration 0008 adds Activity.batch so a repeated submit cannot add the dates twice.
- Validation: 72 organizer tests on local isolated PostgreSQL; deploy and migration checks;
  phone-width end-to-end check on local test data.
- Limitations: single-day activities only; up to 60 dates in a 120-day range per batch.

## 2026-10-14 — Overview task priority filters

- Author: Claude Code. Task: DASH-04 (owner request, ahead of CAL-03).
- Overview "Weekly priorities" (eight tasks) is now "Task priorities": every open task, high
  priority first, then by due date and time with undated tasks last. Quick filters All,
  High priority, Due in 7 days and Due in 1 day show counts; due filters include overdue work.
- Validation: 67 organizer tests on local isolated PostgreSQL; local visual check. No schema change.

## 2026-10-14 — Repeating activities and tasks

- Author: Claude Code. Tasks: CAL-02, TSK-02 (owner chose Option A for clock-change times).
- Activities can repeat daily, weekly on chosen days, monthly by date or nth weekday, or yearly,
  every N periods, ending never, on a date or after a count. Occurrences appear in week, month,
  Upcoming, Today and assistant date checks. Edit or delete only this occurrence, this and
  following, or all; a changed occurrence becomes its own linked activity.
- Clock changes: a skipped spring-forward time moves forward by the gap; a repeated fall-back
  time uses the first. The first date must match the pattern; occurrence edits that change the
  pattern start on its first matching date.
- Tasks can repeat from their due date; completing one creates the next once. Deleting offers
  skip-to-next or stop.
- Export format version 3 includes recurrence; version 2 exports still restore. Migration 0007;
  new dependency python-dateutil 2.9.0.post0 (with six 1.17.0).
- Validation: 66 organizer tests on local isolated PostgreSQL; deploy and migration checks;
  phone-width visual check on local test data.
- Limitations: "this and following" removes later single-date changes and restarts a count;
  preparation tasks link to the whole series; the assistant cannot propose repeats yet (AI-04).

## 2026-10-14 — Upcoming seven-day agenda

- Author: Claude Code. Task: DASH-03.
- Agenda view is now "Upcoming": a rolling seven days from the chosen date (default today)
  showing events and open due tasks with time, assignee, high priority and linked activity,
  high-priority tasks first, plus an Overdue list when today is in range. Overview's removed
  "Next seven days" section stays removed; week and month views are unchanged.
- Validation: 44 organizer tests on local isolated PostgreSQL; phone-width visual check on a
  local test database. No schema change.

## 2026-10-14 — Full household export and restore

- Author: Claude Code. Task: REC-01 (implemented; hosted recovery drill pending).
- Export format version 2 (`/foundation/export/`, `manage.py export_household`) now covers
  notes, family members, activities/participants, tasks, lunch plans and assistant plans and
  suggestions. Accounts, invitations, Google connections/tokens/event caches and usage counters
  are excluded.
- Restore validates every field and reference before writing, shows per-type counts and a
  time zone warning, keeps the preview server-side for one hour per parent (migration 0006,
  PendingRestore), rejects stale previews, saves a full recovery point, then replaces all
  organizer data atomically with new IDs and remapped references. Recovery copies are
  restorable exports. Version 1 notes exports still restore notes only. run_jobs removes
  previews older than one day. Settings and foundation copy describe the full export.
- Validation: 43 organizer tests on local isolated PostgreSQL 16, deploy check, migration drift
  check and collectstatic passed; GitHub Actions CI 38578064839 passed on 4c1323b.
  Deployment and the hosted drill are not yet verified.
- Limitations: AI plan generation does not bump the household version, so it is not detected
  as a stale-preview change; exports include parent emails as plan authors; no scheduled
  off-site export yet.

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
