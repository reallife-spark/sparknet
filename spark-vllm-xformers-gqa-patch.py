#!/usr/bin/env python3
"""Patch vLLM 0.2.7's PagedAttention prefill for xformers on sm_72.

NVIDIA's AGX Xavier is compute capability 7.2, for which xformers ships no
FlashAttention kernel. Its cutlass fallback accepts only 3-/4-D BMK/BMHK
inputs, but vLLM 0.2.7's grouped-query-attention branch leaves the query, key
and value tensors in a 5-D [B, S, H_kv, G, K] layout (G = num_heads //
num_kv_heads) and unsqueezes a leading batch axis, which the cutlass path
rejects:

    ValueError: Query/Key/Value should all have BMHK or BMK shape.
      query.shape: torch.Size([1, 8192, 8, 4, 128])

The 5-D layout is only a reshaping convenience: the G query heads mapped to one
KV head all attend that same KV head, which in 4-D BMHK is expressed by
repeating each KV head G times and folding G into the head axis
([B*S, H_kv, G, K] -> [B, S, H_kv * G, K] = [B, S, H, K], since
H = num_kv_heads * num_queries_per_kv). That is numerically identical to what
the broadcast + reshape computes, and it is the layout xformers accepts.

Only the CUDA path is rewritten; the ROCm path keeps the original 5-D form,
whose flash kernel handles it. The patch asserts the exact upstream block
before changing anything, so a vLLM version drift fails the build rather than
silently patching a source tree this patch does not understand.

Runs inside the image build (see sparknet.agx.docker).
"""

import sys
from pathlib import Path

OLD = """            # TODO(woosuk): Too many view operations. Let's try to reduce them
            # in the future for code readability.
            if self.alibi_slopes is None:
                query = query.unsqueeze(0)
                key = key.unsqueeze(0)
                value = value.unsqueeze(0)
            else:
                query = query.unflatten(0, (batch_size, seq_len))
                key = key.unflatten(0, (batch_size, seq_len))
                value = value.unflatten(0, (batch_size, seq_len))

            out = xops.memory_efficient_attention_forward(
                query,
                key,
                value,
                attn_bias=input_metadata.attn_bias,
                p=0.0,
                scale=self.scale,
                op=xops.fmha.MemoryEfficientAttentionFlashAttentionOp[0] if
                (is_hip()) else None,
            )
            output = out.view_as(query)
"""

NEW = """            # TODO(woosuk): Too many view operations. Let's try to reduce them
            # in the future for code readability.
            if self.alibi_slopes is None and not is_hip():
                # [sparknet L4T] sm_72 has no FlashAttention kernel, so the
                # xformers cutlass path serves this prefill — and it accepts
                # only 4-D BMHK, with a leading batch axis of 1 whenever a
                # block-diagonal bias is in play (which it always is here).
                # The query/key/value are [batch*seq, H_kv, G, K] after the GQA
                # reshape above: fold G into the head axis and lift a unit batch
                # axis to [1, batch*seq, H_kv * G, K]. Identical math to the 5-D
                # broadcast the original code relies on.
                query = query.reshape(1, batch_size * seq_len, self.num_heads,
                                      self.head_size)
                key = key.reshape(1, batch_size * seq_len, self.num_heads,
                                  self.head_size)
                value = value.reshape(1, batch_size * seq_len, self.num_heads,
                                      self.head_size)
                out = xops.memory_efficient_attention_forward(
                    query,
                    key,
                    value,
                    attn_bias=input_metadata.attn_bias,
                    p=0.0,
                    scale=self.scale,
                )
                output = out.view_as(query).squeeze(0)
            else:
                if self.alibi_slopes is None:
                    query = query.unsqueeze(0)
                    key = key.unsqueeze(0)
                    value = value.unsqueeze(0)
                else:
                    query = query.unflatten(0, (batch_size, seq_len))
                    key = key.unflatten(0, (batch_size, seq_len))
                    value = value.unflatten(0, (batch_size, seq_len))

                out = xops.memory_efficient_attention_forward(
                    query,
                    key,
                    value,
                    attn_bias=input_metadata.attn_bias,
                    p=0.0,
                    scale=self.scale,
                    op=xops.fmha.MemoryEfficientAttentionFlashAttentionOp[0] if
                    (is_hip()) else None,
                )
                output = out.view_as(query)
"""

PATH = Path("/usr/local/lib/python3.8/dist-packages/vllm/model_executor/layers/attention.py")


def main() -> None:
    src = PATH.read_text()
    n = src.count(OLD)
    if n != 1:
        sys.exit(f"attention patch: expected exactly 1 match, found {n}")
    PATH.write_text(src.replace(OLD, NEW))
    print(f"attention patched: {PATH}")


if __name__ == "__main__":
    main()
