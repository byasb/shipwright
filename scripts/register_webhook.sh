#!/usr/bin/env bash
# One-time: tell App Store Connect to POST build + version-state events to the Cloud Run service.
# Uses the locally-authenticated `asc` CLI (keychain). The shared secret comes from Secret Manager
# so the service and Apple agree without the secret ever touching the repo.
set -euo pipefail
URL="${1:?usage: register_webhook.sh https://<cloud-run-url>}"
PROJECT="${GOOGLE_CLOUD_PROJECT:-inlaid-backbone-506118-k3}"
APP="${ASC_APP_ID:-6803901837}"
SECRET="$(gcloud secrets versions access latest --secret asc-webhook-secret --project "$PROJECT")"
EVENTS="BUILD_UPLOAD_STATE_UPDATED,APP_STORE_VERSION_APP_VERSION_STATE_UPDATED"
existing="$(asc webhooks list --app "$APP" | python3 -c 'import sys,json; print(" ".join(w["id"] for w in json.load(sys.stdin)["data"] if w["attributes"].get("name")=="shipwright"))')"
if [ -n "$existing" ]; then
  for id in $existing; do asc webhooks update --webhook-id "$id" --url "$URL/webhook/asc" --enabled true >/dev/null; echo "updated webhook $id"; done
else
  asc webhooks create --app "$APP" --name shipwright --url "$URL/webhook/asc" --secret "$SECRET" --events "$EVENTS" --enabled true --pretty
fi
asc webhooks list --app "$APP" --output table
