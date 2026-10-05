"""W&B AgentLens tracing for OpenMontage pipeline runs.

Uses the ``coreweave`` Python SDK to emit AgentLens spans.
All tracing is strictly optional: no-op when ``coreweave`` is not installed
or ``WANDB_API_KEY`` is not set. The module is safe to import unconditionally.

Hook points
-----------
Called from ``lib/checkpoint.py`` and ``tools/base_tool.py``:

    start_run()              – at pipeline start (``init_project``)
    start_stage(stage)       – at ``write_checkpoint`` status="in_progress"
    end_stage(stage, err)   – at ``write_checkpoint`` status="completed"/"awaiting_human"
    record_tool_start()     – before ``BaseTool.execute`` runs
    record_tool_result()    – after successful tool execution
    record_tool_error()     – after a tool exception
    stop()                  – at process exit / final stage completion

Project routing is controlled by the ``WANDB_AGENTLENS_PROJECT`` env var
(default: ``giauphan/openmontage``) and ``WANDB_API_KEY``.
"""

from __future__ import annotations

import atexit
import json
import logging
import os
import threading
import uuid
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module state (guarded by _lock for thread safety)
# ---------------------------------------------------------------------------
_lock = threading.Lock()
_tracing: Optional[Any] = None       # the coreweave.tracing module
_conversation: Optional[Any] = None  # current Conversation object
_active_turns: dict[str, Any] = {}   # stage name -> Turn object
_initialized = False

_DEFAULT_PROJECT = "giauphan/openmontage"


def _project_name() -> str:
    return os.environ.get("WANDB_AGENTLENS_PROJECT", _DEFAULT_PROJECT)


def _ensure_sdk() -> Optional[Any]:
    """Import and initialize the coreweave tracing module. Returns it or None."""
    global _tracing, _initialized
    if _tracing is not None:
        return _tracing
    api_key = os.environ.get("WANDB_API_KEY")
    if not api_key:
        return None
    try:
        from coreweave.forge.agentlens import tracing
        tracing.init(_project_name(), api_key=api_key, service_name="openmontage")
        _tracing = tracing
        _initialized = True
        return _tracing
    except Exception as exc:
        logger.debug("AgentLens init failed: %s", exc)
        return None


def is_active() -> bool:
    """True when tracing is initialised and a conversation is open."""
    return _tracing is not None and _conversation is not None


# ---------------------------------------------------------------------------
# Conversation lifecycle
# ---------------------------------------------------------------------------

def start_run(project_id: str = "") -> None:
    """Start the AgentLens conversation for this pipeline run.

    Idempotent: calling start_run a second time on the same process is a no-op.
    """
    global _conversation
    t = _ensure_sdk()
    if t is None:
        return
    if _conversation is not None:
        return  # already started
    try:
        with _lock:
            if _conversation is not None:
                return
            _conversation = t.start_conversation(
                agent_name="openmontage-pipeline",
                conversation_id=project_id or str(uuid.uuid4()),
                conversation_name="OpenMontage Pipeline Run",
            )
    except Exception as exc:
        logger.warning("AgentLens start_run failed: %s", exc)


def stop() -> None:
    """End the conversation, flush spans, and shut down the session.

    Safe to call multiple times. Registered with atexit so a normal process
    exit flushes pending spans without requiring an explicit call.
    """
    global _conversation, _tracing, _initialized
    t = _tracing
    if t is None:
        return
    # End any lingering stage turns
    for _stage, turn in list(_active_turns.items()):
        try:
            turn.end()
        except Exception:
            pass
    _active_turns.clear()
    # End conversation
    if _conversation is not None:
        try:
            _conversation.end()
        except Exception as exc:
            logger.debug("AgentLens conversation end failed: %s", exc)
        _conversation = None
    try:
        t.force_flush(5000)
        t.shutdown()
    except Exception as exc:
        logger.debug("AgentLens flush/shutdown failed: %s", exc)
    _initialized = False
    _tracing = None


atexit.register(stop)


# ---------------------------------------------------------------------------
# Stage / turn lifecycle
# ---------------------------------------------------------------------------

def start_stage(stage: str) -> None:
    """Open a turn for the given pipeline stage.

    No-op if the stage already has an active turn (heartbeat re-entry) or if
    no conversation is open.
    """
    t = _tracing
    if t is None or _conversation is None:
        return
    if stage in _active_turns:
        return  # in_progress heartbeat — don't start a second turn
    try:
        with _lock:
            turn = t.start_turn(
                user_message=f"Stage: {stage}",
                agent_name="openmontage-pipeline",
            )
            _active_turns[stage] = turn
    except Exception as exc:
        logger.warning("AgentLens start_stage(%r) failed: %s", stage, exc)


def end_stage(stage: str, error: Optional[str] = None) -> None:
    """Close the turn for a pipeline stage.

    Safe to call multiple times. If the stage has no active turn, no-op.
    """
    if _tracing is None:
        return
    turn = _active_turns.pop(stage, None)
    if turn is None:
        return
    try:
        if error:
            try:
                turn.record_error(RuntimeError(error))
            except Exception:
                pass
        turn.end()
    except Exception as exc:
        logger.debug("AgentLens end_stage(%r) failed: %s", stage, exc)


# ---------------------------------------------------------------------------
# Tool span recording
# ---------------------------------------------------------------------------

def record_tool_start(
    tool_name: str,
    arguments: Optional[dict] = None,
    tool_call_id: str = "",
) -> Optional[Any]:
    """Start a Tool span before a tool executes.

    Returns the Tool object (or None if tracing is not active). The caller
    must pass it back to ``record_tool_result`` or ``record_tool_error``.
    """
    t = _tracing
    if t is None or _conversation is None:
        return None
    call_id = tool_call_id or f"om-{uuid.uuid4().hex[:8]}"
    try:
        args_str = json.dumps(arguments, default=str)[:4000] if arguments else ""
        tool_span = t.start_tool(
            name=tool_name,
            arguments=args_str,
            tool_call_id=call_id,
        )
        return tool_span
    except Exception as exc:
        logger.debug("AgentLens record_tool_start(%r) failed: %s", tool_name, exc)
        return None


def record_tool_result(tool_span: Any, result: Any) -> None:
    """Record a successful tool result and end the Tool span."""
    if tool_span is None:
        return
    try:
        tool_span.result = {
            "success": getattr(result, "success", None),
            "cost_usd": getattr(result, "cost_usd", None),
            "error": getattr(result, "error", None),
        }
        tool_span.end()
    except Exception as exc:
        logger.debug("AgentLens record_tool_result failed: %s", exc)


def record_tool_error(tool_span: Any, error: BaseException) -> None:
    """Record a tool exception and end the Tool span."""
    if tool_span is None:
        return
    try:
        tool_span.record_error(error)
        tool_span.end()
    except Exception as exc:
        logger.debug("AgentLens record_tool_error failed: %s", exc)
