"""Canonical narration orchestrator and resource governor for OpenMontage.

Provides:
1. Deterministic cache keyed by SHA256(content + locale + provider + model + voice + settings + version).
2. Media CPU lock (media_cpu.lock) ensuring inference, transcription, and render do not oversubscribe 2-vCPU VPS.
3. Safe text writing preserving st_mtime on identical content.
4. Provider fallback with entire-narration regeneration (voice consistency).
5. Strict atomic replace with ffprobe duration verification.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.base_tool import ToolResult


def probe_audio_duration(path: Path | str) -> float:
    """Probe audio duration in seconds using ffprobe."""
    path = Path(path)
    if not path.is_file() or path.stat().st_size == 0:
        return -1.0
    ffprobe = shutil.which("ffprobe") or "ffprobe"
    cmd = [
        ffprobe, "-v", "error",
        "-show_entries", "format=duration",
        "-of", "csv=p=0", str(path)
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        lines = [line.strip() for line in res.stdout.strip().splitlines() if line.strip()]
        if not lines:
            return -1.0
        return float(lines[-1])
    except Exception:
        return -1.0


def safe_write_narration_text(target_path: Path, text: str) -> bool:
    """Write text to target_path only if contents changed.
    
    Returns True if written, False if unchanged (preserving st_mtime).
    """
    target_path = Path(target_path)
    if target_path.is_file():
        try:
            existing = target_path.read_text(encoding="utf-8")
            if existing == text:
                return False
        except Exception:
            pass

    target_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target_path.with_suffix(".tmp")
    tmp_path.write_text(text, encoding="utf-8")
    os.replace(tmp_path, target_path)
    return True


def _resolve_default_cache_dir() -> Path:
    env_cache = os.environ.get("OPENMONTAGE_CACHE_DIR")
    if env_cache:
        p = Path(env_cache) / "narration"
        p.mkdir(parents=True, exist_ok=True)
        return p
    repo_cache = ROOT / ".cache/narration"
    try:
        repo_cache.mkdir(parents=True, exist_ok=True)
        return repo_cache
    except OSError:
        tmp_cache = Path("/tmp/openmontage_cache/narration")
        tmp_cache.mkdir(parents=True, exist_ok=True)
        return tmp_cache


def _resolve_default_lock_path() -> Path:
    env_lock = os.environ.get("MEDIA_CPU_LOCK_PATH")
    if env_lock:
        return Path(env_lock)
    repo_lock = ROOT / ".media_cpu.lock"
    try:
        repo_lock.parent.mkdir(parents=True, exist_ok=True)
        with open(repo_lock, "a"):
            pass
        return repo_lock
    except OSError:
        return Path("/tmp/openmontage_media_cpu.lock")


class MediaCpuLock:
    """Thread-safe and process-safe re-entrant file lock for CPU-heavy media jobs."""

    def __init__(self, lock_path: Path | str | None = None, timeout_seconds: float = 30.0):
        if lock_path is None:
            lock_path = _resolve_default_lock_path()
        self.lock_path = Path(lock_path)
        self.timeout_seconds = timeout_seconds
        self._fd: int | None = None
        self._reentrant_depth: int = 0

    @property
    def is_locked(self) -> bool:
        return self._reentrant_depth > 0

    def acquire(self) -> bool:
        if self._reentrant_depth > 0:
            self._reentrant_depth += 1
            return True

        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(str(self.lock_path), os.O_CREAT | os.O_RDWR, 0o666)
        except OSError:
            # Fallback to tmp lock if lock_path is on a read-only filesystem
            self.lock_path = Path("/tmp/openmontage_media_cpu.lock")
            fd = os.open(str(self.lock_path), os.O_CREAT | os.O_RDWR, 0o666)

        start = time.time()
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self._fd = fd
                self._reentrant_depth = 1
                return True
            except (BlockingIOError, OSError):
                if time.time() - start >= self.timeout_seconds:
                    os.close(fd)
                    return False
                time.sleep(0.05)

    def release(self):
        if self._reentrant_depth > 1:
            self._reentrant_depth -= 1
            return

        if self._fd is not None:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None
        self._reentrant_depth = 0

    def __enter__(self):
        if not self.acquire():
            raise TimeoutError(f"Could not acquire media CPU lock within {self.timeout_seconds}s at {self.lock_path}")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()


class NarrationOrchestrator:
    """Canonical narration orchestrator handling caching, provider selection, and atomic writes."""

    DEFAULT_VOICES = {
        "en-US": {
            "omniroute": "rachel",
            "elevenlabs": "rachel",
            "kokoro": "am_michael",
            "pocket18": "alba",
            "edge": "en-US-ChristopherNeural",
            "openai": "alloy",
        },
        "vi-VN": {
            "edge": "vi-VN-HoaiMyNeural",
            "elevenlabs": "eleven_multilingual_v2",
            "omniroute": "eleven_multilingual_v2",
            "kokoro": "am_michael",
        }
    }

    def __init__(
        self,
        cache_dir: Path | str | None = None,
        lock_path: Path | str | None = None,
        max_retries: int = 2,
    ):
        if cache_dir is None:
            cache_dir = _resolve_default_cache_dir()
        self.cache_dir = Path(cache_dir)
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            self.cache_dir = Path("/tmp/openmontage_cache/narration")
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.lock = MediaCpuLock(lock_path)
        self.max_retries = max_retries

    def compute_cache_key(
        self,
        text: str,
        locale: str,
        provider: str,
        voice: str | None,
        model: str | None,
        settings: Mapping[str, Any] | None = None,
        version: str = "1.0",
    ) -> str:
        payload = {
            "text": text.strip(),
            "locale": locale,
            "provider": provider.lower(),
            "voice": voice or "",
            "model": model or "",
            "settings": settings or {},
            "version": version,
        }
        serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def resolve_default_voice(self, locale: str, provider: str = "edge") -> str:
        loc_key = "vi-VN" if locale.startswith("vi") else "en-US"
        prov_key = provider.lower()
        return self.DEFAULT_VOICES.get(loc_key, {}).get(prov_key, "en-US-ChristopherNeural" if loc_key == "en-US" else "vi-VN-HoaiMyNeural")

    def prepare_text(self, text: str, locale: str = "en-US") -> str:
        if not text or not text.strip():
            raise ValueError("Narration text is empty or missing")
        text = text.strip()
        if locale.startswith("vi"):
            try:
                from tools.narration_text import prepare_narration
                return prepare_narration(text)
            except ImportError:
                return text
        return text

    def synthesize(
        self,
        text: str,
        output_path: Path | str,
        locale: str = "en-US",
        provider: str = "edge",
        voice: str | None = None,
        model: str | None = None,
        settings: Mapping[str, Any] | None = None,
        provider_instance: Any = None,
        allow_fallback: bool = True,
    ) -> dict[str, Any]:
        """Synthesize narration text to output_path using cache and strict validation."""
        clean_text = self.prepare_text(text, locale)
        output_path = Path(output_path).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)

        voice = voice or self.resolve_default_voice(locale, provider)
        cache_key = self.compute_cache_key(clean_text, locale, provider, voice, model, settings)
        cached_mp3 = self.cache_dir / f"{cache_key}.mp3"

        # 1. Check cache hit
        if cached_mp3.is_file() and cached_mp3.stat().st_size > 0:
            dur = probe_audio_duration(cached_mp3)
            if dur > 0:
                shutil.copy2(cached_mp3, output_path)
                return {
                    "success": True,
                    "cache_hit": True,
                    "duration_seconds": dur,
                    "output_path": str(output_path),
                    "cache_key": cache_key,
                    "provider": provider,
                    "voice": voice,
                }

        # 2. Cache miss: acquire CPU lock and synthesize
        with self.lock:
            # Re-check cache in case another process populated it while waiting
            if cached_mp3.is_file() and cached_mp3.stat().st_size > 0:
                dur = probe_audio_duration(cached_mp3)
                if dur > 0:
                    shutil.copy2(cached_mp3, output_path)
                    return {
                        "success": True,
                        "cache_hit": True,
                        "duration_seconds": dur,
                        "output_path": str(output_path),
                        "cache_key": cache_key,
                        "provider": provider,
                        "voice": voice,
                    }

            tmp_synth = output_path.with_suffix(".synth.mp3")
            if tmp_synth.exists():
                tmp_synth.unlink()

            exec_result = self._invoke_provider(
                provider_instance=provider_instance,
                provider_name=provider,
                text=clean_text,
                output_path=tmp_synth,
                voice=voice,
                model=model,
                settings=settings,
            )

            if not exec_result.success:
                if tmp_synth.exists():
                    tmp_synth.unlink()
                raise RuntimeError(f"Narration provider '{provider}' failed: {exec_result.error}")

            if exec_result.data and exec_result.data.get("audio_path"):
                res_path = Path(exec_result.data["audio_path"])
                if res_path.is_file() and not tmp_synth.exists():
                    shutil.copy2(res_path, tmp_synth)

            # Verify ffprobe duration and integrity
            dur = probe_audio_duration(tmp_synth)
            if dur <= 0:
                if tmp_synth.exists():
                    tmp_synth.unlink()
                raise RuntimeError(f"Generated narration ffprobe integrity check failed (duration: {dur})")

            # Atomic replace into output_path and cache
            os.replace(tmp_synth, output_path)
            shutil.copy2(output_path, cached_mp3)

            return {
                "success": True,
                "cache_hit": False,
                "duration_seconds": dur,
                "output_path": str(output_path),
                "cache_key": cache_key,
                "provider": provider,
                "voice": voice,
            }

    def _invoke_provider(
        self,
        provider_instance: Any,
        provider_name: str,
        text: str,
        output_path: Path,
        voice: str,
        model: str | None,
        settings: Mapping[str, Any] | None,
    ) -> ToolResult:
        if provider_instance is not None:
            return provider_instance.execute({
                "text": text,
                "output_path": str(output_path),
                "voice_id": voice,
                "model_id": model,
                **(settings or {})
            })

        # Direct flite provider (ultra-lightweight, low CPU/RAM, offline)
        if provider_name.lower() == "flite":
            flite_voice = voice if voice in ("slt", "rms", "awb", "kal", "kal16") else "slt"
            txt_tmp = output_path.with_suffix(".txt")
            txt_tmp.write_text(text, encoding="utf-8")
            esc = str(txt_tmp).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
            cmd = [
                "ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                "-i", f"flite=textfile='{esc}':voice={flite_voice}",
                "-af", "highpass=f=80,lowpass=f=7500,volume=1.5,loudnorm",
                "-c:a", "libmp3lame", "-b:a", "192k", str(output_path),
            ]
            res_flite = subprocess.run(cmd, capture_output=True, text=True)
            txt_tmp.unlink(missing_ok=True)
            if res_flite.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
                return ToolResult(success=True, data={"audio_path": str(output_path), "provider": "flite", "voice": flite_voice})
            return ToolResult(success=False, error=f"flite failed: {res_flite.stderr}")

        # Default provider invocation
        if provider_name.lower() in ("edge",):
            args = ["edge-tts", "--voice", voice, "--text", text, "--write-media", str(output_path)]
            if settings and settings.get("rate"):
                args += ["--rate", str(settings["rate"])]
            timeout_s = max(30, int(len(text) / 15))
            try:
                res = subprocess.run(args, capture_output=True, text=True, timeout=timeout_s)
                if res.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
                    return ToolResult(success=True, data={"audio_path": str(output_path), "provider": "edge", "voice": voice})
                return ToolResult(success=False, error=f"edge-tts failed: {(res.stderr or '')[-400:]}")
            except Exception as exc:
                return ToolResult(success=False, error=f"edge-tts failed: {exc}")

        # Look up tool from OpenMontage registry or instantiate
        try:
            from tools.audio.tts_selector import TTSSelector
            selector = TTSSelector()
            inputs = {
                "text": text,
                "output_path": str(output_path),
                "preferred_provider": provider_name,
                "voice_id": voice,
                "model_id": model,
                **(settings or {})
            }
            return selector.execute(inputs)
        except Exception as e:
            return ToolResult(success=False, error=f"Provider {provider_name} lookup error: {e}")

    def synthesize_with_fallback(
        self,
        text: str,
        output_path: Path | str,
        locale: str = "en-US",
        fallback_chain: list[str] | None = None,
        provider_map: Mapping[str, Any] | None = None,
        voice_map: Mapping[str, str] | None = None,
        model_map: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        """Attempt primary provider; on failure, bounded retry and cascade to fallback providers."""
        chain = fallback_chain or ["edge"]
        provider_map = provider_map or {}
        voice_map = voice_map or {}
        model_map = model_map or {}
        last_error = None

        for prov in chain:
            instance = provider_map.get(prov)
            voice = voice_map.get(prov) or self.resolve_default_voice(locale, prov)
            model = model_map.get(prov)

            for attempt in range(1, self.max_retries + 1):
                try:
                    res = self.synthesize(
                        text=text,
                        output_path=output_path,
                        locale=locale,
                        provider=prov,
                        voice=voice,
                        model=model,
                        provider_instance=instance,
                        allow_fallback=False,
                    )
                    res["provider"] = prov
                    return res
                except Exception as e:
                    last_error = e
                    time.sleep(0.05 * attempt)

        raise RuntimeError(f"All narration providers in fallback chain failed ({chain}). Last error: {last_error}")

    def evaluate_tech_voice_fit(
        self,
        text: str,
        target_seconds: float,
        tolerance_seconds: float = 3.0,
        locale: str = "en-US",
        candidates: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Evaluate tech voice candidates to determine the optimal voice and speed factor
        that fits the target project duration within tolerance while minimizing server CPU load.
        """
        enable_heavy = os.environ.get("ENABLE_HEAVY_TTS", "0") == "1"
        default_candidates = [
            {"provider": "flite", "voice": "slt", "label": "Flite (slt, Ultra-Low CPU/RAM)"},
            {"provider": "flite", "voice": "rms", "label": "Flite (rms, Male Tech Tone)"},
            {"provider": "pocket18", "voice": os.environ.get("TTS_POCKET_VOICE", "alba"), "label": "Pocket TTS 18M (alba, Low-CPU)"},
            {"provider": "edge", "voice": "en-US-ChristopherNeural", "label": "Edge-TTS (Christopher, Broadcast Tech)"},
            {"provider": "omniroute", "voice": "rachel", "label": "OmniRoute (rachel, Expressive Cloud)"},
        ]
        if enable_heavy:
            default_candidates.append(
                {"provider": "kokoro", "voice": os.environ.get("TTS_KOKORO_VOICE", "am_michael"), "label": "Kokoro-82M (am_michael, CPU)"}
            )
        tech_candidates = candidates or default_candidates

        rates = [None, "+5%", "-5%", "+10%", "-10%", "+15%", "-15%", "+20%", "+25%"]
        evaluations = []
        tmp_eval = self.cache_dir / "tmp_eval_fit.mp3"

        for cand in tech_candidates:
            provider = cand["provider"]
            voice = cand["voice"]
            best_entry = None

            candidate_failed = False
            for rate in rates:
                if candidate_failed:
                    break
                speed = 1.0
                if rate:
                    clean_rate = str(rate).replace("%", "").strip()
                    if clean_rate.startswith("+"):
                        speed = 1.0 + float(clean_rate[1:]) / 100.0
                    elif clean_rate.startswith("-"):
                        speed = 1.0 - float(clean_rate[1:]) / 100.0
                    else:
                        speed = 1.0 + float(clean_rate) / 100.0

                settings = {"rate": rate, "speed": speed}
                t0 = time.time()
                try:
                    res = self.synthesize(
                        text=text,
                        output_path=tmp_eval,
                        locale=locale,
                        provider=provider,
                        voice=voice,
                        settings=settings,
                        allow_fallback=False,
                    )
                    elapsed = time.time() - t0
                    dur = res.get("duration_seconds", 0.0)
                    if dur <= 0:
                        if rate is None:
                            candidate_failed = True
                        continue
                    delta = abs(dur - target_seconds)
                    rtf = elapsed / dur if dur > 0 else 999.0
                    entry = {
                        "provider": provider,
                        "voice": voice,
                        "label": cand.get("label", f"{provider}:{voice}"),
                        "rate": rate,
                        "speed": speed,
                        "duration": dur,
                        "target_seconds": target_seconds,
                        "delta": round(delta, 3),
                        "within_tolerance": delta <= tolerance_seconds,
                        "elapsed_seconds": round(elapsed, 3),
                        "rtf": round(rtf, 4),
                        "server_fit_score": round(1.0 / (1.0 + delta + rtf), 4),
                    }
                    if best_entry is None or delta < best_entry["delta"]:
                        best_entry = entry
                    if delta <= tolerance_seconds:
                        break
                except Exception:
                    if rate is None:
                        candidate_failed = True
                    continue

            if best_entry:
                evaluations.append(best_entry)

        if tmp_eval.exists():
            tmp_eval.unlink(missing_ok=True)

        evaluations.sort(key=lambda x: (not x["within_tolerance"], x["delta"], x["rtf"]))
        return {
            "best_fit": evaluations[0] if evaluations else None,
            "evaluations": evaluations,
            "target_seconds": target_seconds,
            "tolerance_seconds": tolerance_seconds,
        }
