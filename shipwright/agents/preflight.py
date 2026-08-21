"""Compliance preflight as an ADK ParallelAgent: one CheckAgent per error-index check, fanned out,
then a deterministic gather. Gemini only writes the human-readable report — the BLOCK/PASS verdict is code.
Named patterns: parallel fan-out/gather; deterministic gate.
"""
from __future__ import annotations

import asyncio
import json
from typing import AsyncGenerator

from google.adk.agents import Agent, BaseAgent, ParallelAgent, SequentialAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions
from google.genai import types

from .. import config
from ..asc import ASC
from ..checks.preflight import CHECKS, Ctx, run_check


class CheckAgent(BaseAgent):
    """Runs one preflight check (a pure ASC read) and writes its findings into session state."""

    check_name: str

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        c = Ctx(**ctx.session.state["preflight_ctx"])
        asc = ASC()
        findings = await asyncio.to_thread(run_check, self.check_name, asc, c)
        payload = [f.dict() for f in findings]
        summary = f"{self.check_name}: {len(payload)} finding(s)" + ("".join(f"\n  [{f['severity']}] {f['message']}" for f in payload) if payload else " — pass")
        yield Event(
            author=self.name,
            content=types.Content(role="model", parts=[types.Part(text=summary)]),
            actions=EventActions(state_delta={f"preflight.{self.check_name}": payload}),
        )


REPORT_INSTRUCTION = """You are the preflight reporter. Findings from parallel checks are below as JSON.
Write a crisp report for the operator: first line is the verdict you are GIVEN (do not change it),
then BLOCKING items with their auto-fix status, then OPERATOR items (web-only, one click each),
then warnings. One line per item, no prose. Finish with the single most likely rejection reason if submitted now.

VERDICT: {preflight_verdict}
FINDINGS: {preflight_findings}
FIX RESULTS: {preflight_fix_results}
"""


def build_preflight(model: str = config.MODEL) -> ParallelAgent:
    return ParallelAgent(name="preflight_fanout", sub_agents=[CheckAgent(name=f"check_{n}", check_name=n) for n in CHECKS])


def build_reporter(model: str = config.MODEL) -> Agent:
    return Agent(name="preflight_reporter", model=model, instruction=REPORT_INSTRUCTION, output_key="preflight_report")


def gather(state: dict) -> list[dict]:
    out: list[dict] = []
    for n in CHECKS:
        out.extend(state.get(f"preflight.{n}") or [])
    return out
