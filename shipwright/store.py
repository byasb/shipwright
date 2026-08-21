"""Firestore job + app state. Document state across a multi-day review cycle.

jobs/{job_id}   one release attempt. stages.* make the job resumable: a re-delivered
                Pub/Sub message or a crashed worker picks up at the first unfinished stage.
apps/{app_id}   operator-supplied facts the API cannot know (what the app does, who it's for,
                brand colours, keyword seeds, review notes). Seeded once by scripts/seed_app.py.
"""
from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from google.cloud import firestore

from . import config

log = logging.getLogger("shipwright.store")
_db: firestore.Client | None = None


def db() -> firestore.Client:
    global _db
    if _db is None:
        _db = firestore.Client(project=config.PROJECT)
    return _db


def now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


STAGES = ["intake", "metadata", "screenshots", "preflight", "submit", "watch"]


def create_job(job_id: str, app_id: str, build_id: str, build_version: str, source: str) -> dict:
    ref = db().collection("jobs").document(job_id)
    if ref.get().exists:
        log.info("job %s exists — resuming", job_id)
        return ref.get().to_dict()
    doc = {
        "job_id": job_id,
        "app_id": app_id,
        "build_id": build_id,
        "build_version": build_version,
        "source": source,  # webhook | scheduler | manual
        "dry_run": config.DRY_RUN,
        "state": "received",
        "stages": {s: {"status": "pending"} for s in STAGES},
        "events": [{"at": now(), "msg": f"job created from {source}"}],
        "operator_items": [],
        "created": now(),
        "updated": now(),
    }
    ref.set(doc)
    return doc


def get_job(job_id: str) -> dict | None:
    snap = db().collection("jobs").document(job_id).get()
    return snap.to_dict() if snap.exists else None


def find_job_for_build(build_id: str) -> dict | None:
    q = db().collection("jobs").where(filter=firestore.FieldFilter("build_id", "==", build_id)).limit(1)
    for snap in q.stream():
        return snap.to_dict()
    return None


def find_job_for_version(version_id: str) -> dict | None:
    q = db().collection("jobs").where(filter=firestore.FieldFilter("version_id", "==", version_id)).limit(1)
    for snap in q.stream():
        return snap.to_dict()
    return None


def update(job_id: str, **fields: Any) -> None:
    fields["updated"] = now()
    db().collection("jobs").document(job_id).update(fields)


def event(job_id: str, msg: str, **extra: Any) -> None:
    log.info("[%s] %s", job_id, msg)
    db().collection("jobs").document(job_id).update({
        "events": firestore.ArrayUnion([{"at": now(), "msg": msg, **extra}]),
        "updated": now(),
    })


def stage_start(job_id: str, stage: str) -> None:
    update(job_id, **{f"stages.{stage}.status": "running", f"stages.{stage}.started": now(), "state": stage})


def stage_done(job_id: str, stage: str, output: Any = None) -> None:
    update(job_id, **{f"stages.{stage}.status": "done", f"stages.{stage}.finished": now(),
                      f"stages.{stage}.output": output})


def stage_failed(job_id: str, stage: str, error: str) -> None:
    update(job_id, **{f"stages.{stage}.status": "failed", f"stages.{stage}.error": error,
                      f"stages.{stage}.finished": now(), "state": "failed"})


def stage_status(job: dict, stage: str) -> str:
    return job.get("stages", {}).get(stage, {}).get("status", "pending")


def add_operator_item(job_id: str, item: str) -> None:
    db().collection("jobs").document(job_id).update({"operator_items": firestore.ArrayUnion([item])})


def get_app(app_id: str) -> dict:
    snap = db().collection("apps").document(str(app_id)).get()
    if not snap.exists:
        raise KeyError(f"apps/{app_id} not seeded — run scripts/seed_app.py")
    return snap.to_dict()


def put_app(app_id: str, doc: dict) -> None:
    db().collection("apps").document(str(app_id)).set(doc, merge=True)


def recent_jobs(limit: int = 20) -> list[dict]:
    q = db().collection("jobs").order_by("created", direction=firestore.Query.DESCENDING).limit(limit)
    return [s.to_dict() for s in q.stream()]
