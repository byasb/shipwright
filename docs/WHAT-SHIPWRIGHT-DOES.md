# What Shipwright actually does — the owner's explainer

Read this before the video and before any judge conversation. Every claim in here is true of
the deployed system today; where something is dry-run or operator-gated, it says so.

## The one-sentence version

You upload an iOS build the way you always do; Apple tells Shipwright; Shipwright prepares the
entire App Store release — listing text, screenshots, pricing, compliance — and (when the gate
is open) submits it for review. You find out by email.

## The story you lived (say this, it's yours)

Anyone can vibe-code an app in a weekend now. Then they meet the part AI didn't fix: metadata
character rules, screenshot device-size trivia, 175-territory pricing, age-rating questionnaires,
and rejections for things no error message warns about. You shipped 14 apps and still lost two
days doing this by hand the week before the hackathon. Shipwright is that scar tissue, encoded.

## Step by step — what happens when you upload a build

1. **Apple calls us (nobody types).** App Store Connect fires a `BUILD_UPLOAD_STATE_UPDATED`
   webhook at the Cloud Run service. The request is HMAC-verified (shared secret, so fakes are
   rejected). A Cloud Scheduler sweep every 30 min catches any delivery Apple drops.
2. **Intake** checks the app is on the allowlist, waits until the build is `VALID`, finds or
   creates the App Store version record, writes a job to Firestore, and fans the work out
   over Pub/Sub.
3. **Metadata agent** (Gemini 3.5 Flash) writes the listing: name, subtitle, keywords,
   description, promo text, review notes — from a facts file you seeded once per app.
4. **The critic** rejects that draft until it passes. It holds a deterministic validator as a
   tool (30/30/100-char limits, no word repeated across fields, no plurals, no "app", no brand
   names, no hardcoded prices) and spends its own judgment on claims and tone. The model, not a
   counter, decides when the loop exits. Converged in one round on every run so far.
5. **Screenshot agent** composites your *real* simulator captures onto branded backdrops with
   captions that echo the keywords. No image model ever redraws the UI (they hallucinate text).
   Renders both 1320×2868 (API upload) and 1284×2778 (web-uploader size).
6. **Preflight** fans out ~20 checks against the live App Store Connect API — the encoded
   version of every rejection you ever paid for: price schedule exists, availability in 175
   territories, IAP buyable outside the US, age-rating 2026 fields, review contact, copyright,
   export compliance, build attached… Each finding carries a verdict: **auto-fixable** (the
   fixer runs it, then *reads the state back* — a 2xx from Apple is "stored", not "done"),
   **operator-only** (no API exists: App Privacy publish, medical-device banner, Paid Apps
   Agreement, first-IAP attach — reported as a one-click checklist), or **blocking**.
   Gemini vision also reads the actual screenshots and catches what no API field can — in the
   live run it flagged a Guideline 2.3.1 rejection (paywall promising sync and a keyboard that
   v1.0 doesn't have) plus a visible sample-data password.
7. **Submit agent** — the one semi-irreversible action, behind its own flag. With
   `ALLOW_SUBMIT=false` it stops at "fully prepared, submission withheld" and shows the exact
   payloads it would have sent. With the gate open it creates the review submission, attaches
   the version, flips `submitted=true`, and re-reads Apple's state to confirm.
8. **You get an email** (new): the release report — stage results, preflight verdict, operator
   checklist — lands in your inbox. If SMTP isn't configured, the same report is on the job page.
9. **Watcher** (the multi-day part): review-state webhooks keep arriving for days. On a
   rejection, Gemma 4 does a cheap first-pass label, Gemini 3.5 parses the reviewer's prose
   into a routing decision — back to metadata, screenshots, preflight, or you — with a concrete
   fix plan and a needs-new-build verdict. Job state lives in Firestore the whole time;
   restart anything and it resumes at the first unfinished stage.

## The numbers (memorise these three)

- **23/23** — of the 25 failure modes documented from your 14 releases, 23 are in the agent's
  scope and preflight covers all 23 (13 auto-fixed via API, 2 by vision, 4 operator-gated,
  4 validator/design rules). The 2 out of scope are build-side.
- **13 → 13 → 4 → 2** — live run: 13 blockers found, 13 auto-fixed, 4 operator items reported,
  2 catches no API field could see (incl. the 2.3.1).
- **1 round** — critic-loop convergence, because the critic has tools, not taste.

## What is real vs. not, today

| Real, live now | Gated / pending |
|---|---|
| Webhook from real Apple → real Cloud Run service | Actual submission (`ALLOW_SUBMIT=false` until the 4 operator clicks are done) |
| All writes against the real App Store Connect API, real app record 6803901837 | Email report (code live; SMTP env not yet set) |
| Preflight + auto-fixes + read-backs, real findings | App Group / share-sheet extensions (Apple portal click, build 3) |
| Multi-day watcher wiring (webhook events registered) | A real rejection to route (needs a real submission first) |

## Safety, in one breath

Touches exactly one app (hard allowlist, checked on ingress and before every write); dry-run by
default; submission behind a second flag; the `.p8` key exists only in Secret Manager; every
write is read back; failures dead-letter and jobs resume — a failed email or a flaky Apple 500
never kills a release.

## Words to use with judges (each is true and defined above)

Event-driven trigger · critique loop with tool-grounded validation · parallel fan-out/gather
preflight · deterministic gates around a semi-irreversible action · replayable job evidence ·
multi-day async state · "automates everything Apple's API allows and knows exactly what it
must not touch."
