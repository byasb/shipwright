"""Maintainer-only: run the pipeline once with the real ASC client wrapped in a recorder,
then save every GET response (phones/emails redacted) + the app facts to fixtures/.
Usage: .venv/bin/python scripts/record_fixtures.py [build_id|none]"""
import logging
import os
import pathlib
import sys
import uuid

os.environ.setdefault("SOURCES_BASE", "assets/screens")
logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
for n in ("google_genai", "google_adk", "httpx", "urllib3"):
    logging.getLogger(n).setLevel(logging.WARNING)

from shipwright import config, pipeline, replay, store  # noqa: E402
from shipwright.asc import ASC  # noqa: E402

assert config.DRY_RUN, "record with DRY_RUN=true — recording must not write to Apple"
out = pathlib.Path("fixtures"); out.mkdir(exist_ok=True)
build_id = sys.argv[1] if len(sys.argv) > 1 else "none"
job_id = f"record-{uuid.uuid4().hex[:6]}"
os.environ["OUT_BASE"] = f"out/{job_id}"
pipeline.OUT_BASE = os.environ["OUT_BASE"]

recorder = replay.RecordingASC(ASC(), out / "snipstash.json")
pipeline.ASC = lambda: recorder  # every stage gets the recorder
app_id = sorted(config.ALLOWED_APP_IDS)[0]
store.create_job(job_id, app_id, build_id, "record", "manual")
job = pipeline.run_job(job_id)
recorder.save(app_facts=store.get_app(app_id), build_id=build_id)
print("state:", job["state"], "| fixture:", out / "snipstash.json")
