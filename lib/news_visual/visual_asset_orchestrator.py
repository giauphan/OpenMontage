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

    def _build_beat_context(
        self,
        beat: Dict[str, Any],
        idx: int,
        total_beats: int,
        topic_family: str,
        topic_title: str,
        word_timestamps: Optional[List[Dict[str, Any]]],
    ) -> Dict[str, Any]:
        """Extract and normalize execution context for a single storyboard beat."""
        beat_id = beat.get("beat_id") or beat.get("id", f"vb-{idx+1:02d}")
        fallback_policy = beat.get("fallback_policy", "use_builtin_verified_icon_diagram")
        intent = beat.get("visual_intent", "")
        asset_ids = beat.get("asset_ids") or ([beat.get("asset_id")] if beat.get("asset_id") else [f"asset_{beat_id}"])
        start_s = float(beat.get("start_seconds", 0.0))
        end_s = float(beat.get("end_seconds", 11.0))
        return {
            "beat_id": beat_id,
            "primary_asset_id": asset_ids[0],
            "fallback_policy": fallback_policy,
            "intent": intent,
            "start_s": start_s,
            "end_s": end_s,
            "beat_dur": max(1.0, end_s - start_s),
            "beat_narration": str(beat.get("narration") or intent),
            "beat_num": idx + 1,
            "total_beats": total_beats,
            "topic_family": topic_family,
            "topic_title": topic_title,
            "word_timestamps": word_timestamps,
        }

    def _orchestrate_authentic_capture(
        self,
        project_dir: Path,
        visuals_dir: Path,
        beat: Dict[str, Any],
        ctx: Dict[str, Any],
    ) -> tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
        """Resolve authentic proof capture or contextual SVG fallback."""
        primary_asset_id = ctx["primary_asset_id"]
        capture_path = self._find_authentic_capture(project_dir, beat)
        if capture_path and capture_path.is_file():
            dest_file = visuals_dir / f"{primary_asset_id}{capture_path.suffix}"
            if capture_path != dest_file:
                shutil.copy2(capture_path, dest_file)
            asset = {
                "id": primary_asset_id,
                "file": str(dest_file.relative_to(project_dir)),
                "kind": "authentic_photo",
                "origin": "local_authorized_source",
            }
            res = {
                "status": self.STATUS_READY_CAPTURE,
                "file": str(dest_file),
                "asset_id": primary_asset_id,
            }
            return res, asset

        if ctx["fallback_policy"] == "block" or beat.get("evidence_class") in ("authentic_photo", "approved_source_visual"):
            res = {
                "status": self.STATUS_BLOCKED_MISSING_PROOF,
                "error": f"Proof-bearing beat {ctx['beat_id']} missing authentic capture; release blocked",
                "asset_id": primary_asset_id,
            }
            return res, None

        svg_path = self._get_or_generate_svg(
            visuals_dir,
            primary_asset_id,
            ctx["topic_family"],
            ctx["topic_title"],
            ctx["beat_num"],
            total_beats=ctx["total_beats"],
            duration=ctx["beat_dur"],
            narration=ctx["beat_narration"],
            word_timestamps=ctx["word_timestamps"],
            beat_start_s=ctx["start_s"],
        )
        asset = {
            "id": primary_asset_id,
            "file": str(svg_path.relative_to(project_dir)),
            "kind": "svg_diagram",
            "origin": "deterministic_code",
        }
        res = {
            "status": self.STATUS_FALLBACK_CONTEXTUAL,
            "file": str(svg_path),
            "asset_id": primary_asset_id,
        }
        return res, asset

    def _fallback_to_contextual_svg(
        self,
        project_dir: Path,
        visuals_dir: Path,
        ctx: Dict[str, Any],
        err_msg: Optional[str] = None,
    ) -> tuple[Dict[str, Any], Dict[str, Any]]:
        """Fallback helper producing deterministic contextual SVG when AI or proof is unavailable."""
        primary_asset_id = ctx["primary_asset_id"]
        svg_path = self._get_or_generate_svg(
            visuals_dir,
            primary_asset_id,
            ctx["topic_family"],
            ctx["topic_title"],
            ctx["beat_num"],
            total_beats=ctx["total_beats"],
            cleanup_raster=True,
            duration=ctx["beat_dur"],
            narration=ctx["beat_narration"],
            word_timestamps=ctx["word_timestamps"],
            beat_start_s=ctx["start_s"],
        )
        asset = {
            "id": primary_asset_id,
            "file": str(svg_path.relative_to(project_dir)),
            "kind": "svg_diagram",
            "origin": "deterministic_code",
        }
        res: Dict[str, Any] = {
            "status": self.STATUS_FALLBACK_CONTEXTUAL,
            "file": str(svg_path),
            "asset_id": primary_asset_id,
        }
        if err_msg:
            res["error"] = err_msg
        return res, asset

    def _orchestrate_ai_illustration(
        self,
        project_dir: Path,
        visuals_dir: Path,
        beat: Dict[str, Any],
        ctx: Dict[str, Any],
        ai_visual_enabled: bool,
        ai_images_generated: int,
        max_ai_images: int,
    ) -> tuple[Dict[str, Any], Optional[Dict[str, Any]], bool]:
        """Resolve AI conceptual illustration or fallback to contextual SVG."""
        primary_asset_id = ctx["primary_asset_id"]
        intent = ctx["intent"]
        topic_family = ctx["topic_family"]

        if not (ai_visual_enabled and ai_images_generated < max_ai_images):
            res, asset = self._fallback_to_contextual_svg(project_dir, visuals_dir, ctx)
            return res, asset, False

        prompt = VisualPromptBuilder.build_prompt(topic_family, intent)
        ar = beat.get("aspect_ratio") or ("9:16" if beat.get("visual_kind") == "illustration" else "16:9")
        cache_key = self.cache.compute_cache_key(
            prompt=prompt,
            aspect_ratio=ar,
            provider="muse",
            model="muse-image",
            visual_intent=intent,
            visual_plan_sha256=primary_asset_id,
        )
        cached_img = self.cache.get_cached_asset(cache_key)

        if cached_img:
            dest_file = visuals_dir / f"{primary_asset_id}{cached_img.suffix}"
            shutil.copy2(cached_img, dest_file)
            asset = {
                "id": primary_asset_id,
                "file": str(dest_file.relative_to(project_dir)),
                "kind": "illustration",
                "origin": "ai_generated",
                "cache_hit": True,
            }
            res = {
                "status": self.STATUS_READY_AI,
                "file": str(dest_file),
                "asset_id": primary_asset_id,
                "cache_hit": True,
            }
            return res, asset, True

        temp_dest = visuals_dir / f"{primary_asset_id}.png"
        ai_result = self._dispatch_muse_generation(temp_dest, prompt, cache_key, aspect_ratio=ar)
        if ai_result.get("success"):
            mime = ai_result.get("data", {}).get("mime", "image/png")
            ext_map = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}
            actual_ext = ext_map.get(mime, ".png")
            dest_file = visuals_dir / f"{primary_asset_id}{actual_ext}"
            if temp_dest != dest_file and temp_dest.is_file():
                temp_dest.replace(dest_file)
                ai_result["data"]["output_file"] = str(dest_file)
            self.cache.store_cached_asset(cache_key, dest_file)
            asset = {
                "id": primary_asset_id,
                "file": str(dest_file.relative_to(project_dir)),
                "kind": "illustration",
                "origin": "ai_generated",
                "provenance": ai_result.get("data", {}),
            }
            res = {
                "status": self.STATUS_READY_AI,
                "file": str(dest_file),
                "asset_id": primary_asset_id,
                "cache_hit": False,
            }
            return res, asset, True

        logger.info(
            "AI generation for beat %s failed (%s); falling back to contextual SVG",
            ctx["beat_id"],
            ai_result.get("error"),
        )
        res, asset = self._fallback_to_contextual_svg(project_dir, visuals_dir, ctx, err_msg=ai_result.get("error"))
        return res, asset, False

    def _orchestrate_deterministic_svg(
        self,
        project_dir: Path,
        visuals_dir: Path,
        ctx: Dict[str, Any],
    ) -> tuple[Dict[str, Any], Dict[str, Any]]:
        """Resolve deterministic technical SVG diagram asset."""
        primary_asset_id = ctx["primary_asset_id"]
        svg_path = self._get_or_generate_svg(
            visuals_dir,
            primary_asset_id,
            ctx["topic_family"],
            ctx["topic_title"],
            ctx["beat_num"],
            total_beats=ctx["total_beats"],
            cleanup_raster=False,
            duration=ctx["beat_dur"],
            narration=ctx["beat_narration"],
            word_timestamps=ctx["word_timestamps"],
            beat_start_s=ctx["start_s"],
        )
        asset = {
            "id": primary_asset_id,
            "file": str(svg_path.relative_to(project_dir)),
            "kind": "svg_diagram",
            "origin": "deterministic_code",
        }
        res = {
            "status": self.STATUS_READY_SVG,
            "file": str(svg_path),
            "asset_id": primary_asset_id,
        }
        return res, asset

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
        total_beats = len(beats)
        beat_results: Dict[str, Dict[str, Any]] = {}
        staged_assets: List[Dict[str, Any]] = []

        topic_family = topic.get("topic_family", "context_memory")
        topic_title = topic.get("title", "AI Agent Engineering")

        # Check feature flags
        ai_visual_enabled = os.environ.get("AI_VISUAL_ENABLED", "0") in ("1", "true", "True")
        max_ai_images = int(os.environ.get("AI_VISUAL_MAX_IMAGES_PER_SHORT", "4"))
        ai_images_generated = 0

        # Load word timestamps if available for voice synchronization
        word_timestamps: Optional[List[Dict[str, Any]]] = None
        wt_path = project_dir / "assets" / "word_timestamps.json"
        if wt_path.is_file():
            try:
                wt_data = json.loads(wt_path.read_text(encoding="utf-8"))
                word_timestamps = wt_data.get("word_timestamps")
            except Exception:
                pass

        for idx, beat in enumerate(beats):
            strategy = beat.get("render_strategy")
            if not strategy:
                # Beats without explicit render_strategy keep existing raster/vector assets and are left for resolver
                continue

            ctx = self._build_beat_context(beat, idx, total_beats, topic_family, topic_title, word_timestamps)
            beat_id = ctx["beat_id"]

            if strategy == "authentic_capture":
                res, asset = self._orchestrate_authentic_capture(project_dir, visuals_dir, beat, ctx)
                beat_results[beat_id] = res
                if asset:
                    staged_assets.append(asset)
            elif strategy == "ai_illustration_eligible":
                res, asset, inc = self._orchestrate_ai_illustration(
                    project_dir, visuals_dir, beat, ctx,
                    ai_visual_enabled, ai_images_generated, max_ai_images,
                )
                beat_results[beat_id] = res
                if inc:
                    ai_images_generated += 1
                if asset:
                    staged_assets.append(asset)
            elif strategy == "deterministic_svg":
                res, asset = self._orchestrate_deterministic_svg(project_dir, visuals_dir, ctx)
                beat_results[beat_id] = res
                if asset:
                    staged_assets.append(asset)

        summary = {
            "total_beats": len(beats),
            "ready_capture": sum(1 for r in beat_results.values() if r["status"] == self.STATUS_READY_CAPTURE),
            "ready_svg": sum(1 for r in beat_results.values() if r["status"] == self.STATUS_READY_SVG),
            "ready_ai": sum(1 for r in beat_results.values() if r["status"] == self.STATUS_READY_AI),
            "fallback_contextual": sum(1 for r in beat_results.values() if r["status"] == self.STATUS_FALLBACK_CONTEXTUAL),
            "blocked_missing_proof": sum(1 for r in beat_results.values() if r["status"] == self.STATUS_BLOCKED_MISSING_PROOF),
        }

        out_payload = {
            "project_id": project_dir.name,
            "beat_results": beat_results,
            "assets": staged_assets,
            "summary": summary,
        }
        try:
            orch_file = project_dir / "artifacts" / "orchestrated_assets.json"
            orch_file.parent.mkdir(parents=True, exist_ok=True)
            orch_file.write_text(json.dumps(out_payload, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning(f"Could not persist orchestrated_assets.json: {e}")

        return out_payload

    def _find_authentic_capture(self, project_dir: Path, beat: Dict[str, Any]) -> Optional[Path]:
        """Locate verified screenshot or capture file on disk for authentic proof."""
        candidate_dirs = [
            project_dir / "artifacts" / "news_source_capture",
        ]
        asset_ids = beat.get("asset_ids") or ([beat.get("asset_id")] if beat.get("asset_id") else [])
        beat_id = beat.get("id") or beat.get("beat_id")
        check_ids = list(asset_ids)
        if beat_id and beat_id not in check_ids:
            check_ids.append(beat_id)
        for cid in beat.get("claim_ids", []):
            if cid not in check_ids:
                check_ids.append(cid)

        for cdir in candidate_dirs:
            if not cdir.is_dir():
                continue
            for aid in check_ids:
                for ext in (".png", ".jpg", ".jpeg", ".webp"):
                    target = cdir / f"{aid}{ext}"
                    if target.is_file() and target.stat().st_size > 500:
                        return target
        return None

    def _cleanup_stale_raster(self, visuals_dir: Path, asset_id: str) -> None:
        """Remove any stale raster files when falling back to vector SVG."""
        for ext in (".png", ".jpg", ".jpeg", ".webp"):
            stale = visuals_dir / f"{asset_id}{ext}"
            if stale.is_file():
                try:
                    stale.unlink()
                except OSError:
                    pass

    def _get_or_generate_svg(
        self,
        visuals_dir: Path,
        asset_id: str,
        topic_family: str,
        title: str,
        beat_num: int,
        total_beats: int = 6,
        cleanup_raster: bool = False,
        duration: float = 11.0,
        narration: str = "",
        word_timestamps: Optional[List[Dict[str, Any]]] = None,
        beat_start_s: float = 0.0,
        progressive: bool = True,
    ) -> Path:
        """Return existing non-empty SVG asset if present; otherwise generate technical SVG."""
        if cleanup_raster:
            self._cleanup_stale_raster(visuals_dir, asset_id)
        existing = visuals_dir / f"{asset_id}.svg"
        if existing.is_file() and existing.stat().st_size > 0:
            return existing
        return self._generate_contextual_svg(
            visuals_dir=visuals_dir,
            asset_id=asset_id,
            topic_family=topic_family,
            title=title,
            beat_num=beat_num,
            total_beats=total_beats,
            duration=duration,
            narration=narration,
            word_timestamps=word_timestamps,
            beat_start_s=beat_start_s,
            progressive=progressive,
        )

    def _generate_contextual_svg(
        self,
        visuals_dir: Path,
        asset_id: str,
        topic_family: str,
        title: str,
        beat_num: int,
        total_beats: int = 6,
        duration: float = 11.0,
        narration: str = "",
        word_timestamps: Optional[List[Dict[str, Any]]] = None,
        beat_start_s: float = 0.0,
        progressive: bool = True,
    ) -> Path:
        """Generate high-contrast technical SVG diagram."""
        svg_content = self.storyboard_director.generate_technical_svg(
            asset_id=asset_id,
            topic_family=topic_family,
            title=title,
            beat_num=beat_num,
            total_beats=total_beats,
            duration=duration,
            narration=narration,
            word_timestamps=word_timestamps,
            beat_start_s=beat_start_s,
            progressive=progressive,
        )
        svg_path = visuals_dir / f"{asset_id}.svg"
        svg_path.write_text(svg_content, encoding="utf-8")
        return svg_path

    def _dispatch_muse_generation(self, output_path: Path, prompt: str, submission_key: str, aspect_ratio: str = "9:16") -> Dict[str, Any]:
        """Dispatch image generation using registered muse_gateway_image tool."""
        try:
            registry = ToolRegistry()
            registry.discover()
            if "muse_gateway_image" not in registry._tools:
                return {"success": False, "error": "muse_gateway_image tool not registered"}

            tool_obj = registry._tools["muse_gateway_image"]
            tool_instance = tool_obj() if isinstance(tool_obj, type) else tool_obj
            result = tool_instance.execute({
                "prompt": prompt,
                "aspect_ratio": aspect_ratio,
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
