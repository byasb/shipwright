# I let an agent do the last mile of an App Store release. Here's what it caught.

*Written for the All Things Agentic Hackathon (Google), August 2026.*

I ship iOS apps for a living — fourteen of them on the store. The part of a release nobody talks about is the
mile between "the binary uploaded" and "Waiting for Review": name, subtitle, a 100-character keyword field
where repeating a word is a wasted slot, screenshots in exactly the right pixel sizes, 175 territory prices,
availability, an age-rating questionnaire that grew seven new mandatory booleans this year, review notes
with a phone number that needs a country code, and in-app purchases that sit in `MISSING_METADATA` until
you upload a review screenshot nobody told you about.

Last week that mile took me two days. I keep an error index of every rejection and silent trap I've hit —
64 rows. So for this hackathon I built the agent I wanted to have: **Shipwright**. A build appearing in App
Store Connect wakes it (Apple has webhooks now — real push, HMAC-signed). Seven agents on Google ADK take
it from there.

## The shape

- **Intake** is code. Webhook → build → version → job.
- **Metadata writer ⇄ critic** is an ADK `LoopAgent`. The trick that made it work: the critic's only job is
  to reject, and it has a *deterministic validator as a tool*. Without the tool, a second LLM approves
  31-character names. With it, the loop converges in one round and the model spends its judgment on claims
  and tone — the things code can't see.
- **Screenshots** are composited from real device pixels with Pillow. An image model never touches the UI,
  because it will hallucinate a "SAVE 30%" badge you don't have.
- **Preflight** is an ADK `ParallelAgent`: fourteen checks, each an error-index row as an API read, with an
  auto-fix where Apple's API allows one and a one-click *operator item* where only a web page can do it.
- **Submission** is triple-gated: `DRY_RUN`, `ALLOW_SUBMIT`, and a hard allowlist of app ids. Thirteen of
  my apps are live; a write to the wrong record is damage.
- **Watcher** gets Apple's review-state transitions by the same webhook, days later, with no polling. A
  rejection gets a Gemma 4 first-pass label and a Gemini routing decision, and the job re-queues itself.

## What it found on a real app, first run

Thirteen blocking problems on a fresh app record — including two that only exist because I'd done this by
hand before: new apps have *no* price schedule (required even for Free) and *no* availability (sold
nowhere). Thirteen auto-fixes. Four web-only gates surfaced as operator items.

And then the one I didn't plan for. I added a Gemini-vision pass over the real screenshots with the app's
fact sheet as context. It flagged that the paywall promised "multi-device sync" and a "custom keyboard" —
neither ships in this version — and that the sample data on screen one showed a cleartext Wi-Fi password.
Both are App Review rejections. Neither is a field in any API.

## Things I learned

1. **A 2xx from Apple means stored, not done.** Every fixer reads state back; preflight re-runs after fixes.
2. **Some gates are web-only on purpose.** App Privacy publish, the medical-device banner, the Paid Apps
   Agreement. The honest design surfaces them; it doesn't pretend.
3. **Give the critic tools, not taste.**
4. **Gemma is the right size for a ten-token label.** Cheap classification before the frontier model.
5. **App Groups can't be registered by API key** — so build 2 shipped without the share-sheet extension, and
   I edited the facts the agent writes from so the metadata never claims what the binary can't do.

Code: [github repo]. Stack: ADK · Gemini 3.5 Flash on Vertex · Gemma 4 · Cloud Run · Pub/Sub · Firestore ·
Secret Manager. #AllThingsAgenticHackathon
