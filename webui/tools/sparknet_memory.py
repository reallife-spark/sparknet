"""Sparknet typed-memory tool for Open WebUI.

Every call goes through the loopback memory gateway, which resolves the signed-in
WebUI user to that user's provisioned vault. The tool never reads the Go store or
a vault directly and cannot name another user's memory.
"""

from __future__ import annotations

from typing import Any

import httpx
from pydantic import BaseModel


class Tools:
    class Valves(BaseModel):
        gateway_url: str = "http://127.0.0.1:4093"
        webui_token: str = ""
        timeout_seconds: float = 15.0

    def __init__(self) -> None:
        self.valves = self.Valves()

    @staticmethod
    def _user(__user__: dict[str, Any] | None) -> str:
        if isinstance(__user__, dict):
            value = __user__.get("id") or __user__.get("user_id")
            return str(value) if value else ""
        return ""

    def _headers(self, __user__: dict[str, Any] | None) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "X-Sparknet-Webui-Token": self.valves.webui_token,
            "X-Sparknet-User": self._user(__user__),
        }

    async def _call(self, method: str, path: str, __user__: dict[str, Any] | None, payload: dict | None = None) -> str:
        if not self.valves.webui_token:
            return "Sparknet memory tool is not configured (missing WebUI service token)."
        url = self.valves.gateway_url.rstrip("/") + path
        try:
            async with httpx.AsyncClient(timeout=self.valves.timeout_seconds) as client:
                response = await client.request(method, url, headers=self._headers(__user__), json=payload)
                response.raise_for_status()
                return str(response.json())
        except Exception as exc:
            return f"Sparknet memory tool failed: {exc}"

    async def memory_search(
        self,
        query: str,
        memory_types: list[str] | None = None,
        top_k: int = 5,
        __user__: dict[str, Any] | None = None,
    ) -> str:
        """Search my typed memory (episodic, semantic, procedural, short-term, shared)."""
        return await self._call(
            "POST",
            "/v1/memory/query",
            __user__,
            {
                "query": query,
                "memory_types": memory_types or ["episodic", "semantic", "procedural", "shared"],
                "top_k": max(1, min(int(top_k), 20)),
            },
        )

    async def memory_remember(
        self,
        text: str,
        summary: str = "",
        memory_type: str = "episodic",
        source_ref: str = "open-webui/tool",
        __user__: dict[str, Any] | None = None,
    ) -> str:
        """Store one explicit memory record in my vault's memory index."""
        record = {
            "memory_type": memory_type,
            "subtype": "note",
            "source_kind": "session",
            "source_ref": source_ref,
            "text": text,
            "summary": summary or text[:500],
            "importance": 0.6,
            "consent": {"capture": True, "share": False, "uplift": False},
            "provenance": {"owner_id": self._user(__user__), "agent": "open-webui"},
        }
        return await self._call("POST", "/v1/memory/remember", __user__, {"record": record})

    async def memory_forget(
        self,
        memory_ids: list[str],
        reason: str = "user request",
        __user__: dict[str, Any] | None = None,
    ) -> str:
        """Delete memory records I own by id; the reason is written to the audit log."""
        return await self._call(
            "POST",
            "/v1/memory/forget",
            __user__,
            {"ids": memory_ids, "mode": "delete", "reason": reason},
        )
