# Prioritized first-release checklist

Authoritative shared backlog, migrated from the owner's original eleven-part brief,
README roadmap and subsequent accepted changes. Last reconciled: October 14, 2026.
Owner for next work: Claude Code. REC-01 code is merged (PR 1); its hosted recovery drill remains.
DASH-03 and CAL-02/TSK-02 recurrence are merged (owner chose Option A for clock-change times).
Owner reprioritized DASH-04 (Overview task priority filters) ahead of CAL-03 on October 14; both are done.
AI-04 is implemented; its first live evaluation run needs the owner's API key (see below).
GGL-02 is implemented (owner chose an app-created calendar and per-activity choice); live setup pending.
APP-01 Android installable app and a phone layout pass (owner request) are done on branch pwa-android-mobile.

Statuses: `[x]` implemented with stated evidence; `[ ]` pending or partial (details follow).
An implemented feature is not proof of complete production readiness. Keep stable IDs.
Both assistants MUST update this file and CHANGELOG.md after changes; see AGENTS.md.

## Next work and blockers

1. **FND-03 / REC-01:** hosting moved to Cloud Run + Neon (October 16). Remaining: backup routine,
   and the recovery drill (the Render-to-Neon copy already proved a full database restore).
2. **FAM-02:** verify Melissa's separate account/invitation and own calendar consent when available.
3. **GGL-02** live setup (add the calendar.app.created scope in Google Cloud, deploy, one parent opts in) and AI-04 live run.
4. **REM-01–03:** choose delivery and scheduler, obtain any paid-service approval, then build
   and verify closed-app delivery. Continue remaining release gates below in dependency order.

Paid hosting/scheduling is not approved. Melissa's account/Google consent requires her
participation. No further approval is needed merely to develop reversible local changes.

## 1. Deployment, authentication, storage and recovery foundation

- [x] FND-01 Separate private repository/project; free Render deployment, real Chris sign-in,
  persistent note saved/retrieved, PostgreSQL and migrations. Initial CI 38313660452.
- [x] FND-02 Versioned schema, locked migration startup, security checks and isolated PostgreSQL CI.
- [ ] FND-03 Production durable hosting/backups and retention decision. Free PostgreSQL expiry
  last recorded November 11, 2026, 9:56 PM Eastern; verify current provider state. Costs need approval.
  **In progress (Claude Code).** Owner approved Google Cloud Run (us-east4) + Neon PostgreSQL 17
  on October 14 (aim: $0/month with a budget alert; free run.app address for now). Code: Dockerfile,
  platform-neutral settings (APP_HOSTNAME, proxy header for Cloud Run, APP_COMMIT), deploy job with
  Workload Identity Federation and a migration job, Cloud Shell scripts deploy/gcp-setup.sh and
  deploy/copy-database.sh, runbook docs/HOSTING.md. **Hosting move done October 16**: owner
  ran setup (project home-headquarters-prod), copied the database (all 14 table counts matched),
  first Cloud Run deploy succeeded (run 38930083618, f28fc59), new OAuth client and Google
  reconnect verified, owner switched to https://home-headquarters-140747200253.us-east4.run.app; no further copy needed.
  Remaining: backup routine/retention decision (proposed weekly export to Cloud Storage), budget
  alert confirmation, suspend Render web service; Render database expires November 11.
- [ ] REC-01 Versioned export of **all** household organizer data, validated restore with
  recovery point before replacement, conflict handling and isolated-environment recovery drill.
  **Implemented, hosted drill pending (Claude Code).** Export format version 2 covers notes,
  family members, activities/participants, tasks, lunches and assistant plans/suggestions;
  excludes accounts, invitations, Google connections/tokens/event cache and usage counters.
  Restore validates every field and cross-reference before writing, previews counts, stores
  the preview server-side (PendingRestore, one hour, per parent), rejects stale previews,
  saves a full recovery point, then replaces all organizer data atomically with new IDs
  (references and suggestion payload member IDs remapped). Version 1 notes exports still
  restore notes only. `export_household` writes an operator export. Local PostgreSQL tests
  include a round-trip drill into a separate household and undo via recovery point.
  PostgreSQL 17 CI 38578064839 passed (commit 4c1323b). Remaining: merge, deploy, download a real export, and restore it into an
  isolated hosted environment (never the live household) to confirm. Known limit: AI plan
  generation does not bump the household version, so a generation finishing mid-restore is
  not detected as a stale preview; the restore still succeeds atomically.
- [x] OPS-01 Settings → App version shows the running commit (linked to GitHub) and server start
  time, so a missed deploy is visible (owner request, Claude Code, after PRs 5 and 6 merged on
  October 14 without Render starting deploys; fixed by manual deploy dep-db7ttngm7kps73ct3t4g).
- [x] OPS-02 Reliable deploys (Claude Code, owner request): superseded by the Cloud Run
  deploy-cloud-run job (Workload Identity Federation, migration job, health check). First run
  live October 16 (38930083618). The Render hook job was removed; the RENDER_DEPLOY_HOOK secret
  can be deleted.
- [x] FND-04 Source in private GitHub; environment recreation and secret-name-only example.
  Local source bundle exists separately. Neither is a household-data backup.

## 2. Shared household and family

- [x] FAM-01 Create/edit/archive profiles, roles, initials and colors; household-scoped parent access.
- [ ] FAM-02 Separate parent accounts via secure invitations: implementation and isolated tests
  complete; verify Melissa's live join/sign-in and shared editing. Invitations are email-bound
  bearer links; no email delivery/verification is currently implemented. Share only as authorized.

## 3. Calendar, tasks and preparation relationships

- [x] CAL-01 Week/month/agenda; create/edit/delete one-off activities; dates/times, all-day,
  multi-day, notes, location and multiple participants; household-zone/DST validation.
- [x] CAL-02 Daily/weekly/monthly/custom recurrence with explicit occurrence-versus-series edits,
  exceptions/deletions and DST/multi-day tests (Claude Code). Series store an RFC 5545 RRULE
  (daily/weekly with weekdays/monthly by day or nth weekday/yearly, interval, until or count)
  anchored on a first date that must match the pattern; skipped dates are exdates and a changed
  occurrence is its own Activity linked to the series. Edit/delete: only this, this and following
  (series split), or all (date shifts move the series, exdates and changes). DST decision (owner,
  Option A, matches Google): a skipped spring-forward time moves forward by the gap; a repeated
  fall-back time uses the first. Isolated PostgreSQL tests incl. DST, multi-day and splits.
  Limits: "this and following" removes later single-occurrence changes and restarts a COUNT;
  preparation tasks link to the series, not one date. The assistant can propose repeats (AI-04).
- [x] CAL-03 Multi-date bulk activity entry with reviewed date selection and atomic validation
  (Claude Code). "Add on several dates": details once, a checkbox date grid (up to 120 days shown,
  60 dates; weekday column toggles), then a review listing each date, per-date problems such as
  clock-change times and other plans that day. All dates are created in one transaction or none;
  a batch ID (migration 0008) makes a repeated submit add nothing. Each date is a one-off activity.
  Limits: single-day activities only; batch is an idempotency key and is not exported.
- [x] CAL-04 Rolling calendar (owner request, Claude Code, October 16): the default Overview view
  is five weeks starting with the current week (today on the top row), with month labels at the
  first day and each 1st, earlier days lightly shaded, and arrows moving four weeks. It replaces
  the calendar-month grid. Week view tiles are taller and show time ranges, locations and task
  details (time, person, linked activity). Phones keep the stacked week and compact month.
- [x] TSK-01 Task CRUD, complete/reopen timestamp, member/household assignment, due date/time,
  linked activity and visible preparation tasks; stale-edit checks.
- [x] TSK-02 Recurring tasks and completion/next-occurrence semantics; no duplicate generation
  (Claude Code). A repeating task needs a due date; completing it creates the next due date once
  (series key + due date unique; reopen/re-complete cannot duplicate). Delete offers skip-to-next or
  stop. Changing the rule starts a new series. Only the current task exists; future ones are not shown.
- [x] UX-01 Inline quick Add activity/Add task on Overview; high-priority tasks sort first.
  PostgreSQL CI 38462765334; deployed preview.
- [x] LIST-01 Saved lists and checklists (owner request, Claude Code, October 16). Settings →
  Saved lists holds reusable lists (name plus up to 50 items, one per line). Any activity or task
  page has a Checklist: add items, add a saved list (items already there are skipped), tick,
  untick and remove. On a repeating activity the items are shared and ticks are kept per date
  (the page shows the chosen or next date); a repeating task's next task gets a fresh unticked
  copy, created once. Task rows show "☑ done/total". Editing or deleting a saved list never
  changes checklists already added. Migration 0010; export version 4 includes both.

## 4. Google Calendar and school lunches (required first release)

- [x] GGL-01 Per-parent OAuth implementation, encrypted server refresh tokens, calendar selection,
  sharing explanation/visibility, unified views, source colors/legend; manual snapshot sync,
  deletion handling, same-ID duplicates, failures/reconnect and version checks. Chris connected
  and live unified Google event verified; isolated provider cases tested. CI 38499169193.
- [ ] GGL-02 Create/edit in an explicitly selected writable shared family Google calendar.
  Respect permissions, scope/consent changes, concurrent edits, retries and deletions. Current
  read-only scopes do not permit writes; preserve existing grants until approved migration.
  **Implemented, live verification pending (Claude Code).** Owner decisions (October 14): the
  app creates its own "Home Headquarters" calendar using the narrowest write scope
  (calendar.app.created, opt-in per parent via incremental consent; existing read-only grants
  are kept and every sign-in now preserves earlier grants), and each activity has an "Also add
  to the family Google calendar" choice (default on once set up). Writes run after commit;
  deterministic event IDs make retries idempotent; ETag If-Match prevents overwriting edits
  made in Google (conflict: use this version / keep Google's and stop); deleted-in-Google can
  be re-added or unlinked; local deletes queue Google removals with retry; repeating series
  send RRULE/EXDATE and changed occurrences are separate events; restores and "Stop updating
  Google" never edit or delete Google events; app-written events are not shown twice from the
  read cache. Migration 0009. Mocked-provider tests. Remaining: add the scope to the Google
  Cloud consent screen, deploy, set up the calendar, and verify a real create/edit/delete and
  sharing with the other parent. Edits made in Google are not copied back (by design).
- [ ] GGL-03 Melissa's own live connection/selected visibility and shared overview verification.
- [ ] GGL-04 Scheduled sync while app closed, durable retries and operational monitoring.
  Confirm OAuth testing-mode expiry/reconnection and production consent requirements.
- [x] LUN-01 Monthly weekday grid, children as editable profiles; School/Pack/No school/Not
  decided, multi-date/full-month application and version-protected undo. Leap-year CI coverage.
- [x] LUN-02 School lunch selections appear on main calendar; packed-lunch needs appear in
  daily overview; Overview full lunch table removed as requested.

## 5. AI proposals, approval and task search

- [x] AI-01 Real OpenAI connection, validated structured proposals, local-date resolution,
  clarification and editable activity/task suggestions. No demonstration responses.
- [x] AI-02 Individual approval/approve-all, edits/assignee/deadline/reminder preference,
  dismiss without records, persistent revision/status history, linked tasks and retry deduplication.
  Isolated PostgreSQL approval/privacy tests passed: CI 38568649471.
- [x] AI-03 Editable search prompts, recipient age/budget questions, basic name/email scrub,
  explicit reviewed external Google search. No claim of integrated research or completed search.
- [ ] AI-04 Broaden semantic acceptance cases: attendee versus recipient, same-day weekday
  ambiguity, sparse input, task-only input, recurrence requests, preserving edits/dismissals
  through clarification and avoiding duplicate questions/tasks. Birthday ambiguity was fixed;
  model-generated results still need user review. Add meaningful regression evaluation cases.
  **Implemented, live run pending (Claude Code).** organizer/assistant_cases.py defines seven
  cases with outcome checks (birthday recipient, same-day weekday, sparse input, task-only,
  repeating activity, repeating task, clarification keeping edits and dismissals) plus common
  checks (honest reply, no duplicates, private search prompts, no unrequested priority or
  reminders). CI runs every case against a recorded passing sample and 11 known-bad samples.
  `manage.py assistant_eval` runs the cases against the real provider (API credit) in a
  rolled-back transaction. Server guards: the assistant can now propose repeats (validated like
  saved series; an unusable pattern is dropped and asked about), duplicate tasks/questions are
  removed, and a clarification cannot bring back a dismissed item. Remaining: run
  assistant_eval with the owner's key and record results; same-day weekday and edit retention
  still rely on the model and are measured, not enforced.
- [x] AI-06 Streamlined suggestion review (owner request, Claude Code, October 16): compact
  one-line cards with a summary (date, time, people, due date, assignee, repeat) and any missing
  details ("Needs: end time"), ticked by default; Edit details expands the form (opened
  automatically when something is missing or invalid); reminder, search and repeat fields sit
  under More options; one "Add N selected" button adds ticked items together, activity first so
  tasks link to it, leaving unticked items pending. Stale reply/questions hide once items are
  added. Approval still validates every field; nothing is added without the button.
- [ ] AI-07 Fewer, consolidated tasks (owner request, Claude Code, October 16): instructions now ask
  for one to three tasks, combining steps one person would do together before the same deadline
  ("Buy and wrap a gift", steps in notes). Regression checks: gift buying and wrapping are one
  task; every case keeps at most 4 tasks. Recorded samples and known-bad samples pass in CI.
  Pending: live assistant_eval run to measure the model's actual behavior.
- [x] AI-08 Overview quick approval and assistant defaults (owner request, Claude Code, October 16):
  requests from the Overview return to the Overview, where the Planning assistant tile lists the
  pending suggestion titles with tick boxes, an "Add N selected" button (approves from each
  suggestion's saved draft, validated as usual; a problem opens the detailed review), the number
  of open questions, "Review in detail" and "Start a new request". Owner decisions: a missing end
  time is assumed one hour after the start (capped at 11:59 PM, noted only on the detailed review, and
  end-time questions are dropped); the end date is the start date unless stated.
- [ ] AI-09 Voice input for the assistant (owner chose the free browser option, Claude Code, October
  16): a Speak button on the Overview tile, Assistant page and review follow-up box uses the
  browser's speech recognition to fill the text box (live, editable; nothing is sent to the
  assistant until the usual button). Hidden where unsupported; clear messages for blocked or
  missing microphones. Permissions-Policy now allows the microphone for this site only (camera and
  location stay blocked). Audio is handled by the browser (Chrome uses Google's speech service);
  the app never receives audio. Pending: real dictation check on the owner's Android phone.
- [ ] AI-10 Snap a flyer (owner request, Claude Code, October 16): a "Snap a flyer" button on the
  Overview assistant tile and Assistant page opens the phone camera (or photo picker). The phone
  shrinks the photo (up to 1600 px JPEG) before upload; the server accepts only JPEG/PNG/WebP by
  file signature (8 MB cap), sends it once to OpenAI with the request (store: false) and never
  saves it; the plan keeps only a note that a photo was read. A note is optional. Instructions
  treat text in the image as data only, ask about unreadable details, and turn RSVP/payment/form
  deadlines into tasks. Results are normal suggestions for review. Pending: live check with a
  real flyer and the owner's API key (images use more API credit than text).
- [ ] AI-05 Schedule actual reminders only after approved records; depends on REM-01–03.
  **Implemented (Claude Code, October 16):** approved records keep their reminder choice and the
  reminder job (REM-02) sends it; suggestions that are not approved are never reminded.
  Pending REM-03 real-phone verification.

## 6. Overview and reliable reminders

- [x] DASH-01 Today combines local/selected Google events and due tasks; task priorities include
  clearly overdue work (see DASH-04). Source and participant identity remain distinguishable.
- [x] DASH-02 Remove Overview “Next seven days” section (owner revision). Agenda remains;
  do not re-add the removed section to satisfy the older brief.
- [x] DASH-03 Upcoming/Agenda workflow combining next-seven-day events **and tasks** without
  restoring the unwanted Overview section (Claude Code). Agenda is now a rolling seven days from
  the chosen date (default today) with events, open due tasks (time, assignee, priority, linked
  activity; high priority first) and an Overdue list when today is in range. Week/month unchanged.
  Isolated PostgreSQL test plus local phone-width visual check; CI result reported in handoff.
- [x] DASH-04 Overview "Task priorities" lists all open tasks (owner request, Claude Code), high
  priority first, then due date/time with undated last, with quick filters All, High priority,
  Due in 7 days and Due in 1 day (today or tomorrow). Due filters include overdue tasks; counts
  show on each filter. Server-side links work without JavaScript. Replaces the previous
  eight-task weekly list. Isolated PostgreSQL test and local visual check.
- [x] DASH-05 Tonight's prep (Claude Code, October 16): from 5 PM household time the Overview
  shows a card for tomorrow with its plans (local and shared Google), unticked checklist items as
  "Bring:", tasks due tomorrow and packed lunches. Hidden before 5 PM.
- [ ] REM-01 Choose a supported delivery channel and background schedule with owner-approved
  costs; document browser/device limitations and consent. Free web sleep is not a scheduler.
  **Implemented, live setup pending (Claude Code, October 16; owner approved free Web Push and
  Cloud Scheduler's free allowance).** Web Push (no new libraries; RFC 8291 test vector passes) to
  every parent device that opts in on Settings → Phone reminders (Turn on, Send a test, Turn
  off; device list with Remove). Cloud Scheduler job hhq-reminders every 15 minutes, 6 AM–11 PM
  Eastern, authenticated with a Google-signed token for the permission-less hhq-scheduler
  identity. Setup: deploy/reminders-setup.sh (docs/HOSTING.md). Limits: up to ~8 minutes early
  or late; overnight reminders arrive at 6 AM if the plan hasn't started; untimed plans count
  from 8 AM; titles/times/places pass encrypted through the browser's push service (Google for
  Chrome); iPhones need the app added to the Home Screen (iOS 16.4+).
- [ ] REM-02 Durable reminder jobs: time zones, configurable lead times, retry/backoff,
  deduplication, concurrent workers, cancellation/rescheduling on plan changes and revocation.
  **Implemented (Claude Code):** reminders are recomputed from current plans each run (activity
  time zone, repeating occurrences without skipped dates, changed occurrences, open tasks), so
  edits/deletes/completions reschedule or cancel; ReminderDelivery is unique per device and
  reminder key (key includes start time, so a moved plan reminds again); advisory lock for
  concurrent runs; per-delivery commits; up to 3 attempts across runs; devices reported gone are
  removed; delivery rows older than 14 days are pruned. Migration 0011. 11 isolated tests.
- [ ] REM-03 Verify real delivery while app/browser closed, failure retry and no duplicates;
  do not mark done based on an in-app message or run_jobs heartbeat.
  Hosted scheduler verified October 17: owner ran reminders-setup.sh; Cloud Scheduler calls at
  14:45, 15:00 and 15:07 UTC were answered 200 by the app (signed-token check passing), job
  ENABLED with empty status. Still pending: the owner turns on reminders on an Android phone
  and confirms a test and a real scheduled reminder arrive with the app closed, once.

## 7. End-to-end release and handoff

- [ ] QA-01 Complete primary birthday-party scenario through approvals, linked records,
  search and delivered reminders in isolated test data. Hosted AI draft/edit/dismiss verified;
  real household test proposal was left unapproved. Database approval paths pass CI.
- [x] APP-01 Installable Android app (PWA, owner request, Claude Code): web app manifest
  (standalone, Home HQ, 192/512/maskable icons, Add activity/Tasks/Lunches shortcuts), a root
  service worker that caches only hashed static files and a data-free offline page (family
  pages are never cached), an in-app Install banner/Settings button (beforeinstallprompt) plus
  Chrome menu instructions. Verified in headless Edge: worker active, no installability
  errors, offline page shown during a real server outage. Real Android install pending.
- [ ] QA-02 Full phone/desktop and keyboard/contrast/loading/empty/error checks across all flows.
  Phone pass done (Claude Code, October 14): every page audited at 375px (no sideways scroll);
  bottom tab bar with icons on phones, week view stacked by day, month view fits seven days,
  44px tap targets for task completion, calendar arrows, view switch, back/cancel/delete links
  and disclosure summaries; desktop unchanged. Keyboard/contrast/loading/error audit pending.
  Assistant phone sizing and desktop review checked; broader accessibility audit pending.
- [ ] QA-03 Cross-household/concurrent-parent release regression, operational recovery drill,
  backup/restore instructions and recreation from a fresh clone against isolated PostgreSQL.
- [ ] QA-04 Reconcile all release gates, deployment costs, privacy/retention and limitations;
  only then label production-ready. Remove obsolete bootstrap secret if still configured,
  without reopening setup; verify the already-closed database bootstrap guard.
- [x] HANDOFF-01 Shared PROJECT/ARCHITECTURE/AGENTS/TASKS plus CHANGELOG and Claude entry point;
  canonical GitHub commits are the handoff boundary. Both assistants update tasks and changelog.
  Documentation package reviewed against current code and known verification evidence.

## Latest handoff

- Assistant: Claude Code. Change: REM-03 hosted scheduler verified (owner ran the setup);
  reminders-setup.sh now waits for its test run and reports success or the failing status.
  PRs 19, 20 and 21 merged October 16; deploy of 06ee090 succeeded (health check passed).
- Starting canonical GitHub commit: `06ee090a6ea7fd9adfc2590039ec0ad0039008c5` (merged PR 21); branch `rem-03-scheduler-verified`.
- Outgoing commit: the commit that adds this handoff entry; obtain exact SHA from the handoff
  message or `git log -1 --format=%H -- TASKS.md`. Never put a guessed self-referential SHA here.
- Validation: script syntax-checked (bash -n); documentation-only otherwise.
- Remaining blockers: real-phone reminder delivery with the app closed (REM-03); live flyer
  check; Melissa's invitation and Google test-user access; hosted recovery drill.

## Deferred until first release works

Email ingestion, autonomous purchases, travel intelligence, chore rewards, document storage,
and other advanced features. Integrated AI research is optional; explicit external search
already meets the chosen preview search behavior.
