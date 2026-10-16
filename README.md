# Home Headquarters

A new, private family organizer. **Current milestone: working organizer preview.**

## Shared ChatGPT / Claude handoff

The private repository is the source package: application, migrations, templates, assets,
pinned dependencies, deployment configuration, tests and shared documentation.

Read [AGENTS.md](AGENTS.md) first, then [PROJECT.md](PROJECT.md),
[ARCHITECTURE.md](ARCHITECTURE.md), [TASKS.md](TASKS.md) and [CHANGELOG.md](CHANGELOG.md).
[CLAUDE.md](CLAUDE.md) points Claude Code to the same shared rules.
Both assistants must update tasks and changelog after every change and hand off an exact
GitHub commit SHA. Use a fresh clone of `raineslc/home-headquarters` and check out that
commit; do not merge the historical local mirror, whose commit SHAs differ from GitHub.
GitHub's Download ZIP at a chosen commit provides a source-only archive; a clone also
preserves history. Neither contains credentials or the live household database.

## Release status

Not a production release. Calendar views, one-off and repeating activities, linked,
repeating and high-priority tasks, an installable Android app,
editable family profiles, monthly lunches, parent invitations, read-only Google Calendar,
an opt-in family Google calendar the app writes to, and real AI proposals/approvals are
available. Unattended sync,
a hosted recovery drill and delivered reminders remain outstanding. Full household
export/restore is available under Settings → Backup and restore. See [TASKS.md](TASKS.md).
Do not use the free testing environment as
the only copy of important family plans.

## Architecture

- Django 5.2 LTS: password authentication, server sessions, CSRF protection, templates,
  household-authorized endpoints, versioned migrations.
- PostgreSQL 17 in every environment; no SQLite or browser-storage substitute.
- Google Cloud Run web service and migration job built from the same container image.
- WhiteNoise serves the small compiled static bundle; no CDN script dependencies.
- Secrets remain in ignored local configuration or hosting environment variables.

Every organizer endpoint derives the household from the signed-in parent's active
membership, never from a submitted household ID. The health endpoint returns only
availability. Setup is guarded by an owner email and secret code and closes after one use.

The current scheduler command is a heartbeat only. It proves neither Google sync
nor delivered reminders. The production proposal schedules it once a minute; future
reminder and synchronization handlers must implement durable retries and deduplication.

## Recreate the environment

1. Install Python 3.13.7 and PostgreSQL 17. Create an empty development database.
2. Create a virtual environment; install `requirements.txt`.
3. Copy `.env.example` to an ignored `.env.local` and fill only the needed values.
   Use independently generated random values for `DJANGO_SECRET_KEY` and `BOOTSTRAP_TOKEN`.
   Never copy a production database URL into development.
4. Set `LOCAL_HTTP=1` only for a loopback development server.
5. Run `python manage.py migrate_locked`, then `python manage.py collectstatic --noinput`.
6. Run `python manage.py runserver 127.0.0.1:8000`. Complete `/setup/` as the owner.

The hosted application uses the same code and PostgreSQL schema.

## Deployment

Production runs on **Google Cloud Run** (project `home-headquarters-prod`, us-east4) with a
**Neon PostgreSQL 17** database: https://home-headquarters-140747200253.us-east4.run.app. See [docs/HOSTING.md](docs/HOSTING.md).

Every merge to `main` deploys after all checks pass: the `deploy-cloud-run` job signs in with
Workload Identity Federation (no stored keys), pushes the image, runs migrations as the Cloud
Run job `hhq-migrate`, deploys the service and checks `/health/`. Settings → App version shows
the running commit. Secrets live in Secret Manager; never paste passwords, connection strings
or codes into chat, source, shell arguments or URLs. Setup is closed in the database.

Render was retired on October 16, 2026; `render.yaml` remains only until its database expires
(November 11, 2026).

## Verification

`python manage.py check --deploy`

`python manage.py makemigrations --check --dry-run`

`python manage.py test organizer --noinput`

The CI workflow provisions a disposable PostgreSQL 17 service and creates a separate
test database. Tests exercise password authentication, CSRF, household isolation,
inactive memberships, setup closure, restore conflicts, recovery points, and job retries.
Fixture users use reserved example.test addresses and are created only in tests.

Passing automated tests does not verify a real user's hosted sign-in. The release gate
also requires that the owner sign in to the deployed application, save a note, reload,
and retrieve it in a fresh session.

## Recovery foundation

Exports currently support **foundation notes only**, format `home-headquarters`, version 1.
They exclude account credentials, memberships, API keys, and OAuth secrets. They cannot
yet back up organizer records or assistant history.

Restore is validated, previewed, and explicitly confirmed. It locks the household,
rejects a stale preview if another parent changed data, saves the old state as a durable
recovery point, and replaces notes in one transaction. Recovery copies can be downloaded
from the private recovery page. Restoring an export does not grant access or replace
household identity or accounts.

For an isolated recovery drill, deploy the same commit against a separate PostgreSQL
database, create a separate owner, import a versioned export, and compare its records.
Do not point an isolated drill at the production database. Provider point-in-time recovery
is separate and requires paid PostgreSQL. Its restore drill is a release requirement.

## Deployment preflight evidence

- A Node-to-Git subprocess failed with `EPERM` inside the Windows sandbox.
- The identical read-only test succeeded with approved execution outside the sandbox.
- The private GitHub connector can read and write this new repository; native GitHub
  source operations are available as another supported publishing path.
- Django's deployment security checks and pure export validation passed locally.
- No hosted authentication, persistence, recovery, or delivery result is claimed until
  it has been observed and recorded in `docs/verification.md`.

## First-release priorities

The prioritized checklist has moved to [TASKS.md](TASKS.md). Keep it as the single backlog;
do not maintain a second roadmap here. [PROJECT.md](PROJECT.md) records the primary
birthday-party acceptance scenario and accepted product changes.
