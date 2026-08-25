"""Send the finished job's release report to the operator — the 'right info to the right places'
leg of the workflow. Email is the channel because the operator items it carries (App Privacy
publish, medical-device banner…) are things a human does on the web, usually from wherever
they read mail.

Config is optional on purpose: without SMTP settings the report still exists on the job page
and in Firestore; this just stops it waiting for someone to look. Never raises — a failed
email must not fail a succeeded release job.
"""
from __future__ import annotations

import logging
import os
import smtplib
from email.message import EmailMessage

log = logging.getLogger("shipwright.notify")


def _report(job: dict) -> str:
    stages = job.get("stages", {})
    pre = (stages.get("preflight", {}).get("output") or {})
    sub = (stages.get("submit", {}).get("output") or {})
    lines = [
        f"Shipwright job {job.get('id', '?')} — {job.get('state', '?').upper()}",
        f"app {job.get('app_id')} · build {job.get('build_id')} · dry_run={job.get('dry_run')}",
        "",
        "Stages: " + "  ".join(f"{n}={v.get('status')}" for n, v in stages.items()),
        "",
        f"Preflight: {pre.get('verdict', 'n/a')}",
        pre.get("report", "").strip(),
        "",
        f"Submit: {sub.get('reason') or ('submitted' if sub.get('submitted') else 'n/a')}",
    ]
    return "\n".join(lines)


def job_complete(job: dict) -> bool:
    """Email the release report. Returns True only when a mail was actually accepted for delivery."""
    host, user, password, to = (os.environ.get(k, "") for k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASS", "NOTIFY_EMAIL"))
    body = _report(job)
    if not (host and user and password and to):
        log.info("notify: SMTP not configured — report stays on the job page\n%s", body)
        return False
    try:
        msg = EmailMessage()
        msg["Subject"] = f"Shipwright: {job.get('app_id')} — {job.get('state', '?')}"
        msg["From"], msg["To"] = user, to
        msg.set_content(body)
        with smtplib.SMTP(host, int(os.environ.get("SMTP_PORT", "587")), timeout=20) as s:
            s.starttls()
            s.login(user, password)
            s.send_message(msg)
        return True
    except Exception:  # noqa: BLE001 — see module docstring
        log.exception("notify: send failed; report remains on the job page")
        return False
