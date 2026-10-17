#!/usr/bin/env bash
# One-time setup for phone reminders (REM-01). Run in Google Cloud Shell:
#   bash reminders-setup.sh home-headquarters-prod
# Creates the Web Push key (generated here, stored only in Secret Manager, never shown), a
# no-permission identity for Cloud Scheduler, and a scheduler job that calls the app every
# 15 minutes from 6 AM to 11 PM Eastern. Safe to re-run: the existing key is kept, because a
# new key would turn reminders off on every phone.
# Cost: Cloud Scheduler includes 3 free jobs per billing account; this uses one.
set -euo pipefail
PROJECT="${1:?Usage: bash reminders-setup.sh PROJECT_ID}"
REGION=us-east4
SERVICE=home-headquarters
SCHEDULE="${SCHEDULE:-*/15 6-22 * * *}"
gcloud config set project "$PROJECT" >/dev/null

echo "Enabling Cloud Scheduler..."
gcloud services enable cloudscheduler.googleapis.com

RUNTIME="hhq-runtime@$PROJECT.iam.gserviceaccount.com"
SCHEDULER="hhq-scheduler@$PROJECT.iam.gserviceaccount.com"

echo "Web Push key..."
if gcloud secrets describe hhq-web-push-key >/dev/null 2>&1; then
  echo "  Keeping the existing key."
else
  umask 077
  KEYFILE=$(mktemp)
  openssl ecparam -name prime256v1 -genkey -noout | openssl pkcs8 -topk8 -nocrypt -out "$KEYFILE"
  gcloud secrets create hhq-web-push-key --replication-policy=automatic --data-file="$KEYFILE"
  shred -u "$KEYFILE"
fi
gcloud secrets add-iam-policy-binding hhq-web-push-key --member="serviceAccount:$RUNTIME" \
  --role=roles/secretmanager.secretAccessor >/dev/null

echo "Scheduler identity (no permissions; the app only checks its signed token)..."
gcloud iam service-accounts describe "$SCHEDULER" >/dev/null 2>&1 || \
  gcloud iam service-accounts create hhq-scheduler --display-name="Home Headquarters reminder schedule"
for attempt in $(seq 1 12); do
  gcloud iam service-accounts describe "$SCHEDULER" >/dev/null 2>&1 && break
  echo "  Waiting for the account to be ready..."
  sleep 10
done

HOST=$(gcloud run services describe "$SERVICE" --region "$REGION" --format=json |
  python3 -c "import json,sys; env=json.load(sys.stdin)['spec']['template']['spec']['containers'][0].get('env',[]); print(next((e.get('value','') for e in env if e['name']=='APP_HOSTNAME'),''))")
if [ -z "$HOST" ]; then echo "Could not read APP_HOSTNAME from the $SERVICE service. Deploy the app first."; exit 1; fi
URL="https://$HOST/jobs/reminders/"

echo "Connecting the key and scheduler identity to the app (new revision, same code)..."
gcloud run services update "$SERVICE" --region "$REGION" --quiet \
  --update-secrets WEB_PUSH_PRIVATE_KEY=hhq-web-push-key:latest \
  --update-env-vars "JOB_INVOKER_EMAIL=$SCHEDULER"

echo "Scheduler job ($SCHEDULE, America/New_York)..."
VERB=create
gcloud scheduler jobs describe hhq-reminders --location "$REGION" >/dev/null 2>&1 && VERB=update
gcloud scheduler jobs "$VERB" http hhq-reminders --location "$REGION" --schedule "$SCHEDULE" \
  --time-zone America/New_York --uri "$URL" --http-method POST --attempt-deadline 120s \
  --oidc-service-account-email "$SCHEDULER" --oidc-token-audience "$URL"

echo "Running it once now..."
BEFORE=$(gcloud scheduler jobs describe hhq-reminders --location "$REGION" --format='value(lastAttemptTime)')
gcloud scheduler jobs run hhq-reminders --location "$REGION"
# Wait for the run to finish; before that the status is not meaningful (it can read -1).
for attempt in $(seq 1 12); do
  sleep 10
  AFTER=$(gcloud scheduler jobs describe hhq-reminders --location "$REGION" --format='value(lastAttemptTime)')
  [ -n "$AFTER" ] && [ "$AFTER" != "$BEFORE" ] && break
done
CODE=$(gcloud scheduler jobs describe hhq-reminders --location "$REGION" --format='value(status.code)')
if [ -z "$AFTER" ] || [ "$AFTER" = "$BEFORE" ]; then
  echo "The test run hasn't finished yet. Check later with:"
  echo "  gcloud scheduler jobs describe hhq-reminders --location $REGION --format='yaml(status,lastAttemptTime)'"
elif [ -z "$CODE" ] || [ "$CODE" = "0" ]; then
  echo "Success: the app accepted the scheduler's call."
else
  echo "The app did not accept the call (status $CODE). Share this line and the next command's output:"
  echo "  gcloud logging read 'resource.type=\"cloud_run_revision\" AND httpRequest.requestUrl:\"/jobs/reminders/\"' --limit 3 --format='value(timestamp,httpRequest.status)'"
fi
echo
echo "Next: on your phone open Settings → Phone reminders → Turn on reminders on this device → Send a test."
