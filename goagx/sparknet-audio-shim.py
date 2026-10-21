#!/usr/bin/env python3
# ruff: noqa: UP045 — this file runs on python 3.8 (the L4T r35 base), where a
# PEP 604 `X | None` annotation string cannot survive FastAPI's runtime
# annotation evaluation; Optional[...] is the correct spelling here, not a
# stale one.
# sparknet audio shim — OpenAI transcriptions over whisper.cpp.
#
# whisper.cpp's server speaks its own multipart POST /inference; the node's
# audio contract (and what every OpenAI-compatible client sends) is
# POST /v1/audio/transcriptions. This adapter translates one onto the other
# so the AGX node's audio profile keeps the same API surface as the Spark
# node's vLLM audio server — the engine underneath differs, the contract does
# not. Runs from the compute venv (fastapi / uvicorn / httpx), in front of a
# 127.0.0.1 whisper-server started by `spark-entrypoint whisper-asr`.
#
# Field mapping: file / response_format / language / prompt are understood
# (model is accepted and ignored — one baked model per image); anything else
# a client sends is dropped, and whisper's own fallback ladder handles
# temperature. Known engine responses are relayed unchanged, so `text`
# unwraps to a bare string exactly as OpenAI specifies.
from __future__ import annotations

import os
from typing import Optional

import httpx
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import JSONResponse, PlainTextResponse, Response

UPSTREAM = os.environ.get("WHISPER_UPSTREAM", "http://127.0.0.1:8004")
# A transcription may outlast any default client timeout on the A57 cluster;
# whisper is the rate limiter here, not the proxy. Override with
# WHISPER_FORWARD_TIMEOUT (seconds). All four phases are set explicitly:
# httpx rejects a Timeout that mixes named phases with an implicit default,
# and a long write matters just as much as a long read here — the upload is
# one pre-buffered multipart body over a link that may be slow.
FORWARD_TIMEOUT = httpx.Timeout(
    connect=10.0,
    read=float(os.environ.get("WHISPER_FORWARD_TIMEOUT", "1800")),
    write=float(os.environ.get("WHISPER_FORWARD_TIMEOUT", "1800")),
    pool=10.0,
)
# Uploads are read into memory before forwarding (whisper wants one
# multipart body), so bound them: an unbounded read lets any client that
# reaches the docker network exhaust a 16 GB machine. Starlette has already
# spooled the part to disk by the time we see it; this cap is about the
# buffer we build, and answers 413 rather than dying. Override with
# WHISPER_MAX_UPLOAD_BYTES.
MAX_UPLOAD_BYTES = int(os.environ.get("WHISPER_MAX_UPLOAD_BYTES", str(512 * 1024 * 1024)))
_CHUNK = 1024 * 1024

app = FastAPI(title="sparknet audio shim", docs_url=None, redoc_url=None)

# OpenAI response_format -> whisper's format. `text` and `verbose_json` both
# round-trip as whisper's json and are reshaped on the way out; whisper has
# no verbose shape of its own.
_WHISPER_FMT = {
    "json": "json",
    "text": "json",
    "verbose_json": "json",
    "srt": "srt",
    "vtt": "vtt",
}


@app.get("/health")
async def health() -> Response:
    """Liveness: relay whisper's own /health so the compose healthcheck sees
    the engine, not just the shim."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{UPSTREAM}/health")
    except httpx.HTTPError as exc:
        return JSONResponse(status_code=503, content={"error": f"whisper upstream unreachable: {exc}"})
    return Response(
        content=r.content,
        status_code=r.status_code,
        media_type=r.headers.get("content-type", "application/json"),
    )


@app.post("/v1/audio/transcriptions")
async def transcriptions(
    file: UploadFile = File(...),  # noqa: B008 — FastAPI form idiom (Annotated needs typing_extensions on 3.8)
    model: Optional[str] = Form(None),
    response_format: Optional[str] = Form(None),
    language: Optional[str] = Form(None),
    prompt: Optional[str] = Form(None),
) -> Response:
    """One route: OpenAI multipart in, whisper /inference multipart out."""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(_CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_UPLOAD_BYTES:
            return JSONResponse(
                status_code=413,
                content={"error": f"upload exceeds the {MAX_UPLOAD_BYTES}-byte limit (WHISPER_MAX_UPLOAD_BYTES)"},
            )
        chunks.append(chunk)
    data = b"".join(chunks)
    wanted = (response_format or "json").lower()
    fields = {"response_format": _WHISPER_FMT.get(wanted, "json")}
    if language and language.lower() != "auto":
        fields["language"] = language
    else:
        # Absent language and "auto" are the same intent: detect per segment.
        fields["detect_language"] = "true"
    if prompt:
        fields["prompt"] = prompt

    try:
        async with httpx.AsyncClient(timeout=FORWARD_TIMEOUT) as client:
            r = await client.post(
                f"{UPSTREAM}/inference",
                files={
                    "file": (
                        file.filename or "audio",
                        data,
                        file.content_type or "application/octet-stream",
                    )
                },
                data=fields,
            )
    except httpx.HTTPError as exc:
        return JSONResponse(status_code=502, content={"error": f"whisper upstream unreachable: {exc}"})

    if r.status_code >= 400:
        return Response(
            content=r.content,
            status_code=r.status_code,
            media_type=r.headers.get("content-type", "application/json"),
        )
    if wanted == "text":
        try:
            return PlainTextResponse(r.json().get("text", ""))
        except ValueError:
            return PlainTextResponse(r.text)
    return Response(
        content=r.content,
        status_code=r.status_code,
        media_type=r.headers.get("content-type", "application/json"),
    )
