"""Job pipeline: intake → metadata (critique loop) → screenshots → preflight (fan-out/gather + auto-fix)
→ submit → watch. Every stage records to Firestore; a redelivered Pub/Sub message or a restarted worker
resumes at the first unfinished stage. Nothing here types — the job exists because a build appeared.
"""
from __future__ import annotations

import asyncio
import io
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor

from PIL import Image

from . import assets, config, store
from .agents import captions as captions_agent
from .agents import metadata as metadata_agent
from .agents import preflight as preflight_agent
from .agents import runner
from .asc import ASC, ASCError
from .checks import fixes
from .checks.preflight import BLOCK, Finding, resolve_ctx
from .screenshots import Panel, compose, gen_backdrop, png_bytes, to_web_size

log = logging.getLogger("shipwright.pipeline")
SOURCES_BASE = os.environ.get("SOURCES_BASE", "")  # local override; default gs://bucket/app/sources
OUT_BASE = os.environ.get("OUT_BASE", "")          # local override; default gs://bucket/app/job
FIX_ORDER = ["fix_metadata", "fix_content_rights", "fix_copyright", "fix_age_rating", "fix_categories", "fix_app_price",
             "fix_app_availability", "fix_iap_availability", "fix_sub_availability", "fix_review_details", "fix_screenshots",
             "fix_attach_build", "fix_encryption", "fix_iap_review_screenshot", "fix_sub_review_screenshot",
             "fix_iap_recompute", "fix_sub_recompute", "fix_clear_whats_new"]
PANEL_ORDER = ["list", "edit", "tags", "settings", "paywall"]


def _src(app: dict, screen: str) -> str:
    base = SOURCES_BASE or f"gs://{config.BUCKET}/{app['app_id']}/sources"
    return f"{base}/{screen}.png"


def _out(job: dict, name: str) -> str:
    base = OUT_BASE or f"gs://{config.BUCKET}/{job['app_id']}/{job['job_id']}"
    return f"{base}/{name}"


# --- stage: intake ----------------------------------------------------------

def stage_intake(asc: ASC, job: dict, app: dict) -> dict:
    """Resolve build → marketing version → the appStoreVersion it belongs to (create if absent). Wait for VALID."""
    build_id = job["build_id"]
    if build_id in ("", "none"):  # dry-run without a binary: prepare everything except the build attach
        store.event(job["job_id"], "no build on this job — preparing the version without attaching a binary")
        marketing, state = None, "NONE"
    deadline = time.time() + 40 * 60
    while build_id not in ("", "none"):
        b = asc.get(f"/v1/builds/{build_id}", **{"fields[builds]": "version,processingState,uploadedDate", "include": "preReleaseVersion"})
        state = b["data"]["attributes"]["processingState"]
        marketing = next((i["attributes"]["version"] for i in b.get("included", []) if i["type"] == "preReleaseVersions"), None)
        if state == "VALID":
            break
        if state in ("FAILED", "INVALID") or time.time() > deadline:
            raise RuntimeError(f"build {build_id} processingState={state}")
        store.event(job["job_id"], f"build {build_id} is {state}; waiting")
        time.sleep(60)
    versions = asc.get(f"/v1/apps/{job['app_id']}/appStoreVersions", **{"filter[platform]": "IOS", "limit": 10}).get("data") or []
    editable = [v for v in versions if v["attributes"]["appVersionState"] in ("PREPARE_FOR_SUBMISSION", "DEVELOPER_REJECTED", "REJECTED", "METADATA_REJECTED", "INVALID_BINARY")]
    v = next((x for x in editable if x["attributes"]["versionString"] == marketing), None) or (editable[0] if editable else None)
    if v is None:
        r = asc.post("/v1/appStoreVersions", {"data": {"type": "appStoreVersions", "attributes": {"platform": "IOS", "versionString": marketing or "1.0"},
                     "relationships": {"app": {"data": {"type": "apps", "id": job["app_id"]}}}}}, app_id=job["app_id"])
        version_id = r.get("data", {}).get("id", "dry-run-version")
    else:
        version_id = v["id"]
    store.update(job["job_id"], version_id=version_id, marketing_version=marketing)
    return {"build_id": build_id, "marketing_version": marketing, "version_id": version_id, "build_state": state}


# --- stage: metadata --------------------------------------------------------

def stage_metadata(job: dict, app: dict) -> dict:
    state = asyncio.run(runner.run(metadata_agent.build_metadata_loop(), "Write the metadata.",
                                   {"app_facts": app["facts"] + "\n" + app.get("review_notes_extra", ""),
                                    "metadata_critique": job.get("rejection_feedback", ""), "privacy_url": app.get("privacy_url", "")}))
    final = metadata_agent.parse_final(state)
    if not final:
        raise RuntimeError("critic never approved within max_iterations; last critique: " + str(state.get("metadata_critique"))[:500])
    return {"final": final, "reviewNotes": final.get("reviewNotes", ""), "rounds": sum(1 for k in state if k.startswith("metadata_"))}


# --- stage: screenshots -----------------------------------------------------

def stage_screenshots(job: dict, app: dict) -> dict:
    meta = job["stages"]["metadata"]["output"]["final"]
    screens = {k: v for k, v in app["screens"].items()}
    state = asyncio.run(runner.run(captions_agent.build_captions_agent(), "Write the captions.",
                                   {"screens": "\n".join(f"{k} → {v}" for k, v in screens.items()),
                                    "metadata_final": str({k: meta[k] for k in ("name", "subtitle", "keywords")}), "app_facts": app["facts"]}))
    caps = {c["screen"].strip().lower(): c for c in captions_agent.parse(state)}
    colors = app.get("brand_colors", {})
    backdrop = gen_backdrop(app.get("backdrop_prompt", f"{app['brand']} brand gradient, indigo to violet, soft light")) if os.environ.get("GEN_BACKDROPS") == "true" else None
    composites, web = [], []
    for screen in [s for s in PANEL_ORDER if s in screens]:
        cap = caps.get(screen) or {"headline": meta["name"].split(":")[0], "sub": screens[screen][:48]}
        src = Image.open(io.BytesIO(assets.read(_src(app, screen))))
        img = compose(src, Panel(screen, cap["headline"], cap["sub"]), colors, backdrop=backdrop)
        composites.append(assets.write(_out(job, f"composites/{len(composites) + 1:02d}_{screen}.png"), png_bytes(img)))
        web.append(assets.write(_out(job, f"web/{len(web) + 1:02d}_{screen}.png"), png_bytes(to_web_size(img))))
    paywall = assets.write(_out(job, "paywall.png"), assets.read(_src(app, "paywall")))  # raw capture = IAP review screenshot
    return {"composites": composites, "web": web, "paywall": paywall, "captions": list(caps.values()), "backdrop": "gemini-image" if backdrop else "gradient"}


# --- stage: preflight -------------------------------------------------------

def _run_checks(ctx) -> list[dict]:
    state = asyncio.run(runner.run(preflight_agent.build_preflight(), "Run preflight.", {"preflight_ctx": ctx.__dict__}))
    return preflight_agent.gather(state)


def _verdict(findings: list[dict]) -> str:
    return "BLOCKED" if any(f["severity"] == BLOCK and not f.get("operator") for f in findings) else "PASS"


def stage_preflight(asc: ASC, job: dict, app: dict) -> dict:
    ctx = resolve_ctx(asc, job["app_id"], version_id=job.get("version_id"), build_id=job.get("build_id"))
    ctx.composites = (job["stages"].get("screenshots", {}).get("output") or {}).get("composites") or []
    ctx.facts = app.get("facts", "")
    first = _run_checks(ctx)
    store.event(job["job_id"], f"preflight pass 1: {len(first)} findings, verdict {_verdict(first)}")
    # auto-fix in dependency order (metadata before screenshots before IAP review screenshots...)
    fix_results = []
    by_fix: dict[str, list[dict]] = {}
    for f in first:
        if f.get("auto_fix"):
            by_fix.setdefault(f["auto_fix"], []).append(f)
    job = store.get_job(job["job_id"]) or job
    for name in FIX_ORDER:
        for f in by_fix.get(name, []):
            res = fixes.apply(asc, ctx, Finding(**f), job, app)
            fix_results.append({"fix": name, "check": f["check"], **res})
            store.event(job["job_id"], f"auto-fix {name}: {'ok' if res.get('ok') else res}")
    # read back: a 2xx means stored, not done — re-run every check
    if config.DRY_RUN:
        # fixes were simulated — project what the re-check would show so the report is actionable
        fixed = {(r["check"], r["fix"]) for r in fix_results if r.get("ok") and not (r.get("result") or {}).get("skipped")}
        second = [f for f in first if (f["check"], f.get("auto_fix")) not in fixed]
    else:
        second = _run_checks(ctx)
    verdict = _verdict(second)
    for f in second:
        if f.get("operator"):
            store.add_operator_item(job["job_id"], f["message"])
    state = asyncio.run(runner.run(preflight_agent.build_reporter(), "Write the report.",
                                   {"preflight_verdict": verdict + (" (dry-run: projected after simulated auto-fixes)" if config.DRY_RUN else ""),
                                    "preflight_findings": str(second), "preflight_fix_results": str(fix_results)}))
    return {"verdict": verdict, "findings_before": first, "findings_after": second, "fixes": fix_results, "report": state.get("preflight_report", "")}


# --- stage: submit ----------------------------------------------------------

def stage_submit(asc: ASC, job: dict, app: dict) -> dict:
    pre = job["stages"]["preflight"]["output"]
    if pre["verdict"] != "PASS":
        return {"submitted": False, "reason": "preflight BLOCKED", "blocking": [f["message"] for f in pre["findings_after"] if f["severity"] == BLOCK and not f.get("operator")]}
    if config.DRY_RUN or not config.ALLOW_SUBMIT:
        return {"submitted": False, "reason": "DRY_RUN or ALLOW_SUBMIT=false — version fully prepared, submission withheld"}
    app_id, version_id = job["app_id"], job["version_id"]
    existing = [s for s in (asc.get("/v1/reviewSubmissions", **{"filter[app]": app_id, "filter[state]": "READY_FOR_REVIEW,WAITING_FOR_REVIEW,IN_REVIEW"}).get("data") or [])]
    if existing:
        sub = existing[0]
    else:
        sub = asc.post("/v1/reviewSubmissions", {"data": {"type": "reviewSubmissions", "attributes": {"platform": "IOS"},
                       "relationships": {"app": {"data": {"type": "apps", "id": app_id}}}}}, app_id=app_id)["data"]
    try:
        asc.post("/v1/reviewSubmissionItems", {"data": {"type": "reviewSubmissionItems",
                 "relationships": {"reviewSubmission": {"data": {"type": "reviewSubmissions", "id": sub["id"]}},
                                   "appStoreVersion": {"data": {"type": "appStoreVersions", "id": version_id}}}}}, app_id=app_id)
    except ASCError as e:
        # this POST is where hidden blockers surface (meta.associatedErrors) — capture, don't crash
        details = [x.get("detail") or x.get("title") for x in e.errors] + [a.get("detail") for x in e.errors for a in ((x.get("meta") or {}).get("associatedErrors") or {}).get("/v1/appStoreVersions", [])]
        if e.status != 409 or "already" not in str(e.body).lower():
            return {"submitted": False, "reason": "reviewSubmissionItems rejected", "errors": details, "submission_id": sub["id"]}
    asc.patch(f"/v1/reviewSubmissions/{sub['id']}", {"data": {"type": "reviewSubmissions", "id": sub["id"], "attributes": {"submitted": True}}}, app_id=app_id)
    # read back — five different things: uploaded ≠ attached ≠ submitted ≠ approved ≠ live
    time.sleep(5)
    vs = asc.get(f"/v1/appStoreVersions/{version_id}", **{"fields[appStoreVersions]": "appVersionState"})["data"]["attributes"]["appVersionState"]
    ss = asc.get(f"/v1/reviewSubmissions/{sub['id']}")["data"]["attributes"]["state"]
    return {"submitted": True, "submission_id": sub["id"], "submission_state": ss, "version_state": vs}


# --- driver -------------------------------------------------------------------

def run_job(job_id: str) -> dict:
    job = store.get_job(job_id)
    if not job:
        raise KeyError(job_id)
    app = store.get_app(job["app_id"])
    config.assert_app_allowed(job["app_id"])
    asc = ASC()
    plan = [("intake", lambda: stage_intake(asc, store.get_job(job_id), app)),
            ("metadata", lambda: stage_metadata(store.get_job(job_id), app)),
            ("screenshots", lambda: stage_screenshots(store.get_job(job_id), app)),
            ("preflight", lambda: stage_preflight(asc, store.get_job(job_id), app)),
            ("submit", lambda: stage_submit(asc, store.get_job(job_id), app))]
    for name, fn in plan:
        if store.stage_status(store.get_job(job_id), name) == "done":
            continue
        store.stage_start(job_id, name)
        try:
            out = fn()
        except Exception as e:  # noqa: BLE001
            log.exception("stage %s failed", name)
            store.stage_failed(job_id, name, str(e)[:1500])
            raise
        store.stage_done(job_id, name, out)
    sub = store.get_job(job_id)["stages"]["submit"]["output"]
    state = "waiting_for_review" if sub.get("submitted") else ("prepared" if "withheld" in sub.get("reason", "") else "blocked")
    store.update(job_id, state=state, **{"stages.watch.status": "running" if sub.get("submitted") else "pending"})
    store.event(job_id, f"pipeline finished: {state}")
    return store.get_job(job_id)
