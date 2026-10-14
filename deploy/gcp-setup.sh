#!/usr/bin/env bash
# One-time Google Cloud setup for Home Headquarters on Cloud Run (FND-03).
# Run in Google Cloud Shell:  bash gcp-setup.sh YOUR_PROJECT_ID
# Secret values are typed into hidden prompts and stored only in Secret Manager.
# Safe to re-run: existing resources and secrets are kept.
set -euo pipefail
PROJECT="${1:?Usage: bash gcp-setup.sh PROJECT_ID}"
REGION=us-east4
GITHUB_REPO=raineslc/home-headquarters

gcloud config set project "$PROJECT" >/dev/null
NUMBER=$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')
echo "Enabling services (one minute)..."
gcloud services enable run.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com \
  iam.googleapis.com iamcredentials.googleapis.com sts.googleapis.com

echo "Image repository (keeps the 3 newest images to stay inside the free storage allowance)..."
gcloud artifacts repositories describe hhq --location "$REGION" >/dev/null 2>&1 || \
  gcloud artifacts repositories create hhq --repository-format=docker --location "$REGION" --description="Home Headquarters images"
cat > /tmp/hhq-cleanup.json <<'POLICY'
[{"name": "keep-newest", "action": {"type": "Keep"}, "mostRecentVersions": {"keepCount": 3}},
 {"name": "delete-older", "action": {"type": "Delete"}, "condition": {"tagState": "any", "olderThan": "1d"}}]
POLICY
gcloud artifacts repositories set-cleanup-policies hhq --location "$REGION" --policy=/tmp/hhq-cleanup.json --no-dry-run >/dev/null

echo "Service accounts..."
RUNTIME="hhq-runtime@$PROJECT.iam.gserviceaccount.com"
DEPLOYER="hhq-deployer@$PROJECT.iam.gserviceaccount.com"
gcloud iam service-accounts describe "$RUNTIME" >/dev/null 2>&1 || \
  gcloud iam service-accounts create hhq-runtime --display-name="Home Headquarters app (runtime)"
gcloud iam service-accounts describe "$DEPLOYER" >/dev/null 2>&1 || \
  gcloud iam service-accounts create hhq-deployer --display-name="Home Headquarters deploys (GitHub Actions)"
for role in roles/run.admin roles/artifactregistry.writer; do
  gcloud projects add-iam-policy-binding "$PROJECT" --member="serviceAccount:$DEPLOYER" --role="$role" --condition=None >/dev/null
done
gcloud iam service-accounts add-iam-policy-binding "$RUNTIME" --member="serviceAccount:$DEPLOYER" \
  --role=roles/iam.serviceAccountUser >/dev/null

echo "GitHub Actions sign-in without stored keys (Workload Identity Federation, main branch only)..."
gcloud iam workload-identity-pools describe github --location=global >/dev/null 2>&1 || \
  gcloud iam workload-identity-pools create github --location=global --display-name="GitHub Actions"
gcloud iam workload-identity-pools providers describe github --workload-identity-pool=github --location=global >/dev/null 2>&1 || \
  gcloud iam workload-identity-pools providers create-oidc github --workload-identity-pool=github --location=global \
    --issuer-uri="https://token.actions.githubusercontent.com" \
    --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.ref=assertion.ref" \
    --attribute-condition="assertion.repository=='$GITHUB_REPO' && assertion.ref=='refs/heads/main'"
gcloud iam service-accounts add-iam-policy-binding "$DEPLOYER" --role=roles/iam.workloadIdentityUser \
  --member="principalSet://iam.googleapis.com/projects/$NUMBER/locations/global/workloadIdentityPools/github/attribute.repository/$GITHUB_REPO" >/dev/null

secret() {  # name, prompt
  if gcloud secrets describe "$1" >/dev/null 2>&1; then
    echo "  $1 already exists (kept)."
  else
    read -r -s -p "  $2: " value; echo
    [ -n "$value" ] || { echo "  Empty value; stopping. Re-run the script to continue."; exit 1; }
    printf '%s' "$value" | gcloud secrets create "$1" --data-file=- --replication-policy=automatic >/dev/null
    unset value
  fi
  gcloud secrets add-iam-policy-binding "$1" --member="serviceAccount:$RUNTIME" \
    --role=roles/secretmanager.secretAccessor >/dev/null
}
echo "Secrets (typing is hidden; paste and press Enter):"
if ! gcloud secrets describe hhq-django-secret-key >/dev/null 2>&1; then
  python3 -c "import secrets; print(secrets.token_urlsafe(50), end='')" | \
    gcloud secrets create hhq-django-secret-key --data-file=- --replication-policy=automatic >/dev/null
  echo "  hhq-django-secret-key generated."
fi
gcloud secrets add-iam-policy-binding hhq-django-secret-key --member="serviceAccount:$RUNTIME" --role=roles/secretmanager.secretAccessor >/dev/null
read -r -s -p "  Neon DIRECT connection string (Neon > Connect, connection pooling OFF): " neon; echo
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
gcloud secrets add-iam-policy-binding hhq-database-url --member="serviceAccount:$RUNTIME" --role=roles/secretmanager.secretAccessor >/dev/null
secret hhq-google-token-key "GOOGLE_TOKEN_KEY from Render > Environment (must match exactly)"
secret hhq-google-client-secret "GOOGLE_CLIENT_SECRET from Render > Environment"
secret hhq-openai-api-key "OPENAI_API_KEY from Render > Environment"

HOST="home-headquarters-$NUMBER.$REGION.run.app"
cat <<SUMMARY

Done. Add these as GitHub repository VARIABLES (not secrets) at
https://github.com/$GITHUB_REPO/settings/variables/actions
  GCP_PROJECT_ID   = $PROJECT
  GCP_WIF_PROVIDER = projects/$NUMBER/locations/global/workloadIdentityPools/github/providers/github
  APP_HOSTNAME     = $HOST
  GOOGLE_CLIENT_ID = (the GOOGLE_CLIENT_ID value from Render > Environment; it is not secret)

In Google Cloud Console > Google Auth Platform > Clients > your web client, add this
authorized redirect URI (keep the Render one until cutover):
  https://$HOST/connections/google/callback/

New site address after the first deploy: https://$HOST
SUMMARY
