"""Run the whole pipeline locally (dry-run by default) against a real app record.
Usage: .venv/bin/python scripts/local_job.py [build_id|none]
Writes composites to out/<job>/ and job state to Firestore, exactly like the Cloud Run worker."""
import logging
import os
import sys
import uuid

os.environ.setdefault("SOURCES_BASE", "assets/screens")
os.environ.setdefault("OUT_BASE", "out")
logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
for n in ("google_genai", "google_adk", "httpx", "urllib3"):
    logging.getLogger(n).setLevel(logging.WARNING)

from shipwright import config, pipeline, store  # noqa: E402

build_id = sys.argv[1] if len(sys.argv) > 1 else "none"
job_id = f"local-{uuid.uuid4().hex[:6]}"
os.environ["OUT_BASE"] = f"out/{job_id}"
pipeline.OUT_BASE = os.environ["OUT_BASE"]
app_id = sorted(config.ALLOWED_APP_IDS)[0]
store.create_job(job_id, app_id, build_id, "local", "manual")
job = pipeline.run_job(job_id)
print("\n=== JOB", job_id, "state:", job["state"], "dry_run:", job["dry_run"])
for s, v in job["stages"].items():
    print(f"  {s:12} {v['status']}")
pre = job["stages"]["preflight"].get("output") or {}
print("\n=== PREFLIGHT", pre.get("verdict"))
print(pre.get("report", "")[:3000])
print("\n=== SUBMIT", job["stages"]["submit"].get("output"))
