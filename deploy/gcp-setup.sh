#!/usr/bin/env bash
# One-time Google Cloud setup for Home Headquarters on Cloud Run (FND-03).
# Run in Google Cloud Shell:  bash gcp-setup.sh YOUR_PROJECT_ID
# Secret values are typed into hidden prompts and stored only in Secret Manager.
# Safe to re-run: existing resources and secrets are kept.
set -euo pipefail
PROJECT="${1:?Usage: bash gcp-setup.sh PROJECT_ID}"
REGION=us-east4
GITHUB_REPO=raineslc/home-headquarters

# Newly created service accounts can take a minute to become visible to IAM. Retry quietly,
# and show Google's error only if the last attempt still fails.
retry() {
  for attempt in 1 2 3 4 5 6; do
    "$@" >/dev/null 2>&1 && return 0
    echo "  Google is still finishing setup; retrying in 15 seconds..."
    sleep 15
  done
  "$@" >/dev/null
}

gcloud config set project "$PROJECT" >/dev/null
NUMBER=$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')
echo "Enabling services (one minute)..."
gcloud services enable run.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com \
  iam.googleapis.com iamcredentials.googleapis.com sts.googleapis.com calendar-json.googleapis.com

echo "Image repository (keeps the 3 newest images to stay inside the free storage allowance)..."
gcloud artifacts repositories describe hhq --location "$REGION" >/dev/null 2>&1 || \
  gcloud artifacts repositories create hhq --repository-format=docker --location "$REGION" --description="Home Headquarters images"
cat > /tmp/hhq-cleanup.json <<'POLICY'
[{"name": "keep-newest", "action": {"type": "Keep"}, "mostRecentVersions": {"keepCount": 3}},
 {"name": "delete-older", "action": {"type": "Delete"}, "condition": {"tagState": "any", "olderThan": "1d"}}]
POLICY
retry gcloud artifacts repositories set-cleanup-policies hhq --location "$REGION" --policy=/tmp/hhq-cleanup.json --no-dry-run

echo "Service accounts..."
RUNTIME="hhq-runtime@$PROJECT.iam.gserviceaccount.com"
DEPLOYER="hhq-deployer@$PROJECT.iam.gserviceaccount.com"
gcloud iam service-accounts describe "$RUNTIME" >/dev/null 2>&1 || \
  gcloud iam service-accounts create hhq-runtime --display-name="Home Headquarters app (runtime)"
gcloud iam service-accounts describe "$DEPLOYER" >/dev/null 2>&1 || \
  gcloud iam service-accounts create hhq-deployer --display-name="Home Headquarters deploys (GitHub Actions)"
for account in "$RUNTIME" "$DEPLOYER"; do
  for attempt in $(seq 1 12); do
    gcloud iam service-accounts describe "$account" >/dev/null 2>&1 && break
    echo "  Waiting for $account to be ready..."
    sleep 10
  done
done
for role in roles/run.admin roles/artifactregistry.writer; do
  retry gcloud projects add-iam-policy-binding "$PROJECT" --member="serviceAccount:$DEPLOYER" --role="$role" --condition=None
done
retry gcloud iam service-accounts add-iam-policy-binding "$RUNTIME" --member="serviceAccount:$DEPLOYER" \
  --role=roles/iam.serviceAccountUser

echo "GitHub Actions sign-in without stored keys (Workload Identity Federation, main branch only)..."
gcloud iam workload-identity-pools describe github --location=global >/dev/null 2>&1 || \
  gcloud iam workload-identity-pools create github --location=global --display-name="GitHub Actions"
gcloud iam workload-identity-pools providers describe github --workload-identity-pool=github --location=global >/dev/null 2>&1 || \
  gcloud iam workload-identity-pools providers create-oidc github --workload-identity-pool=github --location=global \
    --issuer-uri="https://token.actions.githubusercontent.com" \
    --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.ref=assertion.ref" \
    --attribute-condition="assertion.repository=='$GITHUB_REPO' && assertion.ref=='refs/heads/main'"
retry gcloud iam service-accounts add-iam-policy-binding "$DEPLOYER" --role=roles/iam.workloadIdentityUser \
  --member="principalSet://iam.googleapis.com/projects/$NUMBER/locations/global/workloadIdentityPools/github/attribute.repository/$GITHUB_REPO"

grant() {  # let the app's runtime account read one secret
  retry gcloud secrets add-iam-policy-binding "$1" --member="serviceAccount:$RUNTIME" --role=roles/secretmanager.secretAccessor
}
clean() {  # label, value: refuse stray key presses, spaces and double pastes (hidden prompts hide them)
  if [ -z "$2" ]; then echo "  Empty $1; stopping. Re-run the script to continue."; exit 1; fi
  if printf '%s' "$2" | LC_ALL=C grep -q '[[:cntrl:][:space:]]'; then
    echo "  The $1 contains spaces or stray key presses. Re-run and paste it once, then press Enter only."; exit 1
  fi
  if [ "$(printf '%s' "$2" | grep -o '://' | wc -l)" -gt 1 ]; then
    echo "  The $1 looks pasted twice. Re-run and paste it once."; exit 1
  fi
}
secret() {  # name, prompt
  if gcloud secrets describe "$1" >/dev/null 2>&1; then
    echo "  $1 already exists (kept)."
  else
    read -r -s -p "  $2: " value; echo
    clean "$1" "$value"
    printf '%s' "$value" | gcloud secrets create "$1" --data-file=- --replication-policy=automatic >/dev/null
    unset value
  fi
  grant "$1"
}
echo "Secrets (typing is hidden; paste and press Enter):"
if ! gcloud secrets describe hhq-django-secret-key >/dev/null 2>&1; then
  python3 -c "import secrets; print(secrets.token_urlsafe(50), end='')" | \
    gcloud secrets create hhq-django-secret-key --data-file=- --replication-policy=automatic >/dev/null
  echo "  hhq-django-secret-key generated."
fi
grant hhq-django-secret-key
read -r -s -p "  Neon DIRECT connection string (Neon > Connect, connection pooling OFF): " neon; echo
clean "Neon connection string" "$neon"
[ "$(printf '%s' "$neon" | grep -o '://' | wc -l)" -eq 1 ] || { echo "  That is not a single connection string."; exit 1; }
rest="${neon#*@}"; echo "  Neon host: ${rest%%[/:?]*}"; unset rest
case "$neon" in
  *-pooler*) echo "  That is the pooled string. Turn pooling off in Neon's Connect dialog and copy again."; exit 1 ;;
  postgres*://*) ;;
  *) echo "  That does not look like a PostgreSQL connection string."; exit 1 ;;
esac
if gcloud secrets describe hhq-database-url >/dev/null 2>&1; then
  printf '%s' "$neon" | gcloud secrets versions add hhq-database-url --data-file=- >/dev/null
else
  printf '%s' "$neon" | gcloud secrets create hhq-database-url --data-file=- --replication-policy=automatic >/dev/null
fi
unset neon
grant hhq-database-url
secret hhq-google-token-key "GOOGLE_TOKEN_KEY from Render > Environment (must match exactly)"
secret hhq-google-client-secret "Client secret of THIS project's web sign-in client (starts with GOCSPX-)"
secret hhq-openai-api-key "OPENAI_API_KEY from Render > Environment"

HOST="home-headquarters-$NUMBER.$REGION.run.app"
cat <<SUMMARY

Done. Add these as GitHub repository VARIABLES (not secrets) at
https://github.com/$GITHUB_REPO/settings/variables/actions
  GCP_PROJECT_ID   = $PROJECT
  GCP_WIF_PROVIDER = projects/$NUMBER/locations/global/workloadIdentityPools/github/providers/github
  APP_HOSTNAME     = $HOST
  GOOGLE_CLIENT_ID = (the Client ID of this project's web sign-in client; it is not secret)

The sign-in client must be in this project (Google Auth Platform > Clients > Web application)
with this authorized redirect URI:
  https://$HOST/connections/google/callback/
If you create the client after this script, store its secret with:
  nano ~/value.txt   (paste once, save), then
  tr -d '\r\n ' < ~/value.txt | gcloud secrets versions add hhq-google-client-secret --data-file=- && shred -u ~/value.txt

New site address after the first deploy: https://$HOST
SUMMARY
