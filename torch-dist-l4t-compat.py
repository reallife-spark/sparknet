"""Single-rank torch.distributed semantics for NVIDIA L4T wheels.

NVIDIA's L4T r35 pytorch wheels (2.0.0a0+nv23.02) are built without
USE_DISTRIBUTED: ``torch.distributed.is_available()`` is False and the
callable API (``is_initialized``, ``init_process_group``, ``all_reduce``,
``get_world_size`` …) is simply absent. vLLM 0.2.7 drives that API
unconditionally — even at tensor-parallel size 1, where every collective
is otherwise a guarded no-op — so on a Xavier the engine dies at worker
init before the first forward.

This file is appended verbatim to ``torch/distributed/__init__.py`` in the
image (see goagx/sparknet.agx.docker). It is inert on any torch build that
does have distributed support. The semantics it provides are exactly the
single-process ones: a world of one, identity collectives, rank 0. It is
never a multi-GPU substitute — tensor parallelism still requires a torch
build with a real backend.
"""

if not is_available():  # noqa: F821 - bound in torch.distributed.__init__
    import threading

    _spark_lock = threading.Lock()
    _spark_initialized = False
    _spark_world_size = 1
    _spark_rank = 0

    def is_initialized():
        return _spark_initialized

    def init_process_group(backend=None, init_method=None, world_size=-1, rank=-1, **kwargs):
        global _spark_initialized, _spark_world_size, _spark_rank
        with _spark_lock:
            if _spark_initialized:
                raise RuntimeError("process group already initialized")
            _spark_world_size = int(world_size) if world_size and world_size > 0 else 1
            _spark_rank = int(rank) if rank and rank >= 0 else 0
            _spark_initialized = True

    def destroy_process_group(group=None):
        global _spark_initialized
        with _spark_lock:
            _spark_initialized = False

    def get_world_size(group=None):
        return _spark_world_size

    def get_rank(group=None):
        return _spark_rank

    def get_backend(group=None):
        return "l4t-single-rank"

    def new_group(ranks=None, timeout=None, backend=None, pg_options=None):
        # A world of one has no subgroups; the sentinel keeps vLLM's
        # parallel_state globals non-None so its group-based getters work.
        return object()

    def all_reduce(tensor, op=None, group=None, async_op=False):
        return tensor

    def all_gather_into_tensor(output_tensor, input_tensor, group=None, async_op=False):
        output_tensor[0].copy_(input_tensor)
        return output_tensor

    def gather(tensor, dst=0, group=None, async_op=False):
        return [tensor] if get_rank() == dst else None

    def broadcast(tensor, src=0, group=None, async_op=False):
        return tensor

    def broadcast_object_list(object_list, src=0, group=None):
        return object_list

    def barrier(group=None, device_ids=None):
        return None

    def is_nccl_available():
        return False

    class _ReduceOp:
        SUM = 0
        AVG = 1
        MAX = 2
        MIN = 3
        PRODUCT = 4

    ReduceOp = _ReduceOp()

    class _GroupModule:
        WORLD = None

    group = _GroupModule()

    __all__ = [
        "ReduceOp",
        "all_gather_into_tensor",
        "all_reduce",
        "barrier",
        "broadcast",
        "broadcast_object_list",
        "destroy_process_group",
        "gather",
        "get_backend",
        "get_rank",
        "get_world_size",
        "group",
        "init_process_group",
        "is_initialized",
        "is_nccl_available",
        "new_group",
    ]
