#!/usr/bin/env python3
"""Patch vLLM 0.2.7's model_loader for NVIDIA's L4T torch wheel.

`with torch.device("cuda")` requires torch.device's context-manager protocol,
which NVIDIA's 2.0.0a0+ec3941ad.nv23.02 wheel predates (and torch.device is
an unsubclassable C type, so it cannot be shimmed). The block's only job is
to place the model's empty parameter tensors on the GPU while the module tree
is constructed. The equivalent on this wheel is switching the default tensor
type to the dtype-matched CUDA class around the construction call and
restoring it afterwards. On sm_72 only float16/float32 are reachable (bf16 is
rejected at dtype resolution, before model load), and the outer
_set_default_torch_dtype context owns the default dtype anyway.

Runs inside the image build (see sparknet.agx.docker). The assertion makes it
fail loudly — and the build fail — if the upstream block is not exactly the
shape this patch knows; it never silently rewrites a vLLM we do not
recognize.
"""

import sys
from pathlib import Path

OLD = """        with torch.device("cuda"):
            model = model_class(model_config.hf_config, linear_method)
"""

NEW = """        # [sparknet L4T] torch.device-as-context-manager is missing from the
        # nv23.02 wheel; switch the default tensor type for the construction
        # call instead (same placement semantics for the empty params).
        _spark_dd = torch.get_default_dtype()
        torch.set_default_tensor_type(
            torch.cuda.HalfTensor if _spark_dd == torch.float16
            else torch.cuda.FloatTensor)
        try:
            model = model_class(model_config.hf_config, linear_method)
        finally:
            torch.set_default_tensor_type(torch.FloatTensor)
            torch.set_default_dtype(_spark_dd)
"""

PATH = Path("/usr/local/lib/python3.8/dist-packages/vllm/model_executor/model_loader.py")


def main() -> None:
    src = PATH.read_text()
    n = src.count(OLD)
    if n != 1:
        sys.exit(f"model_loader patch: expected exactly 1 match, found {n}")
    PATH.write_text(src.replace(OLD, NEW))
    print(f"model_loader patched: {PATH}")


if __name__ == "__main__":
    main()
