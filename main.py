"""Shipwright service (one Cloud Run image, three roles picked by route):

  POST /webhook/asc   App Store Connect webhook receiver. HMAC-verified. A build finishing upload
                      creates a job and publishes it to Pub/Sub; a version state change updates the
                      matching job (the watcher). Nothing types. Ever.
  POST /pubsub        Pub/Sub push worker: runs the job pipeline (resumable; redelivery-safe).
  POST /reconcile     Cloud Scheduler net for missed webhook deliveries (30-min).
  POST /jobs/{id}/rejection   Apple's reviewer text (Resolution Center has no public API) → Gemma+Gemini router.
  GET  /, /jobs/{id}  Status pages straight from Firestore — the "frontend".
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import html
import json
import logging
import os
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

from shipwright import config, pipeline, store
from shipwright.agents import runner, watcher
from shipwright.asc import ASC, ASCError

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("shipwright")
app = FastAPI(title="Shipwright")

REVIEW_STATES_DONE = {"READY_FOR_DISTRIBUTION", "PROCESSING_FOR_DISTRIBUTION", "READY_FOR_SALE", "ACCEPTED"}
REVIEW_STATES_REJECTED = {"REJECTED", "METADATA_REJECTED", "DEVELOPER_REJECTED", "INVALID_BINARY"}


def _publish(job_id: str) -> None:
    from google.cloud import pubsub_v1

    pub = pubsub_v1.PublisherClient()
    pub.publish(pub.topic_path(config.PROJECT, config.PUBSUB_TOPIC), json.dumps({"job_id": job_id}).encode()).result(30)


def _verify_signature(body: bytes, header: str | None) -> bool:
    if not header:
        return False
    algo, _, sig = header.partition("=")
    if algo.lower() != "hmacsha256":
        return False
    expected = hmac.new(config.webhook_secret().encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig.strip())


def _job_for_build(asc: ASC, build_id: str, source: str) -> dict | None:
    b = asc.get(f"/v1/builds/{build_id}", **{"fields[builds]": "version,processingState,app", "include": "app"})
    app_id = b["data"]["relationships"]["app"]["data"]["id"]
    if app_id not in config.ALLOWED_APP_IDS:
        log.info("build %s belongs to app %s — not allowlisted, ignoring", build_id, app_id)
        return None
    if store.find_job_for_build(build_id):
        return None
    job_id = f"job-{b['data']['attributes']['version']}-{uuid.uuid4().hex[:6]}"
    job = store.create_job(job_id, app_id, build_id, b["data"]["attributes"]["version"], source)
    _publish(job_id)
    return job


@app.get("/health")
def healthz():
    return {"ok": True, "dry_run": config.DRY_RUN, "allow_submit": config.ALLOW_SUBMIT, "apps": sorted(config.ALLOWED_APP_IDS)}


@app.post("/webhook/asc")
async def asc_webhook(req: Request):
    body = await req.body()
    if not _verify_signature(body, req.headers.get("x-apple-signature")):
        raise HTTPException(401, "bad signature")
    payload = json.loads(body or b"{}")
    data = payload.get("data") or {}
    etype = data.get("type", "")
    attrs = data.get("attributes") or {}
    inst = ((data.get("relationships") or {}).get("instance") or {}).get("data") or {}
    log.info("webhook %s %s instance=%s", etype, attrs, inst)

    if etype == "webhookPingCreated":
        return {"pong": True}

    asc = ASC()
    if etype == "buildUploadStateUpdated":
        new_state = str(attrs.get("newState") or "")
        if new_state and not any(k in new_state.upper() for k in ("COMPLETE", "VALID", "SUCCESS", "PROCESSED")):
            store.db().collection("webhook_events").add({"at": store.now(), "type": etype, "state": new_state, "instance": inst.get("id")})
            return {"ignored": new_state}
        build_id = None
        try:  # observed 2026-08: the build shares the buildUpload's id
            asc.get(f"/v1/builds/{inst.get('id')}", **{"fields[builds]": "processingState"})
            build_id = inst.get("id")
        except ASCError:
            pass
        try:
            up = asc.get(f"/v1/buildUploads/{inst.get('id')}")
            build_id = build_id or (((up["data"].get("relationships") or {}).get("build") or {}).get("data") or {}).get("id")
            log.info("buildUpload %s attrs=%s", inst.get("id"), up["data"].get("attributes"))
        except ASCError as e:
            log.warning("buildUploads/%s: %s", inst.get("id"), e.status)
        if not build_id:  # instance lacks the build link → newest VALID build on an allowlisted app
            for app_id in config.ALLOWED_APP_IDS:
                bs = asc.get("/v1/builds", **{"filter[app]": app_id, "sort": "-uploadedDate", "limit": 1}).get("data") or []
                if bs and bs[0]["attributes"]["processingState"] in ("VALID", "PROCESSING") and not store.find_job_for_build(bs[0]["id"]):
                    build_id = bs[0]["id"]
                    break
        if not build_id:
            return {"ignored": "no build resolvable yet — scheduler reconcile will pick it up"}
        job = _job_for_build(asc, build_id, "webhook")
        return {"job": job["job_id"] if job else None}

    if etype == "appStoreVersionAppVersionStateUpdated":
        version_id = inst.get("id")
        job = store.find_job_for_version(version_id)
        if not job:
            return {"ignored": "no job for version"}
        new, old = attrs.get("newValue"), attrs.get("oldValue")
        store.event(job["job_id"], f"App Store version state {old} → {new}", source="webhook")
        if new in REVIEW_STATES_REJECTED:
            store.update(job["job_id"], state="rejected", review_state=new)
            store.add_operator_item(job["job_id"], f"Apple rejected ({new}). Paste the Resolution Center message to POST /jobs/{job['job_id']}/rejection to route it.")
        elif new in REVIEW_STATES_DONE:
            store.update(job["job_id"], state="approved", review_state=new, **{"stages.watch.status": "done"})
        else:
            store.update(job["job_id"], state=new.lower(), review_state=new)
        return {"job": job["job_id"], "state": new}
    return {"ignored": etype}


@app.post("/pubsub")
async def pubsub_push(req: Request):
    env = await req.json()
    msg = env.get("message") or {}
    data = json.loads(base64.b64decode(msg.get("data", "")) or b"{}")
    job_id = data.get("job_id")
    if not job_id:
        return JSONResponse({"error": "no job_id"}, status_code=204)  # ack — poison message
    try:
        job = await asyncio.to_thread(pipeline.run_job, job_id)
        return {"job": job_id, "state": job["state"]}
    except Exception as e:  # noqa: BLE001
        log.exception("job %s failed", job_id)
        # 500 → Pub/Sub retries with backoff, up to the dead-letter limit; the job resumes at the failed stage
        raise HTTPException(500, str(e)[:500])


@app.post("/jobs")
async def manual_job(req: Request):
    """Manual trigger for dry-runs and tests. Same token as the webhook secret."""
    if req.headers.get("x-shipwright-token") != config.webhook_secret():
        raise HTTPException(401)
    body = await req.json()
    asc = ASC()
    build_id = body.get("build_id")
    if not build_id:
        builds = asc.get("/v1/builds", **{"filter[app]": body["app_id"], "filter[processingState]": "VALID", "sort": "-uploadedDate", "limit": 1}).get("data") or []
        if not builds:
            raise HTTPException(404, "no VALID build for app")
        build_id = builds[0]["id"]
    job = _job_for_build(asc, build_id, "manual")
    if not job:
        existing = store.find_job_for_build(build_id)
        return {"job": existing["job_id"] if existing else None, "note": "job already exists or app not allowlisted"}
    return {"job": job["job_id"]}


@app.post("/reconcile")
async def reconcile(req: Request):
    """Cloud Scheduler → OIDC-authenticated. Catches builds whose webhook delivery was missed and
    refreshes review state for in-flight jobs."""
    if not _scheduler_ok(req):
        raise HTTPException(401)
    asc = ASC()
    created, refreshed = [], []
    for app_id in config.ALLOWED_APP_IDS:
        for b in asc.get("/v1/builds", **{"filter[app]": app_id, "filter[processingState]": "VALID", "sort": "-uploadedDate", "limit": 3}).get("data") or []:
            if not store.find_job_for_build(b["id"]):
                j = _job_for_build(asc, b["id"], "scheduler")
                if j:
                    created.append(j["job_id"])
    for j in store.recent_jobs(20):
        if j.get("state") in ("waiting_for_review", "in_review", "waiting_for_review".upper().lower()) and j.get("version_id"):
            st = asc.get(f"/v1/appStoreVersions/{j['version_id']}", **{"fields[appStoreVersions]": "appVersionState"})["data"]["attributes"]["appVersionState"]
            if st != j.get("review_state"):
                store.event(j["job_id"], f"reconcile: version state {j.get('review_state')} → {st}", source="scheduler")
                store.update(j["job_id"], review_state=st, state="approved" if st in REVIEW_STATES_DONE else ("rejected" if st in REVIEW_STATES_REJECTED else st.lower()))
                refreshed.append(j["job_id"])
    return {"created": created, "refreshed": refreshed}


def _scheduler_ok(req: Request) -> bool:
    auth = req.headers.get("authorization", "")
    if not auth.startswith("Bearer "):
        return False
    try:
        from google.auth.transport import requests as garequests
        from google.oauth2 import id_token

        info = id_token.verify_oauth2_token(auth[7:], garequests.Request())
        return info.get("email", "").endswith(".gserviceaccount.com")
    except Exception:  # noqa: BLE001
        return False


@app.post("/jobs/{job_id}/rejection")
async def rejection(job_id: str, req: Request):
    if req.headers.get("x-shipwright-token") != config.webhook_secret():
        raise HTTPException(401)
    job = store.get_job(job_id)
    if not job:
        raise HTTPException(404)
    text = (await req.json()).get("text", "")
    label = await asyncio.to_thread(watcher.gemma_classify, text)
    state = await runner.run(watcher.build_rejection_parser(), "Route this rejection.", {"rejection_text": text, "gemma_label": label})
    r = watcher.parse(state)
    store.event(job_id, f"rejection routed → {r.get('route_to')} (gemma={label}, guideline {r.get('guideline')})")
    store.update(job_id, rejection=r, rejection_feedback=f"Apple rejected the last submission: {r.get('summary')}. Fix plan: {r.get('fix_plan')}")
    # re-open the routed stage(s) and everything downstream, then re-queue — the loop closes itself
    reopen = {"metadata": ["metadata", "screenshots", "preflight", "submit"], "screenshots": ["screenshots", "preflight", "submit"],
              "preflight": ["preflight", "submit"]}.get(r.get("route_to"), [])
    if reopen:
        store.update(job_id, **{f"stages.{s}.status": "pending" for s in reopen}, state="rerouted")
        _publish(job_id)
    else:
        store.add_operator_item(job_id, f"Needs a human: {r.get('summary')} — {r.get('fix_plan')}")
    return {"gemma": label, "route": r, "requeued": bool(reopen)}


# --- frontend ------------------------------------------------------------------

CSS = """<style>body{font:15px/1.5 -apple-system,Inter,sans-serif;max-width:960px;margin:2rem auto;padding:0 1rem;color:#111}
h1{font-size:1.6rem}code,pre{background:#f4f4f8;border-radius:6px;padding:.1rem .35rem}pre{padding:1rem;overflow:auto;white-space:pre-wrap}
table{border-collapse:collapse;width:100%}td,th{border-bottom:1px solid #e5e5ee;padding:.4rem .5rem;text-align:left;vertical-align:top}
.s-done{color:#0a7a2f}.s-running{color:#b36b00}.s-failed{color:#b00020}.s-pending{color:#888}.pill{display:inline-block;padding:.1rem .5rem;border-radius:999px;background:#eef;font-size:.8rem}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:.6rem}.grid img{width:100%;border-radius:10px;box-shadow:0 2px 10px #0002}</style>"""


def _page(title: str, body: str) -> HTMLResponse:
    return HTMLResponse(f"<!doctype html><title>{html.escape(title)}</title>{CSS}<h1>{html.escape(title)}</h1>{body}")


@app.get("/", response_class=HTMLResponse)
def index():
    rows = "".join(f"<tr><td><a href='/jobs/{j['job_id']}'>{j['job_id']}</a></td><td>{j.get('app_id')}</td><td>{j.get('build_version')}</td>"
                   f"<td><span class='pill'>{html.escape(str(j.get('state')))}</span></td><td>{j.get('source')}</td><td>{'dry-run' if j.get('dry_run') else 'LIVE'}</td><td>{j.get('updated','')[:19]}</td></tr>"
                   for j in store.recent_jobs())
    return _page("Shipwright — release jobs", f"<p>Build lands in App Store Connect → agent takes it to Waiting for Review. DRY_RUN={config.DRY_RUN} ALLOW_SUBMIT={config.ALLOW_SUBMIT}</p>"
                 f"<table><tr><th>job</th><th>app</th><th>build</th><th>state</th><th>trigger</th><th>mode</th><th>updated</th></tr>{rows}</table>")


@app.get("/jobs/{job_id}", response_class=HTMLResponse)
def job_page(job_id: str):
    j = store.get_job(job_id)
    if not j:
        raise HTTPException(404)
    st = j.get("stages", {})
    stage_rows = "".join(f"<tr><td>{s}</td><td class='s-{st.get(s,{}).get('status','pending')}'>{st.get(s,{}).get('status','pending')}</td>"
                         f"<td>{html.escape(str(st.get(s,{}).get('error',''))[:300])}</td></tr>" for s in store.STAGES)
    meta = (st.get("metadata", {}).get("output") or {}).get("final") or {}
    meta_html = "".join(f"<tr><th>{k}</th><td>{html.escape(str(meta.get(k,'')))} <small>({len(str(meta.get(k,'')))})</small></td></tr>" for k in ("name", "subtitle", "keywords", "promotionalText")) if meta else ""
    shots = (st.get("screenshots", {}).get("output") or {}).get("composites") or []
    shots_html = "".join(f"<img src='/asset?u={html.escape(u)}'>" for u in shots)
    pre = st.get("preflight", {}).get("output") or {}
    findings = "".join(f"<tr><td>{f['severity']}</td><td>{f['check']}</td><td>{html.escape(f['message'])}</td><td>{f.get('auto_fix') or ('operator' if f.get('operator') else '')}</td></tr>"
                       for f in pre.get("findings_before", []))
    ops = "".join(f"<li>{html.escape(o)}</li>" for o in j.get("operator_items", []))
    events = "".join(f"<tr><td>{e.get('at','')[11:19]}</td><td>{html.escape(e.get('msg',''))}</td></tr>" for e in j.get("events", [])[-60:])
    sub = st.get("submit", {}).get("output") or {}
    body = (f"<p>app <code>{j.get('app_id')}</code> build <code>{j.get('build_version')}</code> ({j.get('build_id')}) version <code>{j.get('version_id','')}</code> "
            f"state <span class='pill'>{html.escape(str(j.get('state')))}</span> trigger {j.get('source')} {'<b>DRY-RUN</b>' if j.get('dry_run') else '<b>LIVE</b>'}</p>"
            f"<h2>Stages</h2><table>{stage_rows}</table>"
            + (f"<h2>Metadata (critique loop, {st.get('metadata',{}).get('output',{}).get('rounds','?')} state writes)</h2><table>{meta_html}</table><details><summary>description + review notes</summary><pre>{html.escape(meta.get('description',''))}\n\n--- review notes ---\n{html.escape(meta.get('reviewNotes',''))}</pre></details>" if meta else "")
            + (f"<h2>Screenshots ({(st.get('screenshots',{}).get('output') or {}).get('backdrop','')})</h2><div class='grid'>{shots_html}</div>" if shots else "")
            + (f"<h2>Preflight — {html.escape(pre.get('verdict',''))}</h2><pre>{html.escape(pre.get('report',''))}</pre><details><summary>{len(pre.get('findings_before',[]))} findings before auto-fix</summary><table>{findings}</table></details>" if pre else "")
            + (f"<h2>Submission</h2><pre>{html.escape(json.dumps(sub, indent=1))}</pre>" if sub else "")
            + (f"<h2>Operator items</h2><ul>{ops}</ul>" if ops else "")
            + f"<h2>Events</h2><table>{events}</table>")
    return _page(f"Shipwright — {job_id}", body)


@app.get("/asset")
def asset(u: str):
    from fastapi.responses import Response
    from shipwright import assets as A

    if not (u.startswith(f"gs://{config.BUCKET}/") or u.startswith(os.environ.get("OUT_BASE", "/dev/null"))):
        raise HTTPException(403)
    return Response(A.read(u), media_type="image/png")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
