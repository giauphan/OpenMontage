"""HookAnalyzer tool for generating, grounding, and ranking video hook proposals."""

from __future__ import annotations

import re
from typing import Any, Optional

from tools.base_tool import (
    BaseTool,
    Determinism,
    ExecutionMode,
    ResourceProfile,
    ToolResult,
    ToolStability,
    ToolTier,
)
from lib.hook_guard.config import HookPolicy, load_hook_policy
from lib.hook_guard.guard import evaluate_hook_guard
from lib.hook_guard.ranking import rank_candidates


class HookAnalyzer(BaseTool):
    name = "hook_analyzer"
    version = "1.0.0"
    tier = ToolTier.CORE
    capability = "analysis"
    provider = "hookguard"
    stability = ToolStability.PRODUCTION
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC

    dependencies = []
    agent_skills = ["video-understand", "video-edit"]

    input_schema = {
        "type": "object",
        "required": ["project_id", "source"],
        "properties": {
            "project_id": {"type": "string"},
            "source": {
                "type": "object",
                "required": ["kind"],
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": ["existing_video", "script", "brief"],
                    },
                    "source_video_id": {"type": "string"},
                    "baseline_body_edl_sha256": {"type": "string"},
                    "transcript_text": {"type": "string"},
                    "transcript_words": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "word": {"type": "string"},
                                "start": {"type": "number"},
                                "end": {"type": "number"},
                            },
                        },
                    },
                    "script": {"type": ["object", "string"]},
                    "brief": {"type": ["object", "string"]},
                    "data_points": {
                        "type": "array",
                        "items": {"type": "object"},
                    },
                    "external_news": {
                        "type": "array",
                        "items": {"type": "object"},
                    },
                    "scene_boundaries": {
                        "type": "array",
                        "items": {"type": "object"},
                    },
                },
            },
            "platform": {"type": "string", "default": "youtube_shorts"},
            "target_runtime": {
                "type": "string",
                "enum": ["remotion", "hyperframes", "ffmpeg"],
                "default": "remotion",
            },
            "max_candidates": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5},
            "policy": {"type": "object"},
        },
    }

    resource_profile = ResourceProfile(cpu_cores=1, ram_mb=256, vram_mb=0, disk_mb=10)

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        project_id = inputs["project_id"]
        source = inputs["source"]
        platform = inputs.get("platform", "youtube_shorts")
        target_runtime = inputs.get("target_runtime", "remotion")
        max_candidates = inputs.get("max_candidates", 5)

        policy_overrides = inputs.get("policy", {})
        policy = load_hook_policy(overrides=policy_overrides)

        profile = policy.profiles.get(platform)
        window_duration = profile.preferred_visible_within_seconds if profile else 2.5

        # Check if policy is off
        if not policy.enabled or policy.mode == "off":
            skipped_plan = {
                "version": "1.0",
                "status": "SKIPPED",
                "project_id": project_id,
                "policy": {
                    "mode": "off",
                    "preserve_body_edl": policy.strict_body_edl,
                    "allow_preroll": policy.allow_preroll,
                    "max_added_duration_seconds": policy.max_added_duration_seconds,
                    "allow_generated_tts": policy.allow_generated_tts,
                    "allow_claim_rewrite": policy.allow_claim_rewrite,
                    "fail_behavior": policy.fail_behavior,
                },
                "source": {
                    "kind": source.get("kind", "existing_video"),
                    "source_video_id": source.get("source_video_id", "main"),
                    "baseline_body_edl_sha256": source.get("baseline_body_edl_sha256", ""),
                },
                "candidates": [],
                "selected_candidate_id": None,
                "guard_result": {
                    "status": "SKIPPED",
                    "rule_version": "hookguard-1",
                    "reason_codes": ["SKIPPED_POLICY_OFF"],
                },
            }
            return ToolResult(
                success=True,
                data={"hook_plan": skipped_plan},
            )

        # Generate candidates based on content & intent
        raw_candidates = self._generate_candidates(source, window_duration, target_runtime)

        if not raw_candidates:
            skipped_plan = {
                "version": "1.0",
                "status": "SKIPPED",
                "project_id": project_id,
                "policy": {
                    "mode": policy.mode,
                    "preserve_body_edl": policy.strict_body_edl,
                    "allow_preroll": policy.allow_preroll,
                    "max_added_duration_seconds": policy.max_added_duration_seconds,
                    "allow_generated_tts": policy.allow_generated_tts,
                    "allow_claim_rewrite": policy.allow_claim_rewrite,
                    "fail_behavior": policy.fail_behavior,
                },
                "source": {
                    "kind": source.get("kind", "existing_video"),
                    "source_video_id": source.get("source_video_id", "main"),
                    "baseline_body_edl_sha256": source.get("baseline_body_edl_sha256", ""),
                },
                "candidates": [],
                "selected_candidate_id": None,
                "guard_result": {
                    "status": "SKIPPED",
                    "rule_version": "hookguard-1",
                    "reason_codes": ["SKIPPED_NO_VIABLE_CANDIDATES"],
                },
            }
            return ToolResult(
                success=True,
                data={"hook_plan": skipped_plan},
            )

        # Rank candidates
        ranked = rank_candidates(raw_candidates)[:max_candidates]
        selected_cand = ranked[0] if ranked else None

        # Run guard evaluation on selected candidate
        baseline_sha = source.get("baseline_body_edl_sha256", "")
        guard_res = evaluate_hook_guard(
            candidate=selected_cand,
            policy=policy,
            baseline_body_edl_sha256=baseline_sha,
            mutated_edl=None,
            render_runtime=target_runtime,
            source_context={
                "transcript": source.get("transcript_text", ""),
                "script": str(source.get("script", "")),
                "brief": str(source.get("brief", "")),
            },
        )

        overall_status = "SELECTED" if guard_res["status"] == "PASS" else guard_res["status"]

        hook_plan = {
            "version": "1.0",
            "status": overall_status,
            "project_id": project_id,
            "policy": {
                "mode": policy.mode,
                "preserve_body_edl": policy.strict_body_edl,
                "allow_preroll": policy.allow_preroll,
                "max_added_duration_seconds": policy.max_added_duration_seconds,
                "allow_generated_tts": policy.allow_generated_tts,
                "allow_claim_rewrite": policy.allow_claim_rewrite,
                "fail_behavior": policy.fail_behavior,
            },
            "source": {
                "kind": source.get("kind", "existing_video"),
                "source_video_id": source.get("source_video_id", "main"),
                "baseline_body_edl_sha256": baseline_sha,
            },
            "candidates": ranked,
            "selected_candidate_id": selected_cand["id"] if selected_cand else None,
            "guard_result": guard_res,
        }

        return ToolResult(
            success=True,
            data={"hook_plan": hook_plan},
        )

    def _generate_candidates(
        self,
        source: dict[str, Any],
        window_duration: float,
        target_runtime: str,
    ) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        source_id = source.get("source_video_id", "main")
        transcript = str(source.get("transcript_text", ""))
        brief_data = source.get("brief")
        if isinstance(brief_data, str):
            brief_text = brief_data
            topic = "this workflow"
        elif isinstance(brief_data, dict):
            brief_text = str(brief_data)
            topic = brief_data.get("topic") or brief_data.get("title") or "this topic"
        else:
            brief_text = ""
            topic = "this topic"

        cand_idx = 1

        # 1. Topic Question
        q_text = f"What happens when you change {topic}?" if topic != "this topic" else "What actually happens in this workflow?"
        candidates.append({
            "id": f"cand-{cand_idx}",
            "intent": "topic_question",
            "mode": "overlay_text",
            "text": q_text,
            "window": {"start_seconds": 0.0, "end_seconds": window_duration},
            "evidence": [
                {
                    "kind": "transcript" if transcript else "script",
                    "source_id": source_id,
                    "start_seconds": 0.0,
                    "end_seconds": window_duration,
                    "claim": transcript[:100] if transcript else f"Explaining {topic}",
                }
            ],
            "rank_features": {
                "relevance": 0.85,
                "coherence": 0.90,
                "viewer_promise": 0.80,
                "visual_relevance": 0.70,
                "audio_novelty": 0.70,
            },
            "proposed_runtime": target_runtime,
        })
        cand_idx += 1

        # 2. Problem First
        problem_keywords = ["mistake", "error", "problem", "slow", "fail", "hard", "wrong", "trap", "issue"]
        found_problem = None
        if transcript:
            for line in re.split(r"[.!?]", transcript):
                if any(kw in line.lower() for kw in problem_keywords):
                    found_problem = line.strip()
                    break

        if found_problem:
            p_text = f"The biggest mistake: {found_problem[:45]}"
            claim_text = found_problem
        else:
            p_text = f"The common mistake with {topic}"
            claim_text = f"Addressing key problems in {topic}"

        candidates.append({
            "id": f"cand-{cand_idx}",
            "intent": "problem_first",
            "mode": "overlay_text",
            "text": p_text,
            "window": {"start_seconds": 0.0, "end_seconds": window_duration},
            "evidence": [
                {
                    "kind": "transcript" if transcript else "script",
                    "source_id": source_id,
                    "start_seconds": 0.0,
                    "end_seconds": window_duration,
                    "claim": claim_text,
                }
            ],
            "rank_features": {
                "relevance": 0.90,
                "coherence": 0.95,
                "viewer_promise": 0.92,
                "visual_relevance": 0.75,
                "audio_novelty": 0.75,
            },
            "proposed_runtime": target_runtime,
        })
        cand_idx += 1

        # 3. Solution First
        candidates.append({
            "id": f"cand-{cand_idx}",
            "intent": "solution_first",
            "mode": "overlay_text",
            "text": f"How to master {topic} faster",
            "window": {"start_seconds": 0.0, "end_seconds": window_duration},
            "evidence": [
                {
                    "kind": "transcript" if transcript else "script",
                    "source_id": source_id,
                    "start_seconds": 0.0,
                    "end_seconds": window_duration,
                    "claim": f"Techniques and solutions for {topic}",
                }
            ],
            "rank_features": {
                "relevance": 0.88,
                "coherence": 0.92,
                "viewer_promise": 0.86,
                "visual_relevance": 0.70,
                "audio_novelty": 0.70,
            },
            "proposed_runtime": target_runtime,
        })
        cand_idx += 1

        # 4. Surprise Fact (from data_points)
        data_points = source.get("data_points", [])
        if data_points:
            dp = data_points[0]
            dp_claim = dp.get("claim", "")
            if dp_claim:
                candidates.append({
                    "id": f"cand-{cand_idx}",
                    "intent": "surprise_fact",
                    "mode": "overlay_text",
                    "text": f"Surprising stat: {dp_claim}",
                    "window": {"start_seconds": 0.0, "end_seconds": window_duration},
                    "evidence": [
                        {
                            "kind": "transcript" if transcript else "script",
                            "source_id": source_id,
                            "start_seconds": 0.0,
                            "end_seconds": window_duration,
                            "claim": dp_claim,
                            "source_url": dp.get("source_url", ""),
                        }
                    ],
                    "rank_features": {
                        "relevance": 0.92,
                        "coherence": 0.95,
                        "viewer_promise": 0.89,
                        "visual_relevance": 0.80,
                        "audio_novelty": 0.80,
                    },
                    "proposed_runtime": target_runtime,
                })
                cand_idx += 1

        # 5. News First (if external_news provided)
        external_news = source.get("external_news", [])
        if external_news:
            news_item = external_news[0]
            headline = news_item.get("claim") or news_item.get("headline", "")
            if headline and news_item.get("source_url"):
                candidates.append({
                    "id": f"cand-{cand_idx}",
                    "intent": "news_first",
                    "mode": "overlay_text",
                    "text": f"Breaking: {headline[:60]}",
                    "window": {"start_seconds": 0.0, "end_seconds": window_duration},
                    "evidence": [
                        {
                            "kind": "external_source",
                            "source_id": "news_source",
                            "claim": headline,
                            "source_url": news_item.get("source_url"),
                            "publication_date": news_item.get("publication_date", "2026-10-18"),
                            "event_date": news_item.get("event_date", "2026-10-18"),
                        }
                    ],
                    "rank_features": {
                        "relevance": 0.95,
                        "coherence": 0.95,
                        "viewer_promise": 0.95,
                        "visual_relevance": 0.85,
                        "audio_novelty": 0.85,
                    },
                    "proposed_runtime": target_runtime,
                })
                cand_idx += 1

        return candidates
