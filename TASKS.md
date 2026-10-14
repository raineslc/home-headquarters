# Prioritized first-release checklist

Authoritative shared backlog, migrated from the owner's original eleven-part brief,
README roadmap and subsequent accepted changes. Last reconciled: October 14, 2026.
Owner for next work: Claude Code. REC-01 code is merged (PR 1); its hosted recovery drill remains.
DASH-03 and CAL-02/TSK-02 recurrence are complete (owner chose Option A for clock-change times).

Statuses: `[x]` implemented with stated evidence; `[ ]` pending or partial (details follow).
An implemented feature is not proof of complete production readiness. Keep stable IDs.
Both assistants MUST update this file and CHANGELOG.md after changes; see AGENTS.md.

## Next work and blockers

1. **REC-01 / FND-03:** deploy the full household export, download a real export, and run the
   isolated hosted recovery drill. Decide durable hosting before free database expiry on November 11.
2. **FAM-02:** verify Melissa's separate account/invitation and own calendar consent when available.
3. **CAL-03** multi-date bulk entry, then **GGL-02** Google writes (recurrence is now in place): recurrence/bulk calendar foundations and Google writes.
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
  preparation tasks link to the series, not one date; the assistant cannot propose repeats yet.
- [ ] CAL-03 Multi-date bulk activity entry with reviewed date selection and atomic validation.
- [x] TSK-01 Task CRUD, complete/reopen timestamp, member/household assignment, due date/time,
  linked activity and visible preparation tasks; stale-edit checks.
- [x] TSK-02 Recurring tasks and completion/next-occurrence semantics; no duplicate generation
  (Claude Code). A repeating task needs a due date; completing it creates the next due date once
  (series key + due date unique; reopen/re-complete cannot duplicate). Delete offers skip-to-next or
  stop. Changing the rule starts a new series. Only the current task exists; future ones are not shown.
- [x] UX-01 Inline quick Add activity/Add task on Overview; high-priority tasks sort first.
  PostgreSQL CI 38462765334; deployed preview.

## 4. Google Calendar and school lunches (required first release)

- [x] GGL-01 Per-parent OAuth implementation, encrypted server refresh tokens, calendar selection,
  sharing explanation/visibility, unified views, source colors/legend; manual snapshot sync,
  deletion handling, same-ID duplicates, failures/reconnect and version checks. Chris connected
  and live unified Google event verified; isolated provider cases tested. CI 38499169193.
- [ ] GGL-02 Create/edit in an explicitly selected writable shared family Google calendar.
  Respect permissions, scope/consent changes, concurrent edits, retries and deletions. Current
  read-only scopes do not permit writes; preserve existing grants until approved migration.
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
- [ ] AI-05 Schedule actual reminders only after approved records; depends on REM-01–03.
  Saved reminder preferences are implemented but do not satisfy delivery acceptance.

## 6. Overview and reliable reminders

- [x] DASH-01 Today combines local/selected Google events and due tasks; week priorities include
  clearly overdue work. Source and participant identity remain distinguishable.
- [x] DASH-02 Remove Overview “Next seven days” section (owner revision). Agenda remains;
  do not re-add the removed section to satisfy the older brief.
- [x] DASH-03 Upcoming/Agenda workflow combining next-seven-day events **and tasks** without
  restoring the unwanted Overview section (Claude Code). Agenda is now a rolling seven days from
  the chosen date (default today) with events, open due tasks (time, assignee, priority, linked
  activity; high priority first) and an Overdue list when today is in range. Week/month unchanged.
  Isolated PostgreSQL test plus local phone-width visual check; CI result reported in handoff.
- [ ] REM-01 Choose a supported delivery channel and background schedule with owner-approved
  costs; document browser/device limitations and consent. Free web sleep is not a scheduler.
- [ ] REM-02 Durable reminder jobs: time zones, configurable lead times, retry/backoff,
  deduplication, concurrent workers, cancellation/rescheduling on plan changes and revocation.
- [ ] REM-03 Verify real delivery while app/browser closed, failure retry and no duplicates;
  do not mark done based on an in-app message or run_jobs heartbeat.

## 7. End-to-end release and handoff

- [ ] QA-01 Complete primary birthday-party scenario through approvals, linked records,
  search and delivered reminders in isolated test data. Hosted AI draft/edit/dismiss verified;
  real household test proposal was left unapproved. Database approval paths pass CI.
- [ ] QA-02 Full phone/desktop and keyboard/contrast/loading/empty/error checks across all flows.
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

- Assistant: Claude Code. Changes: DASH-03 (PR 2) and CAL-02/TSK-02 recurrence (migration 0007,
  python-dateutil, export format version 3), stacked on branch `dash-03-upcoming`.
- Starting canonical GitHub commit: `d00763e3b93e402cf069f3c53be2dcdd67b769b8` (merged PR 1, REC-01); branch `cal-02-recurrence`.
- Outgoing commit: the commit that adds this handoff entry; obtain exact SHA from the handoff
  message or `git log -1 --format=%H -- TASKS.md`. Never put a guessed self-referential SHA here.
- Validation: local isolated PostgreSQL (portable PostgreSQL 16, Python 3.11): 66 organizer
  tests passed, deploy check and migration drift check passed; local phone-width visual checks.
  CI status for the pushed branches is reported in the handoff.
- Remaining blockers: hosted recovery drill, paid hosting/scheduler approval, second-parent
  participation, Google writes/reminder delivery. Next: merge PRs 2 and 3, REC-01 drill, FND-03, CAL-03.

## Deferred until first release works

Email ingestion, autonomous purchases, travel intelligence, chore rewards, document storage,
and other advanced features. Integrated AI research is optional; explicit external search
already meets the chosen preview search behavior.
