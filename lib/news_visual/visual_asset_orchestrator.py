"""Visual Asset Orchestrator for claim-grounded and AI illustration production.

Coordinates asset staging per beat using ImageSelector / MuseGatewayImage,
durable caching, and strict proof vs conceptual fallback semantics.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from lib.fixed_niche.storyboard import FixedNicheStoryboardDirector
from lib.news_visual.asset_cache import VisualAssetCache
from lib.news_visual.visual_prompt_builder import VisualPromptBuilder
from tools.tool_registry import ToolRegistry

logger = logging.getLogger(__name__)


class VisualAssetOrchestrator:
    """Orchestrates asset resolution per beat, enforcing proof integrity."""

    STATUS_READY_CAPTURE: str = "READY_CAPTURE"
    STATUS_READY_SVG: str = "READY_SVG"
    STATUS_READY_AI: str = "READY_AI"
    STATUS_FALLBACK_CONTEXTUAL: str = "FALLBACK_CONTEXTUAL"
    STATUS_BLOCKED_MISSING_PROOF: str = "BLOCKED_MISSING_PROOF"
    STATUS_FAILED_PROVIDER: str = "FAILED_PROVIDER"

    def __init__(self, cache: Optional[VisualAssetCache] = None):
        self.cache = cache or VisualAssetCache()
        self.storyboard_director = FixedNicheStoryboardDirector()

    def orchestrate_plan_assets(
        self,
        project_dir: Path,
        plan: Dict[str, Any],
        topic: Dict[str, Any],
        claim_ledger: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Resolve and stage assets for all beats in the visual plan."""
        project_dir = Path(project_dir)
        visuals_dir = project_dir / "assets" / "visuals"
        visuals_dir.mkdir(parents=True, exist_ok=True)

        beats = plan.get("beats", [])
        beat_results: Dict[str, Dict[str, Any]] = {}
        staged_assets: List[Dict[str, Any]] = []

        topic_family = topic.get("topic_family", "context_memory")
        topic_title = topic.get("title", "AI Agent Engineering")
        plan_sha = hashlib.sha256(json.dumps(plan, sort_keys=True).encode("utf-8")).hexdigest()

        # Check feature flags
        ai_visual_enabled = os.environ.get("AI_VISUAL_ENABLED", "0") in ("1", "true", "True")
        max_ai_images = int(os.environ.get("AI_VISUAL_MAX_IMAGES_PER_SHORT", "4"))
        ai_images_generated = 0

        for idx, beat in enumerate(beats):
            beat_id = beat.get("beat_id") or beat.get("id", f"vb-{idx+1:02d}")
            strategy = beat.get("render_strategy", "deterministic_svg")
            fallback_policy = beat.get("fallback_policy", "use_builtin_verified_icon_diagram")
            intent = beat.get("visual_intent", "")
            asset_ids = beat.get("asset_ids") or ([beat.get("asset_id")] if beat.get("asset_id") else [f"asset_{beat_id}"])
            primary_asset_id = asset_ids[0]

            # 1. Strategy: Authentic Capture (Proof-bearing)
            if strategy == "authentic_capture":
                capture_path = self._find_authentic_capture(project_dir, beat)
                if capture_path and capture_path.is_file():
                    dest_file = visuals_dir / f"{primary_asset_id}{capture_path.suffix}"
                    if capture_path != dest_file:
                        shutil.copy2(capture_path, dest_file)
                    staged_assets.append({
                        "id": primary_asset_id,
                        "file": str(dest_file.relative_to(project_dir)),
                        "kind": "authentic_photo",
                        "origin": "local_authorized_source",
                    })
                    beat_results[beat_id] = {
                        "status": self.STATUS_READY_CAPTURE,
                        "file": str(dest_file),
                        "asset_id": primary_asset_id,
                    }
                else:
                    if fallback_policy == "block" or beat.get("evidence_class") in ("authentic_photo", "approved_source_visual"):
                        beat_results[beat_id] = {
                            "status": self.STATUS_BLOCKED_MISSING_PROOF,
                            "error": f"Proof-bearing beat {beat_id} missing authentic capture; release blocked",
                            "asset_id": primary_asset_id,
                        }
                    else:
                        svg_path = self._generate_contextual_svg(visuals_dir, primary_asset_id, topic_family, topic_title, idx + 1)
                        staged_assets.append({
                            "id": primary_asset_id,
                            "file": str(svg_path.relative_to(project_dir)),
                            "kind": "svg_diagram",
                            "origin": "deterministic_code",
                        })
                        beat_results[beat_id] = {
                            "status": self.STATUS_FALLBACK_CONTEXTUAL,
                            "file": str(svg_path),
                            "asset_id": primary_asset_id,
                        }

            # 2. Strategy: AI Illustration (Conceptual Non-Proof)
            elif strategy == "ai_illustration_eligible":
                if ai_visual_enabled and ai_images_generated < max_ai_images:
                    prompt = VisualPromptBuilder.build_prompt(topic_family, intent)
                    cache_key = self.cache.compute_cache_key(
                        prompt=prompt,
                        aspect_ratio="9:16",
                        provider="muse",
                        model="muse-image",
                        visual_intent=intent,
                        visual_plan_sha256=plan_sha,
                    )
                    cached_img = self.cache.get_cached_asset(cache_key)
                    dest_file = visuals_dir / f"{primary_asset_id}.png"

                    if cached_img:
                        shutil.copy2(cached_img, dest_file)
                        staged_assets.append({
                            "id": primary_asset_id,
                            "file": str(dest_file.relative_to(project_dir)),
                            "kind": "illustration",
                            "origin": "ai_generated",
                            "cache_hit": True,
                        })
                        beat_results[beat_id] = {
                            "status": self.STATUS_READY_AI,
                            "file": str(dest_file),
                            "asset_id": primary_asset_id,
                            "cache_hit": True,
                        }
                        ai_images_generated += 1
                    else:
                        # Invoke ImageSelector / MuseGatewayImage
                        ai_result = self._dispatch_muse_generation(dest_file, prompt, cache_key)
                        if ai_result.get("success"):
                            self.cache.store_cached_asset(cache_key, dest_file)
                            staged_assets.append({
                                "id": primary_asset_id,
                                "file": str(dest_file.relative_to(project_dir)),
                                "kind": "illustration",
                                "origin": "ai_generated",
                                "provenance": ai_result.get("data", {}),
                            })
                            beat_results[beat_id] = {
                                "status": self.STATUS_READY_AI,
                                "file": str(dest_file),
                                "asset_id": primary_asset_id,
                                "cache_hit": False,
                            }
                            ai_images_generated += 1
                        else:
                            # Non-proof beat fallback to contextual explanatory SVG
                            logger.info(f"AI generation for beat {beat_id} failed ({ai_result.get('error')}); falling back to contextual SVG")
                            svg_path = self._generate_contextual_svg(visuals_dir, primary_asset_id, topic_family, topic_title, idx + 1)
                            staged_assets.append({
                                "id": primary_asset_id,
                                "file": str(svg_path.relative_to(project_dir)),
                                "kind": "svg_diagram",
                                "origin": "deterministic_code",
                            })
                            beat_results[beat_id] = {
                                "status": self.STATUS_FALLBACK_CONTEXTUAL,
                                "file": str(svg_path),
                                "asset_id": primary_asset_id,
                                "error": ai_result.get("error"),
                            }
                else:
                    # AI visual disabled or quota reached: fallback to deterministic contextual SVG
                    svg_path = self._generate_contextual_svg(visuals_dir, primary_asset_id, topic_family, topic_title, idx + 1)
                    staged_assets.append({
                        "id": primary_asset_id,
                        "file": str(svg_path.relative_to(project_dir)),
                        "kind": "svg_diagram",
                        "origin": "deterministic_code",
                    })
                    beat_results[beat_id] = {
                        "status": self.STATUS_FALLBACK_CONTEXTUAL,
                        "file": str(svg_path),
                        "asset_id": primary_asset_id,
                    }

            # 3. Strategy: Deterministic SVG (Default Technical Diagram)
            else:
                svg_path = self._generate_contextual_svg(visuals_dir, primary_asset_id, topic_family, topic_title, idx + 1)
                staged_assets.append({
                    "id": primary_asset_id,
                    "file": str(svg_path.relative_to(project_dir)),
                    "kind": "svg_diagram",
                    "origin": "deterministic_code",
                })
                beat_results[beat_id] = {
                    "status": self.STATUS_READY_SVG,
                    "file": str(svg_path),
                    "asset_id": primary_asset_id,
                }

        summary = {
            "total_beats": len(beats),
            "ready_capture": sum(1 for r in beat_results.values() if r["status"] == self.STATUS_READY_CAPTURE),
            "ready_svg": sum(1 for r in beat_results.values() if r["status"] == self.STATUS_READY_SVG),
            "ready_ai": sum(1 for r in beat_results.values() if r["status"] == self.STATUS_READY_AI),
            "fallback_contextual": sum(1 for r in beat_results.values() if r["status"] == self.STATUS_FALLBACK_CONTEXTUAL),
            "blocked_missing_proof": sum(1 for r in beat_results.values() if r["status"] == self.STATUS_BLOCKED_MISSING_PROOF),
        }

        return {
            "project_id": project_dir.name,
            "beat_results": beat_results,
            "assets": staged_assets,
            "summary": summary,
        }

    def _find_authentic_capture(self, project_dir: Path, beat: Dict[str, Any]) -> Optional[Path]:
        """Locate verified screenshot or capture file on disk."""
        candidate_dirs = [
            project_dir / "artifacts" / "news_source_capture",
            project_dir / "assets" / "visuals",
        ]
        asset_ids = beat.get("asset_ids", [])
        for cdir in candidate_dirs:
            if not cdir.is_dir():
                continue
            for aid in asset_ids:
                for ext in (".png", ".jpg", ".jpeg", ".webp"):
                    target = cdir / f"{aid}{ext}"
                    if target.is_file() and target.stat().st_size > 500:
                        return target
            # Also check any PNG file in capture directory
            if cdir.name == "news_source_capture":
                for cap_file in sorted(cdir.glob("*.png")):
                    if cap_file.stat().st_size > 500:
                        return cap_file
        return None

    def _generate_contextual_svg(
        self, visuals_dir: Path, asset_id: str, topic_family: str, title: str, beat_num: int
    ) -> Path:
        """Generate high-contrast technical SVG diagram."""
        svg_content = self.storyboard_director.generate_technical_svg(
            asset_id=asset_id,
            topic_family=topic_family,
            title=title,
            beat_num=beat_num,
        )
        svg_path = visuals_dir / f"{asset_id}.svg"
        svg_path.write_text(svg_content, encoding="utf-8")
        return svg_path

    def _dispatch_muse_generation(self, output_path: Path, prompt: str, submission_key: str) -> Dict[str, Any]:
        """Dispatch image generation using registered muse_gateway_image tool."""
        try:
            registry = ToolRegistry()
            registry.discover()
            if "muse_gateway_image" not in registry._tools:
                return {"success": False, "error": "muse_gateway_image tool not registered"}

            tool_cls = registry._tools["muse_gateway_image"]
            tool_instance = tool_cls()
            result = tool_instance.execute({
                "prompt": prompt,
                "aspect_ratio": "9:16",
                "model": "muse-image",
                "submission_key": f"om-{submission_key[:32]}",
                "output_path": str(output_path),
            })
            return {
                "success": result.success,
                "error": result.error,
                "data": result.data,
            }
        except Exception as exc:
            return {"success": False, "error": str(exc)}
