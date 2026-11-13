#!/usr/bin/env python3
"""sparknet-llm-proxy — the OpenAI surface in front of llama-server.

`llama-server` (the b9016 build in the Jetson `llama_cpp` image) has no
`--system-prompt-file` flag. The fabric precontext is a system message, so this
tiny reverse proxy injects it into `POST /v1/chat/completions` and forwards
everything else unchanged:

  * an existing string system message is merged: precontext + blank line +
    the caller's system text;
  * an existing content-part list gets the precontext as its first text part;
  * no system message gets a new first system message.

The proxy is transport only. It carries no key, reads no vault, and adds no
authority: the precontext text is the MASTERSPIKE format + generated fabric
digest baked into the image, and the request still goes to the local model.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.background import BackgroundTask

UPSTREAM = os.environ.get("SPARKNET_LLM_UPSTREAM") or "http://127.0.0.1:8004"
PRECONTEXT_FILE = os.environ.get("SPARKNET_LLM_PRECONTEXT_FILE") or ""


def _load_precontext() -> str:
    if not PRECONTEXT_FILE:
        return ""
    try:
        return Path(PRECONTEXT_FILE).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


PRECONTEXT = _load_precontext()

app = FastAPI(title="sparknet-llm-proxy", docs_url=None, redoc_url=None, openapi_url=None)
client = httpx.AsyncClient(timeout=httpx.Timeout(30.0, read=None), follow_redirects=False)


@app.on_event("shutdown")
async def _shutdown() -> None:
    await client.aclose()


def inject_precontext(payload: dict[str, Any], precontext: str) -> dict[str, Any]:
    """Merge the precontext into the first system message, or prepend one."""
    if not precontext:
        return payload
    messages = payload.get("messages")
    if not isinstance(messages, list):
        return payload
    first = messages[0] if messages else None
    if isinstance(first, dict) and first.get("role") == "system":
        content = first.get("content")
        if isinstance(content, str):
            messages[0] = {**first, "content": precontext + "\n\n" + content}
        elif isinstance(content, list):
            messages[0] = {**first, "content": [{"type": "text", "text": precontext}, *content]}
        else:
            messages.insert(0, {"role": "system", "content": precontext})
    else:
        messages.insert(0, {"role": "system", "content": precontext})
    payload["messages"] = messages
    return payload


def _forward_headers(request: Request) -> dict[str, str]:
    drop = {"host", "content-length", "connection", "transfer-encoding"}
    return {key: value for key, value in request.headers.items() if key.lower() not in drop}


async def _forward(request: Request, body: bytes, path: str) -> StreamingResponse | JSONResponse:
    url = f"{UPSTREAM.rstrip('/')}/{path.lstrip('/')}"
    upstream_request = client.build_request(
        request.method,
        url,
        content=body,
        headers=_forward_headers(request),
        params=request.query_params,
    )
    try:
        response = await client.send(upstream_request, stream=True)
    except httpx.HTTPError as exc:
        return JSONResponse(
            {"error": {"message": f"llama-server unavailable: {exc}", "type": "upstream_unavailable"}},
            status_code=503,
        )
    headers = {
        key: value
        for key, value in response.headers.items()
        if key.lower() not in {"content-length", "transfer-encoding", "connection"}
    }
    return StreamingResponse(
        response.aiter_raw(),
        status_code=response.status_code,
        headers=headers,
        background=BackgroundTask(response.aclose),
    )


@app.post("/v1/chat/completions")
async def chat_completions(request: Request) -> Any:
    body = await request.body()
    if PRECONTEXT:
        try:
            payload = json.loads(body)
        except (TypeError, ValueError):
            payload = None
        if isinstance(payload, dict):
            body = json.dumps(inject_precontext(payload, PRECONTEXT), ensure_ascii=False).encode("utf-8")
    return await _forward(request, body, "v1/chat/completions")


@app.api_route(
    "/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
)
async def proxy(path: str, request: Request) -> Any:
    return await _forward(request, await request.body(), path)
