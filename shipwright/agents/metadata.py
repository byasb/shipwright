"""Metadata writer ⇄ critic loop (ADK LoopAgent).

writer  — Gemini drafts name/subtitle/keywords/description/promo + review notes from app facts.
critic  — separate agent whose only job is to reject: it calls the deterministic validator
          (Apple's limits, cross-field word repetition, plurals, 'app', brands, hardcoded price)
          AND applies judgment (misleading claims, 3.1 accuracy, tone). Approves via exit_loop.
Named pattern: critique loop. max_iterations caps runaway cost.
"""
from __future__ import annotations

import json

from google.adk.agents import Agent, LoopAgent
from google.adk.tools import ToolContext, exit_loop
from pydantic import BaseModel, Field

from .. import config
from ..validators import validate


class Metadata(BaseModel):
    name: str = Field(description="App Store name, ≤30 chars, keyword-led, fill ≥27")
    subtitle: str = Field(description="≤30 chars, fill ≥27, zero words shared with name")
    keywords: str = Field(description="≤100 chars, single words, comma-no-space, no word from name/subtitle, no plurals, no 'app'")
    description: str = Field(description="≤4000 chars. Outcome first, then mechanics, then privacy. Mentions 'pay once' never a price. Ends with Terms (Apple stdEULA link) and Privacy links.")
    promotionalText: str = Field(default="", description="≤170 chars, can change without review")
    reviewNotes: str = Field(description="Exact numbered test steps per feature and permission for App Review. Mention demoAccountRequired is false and why.")
    rationale: str = Field(description="one paragraph: which anchor keyword and why, how the three fields combine into phrases")


def validate_metadata(name: str, subtitle: str, keywords: str, description: str, promotionalText: str = "") -> dict:
    """Deterministic Apple-limit + three-name-doctrine validator. Returns {ok, problems}. Call before approving."""
    v = validate({"name": name, "subtitle": subtitle, "keywords": keywords, "description": description, "promotionalText": promotionalText})
    return {"ok": v.ok, "problems": v.problems}


def approve_metadata(tool_context: ToolContext) -> dict:
    """Approve the current draft and stop the loop. ONLY call after validate_metadata returned ok=true."""
    draft = tool_context.state.get("metadata_draft")
    tool_context.state["metadata_final"] = draft
    tool_context.state["metadata_critique"] = "APPROVED"
    return exit_loop(tool_context) or {"approved": True}


WRITER_INSTRUCTION = """You write App Store metadata for an indie iOS app. You are given APP FACTS and
(after the first round) a CRITIQUE from a separate reviewer. Produce the full metadata JSON.

Hard rules (the critic will reject any violation — do not test them):
- name ≤30 chars, fill ≥27. Three-name doctrine: the App Store name is a keyword-led ranking asset,
  format "<Brand>: <Category Keywords>" e.g. "SnipStash: Clipboard Manager".
- subtitle ≤30, fill ≥27. Zero words in common with name (articles excluded). It is a second ranking field, not a tagline.
- keywords ≤100 chars, fill ≥97: single words, comma-separated, NO spaces, NO word already in name or subtitle,
  NO plurals (Apple matches them), NO "app"/"free"/"best", NO competitor or Apple brand names (Apple, iPhone, iOS, Siri).
  Apple combines words across all three fields into phrases — maximise distinct useful words.
- description: outcome headline first, then what it does, then how (3-5 short paragraphs), then a privacy line,
  then a single line "Terms: https://www.apple.com/legal/internet-services/itunes/dev/stdeula/  Privacy: {privacy_url}".
  Never write a price or currency — say "pay once" or "upgrade". Never claim features the APP FACTS don't list.
- reviewNotes: numbered steps App Review can follow in 2 minutes, one block per feature and per permission
  (what to tap, what to expect). State that no demo account is needed and why (local-only data).

APP FACTS:
{app_facts}

CRITIQUE FROM LAST ROUND (empty on first round — if present, fix EVERY item):
{metadata_critique}
"""

CRITIC_INSTRUCTION = """You are the metadata critic. Your job is to REJECT. A separate writer produced this draft:

{metadata_draft}

APP FACTS the draft must not contradict:
{app_facts}

Procedure:
1. Call validate_metadata with the draft's fields. Every problem it returns is a mandatory rejection reason.
2. Then apply judgment: claims not supported by APP FACTS (guideline 3.1 accuracy / 2.3 metadata), a hardcoded
   price anywhere, competitor brands, the word "app" in name/subtitle, review notes that are vague,
   subtitle that reads like a slogan instead of search terms, wasted characters (<27 in name/subtitle, <97 keywords).
3. If validate_metadata is ok AND you find nothing in step 2: call approve_metadata and reply "APPROVED".
4. Otherwise reply with a terse numbered list of what must change. Do NOT rewrite the metadata yourself.
"""


def build_metadata_loop(model: str = config.MODEL) -> LoopAgent:
    writer = Agent(
        name="metadata_writer",
        model=model,
        instruction=WRITER_INSTRUCTION,
        output_schema=Metadata,
        output_key="metadata_draft",
    )
    critic = Agent(
        name="metadata_critic",
        model=model,
        instruction=CRITIC_INSTRUCTION,
        tools=[validate_metadata, approve_metadata],
        output_key="metadata_critique",
    )
    return LoopAgent(name="metadata_critique_loop", sub_agents=[writer, critic], max_iterations=4)


def parse_final(state: dict) -> dict | None:
    raw = state.get("metadata_final")
    if not raw:
        return None
    return json.loads(raw) if isinstance(raw, str) else raw
