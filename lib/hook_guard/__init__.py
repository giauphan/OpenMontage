"""HookGuard package for OpenMontage.

Provides versioned hook contract, proposal engine, deterministic guard,
and runtime-specific overlay adapters.
"""

from lib.hook_guard.canonical_edl import (
    canonicalize_body_edl,
    compute_body_edl_fingerprint,
    verify_body_edl_preservation,
)
from lib.hook_guard.config import HookPolicy, PlatformProfile, load_hook_policy
from lib.hook_guard.grounding import verify_hook_grounding
from lib.hook_guard.guard import RULE_VERSION, evaluate_hook_guard
from lib.hook_guard.ranking import rank_candidates, score_candidate

__all__ = [
    "canonicalize_body_edl",
    "compute_body_edl_fingerprint",
    "verify_body_edl_preservation",
    "HookPolicy",
    "PlatformProfile",
    "load_hook_policy",
    "verify_hook_grounding",
    "RULE_VERSION",
    "evaluate_hook_guard",
    "score_candidate",
    "rank_candidates",
]
