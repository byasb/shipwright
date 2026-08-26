"""Run the WHOLE pipeline with no Apple account and no GCP project.

  export GEMINI_API_KEY=...   # free key from aistudio.google.com — the only credential needed
  .venv/bin/python scripts/demo_replay.py

Apple reads come from fixtures/snipstash.json (recorded from a real release run, contact
details redacted); writes are dry-run payloads; job state lives in an in-memory Firestore
stand-in. The LLM agents run for real: critique loop, preflight report, vision claims."""
import logging
import os
import sys
import uuid

os.environ["DRY_RUN"] = "true"          # belt: replay must never look submittable
os.environ["ALLOW_SUBMIT"] = "false"    # braces
os.environ.setdefault("SOURCES_BASE", "assets/screens")
if os.environ.get("REPLAY_USE_VERTEX") == "1":
    pass  # GCP-but-no-Apple users: LLM calls go through Vertex AI with your ADC + GOOGLE_CLOUD_PROJECT
else:
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        sys.exit("set GEMINI_API_KEY (free at aistudio.google.com) — the only credential replay needs; "
                 "note: one full run needs ~10 model calls, so a paid-tier key is smoother than free-tier daily caps")
    os.environ["GOOGLE_API_KEY"] = key
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "false"   # AI Studio key, not Vertex/ADC

logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
for n in ("google_genai", "google_adk", "httpx", "urllib3"):
    logging.getLogger(n).setLevel(logging.WARNING)

import pathlib  # noqa: E402

from shipwright import pipeline, replay, store  # noqa: E402

fixture = pathlib.Path(__file__).resolve().parent.parent / "fixtures" / "snipstash.json"
asc = replay.ReplayASC(fixture)
store._db = replay.MemoryFirestore()
pipeline.ASC = lambda: asc

job_id = f"replay-{uuid.uuid4().hex[:6]}"
os.environ["OUT_BASE"] = f"out/{job_id}"
pipeline.OUT_BASE = os.environ["OUT_BASE"]
app_id = asc.app_facts["id"] if "id" in asc.app_facts else "6803901837"
store.db().collection("apps").document(app_id).set(asc.app_facts)
store.create_job(job_id, app_id, asc.build_id, "replay", "manual")
job = pipeline.run_job(job_id)

print("\n=== REPLAY JOB", job_id, "state:", job["state"], "dry_run:", job["dry_run"])
for s, v in job["stages"].items():
    print(f"  {s:12} {v['status']}")
pre = job["stages"]["preflight"].get("output") or {}
print("\n=== PREFLIGHT", pre.get("verdict"))
print(pre.get("report", "")[:3000])
print("\n=== SUBMIT", job["stages"]["submit"].get("output"))
print("\nComposites in", os.environ["OUT_BASE"])
