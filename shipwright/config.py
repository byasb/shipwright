"""Runtime config + safety rails. Every ASC write path consults this module."""
import os
from dotenv import load_dotenv

load_dotenv()

PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
MODEL = os.environ.get("MODEL", "gemini-3.5-flash")
GEMMA_MODEL = os.environ.get("GEMMA_MODEL", "gemma-3-27b-it")

# --- safety rails -------------------------------------------------------
DRY_RUN = os.environ.get("DRY_RUN", "true").lower() != "false"
ALLOW_SUBMIT = os.environ.get("ALLOW_SUBMIT", "false").lower() == "true"
ALLOWED_APP_IDS = frozenset(
    x.strip() for x in os.environ.get("ALLOWED_APP_IDS", "6803901837").split(",") if x.strip()
)


class AppNotAllowed(Exception):
    """Raised before ANY write against an app outside the allowlist."""


def assert_app_allowed(app_id: str) -> None:
    if str(app_id) not in ALLOWED_APP_IDS:
        raise AppNotAllowed(f"app {app_id} is not in ALLOWED_APP_IDS={sorted(ALLOWED_APP_IDS)}")


# --- App Store Connect credentials -------------------------------------
ASC_KEY_ID = os.environ.get("ASC_KEY_ID", "")
ASC_ISSUER_ID = os.environ.get("ASC_ISSUER_ID", "")
ASC_PRIVATE_KEY_PATH = os.environ.get("ASC_PRIVATE_KEY_PATH", "")
ASC_WEBHOOK_SECRET = os.environ.get("ASC_WEBHOOK_SECRET", "")

# --- operator facts -----------------------------------------------------
REVIEW_CONTACT = {
    "contactFirstName": os.environ.get("REVIEW_CONTACT_FIRST", ""),
    "contactLastName": os.environ.get("REVIEW_CONTACT_LAST", ""),
    "contactEmail": os.environ.get("REVIEW_CONTACT_EMAIL", ""),
    "contactPhone": os.environ.get("REVIEW_CONTACT_PHONE", ""),
}
SUPPORT_URL = os.environ.get("SUPPORT_URL", "")
PRIVACY_URL = os.environ.get("PRIVACY_URL", "")
BUCKET = os.environ.get("SCREENSHOT_BUCKET", f"{PROJECT}-shipwright")
PUBSUB_TOPIC = os.environ.get("PUBSUB_TOPIC", "shipwright.jobs")


def secret(name: str) -> str:
    """Read a Secret Manager secret at runtime. Never cached to disk."""
    from google.cloud import secretmanager

    client = secretmanager.SecretManagerServiceClient()
    path = f"projects/{PROJECT}/secrets/{name}/versions/latest"
    return client.access_secret_version(name=path).payload.data.decode()


def private_key() -> str:
    """Local dev: file path. Cloud Run: Secret Manager. Never both, never the repo."""
    if ASC_PRIVATE_KEY_PATH:
        with open(os.path.expanduser(ASC_PRIVATE_KEY_PATH)) as f:
            return f.read()
    return secret("asc-private-key")


def issuer_id() -> str:
    return ASC_ISSUER_ID or secret("asc-issuer-id")


def webhook_secret() -> str:
    return ASC_WEBHOOK_SECRET or secret("asc-webhook-secret")
