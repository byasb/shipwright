"""Rejection router. Gemma 4 (via Gemini API) does a cheap first-pass classification; Gemini 3.5
parses Apple's prose into a structured routing decision that sends the job back to the right agent.
"""
from __future__ import annotations

import json
import os

from google.adk.agents import Agent
from google.genai import Client
from pydantic import BaseModel, Field

from .. import config


class Rejection(BaseModel):
    guideline: str = Field(description="e.g. 2.1, 3.1.2, 5.1.1 — 'unknown' if none cited")
    category: str = Field(description="metadata | screenshots | iap | privacy | binary | design | operator")
    route_to: str = Field(description="metadata | screenshots | preflight | operator — which agent re-runs")
    summary: str = Field(description="one sentence, what Apple objected to")
    fix_plan: str = Field(description="concrete numbered steps the routed agent should take")
    needs_new_build: bool


INSTRUCTION = """Apple rejected an App Store submission. Parse the reviewer's message into a routing decision.
Routing rules:
- metadata text/name/keywords/description problems → route_to=metadata
- screenshot content/size/device family problems → route_to=screenshots
- IAP/subscription missing info, pricing, review screenshot, availability → route_to=preflight
- anything needing a new binary, or a human answer (legal, privacy questionnaire, demo account) → route_to=operator, needs_new_build accordingly
Gemma's first-pass label (may be wrong, verify): {gemma_label}

APPLE'S MESSAGE:
{rejection_text}
"""


def gemma_classify(text: str) -> str:
    """Cheap first-pass label with Gemma 4 through the Gemini API (separate model family = hackathon bonus,
    but also genuinely the right tool: a 10-token classification doesn't need a frontier model)."""
    key = os.environ.get("GEMINI_API_KEY") or config.secret("gemini-api-key")
    client = Client(api_key=key)
    r = client.models.generate_content(
        model=config.GEMMA_MODEL,
        contents=("Classify this App Store rejection into exactly one label from: metadata, screenshots, iap, privacy, binary, design, operator. "
                  "Reply with the label only.\n\n" + text[:4000]),
    )
    return (r.text or "").strip().split()[0].lower().strip(".,") if r.text else "unknown"


def build_rejection_parser(model: str = config.MODEL) -> Agent:
    return Agent(name="rejection_parser", model=model, instruction=INSTRUCTION, output_schema=Rejection, output_key="rejection")


def parse(state: dict) -> dict:
    raw = state.get("rejection")
    return json.loads(raw) if isinstance(raw, str) else (raw or {})
