# Architecture

This document describes implemented behavior. TASKS.md separates remaining requirements.

## Runtime and deployment

Python 3.13.7, Django 5.2 LTS, PostgreSQL 17, Gunicorn and WhiteNoise. Server-rendered
templates with small CSS/JavaScript assets; no SPA, browser database or second local backend.
Dependencies are pinned in requirements.txt. PostgreSQL is required in every environment.

Render's root render.yaml provisions the free preview web service and database. Build
installs requirements and collects static assets. Startup runs migrate_locked under a
PostgreSQL advisory lock, then Gunicorn. GitHub Actions runs deployment checks, migration
drift checks, static collection and all organizer tests against disposable PostgreSQL 17.
Auto-deploy waits for successful checks. render.production-proposal.yaml is unapproved.
run_jobs currently implements a locked/deduplicated heartbeat only; no real reminder queue.

## Code map

| Path | Responsibility |
|---|---|
| hq/settings.py, urls.py | Configuration, middleware and routes |
| organizer/models.py, migrations/ | Durable models and versioned schema (0001–0005) |
| organizer/views.py, forms.py | Authentication, parent authorization, bootstrap, foundation UI |
| organizer/planner.py, planner_forms.py | Calendar, family, tasks, lunch planning and validation |
| organizer/invitations.py | Expiring email-bound single-use invitation links |
| organizer/connections.py, google_service.py | OAuth ownership, sharing choices and manual sync |
| organizer/assistant.py, assistant_forms.py | Proposal history, edits, approvals and external search |
| organizer/assistant_service.py | OpenAI request, strict schema and household-member validation |
| organizer/recovery.py | Versioned foundation-note export and validated restore |
| organizer/management/commands/ | Locked migration startup and heartbeat |
| templates/, static/ | Responsive server-rendered UI and progressive enhancement |
| organizer/tests.py, test_*.py | Isolated database and mocked-provider tests |
| docs/verification.md | Observed checks, deployments and remaining verification limits |

## Data boundaries

- Household owns plans; Membership links a Django user to one household and active parent
  role. FamilyMember is an editable profile, separate from login identity. Children do not
  have login accounts in this preview.
- Activity holds local dates/times, time zone, participants, notes, location and version.
  Task optionally links an activity and assignee; stores deadline, completion timestamp,
  priority, search prompt/questions and reminder preference. No local recurrence model yet.
- LunchPlan is unique per child/date; household-scoped bulk operations use versioned undo.
- GoogleConnection belongs to a parent/household, with encrypted refresh token.
  GoogleCalendar holds visibility, permissions, source color and sync metadata.
  GoogleEvent is a replaceable snapshot cache, not a local Activity or a writable Google copy.
- AssistantPlan stores conversation, revision, status and concurrency version.
  AssistantSuggestion stores draft payload, approval/dismissal/supersession and result links.
  Approval status is independent from Task.completed_at. AssistantUsage limits daily attempts.
- SetupRecord/RecoveryPoint support foundation notes; BootstrapState closes initial setup.
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

Secrets live only in ignored .env.local or Render environment settings. .env.example
lists names without values. Keep OPENAI_API_KEY, GOOGLE_CLIENT_SECRET, GOOGLE_TOKEN_KEY,
DATABASE_URL, session/bootstrap secrets, tokens and invitation links out of source, chats,
logs and exports. Gunicorn logs paths without query strings or referrers. Google access
tokens stay in memory; refresh tokens use Fernet with a separately stored stable key.
Do not rotate that key without a re-encryption/reconnection plan.

## Google Calendar

Dedicated deployed OAuth callback: /connections/google/callback/. State, PKCE, expiry
and one-time callback handling protect authorization. Current scopes are read-only.
Parents choose Not shared, Busy only or Event details per calendar; Google private events
are redacted. A manual complete snapshot covers the past 90/next 366 days with pagination
and Google-expanded recurrence. Successful snapshots remove deleted events; failures keep
the previous cache. Versions reject stale sync writes. Same calendar/event IDs deduplicate;
invited copies across different calendar IDs intentionally remain separate. Unified views
combine this cache with local activities. See docs/GOOGLE-CALENDAR.md.

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

## Recovery and release limitations

Current exports include foundation notes only (format home-headquarters, version 1).
Restore validates and previews, rejects stale replacement, and saves a recovery point.
Full organizer/AI/lunch export and isolated restore drill remain unfinished. Source Git
history and bundles cannot recover live household data. No scheduler, notification channel,
closed-app delivery, local recurrence, bulk event dates or Google write workflow exists yet.
