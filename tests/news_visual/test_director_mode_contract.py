"""T10: Verify prompt and artifact contract alignment across director modes.

Baseline failure (RED):
When NEWS_TEMPLATE_MODE=1, run_daily_news_pipeline.sh still selects director_generate.prompt.md
and director_system.prompt.md (which instruct the director to output script_vi.json and
two raw HTML files). It never instructs the director to produce template_selection.json
and template_content.json, creating a fatal contract mismatch (R13).
"""

from __future__ import annotations

from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_t10_director_prompt_contracts_branch_on_template_mode():
    """Pipeline must provide a dedicated prompt for templated mode requesting typed content."""
    prompt_dir = ROOT / "scripts" / "prompts"
    templated_prompt = prompt_dir / "director_templated_generate.prompt.md"

    # Invariant: A distinct prompt contract must exist for templated mode
    assert templated_prompt.is_file(), (
        "FAIL: scripts/prompts/director_templated_generate.prompt.md does not exist. "
        "Templated mode currently shares the direct HTML generation prompt."
    )
    content = templated_prompt.read_text(encoding="utf-8")
    assert "template_selection.json" in content
    assert "template_content.json" in content


def test_t10_director_generate_prompt_requires_visual_plan_in_visual_mode():
    """In visual enrichment mode, director prompt must mandate visual planning rather than text slides."""
    generate_prompt_path = ROOT / "scripts" / "prompts" / "director_generate.prompt.md"
    content = generate_prompt_path.read_text(encoding="utf-8")

    # Invariant: Prompt must mention visual plan / scene asset binding
    assert "news_visual_plan.json" in content or "visual_intent" in content, (
        "FAIL: scripts/prompts/director_generate.prompt.md mandates glassmorphic text cards "
        "and does not instruct visual planning or asset binding."
    )
