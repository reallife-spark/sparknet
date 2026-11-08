"""Sparknet vault tool for Open WebUI.

Read and capture notes in the signed-in user's own ``peer-<id>`` vault through
the loopback memory gateway. The gateway resolves the user from the WebUI
service token plus the forwarded user header; this tool never sees a vault path
and cannot name another user's vault.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

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
            return "Sparknet vault tool is not configured (missing WebUI service token)."
        url = self.valves.gateway_url.rstrip("/") + path
        try:
            async with httpx.AsyncClient(timeout=self.valves.timeout_seconds) as client:
                response = await client.request(method, url, headers=self._headers(__user__), json=payload)
                response.raise_for_status()
                return str(response.json())
        except Exception as exc:
            return f"Sparknet vault tool failed: {exc}"

    async def vault_list(self, prefix: str = "", __user__: dict[str, Any] | None = None) -> str:
        """List markdown pages in my private vault. ``prefix`` narrows the listing, e.g. ``05_Knowledge``."""
        return await self._call("GET", "/v1/vault/list?" + urlencode({"prefix": prefix}), __user__)

    async def vault_search(self, query: str, top_k: int = 8, __user__: dict[str, Any] | None = None) -> str:
        """Search my private vault for a phrase and return matching paths with a snippet."""
        return await self._call("POST", "/v1/vault/search", __user__, {"query": query, "top_k": top_k})

    async def vault_read(self, path: str, __user__: dict[str, Any] | None = None) -> str:
        """Read one page from my private vault by vault-relative path."""
        return await self._call("GET", "/v1/vault/read?" + urlencode({"path": path}), __user__)

    async def vault_capture(
        self,
        title: str,
        body: str,
        target: str = "",
        __user__: dict[str, Any] | None = None,
    ) -> str:
        """Capture a note in my private vault (default ``01_Inbox/``), marked unsigned until I review it."""
        return await self._call(
            "POST",
            "/v1/vault/capture",
            __user__,
            {"title": title, "body": body, "target": target},
        )
