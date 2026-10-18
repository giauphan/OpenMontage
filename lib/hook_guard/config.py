"""HookGuard configuration and policy loading."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

DEFAULT_CONFIG_PATHS = [
    PROJECT_ROOT / "configs" / "hook_profiles.yaml",
    PROJECT_ROOT / "config" / "hook_profiles.yaml",
]


@dataclass
class SafeZoneConfig:
    top_margin_pct: float = 0.10
    bottom_margin_pct: float = 0.20
    side_margin_pct: float = 0.08


@dataclass
class PlatformProfile:
    name: str
    preferred_visible_within_seconds: float = 3.0
    aspect_ratio: str = "16:9"
    deliver_core_promise_early: bool = True
    safe_zones: SafeZoneConfig = field(default_factory=SafeZoneConfig)


@dataclass
class HookPolicy:
    enabled: bool = False
    mode: str = "off"  # "off", "auto", "required"
    strict_body_edl: bool = True
    default_strategy: str = "overlay_only"  # "overlay_only", "extractive_preroll", "script_native"
    max_candidates: int = 5
    allow_preroll: bool = False
    max_added_duration_seconds: float = 0.0
    allow_generated_tts: bool = False
    allow_claim_rewrite: bool = False
    allow_external_fact_generation: bool = False
    fail_behavior: str = "skip_hook"  # "skip_hook", "block"
    profiles: dict[str, PlatformProfile] = field(default_factory=dict)

    def is_active(self) -> bool:
        """Return True if HookGuard should actively evaluate hooks."""
        if not self.enabled:
            return False
        return self.mode in ("auto", "required")


def _parse_platform_profile(name: str, data: dict[str, Any]) -> PlatformProfile:
    sz_data = data.get("safe_zones", {})
    safe_zones = SafeZoneConfig(
        top_margin_pct=float(sz_data.get("top_margin_pct", 0.10)),
        bottom_margin_pct=float(sz_data.get("bottom_margin_pct", 0.20)),
        side_margin_pct=float(sz_data.get("side_margin_pct", 0.08)),
    )
    return PlatformProfile(
        name=name,
        preferred_visible_within_seconds=float(data.get("preferred_visible_within_seconds", 3.0)),
        aspect_ratio=str(data.get("aspect_ratio", "16:9")),
        deliver_core_promise_early=bool(data.get("deliver_core_promise_early", True)),
        safe_zones=safe_zones,
    )


def load_hook_policy(
    config_path: Optional[Path | str] = None,
    overrides: Optional[dict[str, Any]] = None,
) -> HookPolicy:
    """Load HookGuard policy from config file, environment, and overrides.
    
    Precedence:
      1. Explicit overrides argument
      2. Environment variables:
         - HOOKGUARD_ENABLED (0/1, true/false)
         - HOOKGUARD_MODE (off, auto, required)
         - HOOKGUARD_ALLOW_PREROLL (0/1, true/false)
      3. Configuration file (YAML)
      4. Default: enabled=False, mode="off"
    """
    raw_config: dict[str, Any] = {}

    target_path = Path(config_path) if config_path else None
    if not target_path:
        env_conf = os.environ.get("HOOKGUARD_CONFIG_PATH")
        if env_conf:
            target_path = Path(env_conf)
        else:
            for p in DEFAULT_CONFIG_PATHS:
                if p.is_file():
                    target_path = p
                    break

    if target_path and target_path.is_file():
        try:
            with open(target_path, "r", encoding="utf-8") as f:
                loaded = yaml.safe_load(f)
                if isinstance(loaded, dict):
                    raw_config = loaded.get("hooks", loaded)
        except Exception:
            raw_config = {}

    # Extract profiles
    profiles_dict: dict[str, PlatformProfile] = {}
    for p_name, p_data in raw_config.get("profiles", {}).items():
        if isinstance(p_data, dict):
            profiles_dict[p_name] = _parse_platform_profile(p_name, p_data)

    policy = HookPolicy(
        enabled=bool(raw_config.get("enabled", False)),
        mode=str(raw_config.get("mode", "off")).lower(),
        strict_body_edl=bool(raw_config.get("strict_body_edl", True)),
        default_strategy=str(raw_config.get("default_strategy", "overlay_only")),
        max_candidates=int(raw_config.get("max_candidates", 5)),
        allow_preroll=bool(raw_config.get("allow_preroll", False)),
        max_added_duration_seconds=float(raw_config.get("max_added_duration_seconds", 0.0)),
        allow_generated_tts=bool(raw_config.get("allow_generated_tts", False)),
        allow_claim_rewrite=bool(raw_config.get("allow_claim_rewrite", False)),
        allow_external_fact_generation=bool(raw_config.get("allow_external_fact_generation", False)),
        fail_behavior=str(raw_config.get("fail_behavior", "skip_hook")),
        profiles=profiles_dict,
    )

    # Environment variable overrides
    if "HOOKGUARD_ENABLED" in os.environ:
        val = os.environ["HOOKGUARD_ENABLED"].strip().lower()
        policy.enabled = val in ("1", "true", "yes", "on")

    if "HOOKGUARD_MODE" in os.environ:
        mode_val = os.environ["HOOKGUARD_MODE"].strip().lower()
        if mode_val in ("off", "auto", "required"):
            policy.mode = mode_val

    if "HOOKGUARD_ALLOW_PREROLL" in os.environ:
        val = os.environ["HOOKGUARD_ALLOW_PREROLL"].strip().lower()
        policy.allow_preroll = val in ("1", "true", "yes", "on")

    # Explicit caller overrides
    if overrides:
        for k, v in overrides.items():
            if hasattr(policy, k):
                setattr(policy, k, v)

    # Normalize mode if enabled is false
    if not policy.enabled and policy.mode != "required":
        policy.mode = "off"
    elif policy.enabled and policy.mode == "off":
        policy.mode = "auto"

    return policy
