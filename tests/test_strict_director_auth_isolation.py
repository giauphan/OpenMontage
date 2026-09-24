from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_nested_director_unsets_inherited_model_override():
    script = (ROOT / "scripts" / "run_daily_news_pipeline.sh").read_text(
        encoding="utf-8"
    )
    director_launches = [
        line for line in script.splitlines() if "claude --bare -p" in line
    ]

    assert len(director_launches) == 2
    assert all("-u ANTHROPIC_MODEL" in line for line in director_launches)
