"""Read-only Sparknet node status tool for Open WebUI.

It checks the local service health endpoints only. It cannot sign, grant,
restart or change anything, and it never returns a token or a key.
"""

from __future__ import annotations

from typing import Any

import httpx
from pydantic import BaseModel


class Tools:
    class Valves(BaseModel):
        gateway_url: str = "http://127.0.0.1:4093"
        engine_url: str = "http://127.0.0.1:4204"
        timeout_seconds: float = 8.0

    def __init__(self) -> None:
        self.valves = self.Valves()

    async def _get(self, url: str) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self.valves.timeout_seconds) as client:
                response = await client.get(url)
                return {"status": response.status_code, "body": response.json()}
        except Exception as exc:
            return {"status": 0, "error": str(exc)}

    async def node_status(self, __user__: dict[str, Any] | None = None) -> str:
        """Summarize the local Sparknet gateway, engine and memory service health."""
        gateway = await self._get(self.valves.gateway_url.rstrip("/") + "/healthz")
        engine = await self._get(self.valves.engine_url.rstrip("/") + "/healthz")
        return str(
            {
                "memory_gateway": gateway,
                "opencode_engine": engine,
                "note": "read-only health probes; no authority action was performed",
            }
        )
