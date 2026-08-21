# Demo video — 4 minutes, English, unedited live proof

Record at 1920×1080. Screen + voice. The first frame must NOT be a chat box.

| t | Screen | Say |
|---|---|---|
| 0:00 | `docs/promo_clip.mp4` (Veo, 8s) with `docs/promo_music.wav` (Lyria) under it; title card "Shipwright" | "Fourteen apps on the App Store. The last mile of every release — metadata, screenshots, 175 territories, a dozen silent traps — took me two days by hand last week. This is the agent that does it while I sleep." |
| 0:15 | Terminal: `xcodebuild -exportArchive … Upload succeeded` (pre-recorded or live) | "The only human action in this video: a build upload. Nothing is typed into the agent. Ever." |
| 0:30 | **Cloud Console → Cloud Run → shipwright → Logs**, live, filtered `webhook` | "Apple's webhook hits Cloud Run. HMAC verified. Build resolved. Job created, Pub/Sub fans it out." (point at the log lines as they arrive) |
| 0:55 | `https://shipwright-….a.run.app/` → click the job | "Firestore-backed job. Six stages, resumable. Watch them flip." |
| 1:10 | Job page: Metadata section | "Writer and critic in an ADK LoopAgent. The critic has the validator as a tool — 30, 30, 100 chars, no repeated words across fields, no plurals, no price. Approved in one round." |
| 1:35 | Job page: Screenshots grid | "Real device pixels. An image model never redraws the UI — it hallucinates numbers. Captions echo the keywords." |
| 1:50 | Job page: Preflight report (scroll slowly) | "Fourteen checks in parallel. Every row is a rejection I already paid for: content rights, copyright, the 2026 age-rating fields, the price schedule new apps don't have, availability, IAP review screenshots. Thirteen blockers, thirteen auto-fixes, each read back — a 2xx from Apple means stored, not done." |
| 2:25 | Preflight: the vision WARN rows | "And this one no API field can tell you: the paywall promises sync the build doesn't have, and the sample data shows a password. Gemini looked at the actual screenshots." |
| 2:40 | **Cloud Console: Secret Manager** (names only) → **Pub/Sub** topic + dead-letter → **Firestore** jobs doc | "Credential security: the Apple private key lives only here, read at runtime. Failure handling: retries, dead-letter, stage-level resume." |
| 3:05 | Job page: Submission block — `DRY_RUN` note or live `WAITING_FOR_REVIEW` | "Submission is triple-gated: dry-run flag, submit flag, app allowlist — thirteen of my apps are live and earning." (If live: "Waiting for Review. Unattended.") |
| 3:25 | `/jobs/{id}/rejection` curl with a real Apple rejection text → job page re-queued | "Days later Apple's verdict arrives by the same webhook. Gemma 4 labels the rejection, Gemini routes it to the right agent, and the job re-queues itself." |
| 3:45 | Architecture diagram | "ADK, Gemini 3.5 on Vertex, Cloud Run, Pub/Sub, Firestore, Secret Manager. Seven agents, one trigger, zero typing. Shipwright." |

Checklist before recording: Cloud Console logged in · a fresh build uploaded 2 min before you hit record (or
use `asc webhooks deliveries redeliver`) · job page open in a second tab · rejection curl ready in the terminal.
