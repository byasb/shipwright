# Social post drafts (one per platform; pick one, tag #AllThingsAgenticHackathon)

**X / Threads (≤280):**
Built Shipwright for #AllThingsAgenticHackathon: a build lands in App Store Connect → Apple webhook → Cloud Run → 7 ADK agents take it to Waiting for Review. Nothing typed. First real run: 13 blockers found, 13 auto-fixed, and Gemini *saw* a paywall over-promise no API field could. Gemini 3.5 · Gemma 4 · Cloud Run

**LinkedIn:**
I ship iOS apps for a living. The last mile of a release — metadata, screenshots, 175 territory prices, a dozen silent traps — took me two days by hand last week.

So for the #AllThingsAgenticHackathon I built Shipwright: an event-driven agent on Google ADK. A build appearing in App Store Connect is the trigger (Apple webhooks, HMAC-verified, into Cloud Run). Seven agents — a writer⇄critic loop, a parallel compliance preflight that encodes my 64-row rejection index, a triple-gated submitter, a webhook-driven watcher with Gemma 4 routing rejections — take it to Waiting for Review unattended.

First real run on a fresh app: 13 blocking findings, 13 auto-fixes, 4 one-click web gates surfaced, and Gemini vision caught a paywall promising features the build doesn't have. That's a rejection no API field exposes.

Stack: Gemini 3.5 Flash on Vertex AI · Gemma 4 · Veo · Lyria · Cloud Run · Pub/Sub · Firestore · Secret Manager. Repo + 4-min demo in comments.
