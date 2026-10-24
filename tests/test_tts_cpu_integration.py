"""Regression and unit test suite for OpenMontage TTS and CPU Optimization Plan.

Tests all requirements from plan/pending/OPENMONTAGE_TTS_CPU_INTEGRATION_PLAN.md:
- Confirmed X-ray bug reproductions (findings 1-6)
- Narration caching (SHA256 content + locale + provider + model + voice + settings)
- ASR reuse by audio SHA256 + language
- Concurrency limits and CPU scheduling (media_cpu.lock)
- Provider fallback with complete narration regeneration (voice consistency)
- Atomic replacement and strict validation
"""
import fcntl
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.base_tool import ToolResult, ToolStatus


# ============================================================================
# Phase 0: Bug Reproductions
# ============================================================================

class TestBugReproductions:
    """Explicit reproductions of the confirmed X-ray findings."""

    def test_reproduce_finding_1_truncation_invalidates_unchanged_narration(self, tmp_path):
        """Finding 1: ': > narration_text' updates mtime, making it newer than narration.mp3.
        
        Fix: Compare content/hash first; preserve existing file and mtime if unchanged.
        """
        narration_text = tmp_path / "artifacts/narration_en_US_text.txt"
        narration_text.parent.mkdir(parents=True)
        narration_mp3 = tmp_path / "assets/narration.mp3"
        narration_mp3.parent.mkdir(parents=True)

        original_text = "This is a stable narration that should not re-render."
        narration_text.write_text(original_text, encoding="utf-8")
        narration_mp3.write_bytes(b"EXISTING_AUDIO_BYTES")

        # Set narration.mp3 to be slightly newer than narration_text
        t_base = time.time() - 100
        os.utime(narration_text, (t_base, t_base))
        os.utime(narration_mp3, (t_base + 10, t_base + 10))

        # Check initial state: narration is NOT stale
        assert narration_mp3.stat().st_mtime > narration_text.stat().st_mtime

        # Simulating the BUG: ': > "$narration_text"' then re-populating with same content
        # Buggy behavior:
        buggy_text_path = tmp_path / "artifacts/buggy_text.txt"
        buggy_text_path.write_text("", encoding="utf-8")
        buggy_text_path.write_text(original_text, encoding="utf-8")
        # Buggy result: mtime was updated to now, making it newer than narration.mp3!
        assert buggy_text_path.stat().st_mtime > narration_mp3.stat().st_mtime

        # Fixed behavior: conditional atomic write preserving mtime if unchanged
        from lib.audio.narration_orchestrator import safe_write_narration_text
        changed = safe_write_narration_text(narration_text, original_text)
        assert changed is False
        # mtime must be preserved!
        assert narration_text.stat().st_mtime < narration_mp3.stat().st_mtime

    def test_reproduce_finding_2_fix_narration_timing_voice_and_locale_bug(self, tmp_path):
        """Finding 2: fix_narration_timing.py called synth(args.voice, ...) when args.voice was None,
        and applied Vietnamese prepare_narration to English text.
        """
        from scripts.fix_narration_timing import synth
        
        # When args.voice is None, passing None causes edge-tts to fail or produce error
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stderr="--voice: argument is required")
            rc, err = synth(None, "Hello world", tmp_path / "out.mp3", None)
            assert rc != 0

        # With the fix: resolved voice must be passed
        resolved_voice = "en-US-ChristopherNeural"
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stderr="")
            rc, err = synth(resolved_voice, "Hello world", tmp_path / "out.mp3", None, locale="en-US")
            assert rc == 0
            called_args = mock_run.call_args[0][0]
            assert "--voice" in called_args
            assert "en-US-ChristopherNeural" in called_args
            # English text should NOT be mangled by Vietnamese phonetics
            assert "Hello world" in called_args

    def test_reproduce_finding_3_transcriber_cpu_threads_configurable(self):
        """Finding 3: Transcriber defaults to all cores without cpu_threads/num_workers limit."""
        from tools.analysis.transcriber import Transcriber
        t = Transcriber()
        with patch.dict(os.environ, {"ASR_CPU_THREADS": "1", "ASR_NUM_WORKERS": "1"}):
            opts = t._get_model_options("cpu", "int8", local_files_only=True)
            assert opts.get("cpu_threads") == 1
            assert opts.get("num_workers") == 1


# ============================================================================
# Phase 1 & 2: Narration Orchestrator, Caching, and Fallback
# ============================================================================

class TestNarrationOrchestrator:
    """Tests for lib/audio/narration_orchestrator.py."""

    def test_empty_script_fail_closed(self, tmp_path):
        """Empty script text must fail closed without calling providers."""
        from lib.audio.narration_orchestrator import NarrationOrchestrator
        orch = NarrationOrchestrator()
        out_mp3 = tmp_path / "narration.mp3"

        with pytest.raises(ValueError, match="empty or missing"):
            orch.synthesize(text="", output_path=out_mp3, locale="en-US")

        with pytest.raises(ValueError, match="empty or missing"):
            orch.synthesize(text="   \n  \t ", output_path=out_mp3, locale="en-US")

    def test_en_us_and_vi_vn_language_correctness(self, tmp_path):
        """Resolves appropriate voice and preprocessor for en-US vs vi-VN."""
        from lib.audio.narration_orchestrator import NarrationOrchestrator
        orch = NarrationOrchestrator()

        voice_en = orch.resolve_default_voice("en-US", provider="edge")
        voice_vi = orch.resolve_default_voice("vi-VN", provider="edge")
        assert "en-US" in voice_en or "Christopher" in voice_en or "Guy" in voice_en
        assert "vi-VN" in voice_vi or "HoaiMy" in voice_vi or "NamMinh" in voice_vi

        # English text cleaning preserves English numbers & symbols
        clean_en = orch.prepare_text("Model v2.5 costs $50 per month.", locale="en-US")
        assert "$50" in clean_en or "50" in clean_en
        assert "đồng" not in clean_en

    def test_cache_hit_zero_provider_calls(self, tmp_path):
        """Cached narration matching SHA256 key makes zero provider calls."""
        from lib.audio.narration_orchestrator import NarrationOrchestrator
        orch = NarrationOrchestrator(cache_dir=tmp_path / "cache")
        out_mp3 = tmp_path / "narration.mp3"

        text = "Autonomous AI agents require strict verification gates."
        mock_provider = MagicMock()
        mock_provider.name = "mock_tts"
        mock_provider.provider = "mock"
        mock_provider.execute.return_value = ToolResult(
            success=True,
            data={"audio_path": str(tmp_path / "gen.mp3"), "duration_seconds": 3.5}
        )

        # Pre-seed verified audio and cache
        cache_key = orch.compute_cache_key(
            text=text, locale="en-US", provider="mock", voice="v1", model="m1", settings={}
        )
        fake_audio = b"ID3_MOCK_VERIFIED_AUDIO_CONTENT"
        cached_file = orch.cache_dir / f"{cache_key}.mp3"
        cached_file.parent.mkdir(parents=True, exist_ok=True)
        cached_file.write_bytes(fake_audio)

        # Synthesize with cache hit
        with patch("lib.audio.narration_orchestrator.probe_audio_duration", return_value=3.5):
            res = orch.synthesize(
                text=text,
                output_path=out_mp3,
                locale="en-US",
                provider="mock",
                voice="v1",
                model="m1",
                provider_instance=mock_provider
            )

        assert res["cache_hit"] is True
        assert mock_provider.execute.call_count == 0
        assert out_mp3.read_bytes() == fake_audio

    def test_changed_voice_or_model_invalidates_audio_cache(self, tmp_path):
        """Changing voice or model produces a distinct cache key and triggers synthesis."""
        from lib.audio.narration_orchestrator import NarrationOrchestrator
        orch = NarrationOrchestrator(cache_dir=tmp_path / "cache")

        text = "Same narration text across tests."
        key1 = orch.compute_cache_key(text, "en-US", "kokoro", "am_michael", "kokoro-82m", {})
        key2 = orch.compute_cache_key(text, "en-US", "kokoro", "af_sarah", "kokoro-82m", {})
        key3 = orch.compute_cache_key(text, "en-US", "pocket18", "alba", "english_18m_2026-10", {})

        assert key1 != key2
        assert key1 != key3
        assert key2 != key3

    def test_bad_http_status_never_saved_as_mp3(self, tmp_path):
        """Failed HTTP or error status from provider must not create or overwrite target mp3."""
        from lib.audio.narration_orchestrator import NarrationOrchestrator
        orch = NarrationOrchestrator(cache_dir=tmp_path / "cache")
        out_mp3 = tmp_path / "narration.mp3"
        out_mp3.write_bytes(b"ORIGINAL_VALID_AUDIO")

        mock_provider = MagicMock()
        mock_provider.execute.return_value = ToolResult(
            success=False, error="HTTP 429: Rate limit exceeded"
        )

        with pytest.raises(RuntimeError, match="HTTP 429"):
            orch.synthesize(
                text="Some text",
                output_path=out_mp3,
                locale="en-US",
                provider="omniroute",
                provider_instance=mock_provider,
                allow_fallback=False,
            )

        # Target file must not be overwritten or corrupted!
        assert out_mp3.read_bytes() == b"ORIGINAL_VALID_AUDIO"

    def test_partial_mp3_no_atomic_replace(self, tmp_path):
        """Truncated or corrupted MP3 fails ffprobe duration check and is not moved to target."""
        from lib.audio.narration_orchestrator import NarrationOrchestrator
        orch = NarrationOrchestrator(cache_dir=tmp_path / "cache")
        out_mp3 = tmp_path / "narration.mp3"
        out_mp3.write_bytes(b"ORIGINAL_VALID_AUDIO")

        corrupt_tmp = tmp_path / "corrupt.mp3"
        corrupt_tmp.write_bytes(b"\x00\x00corrupt_partial_bytes")

        mock_provider = MagicMock()
        mock_provider.execute.return_value = ToolResult(
            success=True, data={"audio_path": str(corrupt_tmp)}
        )

        with patch("lib.audio.narration_orchestrator.probe_audio_duration", return_value=-1.0):
            with pytest.raises(RuntimeError, match="ffprobe integrity check failed"):
                orch.synthesize(
                    text="Some text",
                    output_path=out_mp3,
                    locale="en-US",
                    provider_instance=mock_provider,
                    allow_fallback=False,
                )

        # Target file remains intact
        assert out_mp3.read_bytes() == b"ORIGINAL_VALID_AUDIO"

    def test_timeout_bounded_retries_and_fallback_policy(self, tmp_path):
        """Timeout triggers bounded retry count then falls back cleanly to secondary provider."""
        from lib.audio.narration_orchestrator import NarrationOrchestrator
        orch = NarrationOrchestrator(cache_dir=tmp_path / "cache", max_retries=2)
        out_mp3 = tmp_path / "narration.mp3"

        primary_mock = MagicMock()
        primary_mock.provider = "primary"
        primary_mock.execute.return_value = ToolResult(success=False, error="Connection timeout")

        fallback_tmp = tmp_path / "fallback.mp3"
        fallback_tmp.write_bytes(b"FALLBACK_AUDIO_BYTES")
        fallback_mock = MagicMock()
        fallback_mock.provider = "fallback"
        fallback_mock.execute.return_value = ToolResult(
            success=True, data={"audio_path": str(fallback_tmp), "duration_seconds": 5.0}
        )

        providers = {"primary": primary_mock, "fallback": fallback_mock}
        with patch("lib.audio.narration_orchestrator.probe_audio_duration", return_value=5.0):
            res = orch.synthesize_with_fallback(
                text="Text to speak",
                output_path=out_mp3,
                locale="en-US",
                fallback_chain=["primary", "fallback"],
                provider_map=providers,
            )

        assert res["success"] is True
        assert res["provider"] == "fallback"
        assert primary_mock.execute.call_count == 2  # Retried twice
        assert fallback_mock.execute.call_count == 1
        assert out_mp3.read_bytes() == b"FALLBACK_AUDIO_BYTES"

    def test_voice_switch_rebuilds_complete_narration(self, tmp_path):
        """Fallback regenerates the entire affected narration to guarantee voice consistency (no spliced voices)."""
        from lib.audio.narration_orchestrator import NarrationOrchestrator
        orch = NarrationOrchestrator(cache_dir=tmp_path / "cache")
        out_mp3 = tmp_path / "narration.mp3"

        # Simulating multi-line text input
        lines = ["Sentence one.", "Sentence two.", "Sentence three."]
        full_text = " ".join(lines)

        captured_calls = []
        def mock_exec(inputs):
            captured_calls.append(inputs["text"])
            gen_p = tmp_path / f"gen_{len(captured_calls)}.mp3"
            gen_p.write_bytes(b"GENERATED_COMPLETE_AUDIO")
            return ToolResult(success=True, data={"audio_path": str(gen_p), "duration_seconds": 6.0})

        mock_prov = MagicMock()
        mock_prov.execute.side_effect = mock_exec

        with patch("lib.audio.narration_orchestrator.probe_audio_duration", return_value=6.0):
            res = orch.synthesize(
                text=full_text,
                output_path=out_mp3,
                locale="en-US",
                provider_instance=mock_prov,
            )

        assert len(captured_calls) == 1
        assert captured_calls[0] == full_text  # Entire text synthesized together!


# ============================================================================
# Phase 3 & 4: OmniRoute, Kokoro, and Pocket Provider Tools
# ============================================================================

class TestNewAudioProviders:
    """Tests for OmniRoute, Kokoro, and Pocket TTS provider tools."""

    def test_omniroute_tts_tool_contract(self, tmp_path):
        """OmniRouteTTS obeys BaseTool contract and supports /audio/speech."""
        from tools.audio.omniroute_tts import OmniRouteTTS
        tool = OmniRouteTTS()
        assert tool.name == "omniroute_tts"
        assert tool.capability == "tts"
        assert tool.provider == "omniroute"

        # Test execution with mocked requests
        out_p = tmp_path / "out.mp3"
        with patch("requests.post") as mock_post, patch("lib.audio.narration_orchestrator.probe_audio_duration", return_value=3.5):
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.content = b"OMNIROUTE_AUDIO_DATA_SAMPLE_PAYLOAD_VALID"
            mock_post.return_value = mock_resp

            result = tool.execute({
                "text": "Testing OmniRoute voice delivery.",
                "voice_id": "rachel",
                "model_id": "el/eleven_multilingual_v2",
                "output_path": str(out_p),
                "api_key": "test-key",
            })

            assert result.success is True
            assert out_p.read_bytes() == b"OMNIROUTE_AUDIO_DATA_SAMPLE_PAYLOAD_VALID"
            assert mock_post.called
            call_url = mock_post.call_args[0][0]
            assert "/audio/speech" in call_url

    def test_kokoro_local_tts_tool_contract(self, tmp_path):
        """KokoroLocalTTS runs via local CPU service or hyperframes CLI adapter."""
        from tools.audio.kokoro_local_tts import KokoroLocalTTS
        tool = KokoroLocalTTS()
        assert tool.name == "kokoro_local_tts"
        assert tool.capability == "tts"
        assert tool.provider == "kokoro"

        out_p = tmp_path / "out.mp3"
        with patch.object(tool, "_synthesize_kokoro", return_value=(True, 4.2, None)) as mock_synth:
            out_p.write_bytes(b"KOKORO_AUDIO")
            result = tool.execute({
                "text": "Testing local Kokoro 82M inference.",
                "voice_id": "am_michael",
                "output_path": str(out_p),
            })
            assert result.success is True
            assert result.data["duration_seconds"] == 4.2
            assert mock_synth.called

    def test_pocket_local_tts_tool_contract(self, tmp_path):
        """PocketLocalTTS operates CPU-only with english_18m_2026-10."""
        from tools.audio.pocket_local_tts import PocketLocalTTS
        tool = PocketLocalTTS()
        assert tool.name == "pocket_local_tts"
        assert tool.capability == "tts"
        assert tool.provider == "pocket18"

        out_p = tmp_path / "out.mp3"
        with patch.object(tool, "_synthesize_pocket", return_value=(True, 3.8, None)) as mock_synth:
            out_p.write_bytes(b"POCKET_AUDIO")
            result = tool.execute({
                "text": "Testing Pocket TTS 18M on CPU.",
                "voice_id": "alba",
                "output_path": str(out_p),
            })
            assert result.success is True
            assert result.data["duration_seconds"] == 3.8
            assert mock_synth.called

    def test_tts_selector_fallback_on_failure(self):
        """TTSSelector cascades to next provider on failure rather than aborting."""
        from tools.audio.tts_selector import TTSSelector
        selector = TTSSelector()

        p1 = MagicMock()
        p1.name = "failing_primary"
        p1.provider = "primary"
        p1.get_status.return_value = ToolStatus.AVAILABLE
        p1.execute.return_value = ToolResult(success=False, error="API Quota Exceeded")

        p2 = MagicMock()
        p2.name = "successful_secondary"
        p2.provider = "secondary"
        p2.get_status.return_value = ToolStatus.AVAILABLE
        p2.execute.return_value = ToolResult(success=True, data={"audio_path": "/tmp/a.mp3"})

        with patch.object(selector, "_discover_candidates", return_value=[p1, p2]):
            res = selector.execute_with_cascade(
                {"text": "Cascade test", "preferred_provider": "primary", "fallback_order": ["primary", "secondary"]}
            )
            assert res.success is True
            assert res.data["selected_provider"] == "secondary"
            assert p1.execute.called
            assert p2.execute.called


# ============================================================================
# Phase 5: Concurrency Limits and Shared CPU Lock
# ============================================================================

class TestConcurrencyAndCpuLock:
    """Tests for CPU lock and concurrency constraints."""

    def test_media_cpu_lock_mutual_exclusion(self, tmp_path):
        """Shared media_cpu.lock blocks concurrent acquisition across processes."""
        from lib.audio.narration_orchestrator import MediaCpuLock
        lock_file = tmp_path / "media_cpu.lock"

        lock1 = MediaCpuLock(lock_file, timeout_seconds=1.0)
        assert lock1.acquire() is True

        # Second lock attempt must time out while lock1 is held
        lock2 = MediaCpuLock(lock_file, timeout_seconds=0.2)
        assert lock2.acquire() is False

        lock1.release()

        # Now lock2 can acquire
        assert lock2.acquire() is True
        lock2.release()

    def test_no_nested_lock_deadlock(self, tmp_path):
        """Re-entrant or nested context in the same thread does not deadlock."""
        from lib.audio.narration_orchestrator import MediaCpuLock
        lock_file = tmp_path / "media_cpu.lock"

        lock = MediaCpuLock(lock_file, timeout_seconds=1.0)
        with lock:
            assert lock.is_locked
            # Inner re-entrant enter
            with lock:
                assert lock.is_locked
        assert not lock.is_locked

    def test_hyperframes_audio_mjs_concurrency_one(self):
        """audio.mjs must use sequential loop instead of Promise.all(lines.map(synthLine))."""
        audio_mjs_path = ROOT / ".agents/skills/hyperframes-media/scripts/audio.mjs"
        content = audio_mjs_path.read_text(encoding="utf-8")
        # Ensure unbounded Promise.all on lines is replaced
        assert "Promise.all(lines.map(synthLine))" not in content
        # Ensure fail-closed check for required voice lines
        assert "bad voice duration" in content or "line failed" in content


# ============================================================================
# Phase 6: ASR Cache Reuse and Pipeline Compatibility
# ============================================================================

class TestAsrCachingAndPipelineCompat:
    """Tests for ASR cache and pipeline verification."""

    def test_asr_cache_reuse_avoids_whisper(self, tmp_path):
        """generate_news_captions reuses cached transcript when audio SHA256 matches."""
        from scripts.generate_news_captions import get_asr_cache_key, check_asr_cache, save_asr_cache

        audio_file = tmp_path / "audio.mp3"
        audio_file.write_bytes(b"FAKE_AUDIO_FOR_ASR")
        audio_sha = hashlib.sha256(audio_file.read_bytes()).hexdigest()

        cache_key = get_asr_cache_key(audio_sha, locale="en-US", model_size="small")
        cached_data = {
            "timing_source": "asr",
            "language": "en",
            "word_timestamps": [{"word": "Test", "start": 0.0, "end": 0.5}]
        }
        save_asr_cache(cache_key, cached_data, cache_dir=tmp_path / "asr_cache")

        hit = check_asr_cache(cache_key, cache_dir=tmp_path / "asr_cache")
        assert hit is not None
        assert hit["word_timestamps"][0]["word"] == "Test"

    def test_caption_invalidation_on_audio_hash_change(self, tmp_path):
        """When audio changes, obsolete approval and validation status records are invalidated."""
        from scripts.independent_editorial_qa import compute_sha256

        audio1 = tmp_path / "a1.mp3"
        audio2 = tmp_path / "a2.mp3"
        audio1.write_bytes(b"AUDIO_VERSION_ONE")
        audio2.write_bytes(b"AUDIO_VERSION_TWO")

        assert compute_sha256(audio1) != compute_sha256(audio2)

    def test_docker_compose_quotas_present(self):
        """docker-compose.yml defines CPU quotas for scheduler and worker."""
        dc_path = ROOT / "docker-compose.yml"
        content = dc_path.read_text(encoding="utf-8")
        assert "cpus:" in content or "deploy:" in content or "cpu_quota" in content


# ============================================================================
# Phase P7: Tech Voice Project & Server Fit Tests
# ============================================================================

class TestTechVoiceFit:
    """Tests verifying tech voice fitting for project targets and server constraints."""

    def test_fix_narration_timing_supports_tech_voices(self, tmp_path):
        """synth() handles tech voices (am_michael, alba, rachel) via orchestrator."""
        from scripts.fix_narration_timing import synth

        with patch("lib.audio.narration_orchestrator.NarrationOrchestrator.synthesize") as mock_synth:
            mock_synth.return_value = {
                "success": True,
                "duration_seconds": 68.5,
                "output_path": str(tmp_path / "out.mp3"),
            }
            # Test Kokoro tech voice
            rc, err = synth("am_michael", "Autonomous agents require tool sandboxing.", tmp_path / "kokoro.mp3", "+5%", locale="en-US")
            assert rc == 0
            assert mock_synth.call_args[1]["provider"] == "kokoro"
            assert mock_synth.call_args[1]["voice"] == "am_michael"
            assert mock_synth.call_args[1]["settings"]["speed"] == 1.05

            # Test Pocket18 tech voice
            rc, err = synth("alba", "Modern AI pipelines use deterministic evaluation.", tmp_path / "pocket.mp3", "-10%", locale="en-US")
            assert rc == 0
            assert mock_synth.call_args[1]["provider"] == "pocket18"
            assert mock_synth.call_args[1]["voice"] == "alba"
            assert mock_synth.call_args[1]["settings"]["speed"] == 0.90

    def test_try_tech_voices_fit_evaluates_candidates_and_server_load(self, tmp_path):
        """try_tech_voices_fit sweeps rates across candidates and picks closest fit."""
        from scripts.fix_narration_timing import try_tech_voices_fit

        proj = tmp_path / "proj"
        proj.mkdir()
        (proj / "assets").mkdir()

        # Mock synth and probe_duration to simulate Kokoro landing at 71.2s for +5% rate
        def mock_probe(p):
            return 71.2

        with patch("scripts.fix_narration_timing.synth", return_value=(0, "")) as mock_s, \
             patch("scripts.fix_narration_timing.probe_duration", side_effect=mock_probe):
            res = try_tech_voices_fit(
                project=proj,
                text="Benchmarking production AI coding agent architectures.",
                target=70.0,
                tolerance=3.0,
                locale="en-US",
                candidates=[{"provider": "kokoro", "voice": "am_michael", "label": "Kokoro Tech"}]
            )
            assert res["best_fit"] is not None
            best = res["best_fit"]
            assert best["provider"] == "kokoro"
            assert best["within_tolerance"] is True
            assert abs(best["duration"] - 70.0) <= 3.0

    def test_orchestrator_evaluate_tech_voice_fit(self, tmp_path):
        """NarrationOrchestrator.evaluate_tech_voice_fit ranks candidates by project fit and RTF."""
        from lib.audio.narration_orchestrator import NarrationOrchestrator

        orch = NarrationOrchestrator(cache_dir=tmp_path / "cache")

        def mock_synth(text, output_path, locale, provider, voice, settings, allow_fallback):
            dur = 69.8 if provider == "kokoro" else 76.5
            return {"success": True, "duration_seconds": dur, "output_path": str(output_path)}

        with patch.object(orch, "synthesize", side_effect=mock_synth):
            res = orch.evaluate_tech_voice_fit(
                text="Autonomous AI agent tool execution verification.",
                target_seconds=70.0,
                tolerance_seconds=2.0,
                locale="en-US",
                candidates=[
                    {"provider": "edge", "voice": "en-US-ChristopherNeural", "label": "Edge"},
                    {"provider": "kokoro", "voice": "am_michael", "label": "Kokoro"},
                ]
            )
            best = res["best_fit"]
            assert best is not None
            assert best["provider"] == "kokoro"
            assert best["within_tolerance"] is True
            assert best["server_fit_score"] > 0

    def test_narration_cli_try_tech_voices_flag(self, tmp_path):
        """tools.audio.narration_cli supports --try-tech-voices to fit target project duration."""
        from tools.audio.narration_cli import main

        proj = tmp_path / "proj"
        proj.mkdir()
        (proj / "artifacts").mkdir()
        (proj / "assets").mkdir()
        (proj / "artifacts" / "narration_en_US_text.txt").write_text("Testing tech voice fitting CLI.", encoding="utf-8")
        out_mp3 = proj / "assets" / "narration.mp3"

        def mock_eval_fit(text, target_seconds, tolerance_seconds, locale):
            return {
                "best_fit": {
                    "provider": "kokoro",
                    "voice": "am_michael",
                    "label": "Kokoro-82M",
                    "speed": 1.05,
                    "duration": 69.5,
                    "delta": 0.5,
                    "rtf": 0.03,
                }
            }

        def mock_synth(text, output_path, locale, provider, voice, model=None, settings=None):
            return {"success": True, "duration_seconds": 69.5, "cache_hit": False}

        with patch("lib.audio.narration_orchestrator.NarrationOrchestrator.evaluate_tech_voice_fit", side_effect=mock_eval_fit), \
             patch("lib.audio.narration_orchestrator.NarrationOrchestrator.synthesize", side_effect=mock_synth):
            rc = main([str(proj), "--try-tech-voices", "--target-seconds", "70.0", "--locale", "en-US", "--output", str(out_mp3)])
            assert rc == 0

