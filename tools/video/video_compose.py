"""Video composition tool — FFmpeg + Remotion + HyperFrames (runtime-aware).

Pipeline-facing orchestration surface for composition. Takes `edit_decisions`,
`asset_manifest`, and audio, and delegates to the technical runtime chosen
at proposal stage.

Routing is driven by `edit_decisions.render_runtime` (locked at proposal):

- `remotion`   → React-based frame-accurate render via `npx remotion render`.
                 Handles the existing scene-component stack, word-level captions,
                 TalkingHead/CinematicRenderer. Current default.
- `hyperframes` → HTML/CSS/GSAP render via `hyperframes_compose`.
                 Handles kinetic typography, product promos, website-to-video,
                 registry blocks. Added in the parallel-runtime initiative.
- `ffmpeg`     → FFmpeg concat/trim. Used only for simple video cuts without
                 composition, or when the approved path explicitly names FFmpeg.

Authoring mode is orthogonal to runtime. Setting
`edit_decisions.composition_mode = "atelier"` (or `renderer_family="bespoke"`)
means the composition is hand-authored rather than assembled from stock scene
components. Runtime still wins first: HyperFrames atelier routes through
`hyperframes_compose`, FFmpeg stays FFmpeg-only, and only Remotion atelier uses
`_render_via_atelier` for a project-local Remotion entry that bypasses the
cut-schema and stock scene-type registry.

Silent runtime swaps are forbidden by governance. If the chosen runtime is
unavailable or fails, this tool surfaces a structured blocker and waits for
the agent to re-ask the user rather than substituting a different engine.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Optional

from tools.base_tool import (
    BaseTool,
    Determinism,
    ExecutionMode,
    ResourceProfile,
    RetryPolicy,
    ResumeSupport,
    ToolResult,
    ToolStability,
    ToolTier,
)
from tools.video._compose.asset_resolution import (
    IMAGE_EXTENSIONS,
    cuts_to_cinematic_scenes,
    is_image,
    resolve_cuts,
)
from tools.video._compose.atelier import (
    ATELIER_STAGE_EXTS,
    ATELIER_STOCK_IMPORT_RE,
    build_theme_from_playbook,
    render_via_atelier,
    run_atelier_checks,
    stage_atelier_project,
)
from tools.video._compose.ffmpeg_commands import (
    build_atempo,
    build_subtitle_style,
    parse_probe_fps,
    resolve_subtitle_style,
)
from tools.video._compose.ffmpeg_effects import (
    burn_subtitles,
    encode,
    has_audio_stream,
    mux_external_audio,
    overlay,
    probe_video_stream_duration,
)
from tools.video._compose.ffmpeg_render import (
    compose_cuts,
    render_via_ffmpeg,
)
from tools.video._compose.hyperframes_runner import render_via_hyperframes
from tools.video._compose.remotion_runner import (
    REMOTION_COMPONENTS,
    REMOTION_SCENE_TYPES,
    RENDERER_FAMILY_MAP,
    get_composition_id,
    needs_remotion,
    remotion_render,
    stage_remotion_media,
)
from tools.video._compose.review import run_final_review
from tools.video._compose.runtime_policy import (
    check_runtime_availability,
    detect_runtime_swap,
    is_remotion_atelier,
    validate_render_runtime,
)
from tools.video._compose.validation import (
    TTS_PUNCTUATION_LEAK_WORDS,
    compare_transcript_to_script,
    pre_compose_validation,
    read_text_file,
    tokenize_text,
)


class VideoCompose(BaseTool):
    name = "video_compose"
    version = "0.1.0"
    tier = ToolTier.CORE
    capability = "video_post"
    provider = "ffmpeg"
    stability = ToolStability.EXPERIMENTAL
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC

    dependencies = ["cmd:ffmpeg"]
    install_instructions = "Install FFmpeg: https://ffmpeg.org/download.html"
    agent_skills = ["remotion-best-practices", "remotion", "ffmpeg"]

    capabilities = [
        "compose_cuts",
        "burn_subtitles",
        "overlay_assets",
        "encode_profile",
        "remotion_render",
    ]

    input_schema = {
        "type": "object",
        "required": ["operation"],
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["compose", "render", "remotion_render", "burn_subtitles", "overlay", "encode"],
                "description": (
                    "compose: low-level concat cuts + audio + subtitles. "
                    "render: high-level — resolves asset IDs, auto-routes to Remotion "
                    "for images/animations or FFmpeg for video-only. Preferred for compose-director. "
                    "remotion_render: render via Remotion (Node.js). "
                    "burn_subtitles: burn subtitle file into existing video. "
                    "overlay: composite overlays onto base video. "
                    "encode: re-encode to a target profile/codec."
                ),
            },
            "input_path": {
                "type": "string",
                "description": "Input video path (used by burn_subtitles, overlay, encode)",
            },
            "output_path": {
                "type": "string",
                "description": "Output video path (defaults to composed_output.mp4 or operation-specific name)",
            },
            "edit_decisions": {
                "type": "object",
                "description": "Canonical edit_decisions artifact containing cuts, subtitles, audio settings",
            },
            "asset_manifest": {
                "type": "object",
                "description": "Canonical asset_manifest artifact for resolving asset IDs to file paths",
            },
            "proposal_packet": {
                "type": "object",
                "description": (
                    "Canonical proposal_packet (or proposal artifact) from the "
                    "proposal stage. Used to detect silent runtime swaps: its "
                    "production_plan.render_runtime is compared against "
                    "edit_decisions.render_runtime during the final self-review. "
                    "Highly recommended for compose-director calls."
                ),
            },
            "preserve_existing_workspace": {
                "type": "boolean",
                "default": False,
                "description": (
                    "Forwarded to HyperFrames renderer when render_runtime='hyperframes'. "
                    "When True, preserves an existing workspace rather than overwriting."
                ),
            },
            "composition_data": {
                "type": "object",
                "description": "Direct composition data for Remotion (alternative to edit_decisions)",
            },
            "subtitle_path": {
                "type": "string",
                "description": "Path to SRT/VTT subtitle file to burn into video",
            },
            "subtitle_style": {
                "type": "object",
                "description": "ASS subtitle styling overrides",
                "properties": {
                    "font": {"type": "string", "default": "Arial"},
                    "font_size": {"type": "integer", "default": 24},
                    "primary_color": {"type": "string", "default": "&H00FFFFFF"},
                    "outline_color": {"type": "string", "default": "&H00000000"},
                    "outline": {"type": "integer", "default": 2},
                    "alignment": {"type": "integer", "default": 2},
                },
            },
            "overlays": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "asset_path": {"type": "string"},
                        "x": {"type": "number"},
                        "y": {"type": "number"},
                        "width": {"type": "number"},
                        "height": {"type": "number"},
                        "start_seconds": {"type": "number"},
                        "end_seconds": {"type": "number"},
                        "opacity": {"type": "number", "minimum": 0, "maximum": 1},
                    },
                },
            },
            "audio_path": {"type": "string", "description": "Mixed audio to mux into output"},
            "profile": {
                "type": "string",
                "description": (
                    "Media profile name from media_profiles.py "
                    "(e.g. youtube_landscape, tiktok, instagram_reels). "
                    "Applied in render and encode operations."
                ),
            },
            "options": {
                "type": "object",
                "description": "Render options (used by the render operation)",
                "properties": {
                    "subtitle_burn": {"type": "boolean", "default": True},
                    "two_pass_encode": {"type": "boolean", "default": False},
                },
            },
            "codec": {"type": "string", "default": "libx264"},
            "crf": {"type": "integer", "default": 23},
            "preset": {"type": "string", "default": "medium"},
            "remotion_timeout_ms": {
                "type": "integer",
                "description": (
                    "Remotion render timeout in milliseconds, passed through as "
                    "`--timeout` (governs headless-browser setup and delayRender). "
                    "Raise this when the browser is slow to start (e.g. restricted "
                    "networks). The subprocess timeout is widened to match."
                ),
            },
        },
    }

    resource_profile = ResourceProfile(
        cpu_cores=4, ram_mb=2048, vram_mb=0, disk_mb=5000, network_required=False
    )

    # Remotion scene types that trigger React-based rendering
    _REMOTION_COMPONENTS = REMOTION_COMPONENTS
    _REMOTION_SCENE_TYPES = REMOTION_SCENE_TYPES
    RENDERER_FAMILY_MAP = RENDERER_FAMILY_MAP
    _IMAGE_EXTENSIONS = IMAGE_EXTENSIONS
    _ATELIER_STAGE_EXTS = ATELIER_STAGE_EXTS
    _ATELIER_STOCK_IMPORT_RE = ATELIER_STOCK_IMPORT_RE
    _TTS_PUNCTUATION_LEAK_WORDS = TTS_PUNCTUATION_LEAK_WORDS

    best_for = [
        "Final render for explainer and animation pipelines",
        "Image-to-video with spring animations (Remotion)",
        "Animated text cards, stat cards, charts (Remotion)",
        "Complex transitions between scenes (Remotion)",
        "Pure video concat and trim (FFmpeg)",
    ]
    retry_policy = RetryPolicy(max_retries=1, retryable_errors=["Conversion failed"])
    resume_support = ResumeSupport.FROM_START
    idempotency_key_fields = ["operation", "input_path", "edit_decisions"]
    side_effects = ["writes video file to output_path"]
    user_visible_verification = [
        "Play the composed output and verify cuts, subtitles, and overlays",
    ]

    def _remotion_available(self) -> bool:
        """Check if Remotion rendering is available (requires npx + composer project + node_modules)."""
        import shutil as _shutil

        if not _shutil.which("npx"):
            return False
        composer_dir = Path(__file__).resolve().parent.parent.parent / "remotion-composer"
        if not composer_dir.exists() or not (composer_dir / "package.json").exists():
            return False
        if not (composer_dir / "node_modules").exists():
            return False
        return True

    def _ffmpeg_available(self) -> bool:
        """Check if the ffmpeg binary is actually resolvable on PATH."""
        import shutil as _shutil

        return bool(_shutil.which("ffmpeg"))

    def _hyperframes_available(self) -> bool:
        """Check if HyperFrames rendering is available."""
        try:
            from tools.video.hyperframes_compose import HyperFramesCompose
            return bool(HyperFramesCompose()._runtime_check()["runtime_available"])
        except Exception:
            return False

    def get_info(self) -> dict[str, Any]:
        """Extend base get_info to surface all available render runtimes."""
        info = super().get_info()
        ffmpeg_ok = self._ffmpeg_available()
        remotion_ok = self._remotion_available()
        hyperframes_ok = self._hyperframes_available()
        info["render_engines"] = {
            "ffmpeg": ffmpeg_ok,
            "remotion": remotion_ok,
            "hyperframes": hyperframes_ok,
        }
        info["render_runtimes"] = info["render_engines"]

        if remotion_ok:
            info["remotion_components"] = self._REMOTION_COMPONENTS
            info["remotion_note"] = (
                "Remotion is available for React-based rendering. Use it for "
                "image-to-video with spring animations, animated text/stat cards, "
                "charts, callouts, comparisons, and word-level caption burn. "
                "Prefer Remotion over Ken Burns pan-and-zoom for explainer "
                "and motion-graphics pipelines that already use the scene-component stack."
            )
        else:
            composer_dir = Path(__file__).resolve().parent.parent.parent / "remotion-composer"
            if composer_dir.exists() and (composer_dir / "package.json").exists() and not (composer_dir / "node_modules").exists():
                info["remotion_note"] = (
                    "Remotion project exists but node_modules are NOT installed. "
                    "Run 'cd remotion-composer && npm install' to enable Remotion rendering."
                )
            else:
                info["remotion_note"] = (
                    "Remotion is NOT available (needs Node.js/npx + remotion-composer + node_modules)."
                )

        if hyperframes_ok:
            info["hyperframes_note"] = (
                "HyperFrames is available for HTML/CSS/GSAP composition. Use it "
                "for kinetic typography, product promos, launch reels, "
                "website-to-video, and registry-block-driven scenes. Consumed via "
                "'npx hyperframes' (npm package: 'hyperframes'). "
                "Before locking render_runtime='hyperframes' at the proposal stage, "
                "verify the runtime with `hyperframes_compose` operation='doctor' "
                "or `make hyperframes-doctor`. An 'available' flag from the runtime "
                "check means node + ffmpeg + the npm package all resolve; it does "
                "not guarantee a render will succeed on the first specific "
                "composition."
            )
        else:
            info["hyperframes_note"] = (
                "HyperFrames is NOT available. Requires Node.js >= 22, FFmpeg, "
                "npx on PATH, and the 'hyperframes' npm package to be resolvable. "
                "Run `make hyperframes-doctor` to see the specific missing piece, "
                "or call `hyperframes_compose` operation='doctor' directly."
            )

        info["runtime_governance"] = (
            "render_runtime is locked at proposal stage and carried unchanged "
            "through edit_decisions. Silent swaps are forbidden. If the "
            "chosen runtime fails, surface a structured blocker and wait for "
            "user approval before switching."
        )
        return info

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        operation = inputs["operation"]
        start = time.time()

        try:
            if operation == "compose":
                result = self._compose(inputs)
            elif operation == "render":
                result = self._render(inputs)
            elif operation == "remotion_render":
                result = self._remotion_render(inputs)
            elif operation == "burn_subtitles":
                result = self._burn_subtitles(inputs)
            elif operation == "overlay":
                result = self._overlay(inputs)
            elif operation == "encode":
                result = self._encode(inputs)
            else:
                return ToolResult(success=False, error=f"Unknown operation: {operation}")
        except Exception as e:
            return ToolResult(success=False, error=str(e))

        result.duration_seconds = round(time.time() - start, 2)
        return result

    # --- Delegating Methods for Backward Compatibility ---

    @staticmethod
    def _is_image(path: Path) -> bool:
        return is_image(path)

    @staticmethod
    def _has_audio_stream(path: Path) -> bool:
        return has_audio_stream(path)

    def _probe_video_stream_duration(self, video_path: Path) -> float:
        return probe_video_stream_duration(video_path)

    def _mux_external_audio(self, video_path: Path, audio_path: str | Path) -> ToolResult:
        return mux_external_audio(self, video_path, audio_path)

    def _compose(self, inputs: dict[str, Any]) -> ToolResult:
        return compose_cuts(self, inputs)

    @classmethod
    def _get_composition_id(cls, renderer_family: str) -> str:
        return get_composition_id(renderer_family)

    @staticmethod
    def _cuts_to_cinematic_scenes(cuts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return cuts_to_cinematic_scenes(cuts)

    @staticmethod
    def _stage_remotion_media(value: Any, public_dir: Path) -> int:
        return stage_remotion_media(value, public_dir)

    def _render_via_atelier(
        self,
        inputs: dict[str, Any],
        edit_decisions: dict[str, Any],
    ) -> ToolResult:
        return render_via_atelier(self, inputs, edit_decisions)

    def _stage_atelier_project(self, entry_path: Path, composer_dir: Path) -> Path:
        return stage_atelier_project(entry_path, composer_dir)

    def _run_atelier_checks(self, entry_path: Path, bespoke: dict[str, Any]) -> dict[str, Any]:
        return run_atelier_checks(entry_path, bespoke)

    @staticmethod
    def _build_theme_from_playbook(
        playbook_name: str | None,
        composition_data: dict | None,
    ) -> dict[str, Any] | None:
        return build_theme_from_playbook(playbook_name, composition_data)

    def _needs_remotion(self, cuts: list[dict]) -> bool:
        return needs_remotion(self._remotion_available(), cuts, self._IMAGE_EXTENSIONS, self._REMOTION_SCENE_TYPES)

    @staticmethod
    def _pre_compose_validation(
        edit_decisions: dict,
        resolved_cuts: list[dict],
        scene_plan: dict | None = None,
        asset_manifest: dict | None = None,
    ) -> ToolResult | None:
        return pre_compose_validation(
            edit_decisions, resolved_cuts, scene_plan, asset_manifest
        )

    def _render(self, inputs: dict[str, Any]) -> ToolResult:
        """High-level render: assemble edit decisions + asset manifest into final video."""
        edit_decisions = inputs.get("edit_decisions")
        asset_manifest = inputs.get("asset_manifest")
        if not edit_decisions:
            return ToolResult(success=False, error="edit_decisions required for render")

        is_valid_rt, rt_err = validate_render_runtime(edit_decisions)
        if not is_valid_rt:
            return ToolResult(success=False, error=rt_err)

        render_runtime = edit_decisions["render_runtime"].strip().lower()

        if is_remotion_atelier(edit_decisions, render_runtime):
            return self._render_via_atelier(inputs, edit_decisions)

        if not asset_manifest:
            return ToolResult(success=False, error="asset_manifest required for render")

        output_path = Path(inputs.get("output_path", "renders/output.mp4"))
        output_path.parent.mkdir(parents=True, exist_ok=True)

        cuts = edit_decisions.get("cuts", [])
        if not cuts:
            return ToolResult(success=False, error="No cuts in edit_decisions")

        resolved_cuts = resolve_cuts(cuts, asset_manifest)

        scene_plan = inputs.get("scene_plan")
        validation_block = self._pre_compose_validation(
            edit_decisions, resolved_cuts, scene_plan, asset_manifest
        )
        if validation_block is not None:
            return validation_block

        profile = inputs.get("profile") or inputs.get("output_profile")

        if render_runtime == "hyperframes":
            return self._render_via_hyperframes(
                inputs=inputs,
                edit_decisions=edit_decisions,
                asset_manifest=asset_manifest,
                resolved_cuts=resolved_cuts,
                output_path=output_path,
                profile=profile,
            )
        if render_runtime == "ffmpeg":
            return self._render_via_ffmpeg(
                inputs=inputs,
                edit_decisions=edit_decisions,
                resolved_cuts=resolved_cuts,
                output_path=output_path,
                profile=profile,
            )

        if self._needs_remotion(resolved_cuts):
            remotion_inputs: dict[str, Any] = {
                "edit_decisions": dict(edit_decisions, cuts=resolved_cuts),
                "output_path": str(output_path),
            }
            if profile:
                remotion_inputs["profile"] = profile
            if inputs.get("remotion_timeout_ms") is not None:
                remotion_inputs["remotion_timeout_ms"] = inputs["remotion_timeout_ms"]
            if inputs.get("public_dir") is not None:
                remotion_inputs["public_dir"] = inputs["public_dir"]
            render_result = self._remotion_render(remotion_inputs)

            if not render_result.success:
                renderer_family = edit_decisions.get("renderer_family", "unknown")
                return ToolResult(
                    success=False,
                    error=(
                        f"Remotion render failed for renderer_family={renderer_family!r}. "
                        f"Underlying error: {render_result.error}\n\n"
                        f"This composition requires Remotion (images, text cards, animations). "
                        f"Options:\n"
                        f"  1. Fix Remotion setup (cd remotion-composer && npm install)\n"
                        f"  2. Re-run with operation='compose' for FFmpeg-only (video cuts only)\n"
                        f"  3. Approve a degraded FFmpeg render (still images → Ken Burns)\n\n"
                        f"Per governance: renderer downgrade requires user approval."
                    ),
                )
            if inputs.get("audio_path"):
                mux_result = self._mux_external_audio(output_path, inputs["audio_path"])
                if not mux_result.success:
                    return mux_result
                render_result.data["has_mixed_audio"] = True
        else:
            options = inputs.get("options", {})
            subtitle_burn = options.get("subtitle_burn", True)

            subtitle_path = inputs.get("subtitle_path")
            if subtitle_burn and not subtitle_path:
                ed_subs = edit_decisions.get("subtitles", {})
                if ed_subs.get("enabled") and ed_subs.get("source"):
                    subtitle_path = ed_subs["source"]

            compose_inputs = dict(inputs)
            compose_inputs["edit_decisions"] = dict(edit_decisions, cuts=resolved_cuts)
            compose_inputs["output_path"] = str(output_path)
            if subtitle_path:
                compose_inputs["subtitle_path"] = subtitle_path
            if profile:
                compose_inputs["profile"] = profile

            render_result = self._compose(compose_inputs)

        if render_result.success and output_path.exists():
            final_review = self._run_final_review(
                output_path,
                edit_decisions,
                inputs.get("proposal_packet"),
                narration_transcript_path=inputs.get("narration_transcript_path"),
                script_text=inputs.get("script_text") or self._read_text_file(
                    inputs.get("script_path")
                ),
            )

            if render_result.data is None:
                render_result.data = {}
            render_result.data["final_review"] = final_review
            render_result.data["final_review_status"] = final_review["status"]

            if final_review["status"] == "fail":
                return ToolResult(
                    success=False,
                    error=(
                        "Post-render self-review FAILED. The output is not presentable.\n"
                        + "\n".join(f"  • {i}" for i in final_review.get("issues_found", []))
                    ),
                    data=render_result.data,
                )

        return render_result

    def _render_via_hyperframes(
        self,
        *,
        inputs: dict[str, Any],
        edit_decisions: dict[str, Any],
        asset_manifest: dict[str, Any],
        resolved_cuts: list[dict],
        output_path: Path,
        profile: Optional[str],
    ) -> ToolResult:
        return render_via_hyperframes(
            self,
            inputs=inputs,
            edit_decisions=edit_decisions,
            asset_manifest=asset_manifest,
            resolved_cuts=resolved_cuts,
            output_path=output_path,
            profile=profile,
        )

    def _render_via_ffmpeg(
        self,
        *,
        inputs: dict[str, Any],
        edit_decisions: dict[str, Any],
        resolved_cuts: list[dict],
        output_path: Path,
        profile: Optional[str],
    ) -> ToolResult:
        return render_via_ffmpeg(
            self,
            inputs=inputs,
            edit_decisions=edit_decisions,
            resolved_cuts=resolved_cuts,
            output_path=output_path,
            profile=profile,
        )

    def _remotion_render(self, inputs: dict[str, Any]) -> ToolResult:
        return remotion_render(self, inputs)

    @staticmethod
    def _read_text_file(path: str | Path | None) -> str | None:
        return read_text_file(path)

    @classmethod
    def _tokenize(cls, text: str) -> list[str]:
        return tokenize_text(text)

    @classmethod
    def _compare_transcript_to_script(
        cls,
        transcript_path: Path | None,
        script_text: str,
    ) -> dict[str, Any]:
        return compare_transcript_to_script(transcript_path, script_text)

    def _run_final_review(
        self,
        output_path: Path,
        edit_decisions: dict[str, Any] | None = None,
        proposal_packet: dict[str, Any] | None = None,
        narration_transcript_path: str | Path | None = None,
        script_text: str | None = None,
    ) -> dict[str, Any]:
        return run_final_review(
            output_path=output_path,
            edit_decisions=edit_decisions,
            proposal_packet=proposal_packet,
            narration_transcript_path=narration_transcript_path,
            script_text=script_text,
        )

    @staticmethod
    def _parse_probe_fps(fps_str: str) -> float:
        return parse_probe_fps(fps_str)

    def _burn_subtitles(self, inputs: dict[str, Any]) -> ToolResult:
        return burn_subtitles(self, inputs)

    def _overlay(self, inputs: dict[str, Any]) -> ToolResult:
        return overlay(self, inputs)

    def _encode(self, inputs: dict[str, Any]) -> ToolResult:
        return encode(self, inputs)

    @staticmethod
    def _resolve_subtitle_style(
        explicit_style: dict | None,
        edit_decisions: dict | None,
        playbook: dict | None,
    ) -> dict:
        return resolve_subtitle_style(explicit_style, edit_decisions, playbook)

    @staticmethod
    def _build_subtitle_style(style: dict) -> str:
        return build_subtitle_style(style)

    @staticmethod
    def _build_atempo(factor: float) -> str:
        return build_atempo(factor)
