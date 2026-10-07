# 16 — H3 / R4 Result

Task C / R4 media operations fixes implemented (but may still have partial completion provenance gaps).

## Changes mapped to requirements:
- **Profile Usage & Output Verification:** `master_final_video` now correctly uses `profile` parameters (`crf`, `pixel_format`) when burning subtitles and specifically checks output against the profile if `burn_subtitles` is true. Unbounded audio issues are solved by dynamically applying `ffprobe`-derived duration onto unbounded audio outputs if `max_duration_sec` is None.
- **Fail-closed atomic publication:** The process writes intermediate output with a `.tmp.mp4` extension, catching timeouts and other failures, performing strict cleanups of temp files before doing an `os.replace` to cleanly publish the final master only if no exception occurs. Base audio is mapped explicitly instead of unconditionally discarding it.
- **Ducking explicit sidechaining:** Replaced simplsitic `amix` ducking with proper ffmpeg sidechain ducking structure via filter complex using `sidechaincompress`. `narration` audio streams are explicitly split using `asplit` inside the filtergraph when they participate in both the sidechain trigger and final amix. Loudness and explicit customizable fade boundaries with optional parameters (`audio_fade_in_sec`, `ducking_threshold_db`) are wired backward-compatibly.
- **Subtitle escaping:** Included native FFmpeg string escaping over colons and backslashes in `-vf` filtergraphs (`\\\\`, `\\:` and `\\'`).
- **Tests written/adapted:** Wrote real execution (`dry_run=False`) tests in `tests/contracts/test_multishot_media_recovery.py` demonstrating audio ducking executions, missing-middle shots, atomic timeout handling, boundary color ordering logic and subtitle formatting outputs. Tests use miniature realistic clips utilizing lavfi instead of `dry_run=True` alone.

## Unimplemented remaining completion provenance requirements:
Completion checks and tests currently enforce output shape via `validate_final_master`, but strict multi-shot evidence linkage and binding back to current plan/revisions and validating actual accepted media across the whole state store are not deeply modeled beyond duration and metadata checks. End-to-end plan-state linkage constraints may require deeper scheduler state integration.

Check all test runs remotely utilizing `pytest tests/contracts/test_multishot_m3.py tests/contracts/test_multishot_m4.py tests/contracts/test_multishot_media_recovery.py`.