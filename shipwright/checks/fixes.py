"""Auto-fixes for preflight findings. Every call goes through ASC.post/patch, so DRY_RUN and the
app allowlist gate them; a dry-run returns the exact payload that would have been sent.

Each fix reads state back afterwards where Apple's 2xx is known to mean "stored, not done".
"""
from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from .. import assets, config
from ..asc import ASC, ASCError
from .preflight import AGE_RATING_REQUIRED, IPHONE_67, Ctx, Finding

log = logging.getLogger("shipwright.fixes")

AGE_RATING_DEFAULTS = {
    **{k: "NONE" for k in ("alcoholTobaccoOrDrugUseOrReferences", "contests", "gamblingSimulated", "horrorOrFearThemes",
                           "matureOrSuggestiveThemes", "medicalOrTreatmentInformation", "profanityOrCrudeHumor",
                           "sexualContentGraphicAndNudity", "sexualContentOrNudity", "violenceCartoonOrFantasy",
                           "violenceRealistic", "violenceRealisticProlongedGraphicOrSadistic", "gunsOrOtherWeapons")},
    **{k: False for k in ("advertising", "parentalControls", "lootBox", "healthOrWellnessTopics", "ageAssurance",
                          "messagingAndChat", "userGeneratedContent", "gambling", "unrestrictedWebAccess")},
}


def _terr_ids(asc: ASC) -> list[str]:
    return [t["id"] for t in asc.get_all("/v1/territories")]


def fix_content_rights(asc: ASC, c: Ctx, f: Finding, job: dict, app: dict) -> Any:
    return asc.patch(f"/v1/apps/{c.app_id}", {"data": {"type": "apps", "id": c.app_id,
                     "attributes": {"contentRightsDeclaration": app.get("content_rights", "DOES_NOT_USE_THIRD_PARTY_CONTENT")}}}, app_id=c.app_id)


def fix_copyright(asc: ASC, c: Ctx, f: Finding, job: dict, app: dict) -> Any:
    line = f"© {dt.date.today().year} {app.get('company', 'the developer')}"
    return asc.patch(f"/v1/appStoreVersions/{c.version_id}", {"data": {"type": "appStoreVersions", "id": c.version_id,
                     "attributes": {"copyright": line}}}, app_id=c.app_id)


def fix_age_rating(asc: ASC, c: Ctx, f: Finding, job: dict, app: dict) -> Any:
    attrs = {**AGE_RATING_DEFAULTS, **(app.get("age_rating") or {})}
    assert all(k in attrs for k in AGE_RATING_REQUIRED)
    return asc.patch(f"/v1/ageRatingDeclarations/{c.app_info_id}", {"data": {"type": "ageRatingDeclarations", "id": c.app_info_id,
                     "attributes": attrs}}, app_id=c.app_id)


def fix_categories(asc: ASC, c: Ctx, f: Finding, job: dict, app: dict) -> Any:
    rel = {"primaryCategory": {"data": {"type": "appCategories", "id": app.get("primary_category", "PRODUCTIVITY")}}}
    if app.get("secondary_category"):
        rel["secondaryCategory"] = {"data": {"type": "appCategories", "id": app["secondary_category"]}}
    return asc.patch(f"/v1/appInfos/{c.app_info_id}", {"data": {"type": "appInfos", "id": c.app_info_id, "relationships": rel}}, app_id=c.app_id)


def fix_app_price(asc: ASC, c: Ctx, f: Finding, job: dict, app: dict) -> Any:
    pts = asc.get_all(f"/v1/apps/{c.app_id}/appPricePoints", **{"filter[territory]": "USA"})
    free = next(p for p in pts if p["attributes"]["customerPrice"] in ("0.0", "0", "0.00"))
    body = {
        "data": {"type": "appPriceSchedules",
                 "relationships": {"app": {"data": {"type": "apps", "id": c.app_id}},
                                   "baseTerritory": {"data": {"type": "territories", "id": "USA"}},
                                   "manualPrices": {"data": [{"type": "appPrices", "id": "${price1}"}]}}},
        "included": [{"type": "appPrices", "id": "${price1}", "attributes": {"startDate": None},
                      "relationships": {"appPricePoint": {"data": {"type": "appPricePoints", "id": free["id"]}}}}],
    }
    r = asc.post("/v1/appPriceSchedules", body, app_id=c.app_id)
    if not r.get("dry_run"):
        asc.get(f"/v1/appPriceSchedules/{c.app_id}/manualPrices", limit=1)  # read back — 404 here means nothing stuck
    return r


def _availability_body(kind: str, rel_name: str, rel_type: str, rel_id: str, terr: list[str]) -> dict:
    return {"data": {"type": kind, "attributes": {"availableInNewTerritories": True},
                     "relationships": {rel_name: {"data": {"type": rel_type, "id": rel_id}},
                                       "availableTerritories": {"data": [{"type": "territories", "id": t} for t in terr]}}}}


def fix_app_availability(asc: ASC, c: Ctx, f: Finding, job: dict, app: dict) -> Any:
    terr = _terr_ids(asc)
    body = {
        "data": {"type": "appAvailabilities", "attributes": {"availableInNewTerritories": True},
                 "relationships": {"app": {"data": {"type": "apps", "id": c.app_id}},
                                   "territoryAvailabilities": {"data": [{"type": "territoryAvailabilities", "id": f"${{t{i}}}"} for i in range(len(terr))]}}},
        "included": [{"type": "territoryAvailabilities", "id": f"${{t{i}}}", "attributes": {"available": True},
                      "relationships": {"territory": {"data": {"type": "territories", "id": t}}}} for i, t in enumerate(terr)],
    }
    r = asc.post("/v2/appAvailabilities", body, app_id=c.app_id)
    if not r.get("dry_run"):
        got = asc.get(f"/v1/apps/{c.app_id}/appAvailabilityV2")
        n = len(asc.get_all(f"/v2/appAvailabilities/{got['data']['id']}/territoryAvailabilities"))
        log.info("availability read-back: %d territories", n)
    return {"territories": len(terr), **({"dry_run": True} if r.get("dry_run") else {})}


def fix_iap_availability(asc: ASC, c: Ctx, f: Finding, job: dict, app: dict) -> Any:
    terr = _terr_ids(asc)
    return asc.post("/v1/inAppPurchaseAvailabilities", _availability_body("inAppPurchaseAvailabilities", "inAppPurchase", "inAppPurchases", f.data["iap_id"], terr), app_id=c.app_id)


def fix_sub_availability(asc: ASC, c: Ctx, f: Finding, job: dict, app: dict) -> Any:
    terr = _terr_ids(asc)
    return asc.post("/v1/subscriptionAvailabilities", _availability_body("subscriptionAvailabilities", "subscription", "subscriptions", f.data["sub_id"], terr), app_id=c.app_id)


def _paywall_png(job: dict) -> bytes:
    uri = (job.get("stages", {}).get("screenshots", {}).get("output") or {}).get("paywall")
    if not uri:
        raise RuntimeError("no paywall screenshot captured — screenshot stage must run first")
    return assets.read(uri)


def fix_iap_review_screenshot(asc: ASC, c: Ctx, f: Finding, job: dict, app: dict) -> Any:
    png = _paywall_png(job)
    return asc.upload_asset("/v1/inAppPurchaseAppStoreReviewScreenshots", "inAppPurchases", f.data["iap_id"], png, "paywall.png", app_id=c.app_id, rel_key="inAppPurchaseV2")


def fix_sub_review_screenshot(asc: ASC, c: Ctx, f: Finding, job: dict, app: dict) -> Any:
    png = _paywall_png(job)
    return asc.upload_asset("/v1/subscriptionAppStoreReviewScreenshots", "subscriptions", f.data["sub_id"], png, "paywall.png", app_id=c.app_id, rel_key="subscription")


def fix_iap_recompute(asc: ASC, c: Ctx, f: Finding, job: dict, app: dict) -> Any:
    """All fields filled but still MISSING_METADATA: a no-op PATCH on the localization forces Apple's recompute."""
    loc = asc.get(f"/v2/inAppPurchases/{f.data['iap_id']}/inAppPurchaseLocalizations")["data"][0]
    return asc.patch(f"/v1/inAppPurchaseLocalizations/{loc['id']}", {"data": {"type": "inAppPurchaseLocalizations", "id": loc["id"],
                     "attributes": {"name": loc["attributes"]["name"]}}}, app_id=c.app_id)


def fix_sub_recompute(asc: ASC, c: Ctx, f: Finding, job: dict, app: dict) -> Any:
    loc = asc.get(f"/v1/subscriptions/{f.data['sub_id']}/subscriptionLocalizations")["data"][0]
    return asc.patch(f"/v1/subscriptionLocalizations/{loc['id']}", {"data": {"type": "subscriptionLocalizations", "id": loc["id"],
                     "attributes": {"name": loc["attributes"]["name"]}}}, app_id=c.app_id)


def fix_review_details(asc: ASC, c: Ctx, f: Finding, job: dict, app: dict) -> Any:
    notes = (job.get("stages", {}).get("metadata", {}).get("output") or {}).get("reviewNotes") or app.get("review_notes", "")
    attrs = {**config.REVIEW_CONTACT, "demoAccountRequired": False, "notes": notes}
    if not attrs["contactPhone"]:
        attrs["contactPhone"] = app.get("contact_phone", "")
    existing = asc.get(f"/v1/appStoreVersions/{c.version_id}/appStoreReviewDetail").get("data")
    if existing:
        return asc.patch(f"/v1/appStoreReviewDetails/{existing['id']}", {"data": {"type": "appStoreReviewDetails", "id": existing["id"], "attributes": attrs}}, app_id=c.app_id)
    return asc.post("/v1/appStoreReviewDetails", {"data": {"type": "appStoreReviewDetails", "attributes": attrs,
                    "relationships": {"appStoreVersion": {"data": {"type": "appStoreVersions", "id": c.version_id}}}}}, app_id=c.app_id)


def fix_metadata(asc: ASC, c: Ctx, f: Finding, job: dict, app: dict) -> Any:
    meta = (job.get("stages", {}).get("metadata", {}).get("output") or {}).get("final")
    if not meta:
        raise RuntimeError("metadata stage produced nothing — critic never approved")
    out = {}
    locs = asc.get(f"/v1/appStoreVersions/{c.version_id}/appStoreVersionLocalizations")["data"]
    loc = next((l for l in locs if l["attributes"]["locale"] == c.locale), None)
    vattrs = {"description": meta["description"], "keywords": meta["keywords"], "supportUrl": config.SUPPORT_URL or app.get("support_url"),
              "promotionalText": meta.get("promotionalText") or None}
    if loc:
        out["version_loc"] = asc.patch(f"/v1/appStoreVersionLocalizations/{loc['id']}", {"data": {"type": "appStoreVersionLocalizations", "id": loc["id"], "attributes": vattrs}}, app_id=c.app_id)
    else:
        out["version_loc"] = asc.post("/v1/appStoreVersionLocalizations", {"data": {"type": "appStoreVersionLocalizations", "attributes": {**vattrs, "locale": c.locale},
                                     "relationships": {"appStoreVersion": {"data": {"type": "appStoreVersions", "id": c.version_id}}}}}, app_id=c.app_id)
    infos = asc.get(f"/v1/appInfos/{c.app_info_id}/appInfoLocalizations")["data"]
    il = next((l for l in infos if l["attributes"]["locale"] == c.locale), None)
    iattrs = {"name": meta["name"], "subtitle": meta["subtitle"], "privacyPolicyUrl": config.PRIVACY_URL or app.get("privacy_url")}
    if il:
        out["info_loc"] = asc.patch(f"/v1/appInfoLocalizations/{il['id']}", {"data": {"type": "appInfoLocalizations", "id": il["id"], "attributes": iattrs}}, app_id=c.app_id)
    if not config.DRY_RUN:  # read back: name/keywords are the ranking asset, verify they landed
        got = asc.get(f"/v1/appStoreVersionLocalizations/{loc['id'] if loc else out['version_loc']['data']['id']}")["data"]["attributes"]
        assert got["keywords"] == meta["keywords"], "keywords did not persist"
    return out


def fix_clear_whats_new(asc: ASC, c: Ctx, f: Finding, job: dict, app: dict) -> Any:
    return asc.patch(f"/v1/appStoreVersionLocalizations/{f.data['loc_id']}", {"data": {"type": "appStoreVersionLocalizations", "id": f.data["loc_id"], "attributes": {"whatsNew": None}}}, app_id=c.app_id)


def fix_screenshots(asc: ASC, c: Ctx, f: Finding, job: dict, app: dict) -> Any:
    shots = (job.get("stages", {}).get("screenshots", {}).get("output") or {}).get("composites") or []
    if not shots:
        raise RuntimeError("no composites — screenshot stage must run first")
    loc_id = f.data["loc_id"]
    sets = asc.get(f"/v1/appStoreVersionLocalizations/{loc_id}/appScreenshotSets")["data"]
    sset = next((s for s in sets if s["attributes"]["screenshotDisplayType"] == IPHONE_67), None)
    if sset:
        set_id = sset["id"]
    else:
        r = asc.post("/v1/appScreenshotSets", {"data": {"type": "appScreenshotSets", "attributes": {"screenshotDisplayType": IPHONE_67},
                     "relationships": {"appStoreVersionLocalization": {"data": {"type": "appStoreVersionLocalizations", "id": loc_id}}}}}, app_id=c.app_id)
        if r.get("dry_run"):
            return {"dry_run": True, "would_upload": shots}
        set_id = r["data"]["id"]
    results = []
    for i, uri in enumerate(shots, 1):
        results.append(asc.upload_asset("/v1/appScreenshots", "appScreenshotSets", set_id, assets.read(uri), f"{i:02d}.png", app_id=c.app_id, rel_key="appScreenshotSet"))
    if not config.DRY_RUN:
        n = len(asc.get(f"/v1/appScreenshotSets/{set_id}/appScreenshots").get("data") or [])
        log.info("screenshot read-back: %d in %s", n, IPHONE_67)
    return {"set": set_id, "uploaded": len(results)}


def fix_attach_build(asc: ASC, c: Ctx, f: Finding, job: dict, app: dict) -> Any:
    build_id = job.get("build_id")
    if not build_id or build_id == "none":
        return {"skipped": True, "reason": "job has no build — upload one; the attach is the only step left"}
    r = asc.patch(f"/v1/appStoreVersions/{c.version_id}", {"data": {"type": "appStoreVersions", "id": c.version_id,
                  "relationships": {"build": {"data": {"type": "builds", "id": build_id}}}}}, app_id=c.app_id)
    if not r.get("dry_run"):
        got = asc.get(f"/v1/appStoreVersions/{c.version_id}/build").get("data") or {}
        assert got.get("id") == build_id, "build did not attach"
    return r


def fix_encryption(asc: ASC, c: Ctx, f: Finding, job: dict, app: dict) -> Any:
    return asc.patch(f"/v1/builds/{f.data['build_id']}", {"data": {"type": "builds", "id": f.data["build_id"], "attributes": {"usesNonExemptEncryption": False}}}, app_id=c.app_id)


FIXES = {n: g for n, g in globals().items() if n.startswith("fix_") and callable(g)}


def apply(asc: ASC, c: Ctx, finding: Finding, job: dict, app: dict) -> dict:
    fn = FIXES.get(finding.auto_fix)
    if not fn:
        return {"skipped": True, "reason": "no auto-fix"}
    try:
        return {"ok": True, "result": fn(asc, c, finding, job, app)}
    except ASCError as e:
        return {"ok": False, "status": e.status, "errors": [x.get("detail") or x.get("title") for x in e.errors][:3]}
    except Exception as e:  # noqa: BLE001 — a fix failing must not kill the job; it becomes a finding
        return {"ok": False, "error": str(e)}
