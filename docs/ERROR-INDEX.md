# Error index → preflight check map

Every check in `shipwright/checks/preflight.py` is a rejection or silent trap that was paid for in a real
App Store release (14 apps shipped; two of those days were spent by hand the week before this hackathon).
"Paid for" means: a rejection email, a pulled submission, a lost queue slot, or an IAP that was buyable in
exactly one country. The agent encodes them as reads against the App Store Connect API, with an auto-fix
where the API allows one and an **operator item** where only a web click can clear it.

| # | What Apple does | Check | Auto-fix |
|---|---|---|---|
| 1 | `contentRightsDeclaration` missing only surfaces at `reviewSubmissionItems` POST | `content_rights` | PATCH apps |
| 2 | `copyright` missing — hidden blocker at submit | `copyright_line` | PATCH appStoreVersions |
| 3 | 2026 age-rating questionnaire 409s without 7 booleans + `gunsOrOtherWeapons` | `age_rating` | PATCH ageRatingDeclarations |
| 4 | No primary category | `categories` | PATCH appInfos relationships |
| 5 | New apps have **no** price schedule; `asc pricing schedule create --free` fails "timeline must be covered" | `app_price` | POST appPriceSchedules with null-start $0 point |
| 6 | New apps have **no** availability — sold nowhere | `app_availability` | POST /v2/appAvailabilities × 175 territories |
| 7 | `asc iap setup` leaves the IAP buyable in **1** country (silent revenue killer) | `iap_territories` | POST inAppPurchaseAvailabilities / subscriptionAvailabilities |
| 8 | `MISSING_METADATA` with all fields filled: review screenshot, per-territory prices, or the 55-char sub description, or a rerun that silently skipped localization | `iap_readiness` | upload paywall capture as review screenshot; no-op localization PATCH forces Apple's recompute |
| 9 | Review contact needs phone **with country code**; `demoAccountRequired` needs `=false`; notes must be test steps | `review_details` | POST appStoreReviewDetails (notes written by the metadata agent) |
| 10 | Description/keywords/supportUrl live on the *version* localization; subtitle/privacy URL on the *appInfo* localization | `version_localization` | PATCH both (critic-approved metadata) |
| 11 | `whatsNew` 409s on a first version | `version_localization` | clear it |
| 12 | 1320×2868 belongs to `APP_IPHONE_67`; `APP_IPHONE_69` does not exist; the web uploader wants 1284×2778 | `screenshots` | create set + upload composites (both sizes rendered) |
| 13 | Binary declaring iPad ⇒ iPad screenshots demanded | (build-side) `TARGETED_DEVICE_FAMILY: "1"` at target level, verified with `plutil` on the archive |
| 14 | Export compliance unanswered blocks submit | `build_attached` | PATCH builds `usesNonExemptEncryption=false` (and `ITSAppUsesNonExemptEncryption` in the plist) |
| 15 | On-screen claims the app doesn't deliver (a paywall promising "sync" in a v1 without sync) → 2.3.1 / 3.1 | `screenshot_claims` (Gemini vision over the real captures) | operator: fix in-app copy |
| 16 | Visible passwords / personal data in sample-data screenshots | `screenshot_claims` | operator |
| 17 | App Privacy must be **Published**, not saved | `web_only_gates` | operator |
| 18 | 2026 "regulated medical device" banner — API-key auth can't reach it | `web_only_gates` | operator |
| 19 | Paid Apps Agreement inactive ⇒ StoreKit returns 0 products | `web_only_gates` | operator |
| 20 | `reviewSubmissionItems` rejects `inAppPurchaseV2` (2026) — first IAP attaches via the web draft submission | `web_only_gates` | operator |
| 21 | A 2xx from Apple means "stored", not "done" | every fix reads state back; preflight re-runs after fixes |
| 22 | Apple 500s on real endpoints (pricePoints, availability) and rate-limits at 3600/h | `asc.py`: exponential backoff + jitter on 429/5xx, 6 attempts |
| 23 | Metadata: 30/30/100 chars, fill ≥27/≥27/≥97, zero word repeats across fields, no plurals, no "app", no brands, no hardcoded price | `validators.py` (critic tool) | writer redrafts |
| 24 | Subscription localization description caps at **55** chars | `validators.validate_subscription_description` | — |
| 25 | App Group capability cannot be registered by API key or signed-out Xcode | (build-side) operator registers the group once; build 3 restores extensions |

The full 64-row index this was distilled from lives in the operator's private playbook; the rows above are the ones the
API can see. The rest are build-time (Swift concurrency crashes, launch-screen sizing, StoreKit test config) and belong in
the app repo, not the release agent.
