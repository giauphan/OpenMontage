"""Tests for Phase 4: Storyboard, claim-to-scene proof map, and meaningful visual assets.
Covers matrix IDs: VISUAL-001, VISUAL-002, VISUAL-003.
"""
from __future__ import annotations

import json
from pathlib import Path
import pytest

from lib.fixed_niche.storyboard import (
    FixedNicheStoryboardDirector,
    MeaningfulVisualError,
    VideoProofMap,
)
from lib.news_visual.asset_resolver import resolve_assets_for_plan


def test_visual_001_resolver_proposes_placeholder_svg_fails_proof_beat(tmp_path: Path):
    """VISUAL-001: resolver in fixed niche mode must FAIL if proof beat would fall back to placeholder SVG."""
    project_dir = tmp_path / "test_proj"
    project_dir.mkdir()
    visuals_dir = project_dir / "assets" / "visuals"
    visuals_dir.mkdir(parents=True)
    artifacts_dir = project_dir / "artifacts"
    artifacts_dir.mkdir(parents=True)

    # A visual plan with a proof-bearing beat (is_proof_bearing=True or evidence_class in authentic_proof/conceptual_diagram)
    plan = {
        "beats": [
            {
                "beat_id": "B01",
                "script_section_id": "S01",
                "asset_id": "missing_diagram",
                "story_function": "architecture_diagram",
                "visual_kind": "svg_diagram",
                "evidence_class": "conceptual_diagram",
                "is_proof_bearing": True,
                "claim_ids": ["C01"],
            }
        ]
    }
    (artifacts_dir / "news_visual_plan.json").write_text(json.dumps(plan))

    # In fixed niche mode (enforce_meaningful_visuals=True), placeholder fallback must raise MeaningfulVisualError!
    with pytest.raises(MeaningfulVisualError) as exc:
        resolve_assets_for_plan(project_dir, plan, enforce_meaningful_visuals=True)
    assert "Placeholder SVG fallback forbidden for proof-bearing beat" in str(exc.value)


def test_storyboard_produces_65_to_75s_six_beat_plan_with_proof_map(tmp_path: Path):
    """Verify storyboard produces ~65–75s 6-beat sequence with 100% claim coverage."""
    director = FixedNicheStoryboardDirector()
    topic = {
        "candidate_id": "cand_01",
        "title": "Why coding agents lose project requirements between sessions",
        "topic_family": "context_memory",
        "viewer_question": "Why can an AI coding agent forget project rules between sessions?",
    }
    claims = [
        {"claim_id": "C001", "statement": "Conversation context disappears on session boundary"},
        {"claim_id": "C002", "statement": "Durable repo files persist but need explicit read instructions"},
        {"claim_id": "C003", "statement": "Verify persistence with new-session checklist test"},
    ]

    project_dir = tmp_path / "project_01"
    storyboard_res = director.generate_storyboard(
        topic=topic,
        claims=claims,
        project_dir=project_dir,
        target_duration=72.0,
    )

    visual_plan = storyboard_res["visual_plan"]
    proof_map = storyboard_res["proof_map"]

    assert 65.0 <= storyboard_res["total_duration"] <= 75.0
    assert len(visual_plan["beats"]) >= 5

    # Check 100% claim coverage in proof map
    all_covered_claims = set()
    for beat in proof_map["beats"]:
        all_covered_claims.update(beat.get("claim_ids", []))
    for c in claims:
        assert c["claim_id"] in all_covered_claims, f"Claim {c['claim_id']} missing from proof map"

    # Verify meaningful SVGs were actually created
    for beat in visual_plan["beats"]:
        asset_id = beat["asset_id"]
        svg_file = project_dir / "assets" / "visuals" / f"{asset_id}.svg"
        assert svg_file.is_file(), f"Expected SVG {svg_file} to exist"
        content = svg_file.read_text(encoding="utf-8")
        # Must NOT be the plain dark placeholder rectangle with giant uppercase story_function
        assert "<rect" in content
        assert "fill=\"#0f172a\"" in content or "svg" in content
        # Check for technical diagram elements: arrows, paths, or boxes
        assert any(elem in content for elem in ("<path", "<line", "<polygon", "<g", "<circle", "marker-end"))


def test_visual_002_blank_frame_fails_qa(tmp_path: Path):
    """VISUAL-002: first frame blank or empty fails sampled frame QA."""
    director = FixedNicheStoryboardDirector()
    # Mock a totally black / blank frame
    blank_frame_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
    frame_path = tmp_path / "frame_00s_hook.png"
    frame_path.write_bytes(blank_frame_bytes)

    is_valid, reason = director.validate_frame_sample(frame_path, min_variance=10.0)
    assert is_valid is False
    assert "blank or corrupt" in reason.lower() or "variance" in reason.lower()


def test_visual_003_bogus_terminal_screenshot_fails_validation(tmp_path: Path):
    """VISUAL-003: bogus terminal screenshot without provenance fails validation."""
    director = FixedNicheStoryboardDirector()
    beat = {
        "beat_id": "B04",
        "visual_kind": "terminal_screenshot",
        "evidence_class": "authentic_proof",
        "asset_id": "fake_terminal",
        "has_demo_provenance": False,
    }
    is_valid, reason = director.validate_beat_asset(beat, project_dir=tmp_path)
    assert is_valid is False
    assert "terminal screenshot requires verified demo provenance" in reason.lower()


def test_storyboard_validations_and_distinct_beat_artwork(tmp_path: Path):
    """Ensure storyboard rejects empty claims, rejects invalid duration, and produces distinct artwork."""
    director = FixedNicheStoryboardDirector()
    topic = {"candidate_id": "cand_01", "title": "Test Title", "topic_family": "context_memory"}

    # 1. Reject empty claims
    with pytest.raises(ValueError, match="claims list is empty"):
        director.generate_storyboard(topic, [], tmp_path / "p1", target_duration=70.0)

    # 2. Reject duration outside 65-75s
    claims = [{"claim_id": "C01", "statement": "Test claim"}]
    with pytest.raises(ValueError, match="target_duration"):
        director.generate_storyboard(topic, claims, tmp_path / "p2", target_duration=55.0)

    # 3. All 6 beats produce distinct SVGs and single claim does not duplicate in B04
    res = director.generate_storyboard(topic, claims, tmp_path / "p3", target_duration=72.0)
    svg_contents = [
        (tmp_path / "p3" / "assets" / "visuals" / f"{b['asset_id']}.svg").read_text()
        for b in res["visual_plan"]["beats"]
    ]
    assert len(svg_contents) == 6
    assert len(set(svg_contents)) == 6, "Every beat must generate distinct artwork matching its screen state"
    assert res["visual_plan"]["beats"][3]["claim_ids"] == ["C01"]

    # 4. Multi-claim coverage (4+ claims are all preserved in proof map)
    multi_claims = [{"claim_id": f"C0{i}", "statement": f"Claim {i}"} for i in range(1, 6)]
    res_multi = director.generate_storyboard(topic, multi_claims, tmp_path / "p4", target_duration=70.0)
    covered = set()
    for beat in res_multi["proof_map"]["beats"]:
        covered.update(beat["claim_ids"])
    assert covered == {"C01", "C02", "C03", "C04", "C05"}, "All surplus claims must be retained in proof map"


def test_storyboard_handles_entire_65_to_75s_contract_without_exceeding_12s_hold(tmp_path: Path):
    """Ensure storyboard handles boundary durations across [65.0, 75.0] without any hold exceeding 12.0s."""
    director = FixedNicheStoryboardDirector()
    topic = {"candidate_id": "cand_01", "title": "Test Title", "topic_family": "context_memory"}
    claims = [{"claim_id": "C01", "statement": "Test claim"}]

    for duration in [65.0, 70.0, 72.0, 72.02, 74.0, 75.0]:
        p = tmp_path / f"dur_{str(duration).replace('.', '_')}"
        res = director.generate_storyboard(topic, claims, p, target_duration=duration)
        beats = res["visual_plan"]["beats"]
        assert 6 <= len(beats) <= 8
        for i, beat in enumerate(beats):
            hold = round(beat["end_s"] - beat["start_s"], 2)
            assert hold <= 12.0, f"Duration {duration}s produced beat {i+1} with hold {hold}s > 12.0s"


def test_resolver_rejects_fallback_asset_reused_in_proof_bearing_beat(tmp_path: Path):
    """When a non-proof beat triggers a fallback SVG, a later proof beat reusing that asset ID must be rejected."""
    project_dir = tmp_path / "reused_asset_proj"
    project_dir.mkdir()
    visuals_dir = project_dir / "assets" / "visuals"
    visuals_dir.mkdir(parents=True)

    plan = {
        "beats": [
            {
                "beat_id": "B01",
                "script_section_id": "S01",
                "asset_id": "shared_diagram",
                "story_function": "intro_icon",
                "visual_kind": "contextual_icon",
                "evidence_class": "background_context",
                "is_proof_bearing": False,
                "fallback_policy": "use_builtin_verified_icon_diagram",
            },
            {
                "beat_id": "B02",
                "script_section_id": "S02",
                "asset_id": "shared_diagram",
                "story_function": "architecture_diagram",
                "visual_kind": "svg_diagram",
                "evidence_class": "conceptual_diagram",
                "is_proof_bearing": True,
                "claim_ids": ["C01"],
            },
        ]
    }

    with pytest.raises(MeaningfulVisualError) as exc:
        resolve_assets_for_plan(project_dir, plan, enforce_meaningful_visuals=True)
    assert "Placeholder SVG fallback forbidden for proof-bearing beat 'B02'" in str(exc.value)


def test_dynamic_narration_synthesizes_from_topic_evidence(tmp_path: Path):
    """Ensure storyboard incorporates custom topic evidence into narration beats."""
    director = FixedNicheStoryboardDirector()
    topic = {
        "candidate_id": "cand_dyn",
        "title": "Custom Bug Isolation in Multi-Agent Reasoning",
        "topic_family": "debugging_reliability",
        "hook": "Autonomous coding agents loop indefinitely on cyclical import errors, halting delivery.",
        "symptom": "agents cycle through repeated edit attempts on mutual module imports",
        "root_cause": "circular dependency analysis blindness during single-file patch generation",
        "remedy": "topological sort analysis before dispatching agent file modifications",
        "verification_step": "pytest tests/test_cyclic_imports.py --topo-check",
        "key_takeaway": "static dependency boundary validation before executing agent patch pipelines",
    }
    claims = [
        {"claim_id": "C101", "statement": "Mutual import loops freeze multi-turn LLM reasoning"},
        {"claim_id": "C102", "statement": "Topological dependency sort resolves import order deterministically"},
    ]
    res = director.generate_storyboard(topic, claims, tmp_path / "dyn_proj", target_duration=70.0)
    beats = res["visual_plan"]["beats"]

    assert "Autonomous coding agents loop indefinitely on cyclical import errors" in beats[0]["narration"]
    assert "mutual module imports" in beats[1]["narration"]
    assert "circular dependency analysis blindness" in beats[2]["narration"]
    assert "topological sort analysis" in beats[3]["narration"]
    assert "test_cyclic_imports.py" in beats[4]["narration"]
    assert "static dependency boundary validation" in beats[5]["narration"]


