from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HARNESS = ROOT / "scripts" / "verify_hyperframes_seek.cjs"


def test_cli_usage_string_has_no_nested_backtick_delimiters():
    source = HARNESS.read_text(encoding="utf-8")
    usage = source[source.index("function usage()") : source.index("\nfunction fail(")]

    assert "`--root`" not in usage
    assert "--root is relative" in usage


def test_expected_scene_must_exist_and_be_the_only_visible_scene():
    source = HARNESS.read_text(encoding="utf-8")

    assert "if (!expectedNode) throw new Error(`Expected scene selector did not match" in source
    assert "visibleIndexes.length !== 1 || visibleIndexes[0] !== expectedSceneIndex" in source
    assert "Expected exactly ${expected} to be visible" in source
    assert "const effective = effectiveOpacity(node)" in source
    assert "effective > 0.15" in source


def test_running_standalone_gsap_animations_are_rejected():
    source = HARNESS.read_text(encoding="utf-8")

    assert "gsap.globalTimeline.getChildren(true, true, true)" in source
    assert "animation.isActive() && !animation.paused()" in source
    assert "Standalone running GSAP animation(s) detected" in source
    assert "animation.repeat()" in source
    assert "!Number.isFinite(duration) || duration <= 0 || duration > maxDuration" in source


def test_repeated_seeks_compare_real_screenshots_without_disabling_animations():
    source = HARNESS.read_text(encoding="utf-8")

    assert "animations: 'allow'" in source
    assert "first.screenshotSha256 !== second.screenshotSha256" in source
    assert "first.sceneState) !== JSON.stringify(second.sceneState)" in source
    assert "Different expected active scenes produced identical representative screenshots" in source
