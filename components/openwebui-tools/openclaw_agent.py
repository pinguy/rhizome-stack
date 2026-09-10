"""Open WebUI-wide relay into the local OpenClaw agent runtime.

Raw provider/Ollama models stay lean.  When they need OpenClaw memory, tools,
or coordination, this single tool delegates a bounded task to a persistent
OpenClaw session keyed to the originating Open WebUI chat.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path


GATEWAY = "http://127.0.0.1:18789/v1/chat/completions"
CONFIG = Path(os.environ.get("OPENCLAW_CONFIG", str(Path.home() / ".openclaw/openclaw.json")))
MAX_TASK_CHARS = 8000
MAX_CONTEXT_CHARS = 12000


def _gateway_token() -> str:
    return json.loads(CONFIG.read_text(encoding="utf-8"))["gateway"]["auth"]["token"]


def _session_key(metadata: dict | None) -> str:
    chat_id = str((metadata or {}).get("chat_id") or "unsaved")
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "-", chat_id).strip("-")[:96] or "unsaved"
    return f"openwebui-pair-{safe}"


def _consult(task: str, context: str, metadata: dict | None) -> str:
    task = (task or "").strip()
    if not task:
        raise ValueError("task must not be empty")
    if len(task) > MAX_TASK_CHARS:
        raise ValueError(f"task exceeds {MAX_TASK_CHARS} characters")
    context = (context or "").strip()[:MAX_CONTEXT_CHARS]
    prompt = (
        "You are the OpenClaw half of a paired Open WebUI/OpenClaw system. "
        "An Open WebUI model is delegating a bounded task to you. Use your actual tools and "
        "shared memory where useful; do not pretend to have used a tool. Return concrete results "
        "and receipts suitable for the calling model to continue the conversation. Do not send "
        "messages, publish, purchase, alter accounts, or perform other external side effects unless "
        "the delegated task explicitly requests that exact action.\n\n"
        f"Delegated task:\n{task}"
    )
    if context:
        prompt += f"\n\nRelevant context from the Open WebUI conversation:\n{context}"
    payload = {
        "model": "openclaw/default",
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
    }
    request = urllib.request.Request(
        GATEWAY,
        data=json.dumps(payload).encode(),
        method="POST",
        headers={
            "Authorization": "Bearer " + _gateway_token(),
            "Content-Type": "application/json",
            "x-openclaw-message-channel": "webchat",
            "x-openclaw-session-key": _session_key(metadata),
        },
    )
    with urllib.request.urlopen(request, timeout=900) as response:
        result = json.load(response)
    content = (((result.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
    if not content:
        raise RuntimeError(f"OpenClaw returned no answer: {str(result)[:500]}")
    return content


class Tools:
    citation = False

    async def consult_openclaw(
        self,
        task: str,
        context: str = "",
        __metadata__=None,
        __event_emitter__=None,
    ) -> str:
        """Delegate work to the paired OpenClaw agent and its full tool/runtime environment.

        Use this whenever the request benefits from OpenClaw-only capabilities or shared state:
        durable/Rhizome memory, local files and services, browser research, messaging, schedules,
        media generation, system inspection, or coordination with the OpenClaw side. This is the
        general bridge between Open WebUI and OpenClaw. Pass only the relevant conversation context,
        not the entire chat. Do not call it for ordinary knowledge or prose that you can answer
        directly. Treat the returned text as a real agent result and continue the user's conversation.

        :param task: A concrete, self-contained task for OpenClaw to perform.
        :param context: Optional concise context needed to understand the task.
        :return: OpenClaw's result, including tool findings or receipts.
        """
        if __event_emitter__:
            await __event_emitter__({
                "type": "status",
                "data": {"description": "Consulting the paired OpenClaw agent…", "done": False},
            })
        try:
            import asyncio

            answer = await asyncio.to_thread(_consult, task, context, __metadata__)
            if __event_emitter__:
                await __event_emitter__({
                    "type": "status",
                    "data": {"description": "OpenClaw handoff complete.", "done": True},
                })
            return answer
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:800]
            error = f"OpenClaw gateway HTTP {exc.code}: {detail}"
        except Exception as exc:
            error = f"OpenClaw handoff failed: {type(exc).__name__}: {exc}"
        if __event_emitter__:
            await __event_emitter__({
                "type": "status",
                "data": {"description": "OpenClaw handoff failed.", "done": True},
            })
        return error
