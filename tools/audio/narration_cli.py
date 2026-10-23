"""Unified Narration CLI for OpenMontage.

Exposes the canonical NarrationOrchestrator to Bash pipelines and Python scripts.
Ensures identical artifact format, error reporting, caching, and CPU lock governance.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.audio.narration_orchestrator import (
    NarrationOrchestrator,
    safe_write_narration_text,
    probe_audio_duration,
)
from lib.artifact_paths import resolve_project_locale, is_english_locale


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_dir", type=Path, help="Project root directory")
    parser.add_argument("--locale", default=None, help="Project locale (en-US or vi-VN)")
    parser.add_argument("--provider", default=None, help="TTS provider override (omniroute, kokoro, pocket18, edge, elevenlabs)")
    parser.add_argument("--voice", default=None, help="Voice identifier override")
    parser.add_argument("--model", default=None, help="Model identifier override")
    parser.add_argument("--text-file", type=Path, default=None, help="Explicit text file to synthesize from")
    parser.add_argument("--output", type=Path, default=None, help="Output MP3 path override")
    parser.add_argument("--reels", action="store_true", help="Synthesize reels-specific narration")
    parser.add_argument("--speed", type=float, default=1.0, help="Speaking speed factor")
    parser.add_argument("--fallback-chain", default=None, help="Comma-separated provider fallback chain")
    args = parser.parse_args(argv)

    project_dir = args.project_dir.resolve()
    if not project_dir.is_dir():
        print(f"ERROR: project_dir {project_dir} is not a directory", file=sys.stderr)
        return 1

    locale = args.locale or resolve_project_locale(project_dir)
    is_en = is_english_locale(locale)

    # Resolve text file and script JSON
    if args.text_file:
        text_file = args.text_file.resolve()
    else:
        if is_en:
            text_file = project_dir / "artifacts/narration_en_US_text.txt"
            script_file = project_dir / "artifacts/script_en_US.json"
        else:
            text_file = project_dir / "artifacts/narration_vi_text.txt"
            script_file = project_dir / "artifacts/script_vi_reels.json" if args.reels else project_dir / "artifacts/script_vi.json"

        # If text_file doesn't exist or is empty, derive from script_file
        if not text_file.is_file() or text_file.stat().st_size == 0:
            if not script_file.is_file():
                script_file = project_dir / "artifacts/script.json"
            if script_file.is_file():
                try:
                    data = json.loads(script_file.read_text(encoding="utf-8"))
                    text = ""
                    if isinstance(data, dict):
                        sections = data.get("sections") or data.get("scenes") or []
                        if sections:
                            if is_en:
                                parts = [s.get("narration") or s.get("text") or "" for s in sections]
                            else:
                                parts = [s.get("text_vi") or s.get("narration_vi") or s.get("text") or s.get("narration") or "" for s in sections]
                            text = " ".join(p.strip() for p in parts if p.strip())
                        else:
                            text = data.get("narration") or data.get("text") or data.get("script") or ""
                    if text:
                        safe_write_narration_text(text_file, text)
                except Exception as exc:
                    print(f"Warning: could not derive narration from {script_file}: {exc}", file=sys.stderr)

    if not text_file.is_file():
        print(f"ERROR: narration text file not found: {text_file}", file=sys.stderr)
        return 1

    text = text_file.read_text(encoding="utf-8").strip()
    if not text:
        print("ERROR: narration text is empty", file=sys.stderr)
        return 1

    # Output path
    if args.output:
        output_mp3 = args.output.resolve()
    else:
        filename = "narration_reels.mp3" if args.reels else "narration.mp3"
        output_mp3 = project_dir / "assets" / filename

    # Provider and fallback resolution from environment/args
    provider = args.provider or (os.environ.get("TTS_PROVIDER_EN") if is_en else os.environ.get("TTS_PROVIDER_VI")) or "edge"
    fallback_chain_str = args.fallback_chain or (os.environ.get("TTS_FALLBACK_ORDER_EN") if is_en else os.environ.get("TTS_FALLBACK_ORDER_VI"))
    fallback_chain = [p.strip() for p in fallback_chain_str.split(",") if p.strip()] if fallback_chain_str else None
    if fallback_chain and provider not in fallback_chain:
        fallback_chain = [provider] + fallback_chain

    orchestrator = NarrationOrchestrator()
    voice = args.voice or orchestrator.resolve_default_voice(locale, provider)
    settings = {"speed": args.speed}

    try:
        if fallback_chain and len(fallback_chain) > 1:
            result = orchestrator.synthesize_with_fallback(
                text=text,
                output_path=output_mp3,
                locale=locale,
                fallback_chain=fallback_chain,
            )
        else:
            result = orchestrator.synthesize(
                text=text,
                output_path=output_mp3,
                locale=locale,
                provider=provider,
                voice=voice,
                model=args.model,
                settings=settings,
            )
        print(f"Narration synthesized successfully -> {output_mp3} (duration: {result.get('duration_seconds', 0.0):.2f}s, cache_hit: {result.get('cache_hit', False)})")
        return 0
    except Exception as exc:
        print(f"ERROR: Narration synthesis failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
