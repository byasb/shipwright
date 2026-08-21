#!/usr/bin/env bash
# One-time GCP setup for Shipwright. Idempotent — safe to rerun.
# Requires: gcloud authed, a .p8 at $ASC_P8, and $ASC_ISSUER_ID in env.
set -euo pipefail
PROJECT="${GOOGLE_CLOUD_PROJECT:-inlaid-backbone-506118-k3}"
REGION="${REGION:-asia-south1}"
SA="shipwright-sa"
SA_EMAIL="$SA@$PROJECT.iam.gserviceaccount.com"
BUCKET="${SCREENSHOT_BUCKET:-$PROJECT-shipwright}"
TOPIC="shipwright.jobs"
ASC_P8="${ASC_P8:-$HOME/.appstoreconnect/private_keys/AuthKey_YL98VF4UNZ.p8}"

gcloud config set project "$PROJECT" >/dev/null
gcloud services enable run.googleapis.com pubsub.googleapis.com firestore.googleapis.com \
  secretmanager.googleapis.com aiplatform.googleapis.com cloudscheduler.googleapis.com \
  storage.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com

# service account with least privilege
gcloud iam service-accounts create "$SA" --display-name "Shipwright agent" 2>/dev/null || true
for role in roles/datastore.user roles/pubsub.publisher roles/secretmanager.secretAccessor \
            roles/aiplatform.user roles/storage.objectAdmin roles/logging.logWriter; do
  gcloud projects add-iam-policy-binding "$PROJECT" --member "serviceAccount:$SA_EMAIL" --role "$role" --quiet >/dev/null
done

# secrets — the .p8 goes to Secret Manager and NOWHERE else
mk_secret() { # name, value-from-stdin
  if gcloud secrets describe "$1" >/dev/null 2>&1; then
    gcloud secrets versions add "$1" --data-file=-
  else
    gcloud secrets create "$1" --replication-policy automatic --data-file=-
  fi
}
[ -f "$ASC_P8" ] && mk_secret asc-private-key < "$ASC_P8"
[ -n "${ASC_ISSUER_ID:-}" ] && printf '%s' "$ASC_ISSUER_ID" | mk_secret asc-issuer-id
if ! gcloud secrets describe asc-webhook-secret >/dev/null 2>&1; then
  openssl rand -hex 32 | tr -d '\n' | mk_secret asc-webhook-secret
fi

# queue + dead letter
gcloud pubsub topics create "$TOPIC" 2>/dev/null || true
gcloud pubsub topics create "$TOPIC.dead" 2>/dev/null || true

# screenshot bucket (composites + sources)
gcloud storage buckets create "gs://$BUCKET" --location "$REGION" --uniform-bucket-level-access 2>/dev/null || true

# Firestore already exists in this project (native, asia-south1). Create if not:
gcloud firestore databases describe --database='(default)' >/dev/null 2>&1 || \
  gcloud firestore databases create --location "$REGION" --type firestore-native

echo "setup done: project=$PROJECT sa=$SA_EMAIL bucket=gs://$BUCKET topic=$TOPIC"
