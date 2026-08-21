"""Screenshot captions: short, keyword-echoing lines for each composited panel.
Panel 1 must establish the CATEGORY; 2-3 the mechanic; last one trust/privacy if real."""
from __future__ import annotations

import json

from google.adk.agents import Agent
from pydantic import BaseModel, Field

from .. import config


class Caption(BaseModel):
    screen: str = Field(description="screen id from the list, verbatim")
    headline: str = Field(description="≤28 chars, echoes a metadata keyword, establishes what this is")
    sub: str = Field(description="≤48 chars, the benefit")


class Captions(BaseModel):
    panels: list[Caption]


INSTRUCTION = """Write App Store screenshot captions. Screenshots are REAL device captures (never redrawn);
you only write the text that sits above each one on a branded backdrop.

Ordering rule: panel 1 establishes the category so a searcher instantly recognises what this is;
panels 2-3 show the mechanic; the last panel is trust/privacy only if the facts support it.
Produce exactly one entry per screen id, in the order given. Echo words from the final metadata (search-intent match). Never write a price. Never claim what the facts don't list.

SCREENS (id → what the capture shows):
{screens}

FINAL METADATA:
{metadata_final}

APP FACTS:
{app_facts}
"""


def build_captions_agent(model: str = config.MODEL) -> Agent:
    return Agent(name="caption_writer", model=model, instruction=INSTRUCTION, output_schema=Captions, output_key="captions")


def parse(state: dict) -> list[dict]:
    raw = state.get("captions")
    d = json.loads(raw) if isinstance(raw, str) else (raw or {})
    return d.get("panels", [])
