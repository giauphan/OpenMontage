"""Benchmark OpenMontage TTS providers, Narration caching, ASR reuse, and CPU concurrency."""
import hashlib
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lib.audio.narration_orchestrator import (
    NarrationOrchestrator,
    MediaCpuLock,
    safe_write_narration_text,
    probe_audio_duration,
)
from scripts.generate_news_captions import (
    get_asr_cache_key,
    check_asr_cache,
    save_asr_cache,
)


def run_benchmark():
    print("=== OPENMONTAGE TTS & CPU OPTIMIZATION BENCHMARK ===")
    tmp_dir = Path("/tmp/benchmark_tts_cpu")
    tmp_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = tmp_dir / "cache_narration"
    asr_cache_dir = tmp_dir / "cache_asr"

    orchestrator = NarrationOrchestrator(cache_dir=cache_dir)

    test_script_short = (
        "Autonomous AI coding agents operate across structured tool boundaries. "
        "Strict verification gates ensure production deployments remain stable."
    )

    out_mp3_1 = tmp_dir / "bench_run1.mp3"
    out_mp3_2 = tmp_dir / "bench_run2_cache.mp3"

    # 1. First run: cold synthesis (cache miss)
    t0 = time.time()
    res1 = orchestrator.synthesize(
        text=test_script_short,
        output_path=out_mp3_1,
        locale="en-US",
        provider="edge",
    )
    t1 = time.time()
    dur_cold = t1 - t0
    audio_dur = res1.get("duration_seconds", 0.0)
    print(f"1. Cold Synthesis (Edge-TTS en-US): {dur_cold:.3f}s (Audio duration: {audio_dur:.2f}s, RTF: {dur_cold/audio_dur:.2f}x, Cache hit: {res1.get('cache_hit')})")

    # 2. Second run: warm synthesis (cache hit)
    t2 = time.time()
    res2 = orchestrator.synthesize(
        text=test_script_short,
        output_path=out_mp3_2,
        locale="en-US",
        provider="edge",
    )
    t3 = time.time()
    dur_warm = t3 - t2
    print(f"2. Warm Synthesis (Cache Hit): {dur_warm * 1000:.2f}ms (Cache hit: {res2.get('cache_hit')}, Latency reduction: {(1 - dur_warm/dur_cold)*100:.1f}%)")

    # 3. Text file mtime preservation test (safe_write_narration_text)
    txt_file = tmp_dir / "narration_text.txt"
    txt_file.write_text(test_script_short, encoding="utf-8")
    mtime_before = txt_file.stat().st_mtime_ns

    # Safe write with identical text
    changed = safe_write_narration_text(txt_file, test_script_short)
    mtime_after = txt_file.stat().st_mtime_ns
    preserved = (mtime_before == mtime_after and not changed)
    print(f"3. Safe Text Writing (Finding #1 Fix): Changed={changed}, mtime preserved={preserved}")

    # 4. ASR Caching Benchmark
    audio_sha = hashlib.sha256(out_mp3_1.read_bytes()).hexdigest()
    cache_key = get_asr_cache_key(audio_sha, locale="en-US", model_size="small")

    # Simulate saving ASR cache
    sample_asr_data = {
        "timing_source": "asr",
        "language": "en",
        "word_timestamps": [
            {"word": "Autonomous", "start": 0.0, "end": 0.6},
            {"word": "AI", "start": 0.6, "end": 0.9},
            {"word": "coding", "start": 0.9, "end": 1.3},
            {"word": "agents", "start": 1.3, "end": 1.7},
        ]
    }
    save_asr_cache(cache_key, sample_asr_data, cache_dir=asr_cache_dir)

    t4 = time.time()
    asr_hit = check_asr_cache(cache_key, cache_dir=asr_cache_dir)
    t5 = time.time()
    dur_asr_cache = (t5 - t4) * 1000
    print(f"4. ASR Cache Hit Lookup: {dur_asr_cache:.2f}ms (Word count: {len(asr_hit['word_timestamps'])})")

    # 5. Media CPU Lock Benchmark
    lock_file = tmp_dir / "media_cpu.lock"
    lock = MediaCpuLock(lock_file, timeout_seconds=1.0)
    t6 = time.time()
    with lock:
        # Re-entrant acquire
        with lock:
            locked = lock.is_locked
    t7 = time.time()
    dur_lock = (t7 - t6) * 1000
    print(f"5. Media CPU Lock (Re-entrant Acq/Rel): {dur_lock:.2f}ms, Locked state verified={locked}")

    # 6. Provider discovery
    from tools.audio.tts_selector import TTSSelector
    selector = TTSSelector()
    candidates = selector._providers()
    provider_names = [f"{t.name} ({t.provider})" for t in candidates]
    print(f"6. Discovered TTS Providers ({len(candidates)}): {', '.join(provider_names)}")

    results = {
        "cold_synthesis_seconds": round(dur_cold, 3),
        "warm_synthesis_seconds": round(dur_warm, 5),
        "audio_duration_seconds": round(audio_dur, 2),
        "realtime_factor": round(dur_cold / audio_dur, 2) if audio_dur > 0 else 0,
        "latency_reduction_pct": round((1 - dur_warm / dur_cold) * 100, 1),
        "mtime_preserved": preserved,
        "asr_cache_lookup_ms": round(dur_asr_cache, 2),
        "cpu_lock_overhead_ms": round(dur_lock, 2),
        "providers_discovered": provider_names,
    }
    out_json = tmp_dir / "benchmark_results.json"
    out_json.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nBenchmark completed successfully! Results saved to {out_json}")
    return results


if __name__ == "__main__":
    run_benchmark()
