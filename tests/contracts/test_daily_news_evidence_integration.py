from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PIPELINE = ROOT / "scripts" / "run_daily_news_pipeline.sh"

FUNCTIONS_BEGIN = "# NEWS_EVIDENCE_GATE_FUNCTIONS_BEGIN"
FUNCTIONS_END = "# NEWS_EVIDENCE_GATE_FUNCTIONS_END"


def evidence_functions() -> str:
    script = PIPELINE.read_text(encoding="utf-8")
    start = script.index(FUNCTIONS_BEGIN) + len(FUNCTIONS_BEGIN)
    end = script.index(FUNCTIONS_END, start)
    return script[start:end]


def valid_project(project_dir: Path) -> None:
    artifacts = project_dir / "artifacts"
    artifacts.mkdir(parents=True)
    script_bytes = json.dumps(
        {"version": "1.0", "sections": [{"id": "s1", "text_vi": "TEST ONLY: fictional evidence integration fixture."}]},
        ensure_ascii=False,
    ).encode("utf-8")
    (artifacts / "script_vi.json").write_bytes(script_bytes)
    frozen_content = "TEST ONLY: fictional source content, not an actual news report.\n".encode("utf-8")
    (artifacts / "source-s1.txt").write_bytes(frozen_content)
    retrieved = datetime.now(timezone.utc) - timedelta(minutes=2)
    source_time = retrieved - timedelta(minutes=1)
    evidence = {
        "version": "2.0",
        "script_sha256": hashlib.sha256(script_bytes).hexdigest(),
        "claims": [{
            "section_id": "s1",
            "claim": "TEST ONLY: fictional provenance record.",
            "classification": "reported_fact",
            "consequential": False,
            "source_ids": ["source-1"],
            "reviewer": "TEST-ONLY fixture-editor",
            "reviewed_at": retrieved.isoformat(),
            "review_status": "approved",
        }],
        "sources": [{
            "id": "source-1",
            "url": "https://publisher.example/article",
            "status": "available",
            "published_at": source_time.isoformat(),
            "updated_at": source_time.isoformat(),
            "retrieved_at": retrieved.isoformat(),
            "content_path": "artifacts/source-s1.txt",
            "content_sha256": hashlib.sha256(frozen_content).hexdigest(),
            "excerpt": "TEST ONLY: fictional source content",
        }],
        "contradictions": [],
    }
    (artifacts / "news_evidence.json").write_text(
        json.dumps(evidence, ensure_ascii=False), encoding="utf-8"
    )


class DailyNewsEvidenceIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp.name)
        self.project = self.temp_path / "project"
        self.project.mkdir()
        self.validation_log = self.temp_path / "evidence-result.json"
        self.provider_marker = self.temp_path / "provider-invoked"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def run_pipeline_function(self, command: str, *, age: str | None = "24") -> subprocess.CompletedProcess[str]:
        bash = shutil.which("bash")
        if not bash:
            self.skipTest("bash is required to exercise the pipeline's isolated shell functions")
        env = os.environ.copy()
        env["ROOT"] = str(ROOT)
        env["PY"] = sys.executable
        env["PROJECT_DIR"] = str(self.project)
        env["VALIDATION_LOG"] = str(self.validation_log)
        env["PROVIDER_MARKER"] = str(self.provider_marker)
        if age is None:
            env.pop("NEWS_MAX_SOURCE_AGE_HOURS", None)
        else:
            env["NEWS_MAX_SOURCE_AGE_HOURS"] = age
        return subprocess.run(
            [bash, "-c", evidence_functions() + "\n" + command],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_missing_or_invalid_freshness_config_blocks_provider_invocation(self) -> None:
        command = 'validate_news_generation_config && touch "$PROVIDER_MARKER"'
        for age in (None, "0", "720.1", "nan", "inf", "not-a-number"):
            with self.subTest(age=age):
                self.provider_marker.unlink(missing_ok=True)
                result = self.run_pipeline_function(command, age=age)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(self.provider_marker.exists())
                self.assertIn("NEWS_MAX_SOURCE_AGE_HOURS", result.stderr)

    def test_missing_evidence_blocks_provider_before_any_invocation(self) -> None:
        result = self.run_pipeline_function(
            'validate_project_news_evidence "$PROJECT_DIR" "$VALIDATION_LOG" && touch "$PROVIDER_MARKER"'
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.provider_marker.exists())
        validation = json.loads(self.validation_log.read_text(encoding="utf-8"))
        self.assertFalse(validation["ok"])
        self.assertTrue(any("evidence artifact" in error for error in validation["errors"]))

    def test_invalid_evidence_blocks_provider_and_reports_real_validator_errors(self) -> None:
        valid_project(self.project)
        evidence_path = self.project / "artifacts" / "news_evidence.json"
        evidence_path.write_text('{"version":"1.0","claims":[]}', encoding="utf-8")
        result = self.run_pipeline_function(
            'validate_project_news_evidence "$PROJECT_DIR" "$VALIDATION_LOG" && touch "$PROVIDER_MARKER"'
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.provider_marker.exists())
        validation = json.loads(self.validation_log.read_text(encoding="utf-8"))
        self.assertFalse(validation["ok"])
        self.assertTrue(validation["errors"])
        self.assertIn("news evidence validation failed", result.stderr)

    def test_pending_rejected_or_missing_claim_verdict_blocks_provider(self) -> None:
        valid_project(self.project)
        evidence_path = self.project / "artifacts" / "news_evidence.json"
        original = json.loads(evidence_path.read_text(encoding="utf-8"))
        for status in ("pending", "rejected", None):
            with self.subTest(status=status):
                evidence = json.loads(json.dumps(original))
                claim = evidence["claims"][0]
                if status is None:
                    claim.pop("review_status", None)
                else:
                    claim["review_status"] = status
                evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
                self.provider_marker.unlink(missing_ok=True)
                result = self.run_pipeline_function(
                    'validate_project_news_evidence "$PROJECT_DIR" "$VALIDATION_LOG" && touch "$PROVIDER_MARKER"'
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(self.provider_marker.exists())
                validation = json.loads(self.validation_log.read_text(encoding="utf-8"))
                self.assertFalse(validation["ok"])
                self.assertTrue(any("review_status" in error for error in validation["errors"]))

    def test_real_evidence_validator_pass_allows_following_provider_step(self) -> None:
        valid_project(self.project)
        result = self.run_pipeline_function(
            'validate_project_news_evidence "$PROJECT_DIR" "$VALIDATION_LOG" && touch "$PROVIDER_MARKER"'
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.provider_marker.is_file())
        validation = json.loads(self.validation_log.read_text(encoding="utf-8"))
        self.assertTrue(validation["ok"], validation["errors"])

    def test_config_gate_precedes_paid_selection_and_director_generation(self) -> None:
        script = PIPELINE.read_text(encoding="utf-8")
        config_gate_at = script.index("if ! validate_news_generation_config; then")
        produce_at = script.index('tools/news/news_pipeline_cli.py produce')
        directors_at = script.index("run_directors >")
        self.assertLess(config_gate_at, produce_at)
        self.assertLess(config_gate_at, directors_at)

    def test_pipeline_calls_gate_before_narration_materialization(self) -> None:
        script = PIPELINE.read_text(encoding="utf-8")
        gate_at = script.index('validate_project_news_evidence "$PROJECT_DIR"')
        materialize_at = script.index('if ! materialize_hyperframes_assets "$ROOT/projects/$PROJECT_ID"; then')
        tts_at = script.index('edge-tts --voice')
        render_at = script.index('"$HYPERFRAMES_BIN" render')
        self.assertLess(gate_at, materialize_at)
        self.assertLess(gate_at, tts_at)
        self.assertLess(gate_at, render_at)


if __name__ == "__main__":
    unittest.main()
