# Devpost submission — Shipwright

**Track:** The Taskmaster · **Category bonus:** Gemma 4 + Veo 3.1 + Lyria (three additional Google models)

## Inspiration
I have 14 apps on the App Store. The week before this hackathon I spent two days taking a new one from
"build uploaded" to "Waiting for Review" by hand: bundle id, app record, subscription group, localizations,
175 territory prices, availability, review screenshots, metadata. I hit a 55-character limit I'd forgotten,
a rerun that silently skipped a localization, and an availability default that would have left an in-app
purchase buyable in exactly one country. I keep a 64-row error index of these. That index is the product.

## What it does
A build appearing in App Store Connect wakes the agent (Apple webhook → Cloud Run). Seven agents then take
the version to Waiting for Review unattended: an intake agent, a metadata writer and a separate critic in an
ADK LoopAgent, a screenshot compositor that never lets an image model redraw the UI, a parallel compliance
preflight that encodes the error index as API checks with auto-fixes, a triple-gated submission agent, and a
webhook-driven watcher that routes Apple's rejection text back to the right agent via Gemma 4 + Gemini.

On its first real run against a fresh app record it found 13 blocking problems, auto-fixed 13, surfaced 4
one-click web-only gates, and — via Gemini vision over the real captures — flagged a paywall promising
features the build doesn't have and a cleartext password in the sample data. Those two are rejections; no
API field could have revealed them.

## How we built it
Google ADK 2.7 (Agent / LoopAgent / ParallelAgent / custom BaseAgent checks) · Gemini 3.5 Flash on Vertex AI ·
Gemma 4 via the Gemini API · Cloud Run (scale-to-zero, one image, three roles) · Pub/Sub push with OIDC and a
dead-letter topic · Firestore for multi-day job state · Cloud Storage · Secret Manager for the ASC `.p8`
(read at runtime, never an env var, never in the image) · Cloud Scheduler reconcile · raw App Store Connect
REST with ES256 JWTs, backoff, and a read-back after every write.

## Challenges
- `buildUploads` is GET-instance only and the instance carries no build relationship — the build turned out
  to share the upload's UUID. A crash on the very first real delivery was absorbed by Apple's retry/redeliver.
- App Groups cannot be registered with an API key or a signed-out Xcode; build 2 ships without the extensions
  and the facts the agent writes from were edited so the metadata never over-claims.
- Several submission gates are web-only by design (App Privacy publish, medical-device banner, Paid Apps
  Agreement, first-IAP draft attach). The honest answer is to surface them as operator items, not hide them.
- The Gemini API free tier has zero quota for Veo/Lyria — those run on Vertex instead.

## Accomplishments
Real push trigger from Apple, verified HMAC, first delivery to a job in under 2 minutes of upload. A
critique loop that converges in one round because the critic has a deterministic validator as a tool.
A preflight whose every row is a rejection I already paid for.

## What we learned
A 2xx from Apple means stored, not done. Give the critic tools, not taste. Vision on real pixels catches what
fields can't. Surface the gates you can't automate instead of pretending.

## What's next
Gmail watcher for Resolution Center text so rejections route with zero paste; multi-locale metadata;
TestFlight beta-review path; running it across all 14 apps.

## Built with
google-adk · gemini-3.5-flash · gemma-4 · veo-3.1 · lyria · vertex-ai · cloud-run · pub-sub · firestore ·
cloud-storage · secret-manager · cloud-scheduler · python · fastapi · pillow · app-store-connect-api
