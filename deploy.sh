#!/usr/bin/env bash
# Build + deploy Shipwright to Cloud Run, wire Pub/Sub push + Cloud Scheduler reconcile.
# Safe defaults: DRY_RUN=true ALLOW_SUBMIT=false. Flip with:  DRY_RUN=false ALLOW_SUBMIT=true ./deploy.sh
set -euo pipefail
PROJECT="${GOOGLE_CLOUD_PROJECT:-inlaid-backbone-506118-k3}"
REGION="${REGION:-asia-south1}"
SERVICE="shipwright"
SA="shipwright-sa@$PROJECT.iam.gserviceaccount.com"
TOPIC="shipwright.jobs"
BUCKET="${SCREENSHOT_BUCKET:-$PROJECT-shipwright}"
DRY_RUN="${DRY_RUN:-true}"
ALLOW_SUBMIT="${ALLOW_SUBMIT:-false}"
ALLOWED_APP_IDS="${ALLOWED_APP_IDS:-6803901837}"

gcloud run deploy "$SERVICE" --source . --project "$PROJECT" --region "$REGION" \
  --service-account "$SA" \
  --min-instances 0 --max-instances 2 --concurrency 4 --timeout 1800 --memory 2Gi --cpu 2 \
  --allow-unauthenticated \
  --set-env-vars "GOOGLE_CLOUD_PROJECT=$PROJECT,GOOGLE_CLOUD_LOCATION=global,GOOGLE_GENAI_USE_VERTEXAI=true,MODEL=${MODEL:-gemini-3.5-flash},GEMMA_MODEL=${GEMMA_MODEL:-gemma-4-31b-it},PUBSUB_TOPIC=$TOPIC,SCREENSHOT_BUCKET=$BUCKET,ASC_KEY_ID=${ASC_KEY_ID:-YL98VF4UNZ},DRY_RUN=$DRY_RUN,ALLOW_SUBMIT=$ALLOW_SUBMIT,ALLOWED_APP_IDS=$ALLOWED_APP_IDS,REVIEW_CONTACT_FIRST=${REVIEW_CONTACT_FIRST:-Ankit},REVIEW_CONTACT_LAST=${REVIEW_CONTACT_LAST:-Bhandari},REVIEW_CONTACT_EMAIL=${REVIEW_CONTACT_EMAIL:-ankit@utenx.com},REVIEW_CONTACT_PHONE=${REVIEW_CONTACT_PHONE:-},SUPPORT_URL=${SUPPORT_URL:-https://byasb.com/snipstash},PRIVACY_URL=${PRIVACY_URL:-https://byasb.com/snipstash/privacy}" \
  --set-secrets "GEMINI_API_KEY=gemini-api-key:latest"
# NOTE: asc-private-key / asc-issuer-id / asc-webhook-secret are read via the Secret Manager API at
# runtime (config.secret) — not mounted as env, so they never appear in `gcloud run services describe`.

URL="$(gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" --format 'value(status.url)')"
echo "URL=$URL"

# Pub/Sub push → /pubsub (OIDC as the service SA), dead-letter after 5 attempts
gcloud pubsub subscriptions create "$TOPIC.push" --project "$PROJECT" --topic "$TOPIC" \
  --push-endpoint "$URL/pubsub" --push-auth-service-account "$SA" \
  --ack-deadline 600 --dead-letter-topic "$TOPIC.dead" --max-delivery-attempts 5 --min-retry-delay 60s --max-retry-delay 600s 2>/dev/null \
  || gcloud pubsub subscriptions modify-push-config "$TOPIC.push" --project "$PROJECT" --push-endpoint "$URL/pubsub" --push-auth-service-account "$SA"
gcloud pubsub subscriptions create "$TOPIC.dead.sub" --project "$PROJECT" --topic "$TOPIC.dead" 2>/dev/null || true

# Cloud Scheduler reconcile every 30 min (missed-webhook net + review-state refresh)
gcloud scheduler jobs create http shipwright-reconcile --project "$PROJECT" --location "$REGION" \
  --schedule "*/30 * * * *" --uri "$URL/reconcile" --http-method POST \
  --oidc-service-account-email "$SA" --oidc-token-audience "$URL/reconcile" 2>/dev/null \
  || gcloud scheduler jobs update http shipwright-reconcile --project "$PROJECT" --location "$REGION" --uri "$URL/reconcile" --oidc-token-audience "$URL/reconcile"

echo
echo "Next: scripts/register_webhook.sh $URL   (one-time: tells App Store Connect where to POST)"
