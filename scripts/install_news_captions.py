#!/usr/bin/env python3
"""Install validated ASR caption clips into a daily-news HyperFrames composition."""

from __future__ import annotations

import argparse
import hashlib
import html
from html.parser import HTMLParser
import json
import math
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import uuid


VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr",
}
BEGIN_MARKER = "<!-- OPENMONTAGE_ASR_CAPTIONS_BEGIN -->"
END_MARKER = "<!-- OPENMONTAGE_ASR_CAPTIONS_END -->"
CAPTION_CSS = """<style id="om-asr-caption-style">
#main { position: relative; }
.om-asr-caption {
  position: absolute;
  top: auto !important;
  left: 7%;
  right: 7%;
  bottom: 8% !important;
  box-sizing: border-box;
  max-height: 14%;
  overflow: hidden;
  padding: 0.45em 0.7em;
  border-radius: 0.22em;
  background: rgba(0, 0, 0, 0.86);
  color: #fff;
  font: 700 clamp(28px, 4vw, 44px)/1.2 sans-serif;
  text-align: center;
  text-wrap: balance;
  overflow-wrap: anywhere;
}
</style>"""
LEGACY_CAPTION_CSS = CAPTION_CSS.replace(
    "#main { position: relative; }",
    '[data-composition-id="main"] { position: relative; }',
)
STAGE_CAPTION_CSS = CAPTION_CSS.replace(
    "#main { position: relative; }",
    "#stage { position: relative; }",
)
ROOT_CAPTION_CSS = CAPTION_CSS.replace(
    "#main { position: relative; }",
    "#root { position: relative; }",
)


class CompositionParser(HTMLParser):
    def __init__(self, source: str):
        super().__init__(convert_charrefs=False)
        self.source = source
        self.offsets = [0]
        for line in source.splitlines(keepends=True):
            self.offsets.append(self.offsets[-1] + len(line))
        self.stack: list[str] = []
        self.root_records: list[tuple[str, dict[str, str], int, int | None, str | None]] = []
        self.root_record_index: int | None = None
        self.track_indices: list[int] = []
        self.has_existing_caption_markup = False
        self.feed(source)
        self.close()

    def _offset(self) -> int:
        line, column = self.getpos()
        return self.offsets[line - 1] + column

    def handle_starttag(self, tag, attrs):
        attrs_dict = {key: value or "" for key, value in attrs}
        for key, value in attrs_dict.items():
            if key == "data-track-index":
                try:
                    self.track_indices.append(int(value))
                except ValueError:
                    raise ValueError(f"invalid data-track-index: {value!r}")
        classes = set(attrs_dict.get("class", "").split())
        if classes.intersection({"caption", "captions", "subtitle", "subtitles"}) or attrs_dict.get("id", "").startswith("caption-"):
            self.has_existing_caption_markup = True

        if attrs_dict.get("data-composition-id") == "main":
            parent = self.stack[-1] if self.stack else None
            self.root_records.append((tag, attrs_dict, self._offset(), None, parent))
            self.root_record_index = len(self.root_records) - 1
            self._active_root_stack_index = len(self.stack)

        if tag not in VOID_TAGS:
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        match = next((index for index in range(len(self.stack) - 1, -1, -1)
                      if self.stack[index] == tag), None)
        if match is None:
            return
        if (self.root_record_index is not None and
                match == self._active_root_stack_index):
            root = self.root_records[self.root_record_index]
            self.root_records[self.root_record_index] = (*root[:3], self._offset(), root[4])
            self.root_record_index = None
        del self.stack[match:]


def _remove_managed_block(source: str) -> tuple[str, tuple[int, int] | None]:
    begin_count = source.count(BEGIN_MARKER)
    end_count = source.count(END_MARKER)
    if begin_count == 0 and end_count == 0:
        return source, None
    if begin_count != 1 or end_count != 1:
        raise ValueError("malformed OpenMontage ASR caption markers: expected one begin and one end")

    start = source.index(BEGIN_MARKER)
    end = source.index(END_MARKER)
    if end <= start:
        raise ValueError("malformed OpenMontage ASR caption markers: end precedes begin")
    block = source[start : end + len(END_MARKER)]
    caption_pattern = re.compile(
        r'<div id="om-asr-caption-(\d+)" class="clip om-asr-caption" '
        r'data-start="(\d+(?:\.\d+)?)" data-duration="(\d+(?:\.\d+)?)" '
        r'data-track-index="(\d+)">([^<]*)</div>\n'
    )
    allowed_styles = "(?:" + "|".join(
        re.escape(style) for style in (CAPTION_CSS, STAGE_CAPTION_CSS, ROOT_CAPTION_CSS, LEGACY_CAPTION_CSS)
    ) + ")"
    block_pattern = re.compile(
        re.escape(BEGIN_MARKER) + r"\n" + allowed_styles + r"\n"
        + r"(?P<clips>(?:" + caption_pattern.pattern + r")+)"
        + re.escape(END_MARKER)
    )
    match = block_pattern.fullmatch(block)
    if match is None:
        raise ValueError("malformed OpenMontage ASR caption block; refusing to overwrite user HTML")
    clips = list(caption_pattern.finditer(match.group("clips")))
    if not clips:
        raise ValueError("malformed OpenMontage ASR caption block: no managed clips")
    track = None
    for expected_id, clip in enumerate(clips, start=1):
        clip_id, start_text, duration_text, clip_track, text = clip.groups()
        start_time, clip_duration = float(start_text), float(duration_text)
        if (int(clip_id) != expected_id or not math.isfinite(start_time) or
                not math.isfinite(clip_duration) or start_time < 0 or clip_duration <= 0):
            raise ValueError("malformed OpenMontage ASR caption clip metadata")
        if track is None:
            track = clip_track
        elif clip_track != track:
            raise ValueError("malformed OpenMontage ASR caption block: mixed track indexes")
        if "&" in text and re.search(r"&(?!amp;|lt;|gt;|quot;|#x27;|#\d+;)", text):
            raise ValueError("malformed OpenMontage ASR caption block: invalid escaped text")
    block_end = end + len(END_MARKER)
    return source[:start] + source[block_end:], (start, block_end)


def _cue_groups(words: list[dict]) -> list[dict]:
    groups = []
    batch = []
    for word in words:
        if batch and (len(batch) >= 3 or word["end"] - batch[0]["start"] > 2.8):
            groups.append(batch)
            batch = []
        batch.append(word)
    if batch:
        groups.append(batch)
    return [
        {
            "start": group[0]["start"],
            "end": group[-1]["end"],
            "text": " ".join(item["word"].strip() for item in group),
        }
        for group in groups
    ]


def _validate_install_paths(
    composition_path: Path | str,
    audio_path: Path | str,
    timings_path: Path | str,
    allowed_root: Path | str | None,
) -> tuple[Path, Path, Path]:
    raw_comp_str = str(composition_path)
    raw_audio_str = str(audio_path)
    raw_timings_str = str(timings_path)

    for p_str, p in (
        (raw_comp_str, Path(raw_comp_str)),
        (raw_audio_str, Path(raw_audio_str)),
        (raw_timings_str, Path(raw_timings_str)),
    ):
        if "\x00" in p_str or any(part == ".." for part in p.parts):
            raise ValueError(f"Path traversal detected in argument: {p_str}")
        if p.is_symlink():
            raise ValueError(f"Symlink detected in argument: {p_str}")

    comp_resolved = Path(os.path.realpath(raw_comp_str))
    audio_resolved = Path(os.path.realpath(raw_audio_str))
    timings_resolved = Path(os.path.realpath(raw_timings_str))

    repo_root = Path(os.path.realpath(str(Path(__file__).resolve().parents[1])))
    cwd_dir = Path.cwd().resolve()
    tmp_dir = Path(os.path.realpath(tempfile.gettempdir()))
    allowed_roots = (
        repo_root,
        *([cwd_dir] if cwd_dir != Path(cwd_dir.anchor) else []),
        tmp_dir,
        *([Path(os.path.realpath(str(allowed_root)))] if allowed_root is not None else []),
    )

    for p_name, res in (("composition", comp_resolved), ("audio", audio_resolved), ("timings", timings_resolved)):
        res_str = str(res)
        if not any(
            res.is_relative_to(root)
            and os.path.commonpath([res_str, str(root)]) == str(root)
            and (res_str == str(root) or res_str.startswith(str(root) + os.sep))
            for root in allowed_roots
        ):
            raise ValueError(f"{p_name} path outside allowed roots: {res}")

    if allowed_root is not None:
        root_resolved = Path(os.path.realpath(str(allowed_root)))
        for p in (comp_resolved, audio_resolved, timings_resolved):
            try:
                p.relative_to(root_resolved)
            except ValueError as exc:
                raise ValueError(f"Path escapes allowed root {root_resolved}: {p}") from exc

    if not comp_resolved.is_file():
        raise ValueError(f"Composition file not found: {comp_resolved}")
    if not audio_resolved.is_file():
        raise ValueError(f"Audio file not found: {audio_resolved}")
    if not timings_resolved.is_file():
        raise ValueError(f"Timings file not found: {timings_resolved}")
    return comp_resolved, audio_resolved, timings_resolved


def _validate_timings_payload(timings: Any, audio_bytes: bytes) -> list[dict[str, Any]]:
    if not isinstance(timings, dict) or timings.get("timing_source") != "asr":
        raise ValueError("caption timings must declare timing_source='asr'")
    if timings.get("timing_verified") is not False:
        raise ValueError("caption timing verification must remain unasserted")
    audio_hash = hashlib.sha256(audio_bytes).hexdigest()
    if timings.get("audio_sha256") != audio_hash:
        raise ValueError("caption timing audio_sha256 does not match composition audio")
    words = timings.get("word_timestamps")
    if not isinstance(words, list) or not words:
        raise ValueError("caption timing JSON has no word_timestamps")
    return words


def _validate_composition_root(parser: CompositionParser, source: str) -> tuple[str, float, int]:
    if len(parser.root_records) != 1:
        raise ValueError("expected exactly one main HyperFrames composition root")
    _, attrs, _, closing_offset, parent = parser.root_records[0]
    if parent != "body" or closing_offset is None:
        raise ValueError("main composition root must be a closed direct child of body")
    root_id = attrs.get("id")
    if root_id not in ("main", "stage", "root"):
        raise ValueError('main composition root must use id="main"')
    try:
        composition_duration = float(attrs["data-duration"])
        root_start = float(attrs["data-start"])
        width = int(attrs["data-width"])
        height = int(attrs["data-height"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("main composition root needs numeric data-start/data-duration/data-width/data-height") from exc
    if (not math.isfinite(composition_duration) or composition_duration <= 0 or
            not math.isfinite(root_start) or root_start != 0 or width <= 0 or height <= 0):
        raise ValueError("main composition root must start at zero and dimensions/duration must be positive")
    if not re.search(r"gsap\.timeline\(\s*\{[^}]*\bpaused\s*:\s*true\b", source):
        raise ValueError("unsupported composition: expected a synchronously created paused GSAP timeline")
    if not re.search(r"window\.__timelines\s*(?:\[\s*(['\"])main\1\s*\]|\.\s*main\b)", source):
        raise ValueError("unsupported composition: expected timeline registered as window.__timelines['main']")
    if parser.has_existing_caption_markup:
        raise ValueError("unsupported composition: existing caption markup must be removed or explicitly migrated")
    return root_id, composition_duration, closing_offset


def _parse_and_validate_words(words: list[dict[str, Any]], composition_duration: float) -> list[dict[str, Any]]:
    parsed_words = []
    previous_end = -1.0
    for item in words:
        if not isinstance(item, dict) or not isinstance(item.get("word"), str) or not item["word"].strip():
            raise ValueError("invalid or empty ASR word")
        start, end = item.get("start"), item.get("end")
        if (isinstance(start, bool) or isinstance(end, bool) or
                not isinstance(start, (int, float)) or not isinstance(end, (int, float)) or
                not math.isfinite(start) or not math.isfinite(end) or start < 0 or
                end <= start or end > composition_duration or start < previous_end):
            raise ValueError("ASR word timings must be chronological and within composition duration")
        parsed_words.append({"word": item["word"], "start": float(start), "end": float(end)})
        previous_end = end
    return parsed_words


def _build_caption_block(
    groups: list[dict[str, Any]],
    root_id: str,
    track_index: int,
    composition_duration: float,
) -> str:
    css_to_use = (
        CAPTION_CSS
        if root_id == "main"
        else (STAGE_CAPTION_CSS if root_id == "stage" else ROOT_CAPTION_CSS)
    )
    caption_html = [BEGIN_MARKER, css_to_use]
    for index, cue in enumerate(groups, start=1):
        duration = cue["end"] - cue["start"]
        if duration <= 0 or cue["end"] > composition_duration:
            raise ValueError("caption cue falls outside the composition render duration")
        caption_html.append(
            f'<div id="om-asr-caption-{index}" class="clip om-asr-caption" '
            f'data-start="{cue["start"]:.3f}" data-duration="{duration:.3f}" '
            f'data-track-index="{track_index}">{html.escape(cue["text"], quote=True)}</div>'
        )
    caption_html.append(END_MARKER)
    return "\n".join(caption_html)


def install_captions(
    composition_path: Path | str,
    audio_path: Path | str,
    timings_path: Path | str,
    *,
    allowed_root: Path | str | None = None,
) -> int:
    comp_resolved, audio_resolved, timings_resolved = _validate_install_paths(
        composition_path, audio_path, timings_path, allowed_root
    )
    with open(comp_resolved, "r", encoding="utf-8") as f:
        source = f.read()
    with open(timings_resolved, "r", encoding="utf-8") as f:
        timings = json.load(f)
    with open(audio_resolved, "rb") as f:
        audio_bytes = f.read()
    words = _validate_timings_payload(timings, audio_bytes)

    composition_base, managed_span = _remove_managed_block(source)
    parser = CompositionParser(composition_base)
    root_id, composition_duration, closing_offset = _validate_composition_root(parser, source)

    parsed_words = _parse_and_validate_words(words, composition_duration)
    track_index = max(parser.track_indices, default=-1) + 1
    if track_index < 0:
        raise ValueError("could not allocate a caption track")
    groups = _cue_groups(parsed_words)
    managed_block = _build_caption_block(groups, root_id, track_index, composition_duration)

    if managed_span is not None:
        start, end = managed_span
        updated = source[:start] + managed_block + source[end:]
    else:
        insertion = "\n" + managed_block + "\n"
        updated = composition_base[:closing_offset] + insertion + composition_base[closing_offset:]

    comp_parent = comp_resolved.parent
    tmp_comp = comp_parent / f"{comp_resolved.name}.tmp.{uuid.uuid4().hex}"
    try:
        with open(tmp_comp, "w", encoding="utf-8") as out_fh:
            out_fh.write(updated)
        try:
            shutil.copymode(comp_resolved, tmp_comp)
        except OSError:
            pass
        os.replace(tmp_comp, comp_resolved)
    finally:
        if tmp_comp.exists():
            try:
                tmp_comp.unlink()
            except OSError:
                pass
    return len(groups)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("composition", type=str)
    parser.add_argument("audio", type=str)
    parser.add_argument("timings", type=str)
    parser.add_argument("--allowed-root", type=str, default=None, help="Optional boundary root directory")
    args = parser.parse_args(argv)
    try:
        count = install_captions(args.composition, args.audio, args.timings, allowed_root=args.allowed_root)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Caption installation failed: {exc}", file=sys.stderr)
        return 1
    print(f"Installed {count} seek-safe ASR caption clips in {args.composition}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
