#!/usr/bin/env python3
"""Install validated ASR caption clips into a daily-news HyperFrames composition."""

from __future__ import annotations

import argparse
import hashlib
import html
from html.parser import HTMLParser
import json
import math
from pathlib import Path
import re
import sys


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
  z-index: 2147483000;
  left: 7%;
  right: 7%;
  bottom: 4%;
  box-sizing: border-box;
  max-height: 12%;
  overflow: hidden;
  padding: 0.45em 0.7em;
  border-radius: 0.22em;
  background: rgba(0, 0, 0, 0.86);
  color: #fff;
  font: 700 4vw/1.2 sans-serif;
  text-align: center;
  text-wrap: balance;
  overflow-wrap: anywhere;
}
</style>"""
LEGACY_CAPTION_CSS = CAPTION_CSS.replace(
    "#main { position: relative; }",
    '[data-composition-id="main"] { position: relative; }',
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
        re.escape(style) for style in (CAPTION_CSS, LEGACY_CAPTION_CSS)
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


def install_captions(composition_path: Path, audio_path: Path, timings_path: Path) -> int:
    composition_path = Path(composition_path)
    audio_path = Path(audio_path)
    timings_path = Path(timings_path)
    source = composition_path.read_text(encoding="utf-8")
    timings = json.loads(timings_path.read_text(encoding="utf-8"))

    if not isinstance(timings, dict) or timings.get("timing_source") != "asr":
        raise ValueError("caption timings must declare timing_source='asr'")
    if timings.get("timing_verified") is not False:
        raise ValueError("caption timing verification must remain unasserted")
    audio_hash = hashlib.sha256(audio_path.read_bytes()).hexdigest()
    if timings.get("audio_sha256") != audio_hash:
        raise ValueError("caption timing audio_sha256 does not match composition audio")
    words = timings.get("word_timestamps")
    if not isinstance(words, list) or not words:
        raise ValueError("caption timing JSON has no word_timestamps")

    composition_base, managed_span = _remove_managed_block(source)
    parser = CompositionParser(composition_base)
    if len(parser.root_records) != 1:
        raise ValueError("expected exactly one main HyperFrames composition root")
    tag, attrs, _, closing_offset, parent = parser.root_records[0]
    if parent != "body" or closing_offset is None:
        raise ValueError("main composition root must be a closed direct child of body")
    if attrs.get("id") != "main":
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
    if not re.search(r"window\.__timelines\s*\[\s*(['\"])main\1\s*\]", source):
        raise ValueError("unsupported composition: expected timeline registered as window.__timelines['main']")

    if parser.has_existing_caption_markup:
        raise ValueError("unsupported composition: existing caption markup must be removed or explicitly migrated")

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

    track_index = max(parser.track_indices, default=-1) + 1
    if track_index < 0:
        raise ValueError("could not allocate a caption track")
    groups = _cue_groups(parsed_words)
    caption_html = [BEGIN_MARKER, CAPTION_CSS]
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
    managed_block = "\n".join(caption_html)
    if managed_span is not None:
        start, end = managed_span
        updated = source[:start] + managed_block + source[end:]
    else:
        insertion = "\n" + managed_block + "\n"
        updated = composition_base[:closing_offset] + insertion + composition_base[closing_offset:]
    composition_path.write_text(updated, encoding="utf-8")
    return len(groups)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("composition", type=Path)
    parser.add_argument("audio", type=Path)
    parser.add_argument("timings", type=Path)
    args = parser.parse_args(argv)
    try:
        count = install_captions(args.composition, args.audio, args.timings)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Caption installation failed: {exc}", file=sys.stderr)
        return 1
    print(f"Installed {count} seek-safe ASR caption clips in {args.composition}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
