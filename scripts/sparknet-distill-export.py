#!/usr/bin/env python3
"""Merge a 4B LoRA adapter and export a servable GGUF.

Runs inside the distillation image, after ``train_lora.py`` has written the
adapter. The merge is CPU-side (a 4B fp16 model fits the 32 GB peer); the GGUF
conversion and quantization use the `llama.cpp` tools baked into the image.

Usage::

    scripts/sparknet-distill-export.py --adapter adapter --base Qwen/Qwen3-4B-Instruct-2507 \
      --out-dir merged --quant Q4_K_M --sign-key "$KEY" --pubkey "$PUB"

The output is a model artifact for serving/rollback, never knowledge.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

DEFAULT_LLAMA_CPP = Path("/opt/llama.cpp")
DEFAULT_CONVERT = DEFAULT_LLAMA_CPP / "convert_hf_to_gguf.py"
DEFAULT_QUANTIZE = DEFAULT_LLAMA_CPP / "build" / "bin" / "llama-quantize"
SIGNER = Path(__file__).resolve().parent / "sparknet-sign-artifact.py"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run(command: list[str]) -> None:
    completed = subprocess.run(command, check=False)
    if completed.returncode != 0:
        raise SystemExit(f"distill-export: command failed ({completed.returncode}): {' '.join(command)}")


def merge(adapter: Path, base: str, out_dir: Path) -> Path:
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM

    model = AutoModelForCausalLM.from_pretrained(
        base, torch_dtype=torch.float16, device_map="cpu", trust_remote_code=True
    )
    merged = PeftModel.from_pretrained(model, str(adapter)).merge_and_unload()
    merged.save_pretrained(out_dir, safe_serialization=True)
    return out_dir


def export(
    *,
    adapter: Path,
    base: str,
    out_dir: Path,
    quant: str,
    llama_cpp: Path,
    convert: Path,
    quantize: Path,
    sign_key: Path | None,
    pubkey: Path | None,
) -> dict[str, object]:
    if not adapter.is_dir():
        raise SystemExit(f"distill-export: adapter missing: {adapter}")
    out_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    merged_dir = out_dir / "merged"
    merge(adapter, base, merged_dir)
    f16 = out_dir / "student-f16.gguf"
    _run(["python3", str(convert), str(merged_dir), "--outfile", str(f16), "--outtype", "f16"])
    artifact = f16
    if quant and quant.lower() != "none":
        artifact = out_dir / f"student-{quant.lower()}.gguf"
        _run([str(quantize), str(f16), str(artifact), quant])
    artifact.chmod(0o644)
    digest = _sha256(artifact)
    signature = None
    if sign_key is not None and pubkey is not None:
        signature = artifact.with_suffix(artifact.suffix + ".sig")
        _run(
            [
                "python3",
                str(SIGNER),
                "sign",
                "--file",
                str(artifact),
                "--key",
                str(sign_key),
                "--out",
                str(signature),
            ]
        )
    result = {
        "schema": "sparknet-distill-export/1",
        "artifact": str(artifact),
        "sha256": digest,
        "size": artifact.stat().st_size,
        "quant": quant,
        "signature": str(signature) if signature else "",
        "llama_cpp": str(llama_cpp),
    }
    (out_dir / "export.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="merge a LoRA adapter and export GGUF")
    parser.add_argument("--adapter", type=Path, required=True)
    parser.add_argument("--base", default="Qwen/Qwen3-4B-Instruct-2507")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--quant", default="Q4_K_M")
    parser.add_argument("--llama-cpp", type=Path, default=DEFAULT_LLAMA_CPP)
    parser.add_argument("--convert", type=Path, default=DEFAULT_CONVERT)
    parser.add_argument("--quantize", type=Path, default=DEFAULT_QUANTIZE)
    parser.add_argument("--sign-key", type=Path)
    parser.add_argument("--pubkey", type=Path)
    args = parser.parse_args(argv)
    result = export(
        adapter=args.adapter,
        base=args.base,
        out_dir=args.out_dir,
        quant=args.quant,
        llama_cpp=args.llama_cpp,
        convert=args.convert,
        quantize=args.quantize,
        sign_key=args.sign_key,
        pubkey=args.pubkey,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
