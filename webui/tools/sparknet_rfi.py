"""Sparknet RFI tool for Open WebUI.

An RFI is a scoped request for fabric knowledge the local vault cannot answer.
The gateway posts the contract-shaped request to the Master intake and records
it locally. The answer is installed in the node inbox only after it verifies;
it is never treated as authority.
"""

from __future__ import annotations

from typing import Any

import httpx
from pydantic import BaseModel


class Tools:
    class Valves(BaseModel):
        gateway_url: str = "http://127.0.0.1:4093"
        webui_token: str = ""
        timeout_seconds: float = 20.0

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

    async def rfi_ask(
        self,
        question: str,
        scope: list[str] | None = None,
        __user__: dict[str, Any] | None = None,
    ) -> str:
        """Ask the Master for missing fabric knowledge within an explicit scope.

        Allowed scope names: ``contracts``, ``docs``, ``04_Evergreen``,
        ``05_Knowledge``, ``06_Projects`` and the charter pages. Never request
        ``00_System``, daily notes, sources, another user's vault or an
        unscoped dump.
        """
        if not self.valves.webui_token:
            return "Sparknet RFI tool is not configured (missing WebUI service token)."
        scopes = scope or ["contracts", "docs"]
        try:
            async with httpx.AsyncClient(timeout=self.valves.timeout_seconds) as client:
                response = await client.post(
                    self.valves.gateway_url.rstrip("/") + "/v1/rfi",
                    headers=self._headers(__user__),
                    json={"question": question, "scope": scopes},
                )
                response.raise_for_status()
                return str(response.json())
        except Exception as exc:
            return f"Sparknet RFI tool failed: {exc}"
