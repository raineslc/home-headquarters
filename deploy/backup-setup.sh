#!/usr/bin/env bash
# One-time setup for the weekly automatic backup (FND-03). Run in Google Cloud Shell:
#   bash backup-setup.sh home-headquarters-prod
# Creates a private Cloud Storage bucket in us-east1 (inside Google's free storage allowance),
# deletes backups older than 12 weeks, lets the app only add files (it cannot read, replace or
# delete backups), and tells the app the bucket name. Safe to re-run.
set -euo pipefail
PROJECT="${1:?Usage: bash backup-setup.sh PROJECT_ID}"
REGION=us-east4          # where the app runs
LOCATION=us-east1        # free-tier storage region
SERVICE=home-headquarters
BUCKET="$PROJECT-hhq-backups"
RUNTIME="hhq-runtime@$PROJECT.iam.gserviceaccount.com"
gcloud config set project "$PROJECT" >/dev/null

echo "Backup bucket gs://$BUCKET ($LOCATION)..."
if gcloud storage buckets describe "gs://$BUCKET" >/dev/null 2>&1; then
  echo "  Keeping the existing bucket."
else
  gcloud storage buckets create "gs://$BUCKET" --location="$LOCATION" --default-storage-class=STANDARD \
    --uniform-bucket-level-access --public-access-prevention
fi

echo "Keep 12 weeks, then delete..."
cat > /tmp/hhq-backup-lifecycle.json <<'POLICY'
{"rule": [{"action": {"type": "Delete"}, "condition": {"age": 84}}]}
POLICY
gcloud storage buckets update "gs://$BUCKET" --lifecycle-file=/tmp/hhq-backup-lifecycle.json >/dev/null

echo "Let the app add backups (no reading, replacing or deleting)..."
gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" --member="serviceAccount:$RUNTIME" \
  --role=roles/storage.objectCreator >/dev/null

echo "Telling the app where to save backups (new revision, same code)..."
gcloud run services update "$SERVICE" --region "$REGION" --quiet --update-env-vars "BACKUP_BUCKET=$BUCKET"

echo
echo "Done. The first backup is saved within about 15 minutes (between 6 AM and 11 PM Eastern),"
echo "then every Sunday evening. Or open the app: Settings → Open backup and restore → Back up now."
echo "Backups: https://console.cloud.google.com/storage/browser/$BUCKET?project=$PROJECT"
