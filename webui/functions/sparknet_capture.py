"""Sparknet capture action for Open WebUI.

Adds a button under an assistant message that captures the current conversation
into the signed-in user's own vault under ``01_Inbox/``. The write goes through
the loopback memory gateway, which resolves the user from the WebUI session and
refuses any path outside that user's vault.
"""

from __future__ import annotations

from typing import Any

import httpx
from pydantic import BaseModel


class Action:
    class Valves(BaseModel):
        gateway_url: str = "http://127.0.0.1:4093"
        webui_token: str = ""
        timeout_seconds: float = 20.0
        priority: int = 10

    def __init__(self) -> None:
        self.valves = self.Valves()

    @staticmethod
    def _user_id(__user__: dict[str, Any] | None) -> str:
        if isinstance(__user__, dict):
            value = __user__.get("id") or __user__.get("user_id")
            return str(value) if value else ""
        return ""

    @staticmethod
    def _last_text(messages: Any, role: str) -> str:
        if not isinstance(messages, list):
            return ""
        for message in reversed(messages):
            if isinstance(message, dict) and message.get("role") == role:
                content = message.get("content")
                if isinstance(content, str):
                    return content.strip()
        return ""

    async def action(
        self,
        body: dict,
        __user__: dict[str, Any] | None = None,
        __event_emitter__: Any = None,
    ) -> None:
        """Capture this conversation to my private vault."""
        user_id = self._user_id(__user__)
        if not self.valves.webui_token or not user_id:
            if __event_emitter__:
                await __event_emitter__(
                    {
                        "type": "notification",
                        "data": {"type": "error", "content": "Sparknet capture is not configured."},
                    }
                )
            return
        messages = body.get("messages") if isinstance(body, dict) else []
        prompt = self._last_text(messages, "user")
        answer = self._last_text(messages, "assistant")
        title = (prompt.splitlines()[0] if prompt else "Conversation")[:90]
        note = "User: {}\n\nAssistant: {}\n\nchat_id: {}\n".format(
            prompt or "(no user message)",
            answer or "(no assistant message)",
            body.get("chat_id") or "",
        )
        if __event_emitter__:
            await __event_emitter__({"type": "status", "data": {"description": "Capturing to your Sparknet vault…"}})
        try:
            async with httpx.AsyncClient(timeout=self.valves.timeout_seconds) as client:
                response = await client.post(
                    self.valves.gateway_url.rstrip("/") + "/v1/vault/capture",
                    headers={
                        "Content-Type": "application/json",
                        "X-Sparknet-Webui-Token": self.valves.webui_token,
                        "X-Sparknet-User": user_id,
                    },
                    json={"title": title, "body": note},
                )
                response.raise_for_status()
                result = response.json()
            path = result.get("path") if isinstance(result, dict) else ""
            if __event_emitter__:
                await __event_emitter__(
                    {
                        "type": "notification",
                        "data": {"type": "success", "content": "Captured to %s" % (path or "01_Inbox/")},
                    }
                )
        except Exception as exc:
            if __event_emitter__:
                await __event_emitter__(
                    {
                        "type": "notification",
                        "data": {"type": "error", "content": f"Capture failed: {exc}"},
                    }
                )
