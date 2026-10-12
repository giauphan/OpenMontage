from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PIPELINE = ROOT / "scripts" / "run_daily_news_pipeline.sh"
HELPER = ROOT / "lib" / "news_failure_quarantine.py"
spec = importlib.util.spec_from_file_location("news_failure_quarantine", HELPER)
quarantine_module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(quarantine_module)
quarantine = quarantine_module.quarantine


class DailyNewsFailurePreservationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.projects = self.root / "projects"
        self.projects.mkdir()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def project(self, project_id: str = "news-item") -> Path:
        source = self.projects / project_id
        source.mkdir()
        (source / "evidence.json").write_text('{"source":"kept"}', encoding="utf-8")
        return source

    def assert_quarantined(self, source: Path, reason: str) -> Path:
        target = quarantine(self.projects, source.name, reason)
        self.assertFalse(source.exists())
        self.assertEqual((target / "failure_reason.txt").read_text(encoding="utf-8"), reason + "\n")
        self.assertEqual(
            (target / "project" / "evidence.json").read_text(encoding="utf-8"),
            '{"source":"kept"}',
        )
        return target

    def test_preserves_materialization_failure_evidence_and_reason(self) -> None:
        self.assert_quarantined(self.project(), "HyperFrames asset materialization or repair failed")

    def test_preserves_missing_composition_failure_evidence_and_reason(self) -> None:
        self.assert_quarantined(self.project(), "missing full/reels HyperFrames composition index")

    def test_preserves_base_render_validation_failure(self) -> None:
        self.assert_quarantined(self.project(), "Base render quality validation failed")

    def test_preserves_missing_render_failure(self) -> None:
        self.assert_quarantined(self.project(), "one or more expected renders are missing or empty")

    def test_preserves_renderer_command_failure_quarantine(self) -> None:
        """Renderer command nonzero should quarantine candidate (new regression)."""
        source = self.project()
        (source / "failure_reason.txt").write_text("HyperFrames render command failed", encoding="utf-8")
        target = quarantine(self.projects, source.name, "HyperFrames render command failed")
        self.assertFalse(source.exists())
        self.assertEqual((target / "failure_reason.txt").read_text(encoding="utf-8"), "HyperFrames render command failed\n")

    def test_preserves_template_mode_stale_recovery(self) -> None:
        """Template mode stale recovery should preserve failure reason in quarantine."""
        source = self.project()
        reason = "Template materialization failed: stale compositions rejected"
        target = quarantine(self.projects, source.name, reason)
        self.assertFalse(source.exists())
        self.assertEqual((target / "failure_reason.txt").read_text(encoding="utf-8"), reason + "\n")

    def test_preserves_missing_video_metadata_failure(self) -> None:
        self.assert_quarantined(self.project(), "publish metadata not created because one or more video files are missing")

    def test_preserves_codex_validation_failure_even_with_draft_metadata(self) -> None:
        source = self.project()
        (source / "publish_metadata.json").write_text(
            json.dumps({"id": "news-item", "title": "Draft metadata"}), encoding="utf-8"
        )
        target = quarantine(self.projects, "news-item", "Codex validation failed after retries")
        self.assertTrue((target / "project" / "publish_metadata.json").is_file())
        self.assertIn("Codex validation failed", (target / "failure_reason.txt").read_text(encoding="utf-8"))

    def test_retry_creates_unique_location_without_overwriting_existing_recovery(self) -> None:
        first = self.assert_quarantined(self.project(), "first failure")
        preserved_reason = first / "failure_reason.txt"
        preserved_reason.write_text("preserve pre-existing recovery", encoding="utf-8")
        second = self.assert_quarantined(self.project(), "retry failure")
        self.assertNotEqual(first, second)
        self.assertEqual(preserved_reason.read_text(encoding="utf-8"), "preserve pre-existing recovery")
        self.assertEqual(len(list((self.projects / "_failed_generation_recovered").iterdir())), 2)

    def test_rejects_invalid_and_reserved_ids_without_touching_source(self) -> None:
        source = self.project()
        for project_id in ("../escape", "", "a/b", ".", "_failed_generation_recovered", "_failed_generation_recovered_old"):
            with self.subTest(project_id=project_id), self.assertRaises(ValueError):
                quarantine(self.projects, project_id, "failed")
        self.assertTrue(source.is_dir())

    def test_refuses_projects_scheduled_as_strings_or_objects(self) -> None:
        config = self.root / "config"
        config.mkdir()
        cases = (
            ("news-item-string", ["news-item-string"]),
            ("news-item-object", [{"project_id": "news-item-object", "publish_date": "2030-01-01"}]),
        )
        for project_id, active in cases:
            with self.subTest(active=active):
                source = self.project(project_id)
                (config / "publish_schedule.json").write_text(
                    json.dumps({"active_projects": active}), encoding="utf-8"
                )
                with self.assertRaisesRegex(ValueError, "scheduled or marked live"):
                    quarantine(self.projects, project_id, "failure")
                self.assertTrue(source.is_dir())
                (config / "publish_schedule.json").unlink()

    def test_refuses_published_or_scheduled_publish_metadata_status(self) -> None:
        for metadata in (
            {"id": "news-item", "status": "published"},
            {"id": "news-item", "platforms": {"youtube/shorts": {"status": "scheduled"}}},
        ):
            with self.subTest(metadata=metadata):
                source = self.project()
                (source / "publish_metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "scheduled or marked live"):
                    quarantine(self.projects, "news-item", "failure")
                self.assertTrue(source.is_dir())
                shutil.rmtree(source)

    def test_refuses_live_project_marker_and_marker_identity_mismatch(self) -> None:
        source = self.project()
        (source / "project.json").write_text(json.dumps({"project_id": "news-item", "status": "active"}), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "scheduled or marked live"):
            quarantine(self.projects, "news-item", "failure")
        self.assertTrue(source.is_dir())
        (source / "project.json").write_text(json.dumps({"project_id": "another-project"}), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "identity"):
            quarantine(self.projects, "news-item", "failure")
        self.assertTrue(source.is_dir())

    def test_rejects_symlink_source_and_symlink_recovery_without_touching_target(self) -> None:
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "evidence.json").write_text("keep", encoding="utf-8")
        (self.projects / "linked").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            quarantine(self.projects, "linked", "failure")
        self.assertEqual((outside / "evidence.json").read_text(encoding="utf-8"), "keep")

        (self.projects / "linked").unlink()
        source = self.project()
        recovery_target = self.root / "external-recovery"
        recovery_target.mkdir()
        (self.projects / "_failed_generation_recovered").symlink_to(recovery_target, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "recovery directory must not be a symlink"):
            quarantine(self.projects, "news-item", "failure")
        self.assertTrue(source.is_dir())
        self.assertEqual(list(recovery_target.iterdir()), [])

    def test_director_failure_branch_quarantines_after_preserving_diagnostics(self) -> None:
        source = PIPELINE.read_text(encoding="utf-8")
        branch = re.search(r"else\n  echo .*directors FAIL.*?(?=\nfi\n\n# Step 3:)", source, re.DOTALL)
        self.assertIsNotNone(branch)
        body = branch.group(0)
        self.assertIn('"$DIRECTORS_LOG"', body)
        self.assertIn('"$ROOT/lib/news_failure_quarantine.py" "$ROOT/projects" "$PROJECT_ID"', body)
        self.assertIn('"Director run failed with exit code $DIRECTOR_EXIT', body)
        self.assertIn('see $DIRECTORS_LOG', body)
        self.assertLess(body.index('log-error --stage "directors"'), body.index('news_failure_quarantine.py'))
        self.assertLess(body.index('news_failure_quarantine.py'), body.index("continue"))

    def test_missing_composition_branch_quarantines_with_specific_missing_modes(self) -> None:
        source = PIPELINE.read_text(encoding="utf-8")
        start = source.index('FATAL type=no_full_composition')
        end = source.index('\n  fi\nelse\n  echo ', start)
        body = source[start:end]
        self.assertIn('COMPOSITION_FAILURE_REASON="$COMPOSITION_FAILURE_REASON full"', body)
        self.assertIn('COMPOSITION_FAILURE_REASON="$COMPOSITION_FAILURE_REASON reels"', body)
        self.assertIn('"$ROOT/logs/directors_${PROJECT_ID}.log"', body)
        self.assertIn('"$ROOT/lib/news_failure_quarantine.py" "$ROOT/projects" "$PROJECT_ID"', body)
        self.assertLess(body.index('log-error --stage "directors"'), body.index('news_failure_quarantine.py'))
        self.assertLess(body.index('news_failure_quarantine.py'), body.index("continue"))

    def test_daily_news_pipeline_has_valid_bash_syntax(self) -> None:
        result = subprocess.run(
            ["bash", "-n", str(PIPELINE)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_successful_path_never_invokes_quarantine_or_creates_recovery(self) -> None:
        source = self.project()
        self.assertTrue(source.is_dir())
        self.assertFalse((self.projects / "_failed_generation_recovered").exists())


if __name__ == "__main__":
    unittest.main()
