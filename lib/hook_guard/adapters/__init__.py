"""HookGuard runtime adapter registry and factory."""

from __future__ import annotations

from lib.hook_guard.adapters.base import BaseHookAdapter
from lib.hook_guard.adapters.remotion import RemotionHookAdapter
from lib.hook_guard.adapters.ffmpeg import FFmpegHookAdapter
from lib.hook_guard.adapters.hyperframes import HyperFramesHookAdapter

_ADAPTERS: dict[str, BaseHookAdapter] = {
    "remotion": RemotionHookAdapter(),
    "ffmpeg": FFmpegHookAdapter(),
    "hyperframes": HyperFramesHookAdapter(),
}


def get_adapter(render_runtime: str = "remotion") -> BaseHookAdapter:
    """Retrieve the hook adapter for a specific composition render runtime."""
    normalized = render_runtime.lower().strip()
    if normalized not in _ADAPTERS:
        raise ValueError(
            f"Unsupported render runtime for HookGuard: {render_runtime!r}. "
            f"Available: {sorted(_ADAPTERS.keys())}"
        )
    return _ADAPTERS[normalized]


__all__ = [
    "BaseHookAdapter",
    "RemotionHookAdapter",
    "FFmpegHookAdapter",
    "HyperFramesHookAdapter",
    "get_adapter",
]
