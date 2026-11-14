#!/usr/bin/env python3
"""Package a distillation run for an external GPU trainer.

The agx32 L4T r35 trainer image is Python 3.8 / transformers 4.37.2 and cannot
load Qwen3. The supported path is to build this portable bundle on agx32, take
it to an approved external GPU host, train/export there, and return the GGUF to
agx32 for signing and the 8091 upload. The bundle carries training data, not
knowledge; it has no key, no signer socket and no vault.

Usage::

    scripts/sparknet-distill-bundle.py \
      --dataset /mnt/ai/distill/datasets/2ba9274ad65106d9 \
      --out-dir /mnt/ai/distill/bundles
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TRAINER = ROOT / "master-node" / "configs" / "train_lora.py"
DOCKERFILE = ROOT / "master-node" / "configs" / "Dockerfile.distill-external"
ENTRYPOINT = ROOT / "master-node" / "configs" / "distill-external-entrypoint.sh"
EXPORTER = ROOT / "scripts" / "sparknet-distill-export.py"
STUDENT = "Qwen/Qwen3-4B-Instruct-2507"
TEACHER = "qwen3-30b"
MAX_LEN = 16384
LLAMA_CPP_REF = "b9016"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_manifest(dataset: Path) -> dict:
    path = dataset / "manifest.json"
    if not path.is_file():
        raise SystemExit(f"distill-bundle: dataset manifest missing: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit("distill-bundle: dataset manifest is not an object")
    return data


def _readme(dataset_id: str, student: str, teacher: str, max_len: int) -> str:
    return f"""# sparknet distillation bundle

Dataset: `{dataset_id}`
Student: `{student}`
Teacher: `{teacher}`
Sequence length: `{max_len}`

This bundle is training data, not knowledge. It contains no peer key, no
signer socket and no vault. Run it only on the approved external GPU host.

```sh
docker build -f Dockerfile -t sparknet-distill-external .
docker run --rm --gpus all -v "$PWD:/work" sparknet-distill-external
```

The result is `out/student-q4_k_m.gguf`. Return that file plus `out/export.json`
to agx32. On agx32, verify the SHA-256, sign with the peer node key and push:

```sh
scripts/sparknet-distill-import.py \
  --artifact out/student-q4_k_m.gguf \
  --sha256 <sha256-from-export> \
  --run <dataset-or-run-id>
```

Never copy the peer node key to the external host.
"""


def build(
    dataset: Path,
    out_dir: Path,
    *,
    student: str = STUDENT,
    teacher: str = TEACHER,
    max_len: int = MAX_LEN,
    name: str | None = None,
) -> dict:
    if not (dataset / "train.jsonl").is_file():
        raise SystemExit(f"distill-bundle: missing train split: {dataset / 'train.jsonl'}")
    manifest = _read_manifest(dataset)
    dataset_id = str(manifest.get("dataset_id") or dataset.name)
    out_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    archive_name = name or f"sparknet-distill-{dataset_id}-{_now()}.tar.gz"
    if not archive_name.endswith(".tar.gz"):
        archive_name += ".tar.gz"
    archive = out_dir / archive_name

    with tempfile.TemporaryDirectory(prefix="sparknet-distill-bundle-") as temp:
        stage = Path(temp)
        shutil.copy2(TRAINER, stage / "train_lora.py")
        shutil.copy2(DOCKERFILE, stage / "Dockerfile")
        shutil.copy2(ENTRYPOINT, stage / "distill-external-entrypoint.sh")
        shutil.copy2(EXPORTER, stage / "sparknet-distill-export.py")
        shutil.copytree(dataset, stage / "dataset")
        (stage / "README.md").write_text(_readme(dataset_id, student, teacher, max_len), encoding="utf-8")
        files = {}
        for path in sorted(stage.rglob("*")):
            if path.is_file():
                files[str(path.relative_to(stage))] = _sha256(path)
        record = {
            "schema": "sparknet-distill-bundle/1",
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "dataset_id": dataset_id,
            "teacher_model_id": teacher,
            "student_base_model": student,
            "method": "lora-4bit",
            "sequence_length": max_len,
            "max_len": max_len,
            "llama_cpp_ref": LLAMA_CPP_REF,
            "dataset_manifest": manifest,
            "files": files,
            "signing": "return to agx32; never copy the peer key",
        }
        (stage / "manifest.json").write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        with tarfile.open(archive, "w:gz") as tar:
            for path in sorted(stage.rglob("*")):
                tar.add(path, arcname=str(path.relative_to(stage)), recursive=False)
    archive.chmod(0o600)
    return {
        "schema": "sparknet-distill-bundle/1",
        "bundle": str(archive),
        "sha256": _sha256(archive),
        "size": archive.stat().st_size,
        "dataset_id": dataset_id,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="package a distillation dataset for an external GPU trainer")
    parser.add_argument("--dataset", type=Path, required=True, help="dataset directory with train/val/test.jsonl")
    parser.add_argument("--out-dir", type=Path, default=Path("/mnt/ai/distill/bundles"))
    parser.add_argument("--student", default=STUDENT)
    parser.add_argument("--teacher", default=TEACHER)
    parser.add_argument("--max-len", type=int, default=MAX_LEN)
    parser.add_argument("--name", help="archive name (default: sparknet-distill-<dataset>-<utc>.tar.gz)")
    args = parser.parse_args(argv)
    result = build(
        args.dataset,
        args.out_dir,
        student=args.student,
        teacher=args.teacher,
        max_len=args.max_len,
        name=args.name,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
