#!/usr/bin/env python3
"""Deterministic news template materializer.

Generates production HyperFrames composition HTML from a template package
and a validated content instance. No free-form HTML is produced.
"""

from __future__ import annotations

import argparse
import hashlib
import html as html_mod
import json
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CATALOG_PATH = ROOT / "templates" / "news" / "catalog.json"
TEMPLATES_DIR = ROOT / "templates" / "news" / "packages"

ALLOWED_PACKAGES = {"news-debate", "news-evidence", "news-explainer"}
DEFAULT_VERSION = "1.0.0"
GSAP_CDN = "https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"


def esc(text: Any) -> str:
    return html_mod.escape(str(text), quote=True)


def _fmt_time(t: float) -> str:
    val = round(float(t), 2)
    if val == int(val):
        return str(int(val))
    return str(val)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_package_schema(package_id: str) -> dict[str, Any]:
    schema_path = TEMPLATES_DIR / package_id / "content.schema.json"
    if not schema_path.exists():
        raise FileNotFoundError(f"Schema not found: {schema_path}")
    return json.loads(schema_path.read_text(encoding="utf-8"))


def validate_content(content: dict[str, Any], package_id: str) -> None:
    schema = load_package_schema(package_id)
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(content), key=lambda e: list(e.path))
    if errors:
        msgs = [
            f"  {'.'.join(str(p) for p in e.path) or '<root>'}: {e.message}"
            for e in errors[:10]
        ]
        raise ValueError(
            f"Content validation failed for {package_id} ({len(errors)} errors):\n" + "\n".join(msgs)
        )


def derive_captions(narration: str, duration: float, max_captions: int) -> list[dict[str, Any]]:
    words = (narration or "").split()
    if not words:
        return []

    n_caps = min(max_captions, max(1, len(words)))
    seg_dur = float(duration) / n_caps

    cues: list[dict[str, Any]] = []
    words_per_cap = max(1, len(words) // n_caps)
    for i in range(n_caps):
        chunk = words[
            i * words_per_cap : (i + 1) * words_per_cap if i < n_caps - 1 else len(words)
        ]
        text = " ".join(chunk).strip()
        if not text:
            continue

        start = round(i * seg_dur + 0.5, 2)
        end = round(min((i + 1) * seg_dur - 0.5, float(duration)), 2)
        if end <= start:
            end = min(start + 2.0, float(duration))

        cues.append({"text": text, "start": start, "end": end})

    return cues


def _caption_elements(captions: list[dict[str, Any]], track_index: int) -> tuple[str, str]:
    html_parts: list[str] = []
    tl_parts: list[str] = []
    for i, cap in enumerate(captions[:6]):
        start = float(cap.get("start", 0.0))
        end = float(cap.get("end", 45.0))
        dur = max(0.5, end - start)
        text = esc(cap.get("text", ""))
        start_attr = _fmt_time(start)
        dur_attr = _fmt_time(dur)
        html_parts.append(
            f"    <div id=\"caption-{i}\" class=\"caption clip\" "
            f"data-start=\"{start_attr}\" data-duration=\"{dur_attr}\" data-track-index=\"{track_index}\">{text}</div>"
        )
        tl_parts.append(
            f"      tl.from('#caption-{i}', {{ opacity: 0, y: 14, duration: 0.4 }}, {start_attr});"
        )

    return "\n".join(html_parts), "\n".join(tl_parts)


def _scene_timing(content: dict[str, Any], total: float, variant: str) -> dict[str, tuple[float, float]]:
    slots = content.get("slots", {}) if isinstance(content.get("slots"), dict) else {}

    def slot_range(key: str, default_start: float, default_end: float) -> tuple[float, float]:
        s = slots.get(key, {}) if isinstance(slots.get(key), dict) else {}
        start = float(s.get("start", default_start))
        end = float(s.get("end", default_end))
        start = max(0.0, min(start, total))
        end = max(start, min(end, total))
        if end <= start:
            end = min(start + 4.0, total)
        return start, end

    if variant == "full":
        return {
            "hook": slot_range("hook", 0, 8),
            "statement": slot_range("statement", 8, 22),
            "context": slot_range("context", 22, 36),
            "takeaway": slot_range("takeaway", 36, total),
        }

    return {
        "hook": slot_range("hook", 0, 10),
        "statement": slot_range("statement", 10, 28),
        "takeaway": slot_range("takeaway", 28, total),
    }


def _build_debate_html(content: dict[str, Any], variant: str) -> str:
    is_full = variant == "full"
    total = float(content.get("duration", 45.0 if variant == "full" else 40.0))
    if not is_full:
        total = min(total, 58.0)
    timing = _scene_timing(content, total, variant)

    slots = content.get("slots", {}) if isinstance(content.get("slots"), dict) else {}
    hook = slots.get("hook", {}) if isinstance(slots.get("hook"), dict) else {}
    stmt = slots.get("statement", {}) if isinstance(slots.get("statement"), dict) else {}
    ctx = slots.get("context", {}) if isinstance(slots.get("context"), dict) else {}
    tkw = slots.get("takeaway", {}) if isinstance(slots.get("takeaway"), dict) else {}

    e_kicker = esc(content.get("kicker", "TIN NÓNG"))
    e_title = esc(content.get("title", ""))

    e_hook_text = esc(hook.get("text", ""))
    e_stmt_head = esc(stmt.get("heading", "Ý kiến"))
    e_stmt_text = esc(stmt.get("text", ""))
    e_stmt_attr = esc(stmt.get("attribution", ""))

    e_ctx_head = esc(ctx.get("heading", "Bối cảnh"))
    e_ctx_text = esc(ctx.get("text", ""))

    e_tkw_head = esc(tkw.get("heading", "Lời kết"))
    e_tkw_text = esc(tkw.get("text", ""))

    is_full = variant == "full"

    narration_key = "narration" if is_full else "narration_short"
    # Reels falls back to the full narration when no dedicated short narration
    # is supplied, so captions never render empty for the reels variant.
    narration_src = content.get(narration_key) or (content.get("narration") if not is_full else "")
    narration = esc(narration_src)

    # captions
    max_caps = 4 if is_full else 3
    captions = content.get("caption_lines")
    if not captions:
        captions = derive_captions(narration_src, total, max_caps)

    cap_html, cap_tl = _caption_elements(captions, track_index=10)

    s1_start, s1_dur = timing["hook"]
    s2_start, s2_dur = timing["statement"]
    s4_start, s4_dur = timing["takeaway"]

    attr_line = (
        f"        <p id=\"statement-attribution\" class=\"attribution\">{e_stmt_attr}</p>\n"
        if e_stmt_attr
        else ""
    )

    attr_tl = (
        f"      tl.from('#statement-attribution', {{ opacity: 0, duration: 0.5, ease: 'power2.out' }}, {_fmt_time(s2_start + 4)});\n"
        if e_stmt_attr
        else ""
    )

    scene3_html = ""
    scene3_tl = ""
    if is_full and e_ctx_text:
        s3_start, s3_dur = timing["context"]
        scene3_html = (
            f"    <section id=\"scene-context\" class=\"clip\" data-start=\"{_fmt_time(s3_start)}\" data-duration=\"{_fmt_time(s3_dur)}\" data-track-index=\"3\">\n"
            f"      <div class=\"scene-inner\">\n"
            f"        <span class=\"scene-heading\">{e_ctx_head}</span>\n"
            f"        <p class=\"scene-text\">{e_ctx_text}</p>\n"
            f"      </div>\n"
            f"    </section>\n"
        )
        scene3_tl = (
            f"      tl.from('#scene-context .scene-inner', {{ opacity: 0, y: 40, duration: 0.7, ease: 'power2.out' }}, {_fmt_time(s3_start + 0.1)});\n"
        )

    scene4_html = (
        f"    <section id=\"scene-takeaway\" class=\"clip\" data-start=\"{_fmt_time(s4_start)}\" data-duration=\"{_fmt_time(s4_dur)}\" data-track-index=\"{4 if is_full else 3}\">\n"
        f"      <div class=\"scene-inner\">\n"
        f"        <span class=\"kicker\" style=\"font-size:22px\">{e_tkw_head}</span>\n"
        f"        <p class=\"scene-text\">{e_tkw_text}</p>\n"
        f"      </div>\n"
        f"    </section>\n"
    )

    scene4_tl = (
        f"      tl.from('#scene-takeaway .scene-inner', {{ opacity: 0, y: 40, duration: 0.6, ease: 'power2.out' }}, {_fmt_time(s4_start + 0.1)});\n"
    )

    font_size_title = "56px" if is_full else "48px"
    font_size_text = "34px" if is_full else "30px"

    accent = "#e63946"
    css = (
        f"<style>\n"
        f":root {{ --accent: {accent}; }}\n"
        f"* {{ box-sizing: border-box; }}\n"
        f"body {{ margin:0;background:#0a0a14;color:#f1f1f1;font-family:'BeVietnamPro',Inter,system-ui,sans-serif; }}\n"
        f"#root {{ position:relative;width:1080px;height:1920px;overflow:hidden;background:#0a0a14; }}\n"
        f".bg-fill {{ position:absolute;inset:0;background:radial-gradient(ellipse at 30% 40%,rgba(230,57,70,.08) 0%,transparent 60%); }}\n"
        f".clip {{ position:absolute;inset:0; }}\n"
        f".scene-inner {{ display:flex;flex-direction:column;justify-content:center;align-items:center;width:100%;height:100%;padding:120px 80px 160px;text-align:center; }}\n"
        f".kicker {{ font-size:24px;font-weight:700;letter-spacing:.35em;text-transform:uppercase;color:var(--accent);margin-bottom:32px;padding:8px 24px;border:2px solid var(--accent);border-radius:6px; }}\n"
        f".title {{ font-size:{font_size_title};font-weight:900;line-height:1.15;color:#fff;max-width:900px;margin:0 auto 40px; }}\n"
        f".scene-text {{ font-size:{font_size_text};font-weight:400;line-height:1.6;color:#ccc;max-width:860px;margin:0; }}\n"
        f".scene-heading {{ font-size:28px;font-weight:700;letter-spacing:.15em;text-transform:uppercase;color:var(--accent);margin-bottom:36px; }}\n"
        f".statement {{ font-size:40px;font-weight:300;line-height:1.5;color:#fff;max-width:860px;margin:0 auto 32px;font-style:italic;border-left:3px solid var(--accent);padding-left:32px;text-align:left; }}\n"
        f".attribution {{ font-size:24px;font-weight:600;color:#aaa;margin:0;max-width:860px;text-align:left; }}\n"
        f".caption {{ position:absolute;bottom:64px;left:60px;right:60px;display:flex;align-items:center;justify-content:center;font-size:32px;font-weight:700;color:#fff;text-shadow:0 2px 12px rgba(0,0,0,.95);text-align:center;padding:16px 0; }}\n"
        f"</style>"
    )

    gsap = (
        "<script>\n"
        "(function() {\n"
        "  window.__timelines = window.__timelines || {};\n"
        "  var tl = gsap.timeline({ paused: true });\n"
        f"  tl.from('#scene-hook .scene-inner', {{ opacity: 0, y: 40, duration: {0.7 if is_full else 0.6}, ease: 'power2.out' }}, {_fmt_time(s1_start + 0.1)});\n"
        f"  tl.from('#scene-statement .scene-inner', {{ opacity: 0, y: 40, duration: {0.7 if is_full else 0.6}, ease: 'power2.out' }}, {_fmt_time(s2_start + 0.1)});\n"
        f"{attr_tl}"
        f"{scene3_tl}"
        f"{scene4_tl}"
        f"{cap_tl}"
        "  window.__timelines.main = tl;\n"
        "})();\n"
        "</script>"
    )

    audio_src = "assets/narration.mp3" if is_full else "assets/narration_reels.mp3"

    title_tag = f"<title>{e_title} — news-debate</title>"

    html = (
        "<!doctype html>\n"
        "<html lang=\"vi\">\n"
        "<head>\n"
        "  <meta charset=\"UTF-8\" />\n"
        "  <meta name=\"viewport\" content=\"width=1080, height=1920\" />\n"
        f"  {title_tag}\n"
        f"  <script src=\"{GSAP_CDN}\"></script>\n"
        f"  {css}\n"
        "</head>\n"
        "<body>\n"
        f"  <div id=\"root\" data-composition-id=\"main\" data-width=\"1080\" data-height=\"1920\" data-duration=\"{_fmt_time(total)}\">\n"
        "    <div class=\"bg-fill\"></div>\n"
        f"    <audio id=\"narration\" class=\"clip\" data-start=\"0\" data-duration=\"{_fmt_time(total)}\" data-track-index=\"0\" src=\"{audio_src}\"></audio>\n"
        "    <audio id=\"music-bg\" class=\"clip\" data-start=\"0\" data-duration=\"{_fmt_time(total)}\" data-track-index=\"0\" src=\"assets/music-bg.mp3\"></audio>\n"
        f"    <section id=\"scene-hook\" class=\"clip\" data-start=\"{_fmt_time(s1_start)}\" data-duration=\"{_fmt_time(s1_dur)}\" data-track-index=\"1\">\n"
        "      <div class=\"scene-inner\">\n"
        f"        <span class=\"kicker\">{e_kicker}</span>\n"
        f"        <h1 class=\"title\">{e_title}</h1>\n"
        f"        <p class=\"scene-text\">{e_hook_text}</p>\n"
        "      </div>\n"
        "    </section>\n"
        f"    <section id=\"scene-statement\" class=\"clip\" data-start=\"{_fmt_time(s2_start)}\" data-duration=\"{_fmt_time(s2_dur)}\" data-track-index=\"2\">\n"
        "      <div class=\"scene-inner\">\n"
        f"        <span class=\"scene-heading\">{e_stmt_head}</span>\n"
        f"        <blockquote class=\"statement\">{e_stmt_text}</blockquote>\n"
        f"{attr_line}"
        "      </div>\n"
        "    </section>\n"
        f"{scene3_html}"
        f"{scene4_html}"
        f"{cap_html}"
        "  </div>\n"
        f"  {gsap}\n"
        "</body>\n"
        "</html>\n"
    )

    return html


def _build_evidence_html(content: dict[str, Any], variant: str) -> str:
    is_full = variant == "full"
    total = float(content.get("duration", 45.0 if is_full else 40.0))
    if not is_full:
        total = min(total, 58.0)
    s1_dur = 8.0 if is_full else 10.0
    s2_start = 8.0 if is_full else 10.0
    s2_dur = 14.0 if is_full else 16.0
    s3_start = 22.0 if is_full else 20.0
    s3_dur = 14.0 if is_full else 15.0
    s4_start = 36.0
    s4_dur = 9.0

    slots = content.get("slots", {}) if isinstance(content.get("slots"), dict) else {}
    hook = slots.get("hook", {}) if isinstance(slots.get("hook"), dict) else {}
    metric = slots.get("metric", {}) if isinstance(slots.get("metric"), dict) else {}
    comp = slots.get("comparison", {}) if isinstance(slots.get("comparison"), dict) else {}
    caveat = slots.get("caveat", {}) if isinstance(slots.get("caveat"), dict) else {}

    e_kicker = esc(content.get("kicker", "SỐ LIỆU"))
    e_title = esc(content.get("title", ""))
    e_hook_text = esc(hook.get("text", ""))

    e_metric_value = esc(metric.get("label", metric.get("text", "")))
    e_metric_desc = esc(metric.get("text", metric.get("heading", "")))

    e_comp_label = esc(comp.get("label", "So sánh"))
    e_comp_text = esc(comp.get("text", ""))

    e_caveat_head = esc(caveat.get("heading", "Điều cần lưu ý"))
    e_caveat_text = esc(caveat.get("text", ""))

    narration_key = "narration" if is_full else "narration_short"
    narration_src = content.get(narration_key) or (content.get("narration") if not is_full else "")
    max_caps = 4 if is_full else 3

    captions = content.get("caption_lines")
    if not captions:
        captions = derive_captions(narration_src, total, max_caps)

    cap_html, cap_tl = _caption_elements(captions, track_index=10)

    audio_src = "assets/narration.mp3" if is_full else "assets/narration_reels.mp3"

    include_caveat = is_full and bool(e_caveat_text)

    metric_tl = (
        f"      tl.from('#metric-value', {{ opacity: 0, scale: 0.82, duration: 0.8, ease: 'back.out(1.4)' }}, {_fmt_time(s2_start + 0.5)});\n"
    )

    caveat_html = ""
    caveat_tl = ""
    if include_caveat:
        caveat_html = (
            f"    <section id=\"scene-caveat\" class=\"clip\" data-start=\"{_fmt_time(s4_start)}\" data-duration=\"{_fmt_time(s4_dur)}\" data-track-index=\"4\">\n"
            "      <div class=\"scene-inner\">\n"
            f"        <span class=\"kicker\">{e_caveat_head}</span>\n"
            f"        <p class=\"scene-text\">{e_caveat_text}</p>\n"
            "      </div>\n"
            "    </section>\n"
        )
        caveat_tl = (
            f"      tl.from('#scene-caveat .scene-inner', {{ opacity: 0, y: 40, duration: 0.6, ease: 'power2.out' }}, {_fmt_time(s4_start + 0.1)});\n"
        )

    css = (
        "<style>\n"
        ":root { --accent: #3b82f6; }\n"
        "* { box-sizing: border-box; }\n"
        "body { margin:0;background:#08111f;color:#f1f1f1;font-family:'BeVietnamPro',Inter,system-ui,sans-serif; }\n"
        "#root { position:relative;width:1080px;height:1920px;overflow:hidden;background:#08111f; }\n"
        ".bg-fill { position:absolute;inset:0;background:radial-gradient(ellipse at 75% 25%,rgba(59,130,246,.14) 0%,transparent 58%),linear-gradient(160deg,#08111f 0%,#0d1b32 100%); }\n"
        ".clip { position:absolute;inset:0; }\n"
        ".scene-inner { display:flex;flex-direction:column;justify-content:center;align-items:center;width:100%;height:100%;padding:110px 70px 170px;text-align:center; }\n"
        ".kicker { font-size:22px;font-weight:700;letter-spacing:.3em;text-transform:uppercase;color:var(--accent);margin-bottom:24px;padding:6px 20px;border:2px solid var(--accent);border-radius:6px; }\n"
        f".title {{ font-size:{'56px' if is_full else '48px'};font-weight:900;line-height:1.15;color:#fff;max-width:900px;margin:0 auto 40px; }}\n"
        f".scene-text {{ font-size:{'34px' if is_full else '30px'};font-weight:400;line-height:1.5;color:#d5deed;max-width:900px;margin:0; }}\n"
        ".metric-card { width:100%; max-width:820px; padding:58px 60px; border:1px solid rgba(130,180,255,.35); border-radius:16px; background:rgba(59,130,246,.10); }\n"
        f".metric-value {{ font-size:{'112px' if is_full else '88px'};line-height:1;font-weight:900;color:var(--accent);margin:0 0 18px; }}\n"
        ".metric-label { font-size:28px;line-height:1.4;color:#d5deed;margin:0; }\n"
        ".comparison-card { width:100%; max-width:860px; text-align:left; padding:42px 48px; border-left:4px solid var(--accent); background:rgba(255,255,255,.04); }\n"
        ".comparison-label { font-size:26px; color:#91b8f4; margin-bottom:16px; }\n"
        ".comparison-text { font-size:36px; line-height:1.45; color:#fff; margin:0; }\n"
        ".caption { position:absolute;bottom:64px;left:60px;right:60px;display:flex;align-items:center;justify-content:center;font-size:32px;font-weight:700;color:#fff;text-shadow:0 2px 12px rgba(0,0,0,.95);text-align:center;padding:16px 0; }\n"
        "</style>"
    )

    gsap = (
        "<script>\n"
        "(function() {\n"
        "  window.__timelines = window.__timelines || {};\n"
        "  var tl = gsap.timeline({ paused: true });\n"
        f"  tl.from('#scene-hook .scene-inner', {{ opacity: 0, y: 40, duration: 0.7, ease: 'power2.out' }}, 0.1);\n"
        f"  tl.from('#scene-metric .scene-inner', {{ opacity: 0, y: 40, duration: 0.7, ease: 'power2.out' }}, {_fmt_time(s2_start + 0.1)});\n"
        f"{metric_tl}"
        f"  tl.from('#scene-comparison .scene-inner', {{ opacity: 0, y: 40, duration: 0.7, ease: 'power2.out' }}, {_fmt_time(s3_start + 0.1)});\n"
        f"{caveat_tl}"
        f"{cap_tl}"
        "  window.__timelines.main = tl;\n"
        "})();\n"
        "</script>"
    )

    caveat_section = caveat_html

    html = (
        "<!doctype html>\n"
        "<html lang=\"vi\">\n"
        "<head>\n"
        "  <meta charset=\"UTF-8\" />\n"
        "  <meta name=\"viewport\" content=\"width=1080, height=1920\" />\n"
        f"  <title>{e_title} — news-evidence</title>\n"
        f"  <script src=\"{GSAP_CDN}\"></script>\n"
        f"  {css}\n"
        "</head>\n"
        "<body>\n"
        f"  <div id=\"root\" data-composition-id=\"main\" data-width=\"1080\" data-height=\"1920\" data-duration=\"{_fmt_time(total)}\">\n"
        "    <div class=\"bg-fill\"></div>\n"
        f"    <audio id=\"narration\" class=\"clip\" data-start=\"0\" data-duration=\"{_fmt_time(total)}\" data-track-index=\"0\" src=\"{audio_src}\"></audio>\n"
        f"    <audio id=\"music-bg\" class=\"clip\" data-start=\"0\" data-duration=\"{_fmt_time(total)}\" data-track-index=\"0\" src=\"assets/music-bg.mp3\"></audio>\n"
        f"    <section id=\"scene-hook\" class=\"clip\" data-start=\"0\" data-duration=\"{_fmt_time(s1_dur)}\" data-track-index=\"1\">\n"
        "      <div class=\"scene-inner\">\n"
        f"        <span class=\"kicker\">{e_kicker}</span>\n"
        f"        <h1 class=\"title\">{e_title}</h1>\n"
        f"        <p class=\"scene-text\">{e_hook_text}</p>\n"
        "      </div>\n"
        "    </section>\n"
        f"    <section id=\"scene-metric\" class=\"clip\" data-start=\"{_fmt_time(s2_start)}\" data-duration=\"{_fmt_time(s2_dur)}\" data-track-index=\"2\">\n"
        "      <div class=\"scene-inner\">\n"
        "        <div class=\"metric-card\">\n"
        f"          <p id=\"metric-value\" class=\"metric-value\">{e_metric_value}</p>\n"
        f"          <p class=\"metric-label\">{e_metric_desc}</p>\n"
        "          <div class=\"comparison-label\">{e_comp_label}</div>\n"
        f"          <p class=\"comparison-text\">{e_comp_text}</p>\n"
        "        </div>\n"
        "      </div>\n"
        "    </section>\n"
        f"    <section id=\"scene-comparison\" class=\"clip\" data-start=\"{_fmt_time(s3_start)}\" data-duration=\"{_fmt_time(s3_dur)}\" data-track-index=\"3\">\n"
        "      <div class=\"scene-inner\">\n"
        f"        <span class=\"kicker\">{e_comp_label}</span>\n"
        f"        <p class=\"scene-text\">{e_comp_text}</p>\n"
        "      </div>\n"
        "    </section>\n"
        f"{caveat_section}"
        f"{cap_html}"
        "  </div>\n"
        f"  {gsap}\n"
        "</body>\n"
        "</html>\n"
    )

    return html


def _build_explainer_html(content: dict[str, Any], variant: str) -> str:
    is_full = variant == "full"
    total = float(content.get("duration", 45.0 if is_full else 40.0))
    if not is_full:
        total = min(total, 58.0)

    slots = content.get("slots", {}) if isinstance(content.get("slots"), dict) else {}
    hook = slots.get("hook", {}) if isinstance(slots.get("hook"), dict) else {}
    cap = slots.get("capability", {}) if isinstance(slots.get("capability"), dict) else {}
    steps = slots.get("steps", {}) if isinstance(slots.get("steps"), dict) else {}
    lim = slots.get("limitations", {}) if isinstance(slots.get("limitations"), dict) else {}

    e_kicker = esc(content.get("kicker", "HƯỚNG DẪN"))
    e_title = esc(content.get("title", ""))
    e_hook_text = esc(hook.get("text", ""))

    e_cap_label = esc(cap.get("label", ""))
    e_cap_text = esc(cap.get("text", ""))

    e_steps_text = esc(steps.get("text", ""))

    e_lim_head = esc(lim.get("heading", "Hạn chế"))
    e_lim_text = esc(lim.get("text", ""))

    narration_key = "narration" if is_full else "narration_short"
    narration_src = content.get(narration_key) or (content.get("narration") if not is_full else "")
    narration = esc(narration_src)

    max_caps = 4 if is_full else 3
    captions = content.get("caption_lines")
    if not captions:
        captions = derive_captions(narration_src, total, max_caps)

    cap_html, cap_tl = _caption_elements(captions, track_index=10)

    audio_src = "assets/narration.mp3" if is_full else "assets/narration_reels.mp3"

    include_lim = is_full and bool(e_lim_text)

    # timings
    s1_dur = 8.0 if is_full else 10.0
    s2_start = 8.0 if is_full else 10.0
    s2_dur = 14.0 if is_full else 18.0
    s3_start = 22.0 if is_full else 28.0
    s3_dur = 14.0 if is_full else 12.0
    s4_start = 36.0
    s4_dur = 9.0

    css = (
        "<style>\n"
        ":root { --accent: #06d6a0; }\n"
        "* { box-sizing: border-box; }\n"
        "body { margin:0;background:#0a1410;color:#f1f1f1;font-family:'BeVietnamPro',Inter,system-ui,sans-serif; }\n"
        "#root { position:relative;width:1080px;height:1920px;overflow:hidden;background:#0a1410; }\n"
        ".bg-fill { position:absolute;inset:0;background:radial-gradient(ellipse at 30% 80%,rgba(6,214,160,.08) 0%,transparent 55%),linear-gradient(180deg,#0a1410 0%,#0d1f1a 100%); }\n"
        ".clip { position:absolute;inset:0; }\n"
        ".scene-inner { display:flex;flex-direction:column;justify-content:center;align-items:center;width:100%;height:100%;padding:110px 70px 170px;text-align:center; }\n"
        f".kicker {{ font-size:22px;font-weight:700;letter-spacing:.35em;text-transform:uppercase;color:var(--accent);margin-bottom:24px;padding:8px 24px;border:2px solid var(--accent);border-radius:6px; }}\n"
        f".title {{ font-size:{'56px' if is_full else '48px'};font-weight:900;line-height:1.15;color:#fff;max-width:900px;margin:0 auto 40px; }}\n"
        f".scene-text {{ font-size:{'34px' if is_full else '30px'};font-weight:400;line-height:1.6;color:#c8d8d4;max-width:860px;margin:0; }}\n"
        f".capability-card {{ width:100%;max-width:{'820px' if is_full else '780px'};padding:40px 48px;border:1px solid rgba(6,214,160,.3);border-radius:14px;background:rgba(6,214,160,.07); }}\n"
        f".capability-label {{ display:block;font-size:26px;font-weight:700;color:var(--accent);margin-bottom:14px; }}\n"
        f".capability-text {{ font-size:{'36px' if is_full else '32px'};line-height:1.45;color:#fff;margin:0; }}\n"
        f".caption {{ position:absolute;bottom:64px;left:60px;right:60px;display:flex;align-items:center;justify-content:center;font-size:32px;font-weight:700;color:#fff;text-shadow:0 2px 12px rgba(0,0,0,.95);text-align:center;padding:16px 0; }}\n"
        ".limitation-box { width:100%;max-width:820px;padding:42px 48px;border:1px solid rgba(255,255,255,.12);border-left:4px solid var(--accent);border-radius:12px;background:rgba(255,255,255,.03);text-align:left; }\n"
        ".limitation-box p { font-size:28px;line-height:1.5;color:#c8d8d4;margin:0; }\n"
        ".steps-box { width:100%;max-width:820px; }\n"
        "</style>"
    )

    lim_section = ""
    lim_tl = ""
    if include_lim:
        lim_section = (
            f"    <section id=\"scene-limitations\" class=\"clip\" data-start=\"{_fmt_time(s4_start)}\" data-duration=\"{_fmt_time(s4_dur)}\" data-track-index=\"4\">\n"
            "      <div class=\"scene-inner\">\n"
            f"        <span class=\"kicker\">{e_lim_head}</span>\n"
            f"        <div class=\"limitation-box\"><p>{e_lim_text}</p></div>\n"
            "      </div>\n"
            "    </section>\n"
        )
        lim_tl = (
            f"      tl.from('#scene-limitations .scene-inner', {{ opacity: 0, y: 40, duration: 0.6, ease: 'power2.out' }}, {_fmt_time(s4_start + 0.1)});\n"
        )

    gsap = (
        "<script>\n"
        "(function() {\n"
        "  window.__timelines = window.__timelines || {};\n"
        "  var tl = gsap.timeline({ paused: true });\n"
        f"  tl.from('#scene-hook .scene-inner', {{ opacity: 0, y: 40, duration: 0.6, ease: 'power2.out' }}, 0.1);\n"
        f"  tl.from('#scene-capability .scene-inner', {{ opacity: 0, y: 40, duration: 0.6, ease: 'power2.out' }}, {_fmt_time(s2_start + 0.1)});\n"
        f"  tl.from('.capability-card', {{ opacity: 0, scale: 0.9, duration: 0.8, ease: 'back.out(1.4)' }}, {_fmt_time(s2_start + 0.5)});\n"
        f"  tl.from('#scene-steps .scene-inner', {{ opacity: 0, y: 40, duration: 0.6, ease: 'power2.out' }}, {_fmt_time(s3_start + 0.1)});\n"
        f"{lim_tl}"
        f"{cap_tl}"
        "  window.__timelines.main = tl;\n"
        "})();\n"
        "</script>"
    )

    html = (
        "<!doctype html>\n"
        "<html lang=\"vi\">\n"
        "<head>\n"
        "  <meta charset=\"UTF-8\" />\n"
        "  <meta name=\"viewport\" content=\"width=1080, height=1920\" />\n"
        f"  <title>{e_title} — news-explainer</title>\n"
        f"  <script src=\"{GSAP_CDN}\"></script>\n"
        f"  {css}\n"
        "</head>\n"
        "<body>\n"
        f"  <div id=\"root\" data-composition-id=\"main\" data-width=\"1080\" data-height=\"1920\" data-duration=\"{_fmt_time(total)}\">\n"
        "    <div class=\"bg-fill\"></div>\n"
        f"    <audio id=\"narration\" class=\"clip\" data-start=\"0\" data-duration=\"{_fmt_time(total)}\" data-track-index=\"0\" src=\"{audio_src}\"></audio>\n"
        f"    <audio id=\"music-bg\" class=\"clip\" data-start=\"0\" data-duration=\"{_fmt_time(total)}\" data-track-index=\"0\" src=\"assets/music-bg.mp3\"></audio>\n"
        f"    <section id=\"scene-hook\" class=\"clip\" data-start=\"0\" data-duration=\"{_fmt_time(s1_dur)}\" data-track-index=\"1\">\n"
        "      <div class=\"scene-inner\">\n"
        f"        <span class=\"kicker\">{e_kicker}</span>\n"
        f"        <h1 class=\"title\">{e_title}</h1>\n"
        f"        <p class=\"scene-text\">{e_hook_text}</p>\n"
        "      </div>\n"
        "    </section>\n"
        f"    <section id=\"scene-capability\" class=\"clip\" data-start=\"{_fmt_time(s2_start)}\" data-duration=\"{_fmt_time(s2_dur)}\" data-track-index=\"2\">\n"
        "      <div class=\"scene-inner\">\n"
        "        <div class=\"capability-card\">\n"
        f"          <span class=\"capability-label\">{e_cap_label}</span>\n"
        f"          <p class=\"capability-text\">{e_cap_text}</p>\n"
        "        </div>\n"
        "      </div>\n"
        "    </section>\n"
        f"    <section id=\"scene-steps\" class=\"clip\" data-start=\"{_fmt_time(s3_start)}\" data-duration=\"{_fmt_time(s3_dur)}\" data-track-index=\"3\">\n"
        "      <div class=\"scene-inner\">\n"
        "        <span class=\"kicker\">CÁC BƯỚC</span>\n"
        f"        <p class=\"scene-text\">{e_steps_text}</p>\n"
        "      </div>\n"
        "    </section>\n"
        f"{lim_section}"
        f"{cap_html}"
        "  </div>\n"
        f"  {gsap}\n"
        "</body>\n"
        "</html>\n"
    )

    return html


def materialize(package_id: str, content: dict[str, Any], project_dir: Path, variant: str) -> dict[str, Any]:
    if package_id not in ALLOWED_PACKAGES:
        raise ValueError(f"Unknown package: {package_id}")

    validate_content(content, package_id)

    do_full = variant in {"full", "both"}
    do_short = variant in {"short", "both"}

    do_reels = do_short

    full_html = ""
    short_html = ""

    if do_full:
        full_html = (
            _build_debate_html(content, "full")
            if package_id == "news-debate"
            else _build_evidence_html(content, "full")
            if package_id == "news-evidence"
            else _build_explainer_html(content, "full")
        )

        out_full = project_dir / "hyperframes" / "index.html"
        out_full.parent.mkdir(parents=True, exist_ok=True)
        out_full.write_text(full_html, encoding="utf-8")

    if do_reels:
        short_html = (
            _build_debate_html(content, "reels")
            if package_id == "news-debate"
            else _build_evidence_html(content, "reels")
            if package_id == "news-evidence"
            else _build_explainer_html(content, "reels")
        )

        out_reels = project_dir / "hyperframes_reels" / "index.html"
        out_reels.parent.mkdir(parents=True, exist_ok=True)
        out_reels.write_text(short_html, encoding="utf-8")

    from tools.news import template_provenance

    provenance = template_provenance.record_provenance(
        project_dir=project_dir,
        template_id=package_id,
        template_version=DEFAULT_VERSION,
        content=content,
        full_html=full_html or None,
        reels_html=short_html or None,
        variant=variant,
    )
    return provenance


def main() -> int:
    parser = argparse.ArgumentParser(description="Materialize news template composition")
    parser.add_argument("--package", required=True, choices=sorted(ALLOWED_PACKAGES))
    parser.add_argument("--content", required=True, type=Path)
    parser.add_argument("--project-dir", required=True, type=Path)
    parser.add_argument("--variant", default="both", choices=["full", "short", "both"])
    args = parser.parse_args()

    content = json.loads(args.content.read_text(encoding="utf-8"))
    project_dir = args.project_dir

    result = materialize(args.package, content, project_dir, args.variant)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
