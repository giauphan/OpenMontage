"""Fast unit tests for the HyperFrames runtime integration.

These tests do NOT invoke the HyperFrames CLI — they verify schema
acceptance, tool contract wiring, and governance routing in video_compose.
Subprocess-based smoke tests live in tests/qa/test_09_hyperframes_compose.py.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from tools.base_tool import ToolResult
from tools.video.hyperframes_compose import HyperFramesCompose
from tools.video.video_compose import VideoCompose
from tests.tools._hyperframes_test_helpers import build_tiny_mp4, make_render_runner


# ------------------------------------------------------------------
# Tool contract
# ------------------------------------------------------------------


def test_hyperframes_tool_identity():
    t = HyperFramesCompose()
    assert t.name == "hyperframes_compose"
    assert t.capability == "video_post"
    assert t.provider == "hyperframes"
    assert "hyperframes" in t.agent_skills
    assert "hyperframes-cli" in t.agent_skills


def test_hyperframes_get_info_reports_runtime():
    info = HyperFramesCompose().get_info()
    assert "hyperframes_runtime" in info
    rc = info["hyperframes_runtime"]
    assert set(rc.keys()) >= {
        "runtime_available",
        "node_major",
        "ffmpeg_available",
        "npx_available",
        "reasons",
    }


def test_hyperframes_layer2_skill_names_correct_package():
    """Regression: skills/core/hyperframes.md must reference `npx hyperframes`."""
    body = (
        Path(__file__).resolve().parent.parent.parent
        / "skills" / "core" / "hyperframes.md"
    ).read_text(encoding="utf-8")
    if "@hyperframes/cli" in body:
        assert (
            "404" in body
            or "NOT" in body
            or "do not" in body.lower()
            or "trap" in body.lower()
        ), (
            "skills/core/hyperframes.md still recommends `@hyperframes/cli` "
            "(the 404-ing monorepo name) without a warning."
        )
    assert "npx hyperframes" in body, (
        "skills/core/hyperframes.md must reference `npx hyperframes`."
    )


def test_animation_proposal_director_has_no_hardcoded_costs_or_keys():
    """Regression: animation/proposal-director.md must not hardcode non-zero dollar costs or API key names."""
    body = (
        Path(__file__).resolve().parent.parent.parent
        / "skills" / "pipelines" / "animation" / "proposal-director.md"
    ).read_text(encoding="utf-8")

    dollar_pattern = re.compile(
        r"\$(?!0(?!\.?\d*[1-9]))"
        r"\d+(?:[.,]\d+)?"
        r"(?:\s*-\s*\$?\d+(?:[.,]\d+)?)?"
    )
    env_var_pattern = re.compile(
        r"\b(FAL_KEY|OPENAI_API_KEY|RUNWAY_API_KEY|KLING_API_KEY|"
        r"REPLICATE_API_TOKEN|ANTHROPIC_API_KEY|GEMINI_API_KEY|"
        r"ELEVENLABS_API_KEY|HEYGEN_API_KEY)\b"
    )
    anti_pattern_markers = [
        "do not hardcode",
        "do not fill in",
        "don't type them from memory",
        "drift between releases",
        "governance regression",
        "if you find yourself typing",
        "read each missing tool",
        "do not fill in a dollar figure",
    ]

    violations: list[tuple[int, str]] = []
    for lineno, line in enumerate(body.splitlines(), start=1):
        if not (dollar_pattern.search(line) or env_var_pattern.search(line)):
            continue
        if any(marker in line.lower() for marker in anti_pattern_markers):
            continue
        if line.strip() in ("```", "```python", "```bash"):
            continue
        violations.append((lineno, line.strip()[:140]))

    if violations:
        formatted = "\n".join(f"  line {n}: {text}" for n, text in violations)
        raise AssertionError(
            f"Hardcoded cost figures or env var names in "
            f"animation/proposal-director.md. Violations:\n{formatted}"
        )
    assert "provider_menu_summary" in body or "estimate_cost" in body


def test_provider_menu_summary_deduplicates_providers_across_buckets():
    """Regression: any-available wins over any-unavailable in provider_menu_summary."""
    from tools.tool_registry import registry

    registry.discover()
    s = registry.provider_menu_summary()
    for cap_entry in s["capabilities"]:
        both = set(cap_entry["available_providers"]) & set(
            cap_entry["unavailable_providers"]
        )
        assert not both, (
            f"Capability {cap_entry['capability']!r} lists providers in BOTH "
            f"available and unavailable buckets: {sorted(both)}."
        )


def test_provider_menu_summary_is_cp1252_safe():
    """Regression: provider_menu_summary() scrubs unicode dashes for cp1252 safety."""
    from tools.tool_registry import registry, _scrub_unicode_dashes

    dirty = "one \u2014 two \u2013 three \u2018quoted\u2019"
    clean = _scrub_unicode_dashes(dirty)
    assert "\u2014" not in clean
    assert "\u2013" not in clean
    assert "--" in clean

    registry.discover()
    summary_json = json.dumps(registry.provider_menu_summary())
    assert "\u2014" not in summary_json
    assert "\u2013" not in summary_json
    nested = _scrub_unicode_dashes({"a": ["x \u2014 y", {"b": "c \u2014 d"}]})
    assert "\u2014" not in json.dumps(nested)


def test_install_instructions_reference_correct_npm_package_name():
    """Regression: install_instructions must reference `npx hyperframes`."""
    hint = HyperFramesCompose.install_instructions
    assert "`npx hyperframes" in hint or "npm package: `hyperframes`" in hint
    assert "404" in hint or "@hyperframes/cli" in hint


def test_runtime_check_fails_when_npm_package_unresolvable(monkeypatch):
    """Regression: `_runtime_check()` must include a real npm resolve."""
    monkeypatch.setattr(HyperFramesCompose, "_npm_resolve_cache", None, raising=False)
    monkeypatch.setattr(
        HyperFramesCompose,
        "_resolve_npm_package",
        classmethod(lambda cls: {"error": "npm package `hyperframes` not found (404)"}),
    )
    rc = HyperFramesCompose()._runtime_check()
    assert rc["runtime_available"] is False
    assert any("404" in r for r in rc["reasons"])
    assert rc["npm_resolve_error"] is not None
    assert rc["npm_package"] == "hyperframes"


def test_runtime_check_succeeds_when_npm_resolves(monkeypatch):
    monkeypatch.setattr(HyperFramesCompose, "_npm_resolve_cache", None, raising=False)
    monkeypatch.setattr(
        HyperFramesCompose,
        "_resolve_npm_package",
        classmethod(lambda cls: {"version": "0.4.5"}),
    )
    monkeypatch.setattr(
        HyperFramesCompose,
        "_probe_cli",
        classmethod(lambda cls: {"status": "ok"}),
    )
    rc = HyperFramesCompose()._runtime_check()
    if rc["node_major"] is None or not rc["ffmpeg_available"] or not rc["npx_available"]:
        pytest.skip("Local runtime floor not met on this machine")
    assert rc["runtime_available"] is True
    assert rc["npm_package_version"] == "0.4.5"
    assert rc["reasons"] == []


def test_runtime_check_fails_when_published_cli_crashes(monkeypatch):
    monkeypatch.setattr(
        HyperFramesCompose,
        "_resolve_npm_package",
        classmethod(lambda cls: {"version": "0.7.89"}),
    )
    monkeypatch.setattr(
        HyperFramesCompose,
        "_probe_cli",
        classmethod(
            lambda cls: {
                "error": 'doctor failed: The "file" argument must be of type string'
            }
        ),
    )

    rc = HyperFramesCompose()._runtime_check()

    if rc["node_major"] is None or not rc["ffmpeg_available"] or not rc["npx_available"]:
        pytest.skip("Local runtime floor not met on this machine")
    assert rc["runtime_available"] is False
    assert rc["cli_probe_error"] is not None
    assert any("not executable" in reason for reason in rc["reasons"])


def test_video_compose_render_engines_follow_hyperframes_runtime_check(monkeypatch):
    """Regression: `video_compose.get_info()['render_engines']['hyperframes']` tracks true availability."""
    monkeypatch.setattr(HyperFramesCompose, "_npm_resolve_cache", None, raising=False)
    monkeypatch.setattr(
        HyperFramesCompose,
        "_resolve_npm_package",
        classmethod(lambda cls: {"error": "npm package not found (404)"}),
    )
    info = VideoCompose().get_info()
    assert info["render_engines"]["hyperframes"] is False


def test_provider_menu_summary_returns_expected_shape():
    """Regression: provider_menu_summary shape must be stable."""
    from tools.tool_registry import registry

    registry.discover()
    s = registry.provider_menu_summary()

    assert set(s.keys()) == {
        "composition_runtimes",
        "capabilities",
        "setup_offers",
        "runtime_warnings",
    }
    for engine in ("ffmpeg", "remotion", "hyperframes"):
        assert engine in s["composition_runtimes"]
        assert isinstance(s["composition_runtimes"][engine], bool)

    assert isinstance(s["capabilities"], list)
    assert len(s["capabilities"]) > 0
    for entry in s["capabilities"]:
        assert set(entry.keys()) >= {
            "capability",
            "configured",
            "total",
            "available_providers",
            "unavailable_providers",
        }
        assert entry["configured"] <= entry["total"]

    assert isinstance(s["setup_offers"], list)
    assert isinstance(s["runtime_warnings"], list)


def test_agent_guide_references_provider_menu_summary():
    """Regression: AGENT_GUIDE.md must route agents to provider_menu_summary."""
    root = Path(__file__).resolve().parent.parent.parent
    guide = (root / "AGENT_GUIDE.md").read_text(encoding="utf-8")
    assert "provider_menu_summary" in guide


def test_hyperframes_unknown_operation_returns_error():
    result = HyperFramesCompose().execute({"operation": "bogus"})
    assert not result.success
    assert "Unknown operation" in (result.error or "")


def test_hyperframes_lint_requires_workspace():
    result = HyperFramesCompose().execute({"operation": "lint"})
    assert not result.success
    assert "workspace_path" in (result.error or "")


def test_hyperframes_render_requires_workspace():
    result = HyperFramesCompose().execute({"operation": "render"})
    assert not result.success
    err = (result.error or "").lower()
    assert ("workspace" in err) or ("runtime" in err) or ("hyperframes" in err)


def test_hyperframes_render_resolves_relative_output_path_once(tmp_path, monkeypatch):
    """A successful CLI render must not be reported missing for a relative path."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    tool = HyperFramesCompose()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(tool, "_runtime_check", lambda: {"runtime_available": True})
    monkeypatch.setattr(tool, "_scaffold", lambda inputs: ToolResult(success=True, data={}))
    monkeypatch.setattr(tool, "_lint", lambda inputs: ToolResult(success=True, data={}))
    monkeypatch.setattr(tool, "_validate", lambda inputs: ToolResult(success=True, data={}))
    monkeypatch.setattr(tool, "_run_hf", make_render_runner(b"rendered"))

    result = tool._render(
        {"workspace_path": str(workspace), "output_path": "renders/final.mp4"}
    )

    expected = tmp_path / "renders" / "final.mp4"
    assert result.success, result.error
    assert result.data["output"] == str(expected)
    assert result.artifacts == [str(expected)]


def test_hyperframes_render_blocks_on_lint_failure(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "index.html").write_text("<html></html>", encoding="utf-8")
    (workspace / "hyperframes.json").write_text("{}", encoding="utf-8")
    tool = HyperFramesCompose()
    monkeypatch.setattr(tool, "_runtime_check", lambda: {"runtime_available": True})
    monkeypatch.setattr(tool, "_lint", lambda inputs: ToolResult(success=False, error="bad lint"))
    monkeypatch.setattr(
        tool,
        "_validate",
        lambda inputs: (_ for _ in ()).throw(AssertionError("validate must not run")),
    )
    monkeypatch.setattr(
        tool,
        "_run_hf",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("render must not run")),
    )

    result = tool._render(
        {"workspace_path": str(workspace), "preserve_existing_workspace": True}
    )
    assert result.success is False
    assert "Lint failed" in (result.error or "")


def test_hyperframes_render_preserves_workspace_success(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    index_file = workspace / "index.html"
    index_file.write_text("<html><body>Authored Page</body></html>", encoding="utf-8")
    config_file = workspace / "hyperframes.json"
    config_file.write_text('{"paths": {"blocks": "compositions"}}', encoding="utf-8")

    tool = HyperFramesCompose()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(tool, "_runtime_check", lambda: {"runtime_available": True})
    scaffold_called = False

    def _scaffold_trap(inputs):
        nonlocal scaffold_called
        scaffold_called = True
        return ToolResult(success=True, data={})

    monkeypatch.setattr(tool, "_scaffold", _scaffold_trap)
    monkeypatch.setattr(tool, "_lint", lambda inputs: ToolResult(success=True, data={}))
    monkeypatch.setattr(tool, "_validate", lambda inputs: ToolResult(success=True, data={}))
    monkeypatch.setattr(tool, "_run_hf", make_render_runner(b"rendered"))

    result = tool._render(
        {
            "workspace_path": str(workspace),
            "output_path": "renders/final.mp4",
            "preserve_existing_workspace": True,
        }
    )

    assert result.success, result.error
    assert scaffold_called is False
    assert result.data["steps"]["scaffold"]["skipped"] is True
    assert index_file.read_text(encoding="utf-8") == "<html><body>Authored Page</body></html>"


def test_hyperframes_render_preserves_workspace_fails_when_files_missing(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    tool = HyperFramesCompose()
    monkeypatch.setattr(tool, "_runtime_check", lambda: {"runtime_available": True})

    result = tool._render(
        {"workspace_path": str(workspace), "preserve_existing_workspace": True}
    )

    assert not result.success
    assert "preserve_existing_workspace requires existing workspace files" in (result.error or "")


def test_hyperframes_render_preserves_workspace_fails_on_tampering(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    index_file = workspace / "index.html"
    index_file.write_text("<html><body>Authored Page</body></html>", encoding="utf-8")
    config_file = workspace / "hyperframes.json"
    config_file.write_text('{"paths": {"blocks": "compositions"}}', encoding="utf-8")

    tool = HyperFramesCompose()
    monkeypatch.setattr(tool, "_runtime_check", lambda: {"runtime_available": True})
    monkeypatch.setattr(tool, "_lint", lambda inputs: ToolResult(success=True, data={}))
    monkeypatch.setattr(tool, "_validate", lambda inputs: ToolResult(success=True, data={}))
    monkeypatch.setattr(tool, "_run_hf", make_render_runner(b"rendered", tamper_file=index_file))

    result = tool._render(
        {
            "workspace_path": str(workspace),
            "output_path": "renders/final.mp4",
            "preserve_existing_workspace": True,
        }
    )

    assert not result.success
    assert "modified preserved workspace files" in (result.error or "")


def test_video_compose_forwards_preserve_existing_workspace(tmp_path, monkeypatch):
    captured_inputs = {}

    def mock_hf_execute(self, hf_inputs):
        captured_inputs.update(hf_inputs)
        return ToolResult(success=True, data={"operation": "render", "output": str(tmp_path / "o.mp4")})

    monkeypatch.setattr(VideoCompose, "_hyperframes_available", lambda self: True)
    monkeypatch.setattr("tools.video.hyperframes_compose.HyperFramesCompose.execute", mock_hf_execute)
    monkeypatch.setattr(VideoCompose, "_run_final_review", lambda self, *a, **k: {"status": "pass", "issues_found": []})

    vc = VideoCompose()
    result = vc._render_via_hyperframes(
        inputs={"workspace_path": "/tmp/ws", "preserve_existing_workspace": True},
        edit_decisions={"version": "1.0", "cuts": []},
        asset_manifest={"assets": []},
        resolved_cuts=[],
        output_path=tmp_path / "out.mp4",
        profile=None,
    )
    assert result.success
    assert captured_inputs.get("preserve_existing_workspace") is True


# ------------------------------------------------------------------
# video_compose runtime routing
# ------------------------------------------------------------------


def test_video_compose_reports_hyperframes_engine():
    info = VideoCompose().get_info()
    assert "render_engines" in info
    assert "hyperframes" in info["render_engines"]
    assert "hyperframes_note" in info
    assert "render_runtimes" in info
    assert info["render_engines"] == info["render_runtimes"]


def test_video_compose_governance_note_present():
    info = VideoCompose().get_info()
    assert "runtime_governance" in info
    assert "silent swap" in info["runtime_governance"].lower()


def test_video_compose_rejects_unknown_render_runtime(tmp_path):
    """Governance: an unknown render_runtime must fail, not silently fall back."""
    comp_out = tmp_path / "out.mp4"
    result = VideoCompose().execute(
        {
            "operation": "render",
            "edit_decisions": {
                "version": "1.0",
                "cuts": [{"id": "c1", "source": "nonexistent", "in_seconds": 0, "out_seconds": 3}],
                "render_runtime": "totally-made-up",
                "renderer_family": "explainer-data",
            },
            "asset_manifest": {"assets": []},
            "output_path": str(comp_out),
        }
    )
    assert not result.success
    assert "Unknown render_runtime" in (result.error or "")


def test_video_compose_rejects_missing_render_runtime(tmp_path):
    """Regression: missing render_runtime MUST NOT silently fall back to Remotion."""
    comp_out = tmp_path / "out.mp4"
    result = VideoCompose().execute(
        {
            "operation": "render",
            "edit_decisions": {
                "version": "1.0",
                "cuts": [{"id": "c1", "source": "nonexistent", "in_seconds": 0, "out_seconds": 3}],
                "renderer_family": "explainer-data",
            },
            "asset_manifest": {"assets": []},
            "output_path": str(comp_out),
        }
    )
    assert not result.success
    err = (result.error or "").lower()
    assert "render_runtime" in err
    assert "not set" in err or "must be" in err
    assert "remotion render failed" not in err


def test_schemas_require_render_runtime():
    """Regression: both proposal_packet and edit_decisions schemas must REQUIRE render_runtime."""
    root = Path(__file__).resolve().parent.parent.parent

    ed = json.loads(
        (root / "schemas" / "artifacts" / "edit_decisions.schema.json").read_text(encoding="utf-8")
    )
    assert "render_runtime" in ed["required"]

    pp = json.loads(
        (root / "schemas" / "artifacts" / "proposal_packet.schema.json").read_text(encoding="utf-8")
    )
    pp_prod = pp["properties"]["production_plan"]
    assert "render_runtime" in pp_prod["required"]


def test_runtime_swap_detected_flips_when_proposal_packet_disagrees(tmp_path):
    """Regression: runtime_swap_detected fires when proposal_packet disagrees with edit_decisions."""
    mp4 = build_tiny_mp4(tmp_path / "tiny.mp4")

    edit_decisions = {
        "version": "1.0",
        "render_runtime": "hyperframes",
        "renderer_family": "animation-first",
        "cuts": [{"id": "c1", "source": "x", "in_seconds": 0, "out_seconds": 2}],
    }
    proposal_packet = {"production_plan": {"render_runtime": "remotion"}}

    review = VideoCompose()._run_final_review(mp4, edit_decisions, proposal_packet)
    pp = review["checks"]["promise_preservation"]
    assert pp.get("runtime_swap_detected") is True
    assert "runtime_swap_check" in pp
    assert "detected" in pp["runtime_swap_check"]
    assert any("render_runtime changed" in i for i in pp.get("issues", []))


def test_runtime_swap_detected_stays_false_when_proposal_matches(tmp_path):
    mp4 = build_tiny_mp4(tmp_path / "tiny.mp4")
    edit_decisions = {
        "version": "1.0",
        "render_runtime": "remotion",
        "cuts": [{"id": "c1", "source": "x", "in_seconds": 0, "out_seconds": 2}],
    }
    proposal_packet = {"production_plan": {"render_runtime": "remotion"}}
    review = VideoCompose()._run_final_review(mp4, edit_decisions, proposal_packet)
    pp = review["checks"]["promise_preservation"]
    assert pp.get("runtime_swap_detected", False) is False
    assert "ok" in pp["runtime_swap_check"]


def test_both_runtimes_visible_in_render_engines_when_available():
    """Regression: render_engines dict MUST expose remotion, hyperframes, and ffmpeg."""
    info = VideoCompose().get_info()
    engines = info["render_engines"]
    assert "remotion" in engines
    assert "hyperframes" in engines
    assert "ffmpeg" in engines
    assert "remotion_note" in info
    assert "hyperframes_note" in info
    assert "runtime_governance" in info
    assert "silent" in info["runtime_governance"].lower()
