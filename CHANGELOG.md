# Changelog

Both ChatGPT/Codex and Claude Code must update this file and TASKS.md after every change.
Entries describe the final change, task IDs, validation and limitations. New entries go first.
The containing Git commit identifies an entry; do not invent its own SHA before committing.

## 2026-10-16 — Quick approval on the Overview

- Author: Claude Code. Task: AI-08 (owner request).
- After the assistant prepares suggestions from the Overview, its tile shows their titles with
  tick boxes (titles only) and "Add N selected", plus "Review in detail" and "Start a new request". Quick
  approval uses each suggestion's saved draft and is validated like the detailed review; any
  problem opens the detailed review instead.
- A missing end time is assumed to be one hour after the start (noted on the detailed review
  card, not on the Overview; no question asked); the end date is the start date unless the request says otherwise.
- Validation: 102 organizer tests (3 new) on local PostgreSQL; local walk-through added a
  birthday party (2:00–3:00 PM, same day) and two linked tasks from the Overview tile.

## 2026-10-16 — Assistant suggests fewer, combined tasks

- Author: Claude Code. Task: AI-07 (owner request).
- The assistant is asked for one to three tasks, combining steps one person would do together
  before the same deadline (for example "Buy and wrap a gift", with the steps in its notes).
- New regression checks: the birthday plan has one buy-and-wrap task, and every case keeps at
  most 4 tasks. 99 organizer tests pass locally. The model's real behavior is measured by the
  live assistant_eval run, still pending the owner's API key.

## 2026-10-16 — Faster assistant review

- Author: Claude Code. Task: AI-06 (owner request).
- Suggestions show as one-line cards with a tick box (on by default), a summary and any missing
  details. Edit details expands the form only when needed; reminder, search and repeat fields
  are under More options. "Add N selected" adds ticked items together, activity first, so tasks
  link to it; the "approve the activity first" error is gone. Unticked items stay pending.
- Validation: 99 organizer tests (2 new) on local PostgreSQL; local walk-through of a birthday
  plan (missing end time flagged, one task unticked, three items added and linked).

## 2026-10-16 — Switched to Cloud Run + Neon

- Author: Claude Code. Tasks: FND-03, OPS-02.
- The owner moved the live site to Google Cloud Run + Neon and verified sign-in, data and
  Google calendars. The Render deploy job and the unapproved Render production proposal were
  removed; render.yaml is marked retired. Docs, settings defaults and the Settings page now
  describe Cloud Run. The setup script checks each pasted value (one copy, no stray keys) and
  asks for the client secret of this project's own sign-in client.

## 2026-10-16 — Google connect failures are diagnosable

- Author: Claude Code. Task: FND-03 / GGL-01 (first Google connect on Cloud Run failed).
- A failed Google sign-in callback now logs only the error type and Google's short error code
  (for example invalid_client), never tokens, URL codes or provider responses. Test added;
  97 organizer tests pass locally.

## 2026-10-14 — Setup script waits for new service accounts

- Author: Claude Code. Task: FND-03.
- deploy/gcp-setup.sh failed for the owner with "service account does not exist" because new
  service accounts take up to a minute to appear in IAM. It now waits for them and retries
  permission grants quietly, showing Google's error only if retries are exhausted.
- The Google sign-in client moves to the new Cloud Run project. Tokens issued to a different
  client now show "Reconnect required" (unauthorized_client/invalid_client) instead of an
  endless "temporarily unavailable". Test added; 96 organizer tests pass locally.

## 2026-10-14 — Preparing the move to Cloud Run + Neon

- Author: Claude Code. Task: FND-03 (owner approved Cloud Run + Neon, free address for now).
- Dockerfile (Python 3.13.7, static files collected at build, non-root user); settings no
  longer assume Render (APP_HOSTNAME, CSRF trusted origins, proxy header on Cloud Run, APP_COMMIT
  for the version display). CI now builds the container on every run.
- Deploy job for Cloud Run using Workload Identity Federation, Artifact Registry and a
  migration job; it takes over from the Render job once the GCP_* repository variables exist.
- Cloud Shell scripts for one-time Google Cloud setup and a verified database copy, and the
  runbook docs/HOSTING.md.
- Validation: 94 organizer tests locally; workflow YAML parsed; scripts syntax-checked. The
  container build is checked by CI; nothing is deployed until the owner completes setup.

## 2026-10-14 — Deploy from GitHub Actions

- Author: Claude Code. Task: OPS-02 (owner request).
- Render missed deploys for PRs 5, 6 and 8 and later refused a manual deploy (503, deploys
  unavailable). The workflow now has a `deploy` job that calls Render's deploy hook after all
  checks pass on main, with retries; render.yaml turns Render auto-deploy off.
- Validation: workflow reviewed; deploy job runs only for pushes to main. First live run is
  recorded in docs/verification.md.

## 2026-10-14 — Installable Android app and phone layout

- Author: Claude Code. Tasks: APP-01 (owner request), QA-02 phone pass.
- Home Headquarters can be installed on Android from Chrome ("Install app"): manifest, icons
  (including Android's maskable shape), home-screen shortcuts, an Install banner and a Settings
  card. The service worker caches only app files and shows an offline page; family pages are
  never stored on the phone.
- Phones get a bottom tab bar, a week view listing days top to bottom, a month view that fits
  all seven days, and larger tap targets. Desktop is unchanged.
- Validation: 94 organizer tests; headless Edge installability and offline check; 375px audit.

## 2026-10-14 — App version in Settings

- Author: Claude Code. Task: OPS-01 (owner request).
- Settings shows the running commit (from Render's RENDER_GIT_COMMIT, linked to GitHub), its
  branch and when the server started, so a merge that did not deploy is easy to spot.
- Context: PRs 5 and 6 merged with passing CI but Render started no deploys; a manual deploy
  of 790fc54 (dep-db7ttngm7kps73ct3t4g) brought the site up to date.
- Validation: 90 organizer tests on local isolated PostgreSQL.

## 2026-10-14 — Family Google calendar (writes)

- Author: Claude Code. Task: GGL-02 (implemented; live verification pending).
- Owner decisions: an app-created "Home Headquarters" calendar using the narrowest write scope
  (calendar.app.created), and a per-activity "Also add to the family Google calendar" choice.
- One parent opts in from the Google calendars page; existing read-only connections are
  unchanged, and every sign-in now keeps earlier grants.
- Saving, editing, unticking or deleting an activity updates Google after the local save.
  Retries never duplicate; edits made in Google are never overwritten without a choice;
  events deleted in Google can be re-added; failed deletions stay queued; repeating series and
  changed occurrences are supported; restores and "Stop updating Google" leave Google alone.
- Migration 0009. Validation: 89 organizer tests (Google simulated) on local PostgreSQL.
- Limitations: edits made in Google are not copied back; the scope must be added in Google
  Cloud before use; not yet verified against a real Google account.

## 2026-10-14 — Assistant regression cases and repeat suggestions

- Author: Claude Code. Task: AI-04 (implemented; first live evaluation pending).
- Seven regression cases with checks (organizer/assistant_cases.py): birthday recipient,
  same-day weekday, sparse input, task-only, repeating activity, repeating task, and a
  clarification that must keep edits and dismissals. CI runs them against recorded samples;
  `manage.py assistant_eval` runs them against the real provider without keeping any records.
- The assistant can now suggest repeating activities and tasks. Patterns are validated like
  saved series; an unusable one is dropped and turned into a question. Approval creates the
  series or repeating task.
- Server guards: near-duplicate tasks and questions are removed; a clarification cannot bring
  back a dismissed suggestion. The prompt context now includes the current weekday.
- Validation: 79 organizer tests on local isolated PostgreSQL; local visual check.
- Limitations: live evaluation not yet run; same-day weekday questions and keeping edited
  titles still depend on the model and are measured by the cases rather than enforced.

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
