"""Compliance preflight: the error index as a checklist.

Every check here is a rejection or silent trap that was actually paid for in a real release
(see docs/ERROR-INDEX.md). Checks are pure reads. Each returns Findings; a Finding may name an
auto-fix (applied later by fixes.py under DRY_RUN/allowlist gates) or an operator item (web-only
gates the API cannot reach — App Privacy publish, medical-device banner, Paid Apps Agreement).

Checks are independent so they fan out in parallel (ADK ParallelAgent wraps them).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Callable

from ..asc import ASC, ASCError

BLOCK, WARN, INFO = "BLOCK", "WARN", "INFO"

# 2026 age-rating questionnaire fields Apple rejects the PATCH without (error index row)
AGE_RATING_REQUIRED = ["advertising", "parentalControls", "lootBox", "healthOrWellnessTopics",
                       "ageAssurance", "messagingAndChat", "userGeneratedContent", "gunsOrOtherWeapons"]
IPHONE_67 = "APP_IPHONE_67"  # 1320×2868 lives here; APP_IPHONE_69 does not exist
REQUIRED_VERSION_LOC = ["description", "keywords", "supportUrl"]
REQUIRED_INFO_LOC = ["name", "subtitle", "privacyPolicyUrl"]


@dataclass
class Finding:
    check: str
    severity: str
    message: str
    fix: str = ""            # human-readable remedy
    auto_fix: str = ""       # name of a fixes.py function that can remedy it unattended
    operator: bool = False   # True = only a human web click can clear it
    data: dict = field(default_factory=dict)

    def dict(self) -> dict:
        return asdict(self)


@dataclass
class Ctx:
    app_id: str
    version_id: str
    app_info_id: str
    locale: str = "en-US"
    build_id: str | None = None
    composites: list[str] = field(default_factory=list)
    facts: str = ""


def _attrs(r: dict) -> dict:
    d = r.get("data")
    return (d or {}).get("attributes", {}) if isinstance(d, dict) else {}


# --- checks ------------------------------------------------------------------

def content_rights(asc: ASC, c: Ctx) -> list[Finding]:
    v = _attrs(asc.get(f"/v1/apps/{c.app_id}", **{"fields[apps]": "contentRightsDeclaration"}))
    if not v.get("contentRightsDeclaration"):
        return [Finding("content_rights", BLOCK, "contentRightsDeclaration unset — surfaces only at reviewSubmissionItems POST",
                        "PATCH /v1/apps contentRightsDeclaration=DOES_NOT_USE_THIRD_PARTY_CONTENT", auto_fix="fix_content_rights")]
    return []


def copyright_line(asc: ASC, c: Ctx) -> list[Finding]:
    v = _attrs(asc.get(f"/v1/appStoreVersions/{c.version_id}", **{"fields[appStoreVersions]": "copyright,versionString"}))
    if not v.get("copyright"):
        return [Finding("copyright", BLOCK, "version.copyright empty — hidden blocker at submit", "PATCH appStoreVersions copyright", auto_fix="fix_copyright")]
    return []


def age_rating(asc: ASC, c: Ctx) -> list[Finding]:
    v = _attrs(asc.get(f"/v1/appInfos/{c.app_info_id}/ageRatingDeclaration"))
    missing = [k for k in AGE_RATING_REQUIRED if v.get(k) is None]
    if missing:
        return [Finding("age_rating", BLOCK, f"2026 age-rating fields unanswered: {missing}",
                        "PATCH ageRatingDeclarations with all 2026 booleans + gunsOrOtherWeapons=NONE", auto_fix="fix_age_rating", data={"missing": missing})]
    return []


def categories(asc: ASC, c: Ctx) -> list[Finding]:
    r = asc.get(f"/v1/appInfos/{c.app_info_id}/primaryCategory")
    if not r.get("data"):
        return [Finding("categories", BLOCK, "no primary category", "PATCH appInfos relationships.primaryCategory", auto_fix="fix_categories")]
    return []


def app_price(asc: ASC, c: Ctx) -> list[Finding]:
    try:
        asc.get(f"/v1/appPriceSchedules/{c.app_id}/manualPrices", limit=1)
    except ASCError as e:
        if e.status == 404:
            return [Finding("app_price", BLOCK, "app has NO price schedule (new apps ship without one; required even for Free)",
                            "POST /v1/appPriceSchedules with the $0 price point, null start date", auto_fix="fix_app_price")]
        raise
    return []


def app_availability(asc: ASC, c: Ctx) -> list[Finding]:
    try:
        r = asc.get(f"/v1/apps/{c.app_id}/appAvailabilityV2")
    except ASCError as e:
        if e.status == 404:
            return [Finding("app_availability", BLOCK, "app availability unset — app would be sold nowhere",
                            "POST /v2/appAvailabilities with all territories", auto_fix="fix_app_availability")]
        raise
    terr = asc.get_all(f"/v2/appAvailabilities/{r['data']['id']}/territoryAvailabilities")
    total = len(asc.get_all("/v1/territories"))
    on = [t for t in terr if t["attributes"].get("available")]
    if len(on) < total:
        return [Finding("app_availability", WARN, f"app available in {len(on)}/{total} territories", "extend availability", auto_fix="fix_app_availability", data={"on": len(on), "total": total})]
    return []


def iap_territories(asc: ASC, c: Ctx) -> list[Finding]:
    """The one-country trap: `asc iap setup` leaves availability = base territory only."""
    out: list[Finding] = []
    total = len(asc.get_all("/v1/territories"))
    for iap in asc.get_all(f"/v1/apps/{c.app_id}/inAppPurchasesV2"):
        n = len(asc.get_all(f"/v1/inAppPurchaseAvailabilities/{iap['id']}/availableTerritories"))
        if n < total:
            out.append(Finding("iap_territories", BLOCK, f"IAP {iap['attributes']['productId']} buyable in {n}/{total} territories (silent revenue killer)",
                               "POST inAppPurchaseAvailabilities all territories", auto_fix="fix_iap_availability", data={"iap_id": iap["id"], "n": n, "total": total}))
    for grp in asc.get_all(f"/v1/apps/{c.app_id}/subscriptionGroups"):
        for sub in asc.get_all(f"/v1/subscriptionGroups/{grp['id']}/subscriptions"):
            n = len(asc.get_all(f"/v1/subscriptionAvailabilities/{sub['id']}/availableTerritories"))
            if n < total:
                out.append(Finding("iap_territories", BLOCK, f"subscription {sub['attributes']['productId']} available in {n}/{total} territories",
                                   "POST subscriptionAvailabilities all territories", auto_fix="fix_sub_availability", data={"sub_id": sub["id"], "n": n, "total": total}))
    return out


def iap_readiness(asc: ASC, c: Ctx) -> list[Finding]:
    """MISSING_METADATA diagnosis: localization / per-territory prices / review screenshot."""
    out: list[Finding] = []
    total = len(asc.get_all("/v1/territories"))
    for iap in asc.get_all(f"/v1/apps/{c.app_id}/inAppPurchasesV2"):
        pid, st = iap["attributes"]["productId"], iap["attributes"]["state"]
        if st in ("READY_TO_SUBMIT", "APPROVED", "WAITING_FOR_REVIEW", "IN_REVIEW"):
            continue
        why = []
        if not asc.get(f"/v2/inAppPurchases/{iap['id']}/inAppPurchaseLocalizations").get("data"):
            why.append("no localization")
        if not asc.get(f"/v2/inAppPurchases/{iap['id']}/appStoreReviewScreenshot").get("data"):
            why.append("no review screenshot")
        try:
            prices = len(asc.get_all(f"/v1/inAppPurchasePriceSchedules/{iap['id']}/manualPrices")) + len(asc.get_all(f"/v1/inAppPurchasePriceSchedules/{iap['id']}/automaticPrices"))
        except ASCError:
            prices = 0
        if prices < total:
            why.append(f"prices in {prices}/{total} territories")
        out.append(Finding("iap_readiness", BLOCK, f"IAP {pid} is {st}: {', '.join(why) or 'cause not visible — no-op PATCH localization forces recompute'}",
                           "upload review screenshot / set prices / no-op localization PATCH",
                           auto_fix="fix_iap_review_screenshot" if "no review screenshot" in why else "fix_iap_recompute",
                           data={"iap_id": iap["id"], "why": why}))
    for grp in asc.get_all(f"/v1/apps/{c.app_id}/subscriptionGroups"):
        for sub in asc.get_all(f"/v1/subscriptionGroups/{grp['id']}/subscriptions"):
            pid, st = sub["attributes"]["productId"], sub["attributes"]["state"]
            if st in ("READY_TO_SUBMIT", "APPROVED", "WAITING_FOR_REVIEW", "IN_REVIEW"):
                continue
            why = []
            locs = asc.get(f"/v1/subscriptions/{sub['id']}/subscriptionLocalizations").get("data") or []
            if not locs:
                why.append("no localization (rerun of `asc subscriptions setup` silently skips it)")
            for loc in locs:
                d = loc["attributes"].get("description") or ""
                if len(d) > 55:
                    why.append(f"localization description {len(d)} chars > 55")
            if not asc.get(f"/v1/subscriptions/{sub['id']}/appStoreReviewScreenshot").get("data"):
                why.append("no review screenshot")
            n = len(asc.get_all(f"/v1/subscriptions/{sub['id']}/prices"))
            if n < total:
                why.append(f"prices in {n}/{total} territories (equalizations not written)")
            out.append(Finding("iap_readiness", BLOCK, f"subscription {pid} is {st}: {', '.join(why) or 'cause not visible — no-op PATCH localization forces recompute'}",
                               "upload review screenshot / equalize prices / no-op localization PATCH",
                               auto_fix="fix_sub_review_screenshot" if "no review screenshot" in why else "fix_sub_recompute",
                               data={"sub_id": sub["id"], "why": why}))
    return out


def review_details(asc: ASC, c: Ctx) -> list[Finding]:
    v = _attrs(asc.get(f"/v1/appStoreVersions/{c.version_id}/appStoreReviewDetail"))
    missing = [k for k in ("contactFirstName", "contactLastName", "contactPhone", "contactEmail", "notes") if not v.get(k)]
    if not v or missing:
        return [Finding("review_details", BLOCK, f"review contact/notes missing: {missing or 'all'} (phone needs country code; notes = exact test steps)",
                        "POST/PATCH appStoreReviewDetails", auto_fix="fix_review_details", data={"missing": missing})]
    return []


def version_localization(asc: ASC, c: Ctx) -> list[Finding]:
    out: list[Finding] = []
    locs = asc.get(f"/v1/appStoreVersions/{c.version_id}/appStoreVersionLocalizations").get("data") or []
    loc = next((l for l in locs if l["attributes"]["locale"] == c.locale), None)
    if not loc:
        return [Finding("version_localization", BLOCK, f"no {c.locale} version localization", "POST appStoreVersionLocalizations", auto_fix="fix_metadata")]
    missing = [k for k in REQUIRED_VERSION_LOC if not loc["attributes"].get(k)]
    if missing:
        out.append(Finding("version_localization", BLOCK, f"version localization missing {missing}", "PATCH appStoreVersionLocalizations", auto_fix="fix_metadata", data={"loc_id": loc["id"]}))
    if loc["attributes"].get("whatsNew"):
        vs = _attrs(asc.get(f"/v1/appStoreVersions/{c.version_id}", **{"fields[appStoreVersions]": "versionString"})).get("versionString", "")
        if vs.startswith("1.0"):
            out.append(Finding("version_localization", WARN, "whatsNew set on a first version — Apple 409s; must be omitted", "clear whatsNew", auto_fix="fix_clear_whats_new", data={"loc_id": loc["id"]}))
    info = asc.get(f"/v1/appInfos/{c.app_info_id}/appInfoLocalizations").get("data") or []
    il = next((l for l in info if l["attributes"]["locale"] == c.locale), None)
    imissing = [k for k in REQUIRED_INFO_LOC if not (il or {"attributes": {}})["attributes"].get(k)]
    if imissing:
        out.append(Finding("version_localization", BLOCK, f"app-info localization missing {imissing}", "PATCH appInfoLocalizations", auto_fix="fix_metadata", data={"info_loc_id": il["id"] if il else None}))
    return out


def screenshots(asc: ASC, c: Ctx) -> list[Finding]:
    locs = asc.get(f"/v1/appStoreVersions/{c.version_id}/appStoreVersionLocalizations").get("data") or []
    loc = next((l for l in locs if l["attributes"]["locale"] == c.locale), None)
    if not loc:
        return []
    sets = asc.get(f"/v1/appStoreVersionLocalizations/{loc['id']}/appScreenshotSets", include="appScreenshots").get("data") or []
    by_type = {s["attributes"]["screenshotDisplayType"]: len((s.get("relationships", {}).get("appScreenshots", {}).get("data") or [])) for s in sets}
    n = by_type.get(IPHONE_67, 0)
    if n == 0:
        return [Finding("screenshots", BLOCK, f"no {IPHONE_67} screenshots (1320×2868 go here; APP_IPHONE_69 does not exist)",
                        "upload composites via appScreenshotSets", auto_fix="fix_screenshots", data={"loc_id": loc["id"], "sets": by_type})]
    if n < 3:
        return [Finding("screenshots", WARN, f"only {n} {IPHONE_67} screenshots — first 3 sell the app", "add panels", data={"sets": by_type})]
    return []


def build_attached(asc: ASC, c: Ctx) -> list[Finding]:
    r = asc.get(f"/v1/appStoreVersions/{c.version_id}/build")
    if not r.get("data"):
        return [Finding("build", BLOCK, "no build attached to the version", "PATCH appStoreVersions relationships.build", auto_fix="fix_attach_build")]
    b = _attrs(asc.get(f"/v1/builds/{r['data']['id']}", **{"fields[builds]": "processingState,usesNonExemptEncryption,version"}))
    out = []
    if b.get("processingState") != "VALID":
        out.append(Finding("build", BLOCK, f"build processingState={b.get('processingState')}", "wait for VALID"))
    if b.get("usesNonExemptEncryption") is None:
        out.append(Finding("build", BLOCK, "export compliance unanswered (ITSAppUsesNonExemptEncryption missing from Info.plist)",
                           "PATCH builds usesNonExemptEncryption=false", auto_fix="fix_encryption", data={"build_id": r["data"]["id"]}))
    return out


def web_only_gates(asc: ASC, c: Ctx) -> list[Finding]:
    """Things the API-key auth genuinely cannot reach. Always surfaced; the operator confirms once."""
    items = [
        ("app_privacy", "App Privacy questionnaire must be PUBLISHED (saved ≠ published)"),
        ("medical_device", "2026 'regulated medical device' banner under App Information — answer No"),
        ("paid_apps_agreement", "Paid Applications Agreement + banking + tax Active, else StoreKit returns 0 products"),
        ("iap_draft_submission", "first subscription/IAP attaches via the version page IAP dialog (reviewSubmissionItems rejects inAppPurchaseV2 in 2026)"),
    ]
    return [Finding(k, WARN, m, "one web click", operator=True) for k, m in items]


def screenshot_claims(asc: ASC, c: Ctx) -> list[Finding]:
    """Gemini vision reads the REAL captures and flags on-screen claims the app facts do not support
    (guideline 2.3.1 / 3.1 accuracy). Error-index lesson: a paywall promising 'sync' that v1 lacks is a rejection."""
    if not c.composites or not c.facts:
        return []
    import json as _json
    import os as _os

    from google.genai import Client, types

    from .. import assets, config as _cfg

    client = Client(vertexai=True, project=_cfg.PROJECT, location=_os.environ.get("GOOGLE_CLOUD_LOCATION", "global"))
    parts = [types.Part.from_text(text=(
        "These are App Store screenshots of an iOS app. APP FACTS list what ships in this version. "
        "List every visible claim, feature name or promise in the screenshots that the facts do NOT support "
        "(features marked not-in-this-version count as unsupported). Also flag any visible personal data, passwords, or a hardcoded price banner outside genuine paywall UI. "
        "Reply as JSON: {\"unsupported\": [{\"panel\": n, \"text\": str, \"why\": str}]}.\n\nAPP FACTS:\n" + c.facts))]
    for uri in c.composites[:6]:
        parts.append(types.Part.from_bytes(data=assets.read(uri), mime_type="image/png"))
    r = client.models.generate_content(model=_cfg.MODEL, contents=types.Content(role="user", parts=parts),
                                       config=types.GenerateContentConfig(response_mime_type="application/json"))
    try:
        items = _json.loads(r.text or "{}").get("unsupported", [])
    except _json.JSONDecodeError:
        return [Finding("screenshot_claims", INFO, "vision check returned non-JSON", "rerun")]
    return [Finding("screenshot_claims", WARN, f"panel {i.get('panel')}: '{i.get('text')}' — {i.get('why')}",
                    "fix the in-app copy or drop the panel; review tests every on-screen claim (3.1)", data=i) for i in items]


CHECKS: dict[str, Callable[[ASC, Ctx], list[Finding]]] = {
    f.__name__: f for f in (content_rights, copyright_line, age_rating, categories, app_price, app_availability,
                            iap_territories, iap_readiness, review_details, version_localization, screenshots,
                            build_attached, web_only_gates, screenshot_claims)
}


def resolve_ctx(asc: ASC, app_id: str, version_id: str | None = None, build_id: str | None = None) -> Ctx:
    info = asc.get(f"/v1/apps/{app_id}/appInfos")["data"][0]["id"]
    if not version_id:
        vs = asc.get(f"/v1/apps/{app_id}/appStoreVersions", **{"filter[appVersionState]": "PREPARE_FOR_SUBMISSION,DEVELOPER_REJECTED,REJECTED,METADATA_REJECTED"}).get("data") or []
        version_id = vs[0]["id"] if vs else None
    return Ctx(app_id=str(app_id), version_id=version_id or "", app_info_id=info, build_id=build_id)


def run_check(name: str, asc: ASC, c: Ctx) -> list[Finding]:
    try:
        return CHECKS[name](asc, c)
    except ASCError as e:
        return [Finding(name, WARN, f"check errored: {e.status} {[x.get('detail') for x in e.errors][:1]}", "rerun")]
