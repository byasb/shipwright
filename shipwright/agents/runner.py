"""One helper to run any ADK agent tree to completion and hand back session state."""
from __future__ import annotations

import logging
from typing import Any

from google.adk.runners import InMemoryRunner
from google.genai import types

log = logging.getLogger("shipwright.adk")


async def run(agent, prompt: str, state: dict[str, Any] | None = None, user_id: str = "shipwright") -> dict[str, Any]:
    runner = InMemoryRunner(agent=agent, app_name="shipwright")
    session = await runner.session_service.create_session(app_name="shipwright", user_id=user_id, state=state or {})
    async for ev in runner.run_async(user_id=user_id, session_id=session.id,
                                     new_message=types.Content(role="user", parts=[types.Part(text=prompt)])):
        if ev.content and ev.content.parts and ev.author:
            txt = "".join(p.text or "" for p in ev.content.parts if p.text and not getattr(p, "thought", False))
            if txt.strip():
                log.info("[%s] %s", ev.author, txt[:300].replace("\n", " "))
    session = await runner.session_service.get_session(app_name="shipwright", user_id=user_id, session_id=session.id)
    return dict(session.state)
