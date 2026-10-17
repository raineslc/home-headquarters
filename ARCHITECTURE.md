# Architecture

This document describes implemented behavior. TASKS.md separates remaining requirements.

## Runtime and deployment

Python 3.13.7, Django 5.2 LTS, PostgreSQL 17, Gunicorn and WhiteNoise. Server-rendered
templates with small CSS/JavaScript assets; no SPA, browser database or second local backend.
Dependencies are pinned in requirements.txt. PostgreSQL is required in every environment.

Hosting (FND-03): Google Cloud Run (us-east4, scales to zero) with Neon PostgreSQL 17 (direct,
non-pooled connection). The Dockerfile collects static files at build; Gunicorn serves the app.
GitHub Actions runs deployment checks, migration drift checks, static collection, all organizer
tests against disposable PostgreSQL 17 and a container build. On main, deploy-cloud-run pushes
the image, runs migrate_locked as the Cloud Run job hhq-migrate (PostgreSQL advisory lock),
deploys the service with Secret Manager secrets and checks /health/. See docs/HOSTING.md.
Render (render.yaml) is retired and kept only until its database expires.
run_jobs is a locked heartbeat for housekeeping. Phone reminders (organizer/reminders.py) are
Web Push: organizer/webpush.py encrypts (RFC 8291) and signs (VAPID, RFC 8292) with only
`cryptography`; endpoints are limited to the major browsers' push services. Cloud Scheduler
calls POST /jobs/reminders/ with a Google-signed identity token (audience and the
JOB_INVOKER_EMAIL identity are checked). Each run recomputes due reminders from current plans
(so edits, deletes and completions reschedule or cancel them), sends each once per device
(ReminderDelivery unique on device + reminder key; key includes the start time), commits per
delivery, retries failures up to 3 runs and removes devices the push service reports gone.
After reminders, the same call refreshes Google Calendar (GGL-04): google_service.sync_due
re-snapshots each connected account's shared calendars not synced in the last 10 minutes
(without bumping the connection version, so open forms stay valid; accounts needing reconnect
are skipped and the owner sees an Overview notice), then google_writes.retry_failed retries
pending Google removals and failed family-calendar updates (never conflicts or deletions made in
Google). Errors there are logged and never fail the reminder run.

## Code map

| Path | Responsibility |
|---|---|
| hq/settings.py, urls.py | Configuration, middleware and routes |
| organizer/models.py, migrations/ | Durable models and versioned schema (0001–0009) |
| organizer/views.py, forms.py | Authentication, parent authorization, bootstrap, foundation UI |
| organizer/planner.py, planner_forms.py | Calendar, family, tasks, lunch planning and validation |
| organizer/pwa.py | Installable app: manifest, root service worker (static files and offline page only) |
| organizer/recurrence.py | RRULE building/validation, occurrence expansion and clock-change handling |
| organizer/invitations.py | Expiring email-bound single-use invitation links |
| organizer/connections.py, google_service.py | OAuth ownership, sharing choices and manual sync |
| organizer/assistant.py, assistant_forms.py | Proposal history, edits, approvals and external search |
| organizer/assistant_service.py | OpenAI request, strict schema and household-member validation |
| organizer/recovery.py | Versioned full-household export, validation and replacing restore |
| organizer/management/commands/ | Locked migration startup, heartbeat and operator household export |
| templates/, static/ | Responsive server-rendered UI and progressive enhancement |
| organizer/tests.py, test_*.py | Isolated database and mocked-provider tests |
| docs/verification.md | Observed checks, deployments and remaining verification limits |

## Data boundaries

- Household owns plans; Membership links a Django user to one household and active parent
  role. FamilyMember is an editable profile, separate from login identity. Children do not
  have login accounts in this preview.
- Activity holds local dates/times, time zone, participants, notes, location and version.
  Task optionally links an activity and assignee; stores deadline, completion timestamp,
  priority, search prompt/questions and reminder preference.
- Recurrence: an Activity series stores an RFC 5545 RRULE (no DTSTART; anchored on start_date,
  which must be an occurrence) plus recurrence_exdates. A changed occurrence is a separate
  Activity with series and occurrence_date (unique together) and the date added to exdates.
  Views expand series per date window (recurrence.household_events); an Occurrence wrapper
  carries the instance date. Wall times follow Option A for clock changes. A repeating Task
  stores recurrence, recurrence_start and series_key; completion creates the next due date once.
- Multi-date add (planner.bulk_activity) validates shared details, then each date with ActivityForm,
  and creates every date in one locked transaction. Activity.batch (a submitted UUID) makes the
  create idempotent; it is not part of exports.
- LunchPlan is unique per child/date; household-scoped bulk operations use versioned undo.
- GoogleConnection belongs to a parent/household, with encrypted refresh token.
  GoogleCalendar holds visibility, permissions, source color and sync metadata.
  GoogleEvent is a replaceable snapshot cache, not a local Activity or a writable Google copy.
- AssistantPlan stores conversation, revision, status and concurrency version.
  AssistantSuggestion stores draft payload, approval/dismissal/supersession and result links.
  Approval status is independent from Task.completed_at. AssistantUsage limits daily attempts.
- SetupRecord holds foundation notes. RecoveryPoint stores a full export saved before each
  restore; PendingRestore holds a validated upload awaiting confirmation. BootstrapState closes setup.
  RateLimit and JobRun support login/request limits and heartbeat deduplication.

## Authorization, consistency and secrets

Protected views derive household from the authenticated active parent's membership.
All object lookups and form choices must be household-scoped; submitted household IDs
are not authorization. Django sessions, CSRF, secure cookies, HTTPS and private-response
headers protect the UI. Parent invitations are hashed, email-bound bearer links (not
email verification); the app does not send them.

Household/record locks and optimistic versions reject stale edits. AI approval validates
again through organizer forms, locks the plan/household and creates linked records in one
transaction. Approve-all is atomic; successful retries do not recreate deleted results.
Dates use the household zone. DST-nonexistent and ambiguous local activity times are
rejected in the current preview; supporting ambiguity explicitly remains a design task.

Secrets live only in ignored .env.local or Google Secret Manager (hhq-* secrets). .env.example
lists names without values. Keep OPENAI_API_KEY, GOOGLE_CLIENT_SECRET, GOOGLE_TOKEN_KEY,
DATABASE_URL, session/bootstrap secrets, tokens and invitation links out of source, chats,
logs and exports. Gunicorn logs paths without query strings or referrers. Google access
tokens stay in memory; refresh tokens use Fernet with a separately stored stable key.
Do not rotate that key without a re-encryption/reconnection plan.

## Google Calendar

Dedicated deployed OAuth callback: /connections/google/callback/. State, PKCE, expiry
and one-time callback handling protect authorization. Base scopes are read-only; every
sign-in requests include_granted_scopes so earlier grants are kept.
Parents choose Not shared, Busy only or Event details per calendar; Google private events
are redacted. A manual complete snapshot covers the past 90/next 366 days with pagination
and Google-expanded recurrence. Successful snapshots remove deleted events; failures keep
the previous cache. Versions reject stale sync writes. Same calendar/event IDs deduplicate;
invited copies across different calendar IDs intentionally remain separate. Unified views
combine this cache with local activities. See docs/GOOGLE-CALENDAR.md.

Writes (organizer/google_writes.py) go only to one app-created calendar per household
(FamilyCalendar), using calendar.app.created granted by explicit opt-in (GoogleConnection.can_write).
Activity.google_sync marks activities to copy; post_save/post_delete hooks push after commit
(transaction.on_commit), recording google_state/google_error with queryset updates so pushes do
not re-trigger. Event IDs derive from the activity UUID (retries become updates); updates send
If-Match ETags (412 → conflict); 404/410 → removed; deletes queue GooglePendingDeletion rows.
Series send RRULE (timed UNTIL converted to UTC end of day) and EXDATEs; changed occurrences are
separate events. Restores run with writes paused. shared_events skips cached copies of
app-written events (including "<id>_<instance>" recurring IDs).

## AI and search

OpenAI Responses API, default gpt-5-mini with medium reasoning, strict JSON schema,
store=false and bounded timeout. Input contains entered conversation, current drafts,
active family names/roles/IDs, local date and zone. Existing calendar entries are checked
locally, not sent to the provider. Generated fields and member IDs are validated; server
wording prevents false claims that model-suggested actions happened. No tool execution.

Up to 30 generation attempts per household/local day and six per user/15-minute window;
failed attempts count. No automatic API retry. Interrupted requests can be retried after
two minutes. API-key presence enables the UI; only a real successful request proves the
connection. Search prompts require an explicit reviewed submit to external Google search;
they are not integrated research results. See docs/assistant-preview.md.

Drafts may include a structured repeat (frequency, interval, weekdays, monthly mode, end).
The server flattens it into the same repeat fields as the planner forms, builds the RRULE
against the first date and, if it does not fit, drops it and asks instead. Approval uses the
planner forms with repeat enabled. The server also removes near-duplicate tasks and
questions, and generation skips items matching a dismissed suggestion's title.
organizer/assistant_cases.py holds regression cases and checks; tests run them against
recorded samples, and `manage.py assistant_eval` runs them live in a rolled-back transaction.

## Recovery and release limitations

Exports use format home-headquarters, version 5, scope household: notes, family members,
activities with participants, recurrence (series, exdates, changed occurrences) and checklists,
tasks with recurrence and checklists, lunch plans, assistant plans with suggestions, and saved
lists. Version 2 files are upgraded with non-repeating defaults, version 2/3 files with empty
checklists and lists, and version 2–4 tasks with repeat_after_done false on restore; series keys are regenerated so restores never collide.
Accounts, memberships, invitations, Google connections/tokens/event caches, usage counters
and recovery points are never exported; plan/suggestion authors appear as parent emails.
Restore validates every field (model validation) and cross-reference before writing, stores
the preview server-side for one hour per parent, rejects it if the household version changed,
saves a full recovery point, then atomically replaces all organizer data with newly generated
IDs, remapping references and member IDs inside suggestion payloads. Household name, zone,
accounts and connections are unchanged. Unknown authors fall back to the restoring parent.
Version 1 notes-only exports still restore notes only. `manage.py export_household <file>`
writes the same export for operators. A hosted isolated recovery drill is still pending.
Source Git history and bundles cannot recover live household data. Phone reminders run from
Cloud Scheduler, which also refreshes Google calendars (see above).
