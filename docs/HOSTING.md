# Hosting: Google Cloud Run + Neon (FND-03)

**Status:** live since October 16, 2026 at https://home-headquarters-140747200253.us-east4.run.app.
Render is retired (database kept as a fallback until it expires November 11).

Owner approved October 14, 2026, after Render's free tier missed deploys and paused free
deploys during an incident. Goal: about $0/month for one household, with a budget alert.

| Piece | Service | Notes |
|---|---|---|
| App | Cloud Run `home-headquarters`, region us-east4 | Scales to zero; min 0, max 2 instances, 512 MiB |
| Sign-in | OAuth client "Home Headquarters (Cloud Run)" in home-headquarters-prod | Calendar API enabled; scopes include calendar.app.created |
| Database | Neon PostgreSQL 17, US East (Virginia) | Free plan; use the **direct** (non-pooler) connection string, because `migrate_locked` holds a session advisory lock |
| Secrets | Secret Manager (`hhq-*`) | Django key, database URL, Google client secret and token key, OpenAI key |
| Images | Artifact Registry `hhq` (us-east4) | Cleanup keeps the 3 newest images |
| Deploys | GitHub Actions `deploy-cloud-run` job | Workload Identity Federation, main branch only; no stored keys |
| Migrations | Cloud Run job `hhq-migrate` | Runs before each web deploy, so cold starts stay fast |

The Google sign-in client moves to `home-headquarters-prod` (owner decision): a new web client
with the Cloud Run redirect address, Calendar API enabled and the same scopes, including
`calendar.app.created`. Google ties refresh tokens to the client that issued them, so each
parent reconnects Google once on the new site; old connections show "Reconnect required".

`GOOGLE_TOKEN_KEY` must be copied exactly from Render; it decrypts the stored Google refresh
tokens. A new `DJANGO_SECRET_KEY` is generated, so everyone signs in once after the move.
`BOOTSTRAP_TOKEN` and `OWNER_EMAIL` are not carried over: setup is already closed in the
database (QA-04).

## Steps

1. **Backup:** download an export from Settings → Backup and restore on the current site.
2. **Google Cloud setup:** in Google Cloud Shell, run `bash gcp-setup.sh PROJECT_ID` (from
   `deploy/`). Values from Render → Environment are typed into hidden prompts. Then:
   - add the printed repository variables (`GCP_PROJECT_ID`, `GCP_WIF_PROVIDER`,
     `APP_HOSTNAME`, `GOOGLE_CLIENT_ID`) in GitHub → Settings → Secrets and variables →
     Actions → **Variables**;
   - add the printed redirect URI to the Google sign-in client;
   - create a budget alert (Billing → Budgets & alerts, $5, email at 50/90/100%).
3. **Copy the database:** allow Cloud Shell's address in Render → database → Networking, run
   `bash copy-database.sh`, confirm "Row counts match", then remove the address again.
4. **Deploy:** the next merge to main (or re-running the latest main workflow) builds the
   image, runs migrations on Neon and deploys. The job checks `/health/` afterwards.
5. **Check the new site:** sign in, view calendar, tasks and lunches, Google calendars (Sync
   now), and Settings → App version shows the deployed commit.
6. **Cutover:** stop making changes on Render, run `copy-database.sh` again for a final copy,
   check again, then use the new address. Keep Render until November 11 as a read-only fallback.

## Phone reminders (REM-01)

1. In Cloud Shell, upload `deploy/reminders-setup.sh` and run `bash reminders-setup.sh home-headquarters-prod`.
   It generates the Web Push key straight into Secret Manager (`hhq-web-push-key`; never
   shown), creates the permission-less `hhq-scheduler` identity, connects both to the app and
   creates the Cloud Scheduler job `hhq-reminders` (every 15 minutes, 6 AM–11 PM Eastern), then
   runs it once. Re-running keeps the existing key (a new key would switch off every phone).
2. On each phone: Settings → Phone reminders → Turn on reminders on this device → Send a test.
3. The scheduler calls `POST /jobs/reminders/` with a Google-signed identity token; the app
   accepts only the `hhq-scheduler` identity for exactly that address. Change the times with
   `SCHEDULE="*/20 6-22 * * *" bash reminders-setup.sh home-headquarters-prod`.
4. The deploy job updates (rather than replaces) the service's secrets and settings, so the
   reminder key and scheduler identity stay attached across deploys.
5. The same call also refreshes shared Google calendars and retries failed family-calendar
   updates (GGL-04), so no extra scheduler job is needed.

## Costs to watch

Cloud Run, Secret Manager and Artifact Registry have monthly free allowances that one family
should stay well inside; Neon's free plan has no expiry. Prices and allowances change, so the
budget alert is the safety net. Any paid upgrade needs the owner's approval.

Reminders: Cloud Scheduler gives 3 free jobs per billing account (this uses one). Each run
wakes the Neon database, which then stays on about 5 minutes; every 15 minutes for 17 hours a
day is roughly 40–45 of Neon's free monthly compute hours (100 per project at the time of
writing; check Neon → Usage). If usage gets close, slow the schedule (step 3 above).

## Lessons from the move (October 15–16)

- Paste each value **once**; hidden prompts make doubles easy. Prefer the visible editor:
  `nano ~/value.txt`, then `tr -d '\r\n ' < ~/value.txt | gcloud secrets versions add NAME --data-file=- && shred -u ~/value.txt`.
- Check a secret without showing it: length, number of `://`, and host only.
- Secrets are read when Cloud Run starts. After changing one, restart with
  `gcloud run services update home-headquarters --region us-east4 --update-env-vars SECRETS_REFRESHED=$(date +%s)`.
- A new OAuth client needs its own secret (create one on the client page) and Calendar API
  enabled in the same project; old Google connections must reconnect.
