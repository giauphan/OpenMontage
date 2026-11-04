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

from lib.news_visual.hyperframes_adapter import build_media_layer_elements
from lib.news_visual.scene_layouts import render_scene_visual_html, visual_layout_css

CATALOG_PATH = ROOT / "templates" / "news" / "catalog.json"
TEMPLATES_DIR = ROOT / "templates" / "news" / "packages"

ALLOWED_PACKAGES = {"news-debate", "news-evidence", "news-explainer"}
DEFAULT_VERSION = "1.0.0"
GSAP_CDN = "https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"
HAS_VISUAL = " has-visual"
ASSET_NARRATION_FULL = "assets/narration.mp3"
ASSET_NARRATION_REELS = "assets/narration_reels.mp3"


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
    wpc = max(1, len(words) // n_caps)
    for i in range(n_caps):
        text = " ".join(words[i * wpc : ((i + 1) * wpc if i < n_caps - 1 else len(words))]).strip()
        if not text:
            continue
        start = round(i * seg_dur + 0.5, 2)
        end = round(min((i + 1) * seg_dur - 0.5, float(duration)), 2)
        cues.append({"text": text, "start": start, "end": end if end > start else min(start + 2.0, float(duration))})
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


def _slot_has_visual(slot: dict[str, Any]) -> str:
    return HAS_VISUAL if slot.get("visual") else ""


def _resolve_template_captions(content: dict[str, Any], total: float, is_full: bool) -> tuple[str, list[dict[str, Any]]]:
    key = "narration" if is_full else "narration_short"
    src = content.get(key) or (content.get("narration") if not is_full else "")
    caps = content.get("caption_lines") or derive_captions(src, total, 4 if is_full else 3)
    return str(src), caps


def _extract_slot_visuals(slots: dict[str, Any], total: float) -> tuple[str, str]:
    visual_htmls = []
    visual_tls = []
    for slot_name, slot_obj in slots.items():
        if isinstance(slot_obj, dict) and "visual" in slot_obj:
            v_spec = slot_obj["visual"]
            v_start = float(slot_obj.get("start", 0))
            v_end = float(slot_obj.get("end", total))
            v_dur = max(0.5, v_end - v_start)
            v_html = render_scene_visual_html(slot_name, v_spec, v_start, v_dur)
            if v_html:
                visual_htmls.append(v_html)
                visual_tls.append(
                    f"      tl.from('#visual-{slot_name} .visual-media-wrapper', {{ opacity: 0, scale: 0.95, duration: 0.6, ease: 'power2.out' }}, {_fmt_time(v_start)});"
                )
    return "\n".join(visual_htmls), "\n".join(visual_tls)


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


def _resolve_debate_slots(content: dict[str, Any]) -> tuple[dict, dict, dict, dict, dict, dict[str, str]]:
    slots = content.get("slots") if isinstance(content.get("slots"), dict) else {}
    hook = slots.get("hook") if isinstance(slots.get("hook"), dict) else {}
    stmt = slots.get("statement") if isinstance(slots.get("statement"), dict) else {}
    ctx = slots.get("context") if isinstance(slots.get("context"), dict) else {}
    tkw = slots.get("takeaway") if isinstance(slots.get("takeaway"), dict) else {}
    es = {
        "kicker": esc(content.get("kicker", "TIN NÓNG")),
        "title": esc(content.get("title", "")),
        "hook_text": esc(hook.get("text", "")),
        "stmt_head": esc(stmt.get("heading", "Ý kiến")),
        "stmt_text": esc(stmt.get("text", "")),
        "stmt_attr": esc(stmt.get("attribution", "")),
        "ctx_head": esc(ctx.get("heading", "Bối cảnh")),
        "ctx_text": esc(ctx.get("text", "")),
        "tkw_head": esc(tkw.get("heading", "Lời kết")),
        "tkw_text": esc(tkw.get("text", "")),
    }
    return slots, hook, stmt, ctx, tkw, es


def _resolve_debate_scenes(
    timing: dict[str, tuple[float, float]],
    es: dict[str, str],
    is_full: bool,
    ctx_v: str,
    tkw_v: str,
    s2_start: float,
) -> tuple[str, str, str, str, str, str]:
    attr_line = f'        <p id="statement-attribution" class="attribution">{es["stmt_attr"]}</p>\n' if es["stmt_attr"] else ""
    attr_tl = f"      tl.from('#statement-attribution', {{ opacity: 0, duration: 0.5, ease: 'power2.out' }}, {_fmt_time(s2_start + 4)});\n" if es["stmt_attr"] else ""
    scene3_html, scene3_tl = "", ""
    if is_full and es["ctx_text"]:
        s3_start, s3_dur = timing["context"]
        scene3_html = (
            f"    <section id=\"scene-context\" class=\"clip{ctx_v}\" data-start=\"{_fmt_time(s3_start)}\" data-duration=\"{_fmt_time(s3_dur)}\" data-track-index=\"3\">\n"
            f"      <div class=\"scene-inner\">\n"
            f"        <span class=\"scene-heading\">{es['ctx_head']}</span>\n"
            f"        <p class=\"scene-text\">{es['ctx_text']}</p>\n"
            f"      </div>\n"
            f"    </section>\n"
        )
        scene3_tl = f"      tl.from('#scene-context .scene-inner', {{ opacity: 0, y: 40, duration: 0.7, ease: 'power2.out' }}, {_fmt_time(s3_start + 0.1)});\n"

    s4_start, s4_end = timing["takeaway"]
    s4_dur = max(0.5, s4_end - s4_start)
    track_idx = 4 if is_full else 3
    scene4_html = (
        f"    <section id=\"scene-takeaway\" class=\"clip{tkw_v}\" data-start=\"{_fmt_time(s4_start)}\" data-duration=\"{_fmt_time(s4_dur)}\" data-track-index=\"{track_idx}\">\n"
        f"      <div class=\"scene-inner\">\n"
        f"        <span class=\"kicker\" style=\"font-size:22px\">{es['tkw_head']}</span>\n"
        f"        <p class=\"scene-text\">{es['tkw_text']}</p>\n"
        f"      </div>\n"
        f"    </section>\n"
    )
    scene4_tl = f"      tl.from('#scene-takeaway .scene-inner', {{ opacity: 0, y: 40, duration: 0.6, ease: 'power2.out' }}, {_fmt_time(s4_start + 0.1)});\n"
    return attr_line, attr_tl, scene3_html, scene3_tl, scene4_html, scene4_tl


def _build_debate_css(is_full: bool, media_css: str) -> str:
    title_sz = "56px" if is_full else "48px"
    text_sz = "34px" if is_full else "30px"
    return (
        f"<style>\n"
        f":root {{ --accent: #e63946; }}\n"
        f"* {{ box-sizing: border-box; }}\n"
        f"body {{ margin:0;background:#0a0a14;color:#f1f1f1;font-family:'BeVietnamPro',Inter,system-ui,sans-serif; }}\n"
        f"#root {{ position:relative;width:1080px;height:1920px;overflow:hidden;background:#0a0a14; }}\n"
        f".bg-fill {{ position:absolute;inset:0;background:radial-gradient(ellipse at 30% 40%,rgba(230,57,70,.08) 0%,transparent 60%); }}\n"
        f".clip {{ position:absolute;inset:0; }}\n"
        f".scene-inner {{ display:flex;flex-direction:column;justify-content:center;align-items:center;width:100%;height:100%;padding:120px 80px 160px;text-align:center; }}\n"
        f".kicker {{ font-size:24px;font-weight:700;letter-spacing:.35em;text-transform:uppercase;color:var(--accent);margin-bottom:32px;padding:8px 24px;border:2px solid var(--accent);border-radius:6px; }}\n"
        f".title {{ font-size:{title_sz};font-weight:900;line-height:1.15;color:#fff;max-width:900px;margin:0 auto 40px; }}\n"
        f".scene-text {{ font-size:{text_sz};font-weight:400;line-height:1.6;color:#ccc;max-width:860px;margin:0; }}\n"
        f".scene-heading {{ font-size:28px;font-weight:700;letter-spacing:.15em;text-transform:uppercase;color:var(--accent);margin-bottom:36px; }}\n"
        f".statement {{ font-size:40px;font-weight:300;line-height:1.5;color:#fff;max-width:860px;margin:0 auto 32px;font-style:italic;border-left:3px solid var(--accent);padding-left:32px;text-align:left; }}\n"
        f".attribution {{ font-size:24px;font-weight:600;color:#aaa;margin:0;max-width:860px;text-align:left; }}\n"
        f".caption {{ position:absolute;top:auto !important;bottom:96px !important;left:60px;right:60px;height:auto !important;min-height:56px;display:flex;align-items:center;justify-content:center;font-size:32px;font-weight:700;color:#fff;text-shadow:0 2px 12px rgba(0,0,0,.95);text-align:center;padding:14px 28px;background:rgba(0,0,0,0.75);border-radius:14px;backdrop-filter:blur(8px);z-index:100; }}\n"
        f"{media_css}\n"
        f"{visual_layout_css()}\n"
        f"</style>"
    )


def _build_debate_gsap(
    is_full: bool, s1_start: float, s2_start: float, attr_tl: str, scene3_tl: str, scene4_tl: str,
    media_tl: str, slot_v_tl: str, cap_tl: str,
) -> str:
    dur = 0.7 if is_full else 0.6
    return (
        f"<script>\n"
        f"(function() {{\n"
        f"  window.__timelines = window.__timelines || {{}};\n"
        f"  var tl = gsap.timeline({{ paused: true }});\n"
        f"  tl.from('#scene-hook .scene-inner', {{ opacity: 0, y: 40, duration: {dur}, ease: 'power2.out' }}, {_fmt_time(s1_start + 0.1)});\n"
        f"  tl.from('#scene-statement .scene-inner', {{ opacity: 0, y: 40, duration: {dur}, ease: 'power2.out' }}, {_fmt_time(s2_start + 0.1)});\n"
        f"{attr_tl}{scene3_tl}{scene4_tl}{media_tl}\n"
        f"{slot_v_tl}\n"
        f"{cap_tl}"
        f"  window.__timelines.main = tl;\n"
        f"}})();\n"
        f"</script>"
    )


def _build_debate_html(content: dict[str, Any], variant: str) -> str:
    is_full = variant == "full"
    total = min(float(content.get("duration", 40.0)), 58.0) if not is_full else float(content.get("duration", 45.0))
    timing = _scene_timing(content, total, variant)

    slots, hook, stmt, ctx, tkw, es = _resolve_debate_slots(content)
    _, captions = _resolve_template_captions(content, total, is_full)
    cap_html, cap_tl = _caption_elements(captions, track_index=10)

    s1_start, s1_end = timing["hook"]
    s2_start, s2_end = timing["statement"]
    s1_dur = max(0.5, s1_end - s1_start)
    s2_dur = max(0.5, s2_end - s2_start)

    ctx_v, tkw_v = _slot_has_visual(ctx), _slot_has_visual(tkw)
    hook_v, stmt_v = _slot_has_visual(hook), _slot_has_visual(stmt)

    attr_line, attr_tl, scene3_html, scene3_tl, scene4_html, scene4_tl = _resolve_debate_scenes(
        timing, es, is_full, ctx_v, tkw_v, s2_start
    )

    media_html, media_tl, media_css = build_media_layer_elements(content.get("media", []), total)
    slot_v_html, slot_v_tl = _extract_slot_visuals(slots, total)
    css = _build_debate_css(is_full, media_css)
    gsap = _build_debate_gsap(is_full, s1_start, s2_start, attr_tl, scene3_tl, scene4_tl, media_tl, slot_v_tl, cap_tl)
    audio_src = ASSET_NARRATION_FULL if is_full else ASSET_NARRATION_REELS

    return (
        "<!doctype html>\n"
        "<html lang=\"vi\">\n"
        "<head>\n"
        "  <meta charset=\"UTF-8\" />\n"
        "  <meta name=\"viewport\" content=\"width=1080, height=1920\" />\n"
        f"  <title>{es['title']} — news-debate</title>\n"
        f"  <script src=\"{GSAP_CDN}\"></script>\n"
        f"  {css}\n"
        "</head>\n"
        "<body>\n"
        f"  <div id=\"root\" data-composition-id=\"main\" data-width=\"1080\" data-height=\"1920\" data-duration=\"{_fmt_time(total)}\">\n"
        "    <div class=\"bg-fill\"></div>\n"
        f"    <audio id=\"narration\" class=\"clip\" data-start=\"0\" data-duration=\"{_fmt_time(total)}\" data-track-index=\"0\" src=\"{audio_src}\"></audio>\n"
        f"    <audio id=\"music-bg\" class=\"clip\" data-start=\"0\" data-duration=\"{_fmt_time(total)}\" data-track-index=\"0\" src=\"assets/music-bg.mp3\"></audio>\n"
        f"{media_html}\n"
        f"{slot_v_html}\n"
        f"    <section id=\"scene-hook\" class=\"clip{hook_v}\" data-start=\"{_fmt_time(s1_start)}\" data-duration=\"{_fmt_time(s1_dur)}\" data-track-index=\"2\">\n"
        "      <div class=\"scene-inner\">\n"
        f"        <span class=\"kicker\">{es['kicker']}</span>\n"
        f"        <h1 class=\"title\">{es['title']}</h1>\n"
        f"        <p class=\"scene-text\">{es['hook_text']}</p>\n"
        "      </div>\n"
        "    </section>\n"
        f"    <section id=\"scene-statement\" class=\"clip{stmt_v}\" data-start=\"{_fmt_time(s2_start)}\" data-duration=\"{_fmt_time(s2_dur)}\" data-track-index=\"2\">\n"
        "      <div class=\"scene-inner\">\n"
        f"        <span class=\"scene-heading\">{es['stmt_head']}</span>\n"
        f"        <blockquote class=\"statement\">{es['stmt_text']}</blockquote>\n"
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


def _resolve_evidence_slots(content: dict[str, Any]) -> tuple[dict, dict, dict, dict, dict, dict[str, str]]:
    slots = content.get("slots") if isinstance(content.get("slots"), dict) else {}
    hook = slots.get("hook") if isinstance(slots.get("hook"), dict) else {}
    metric = slots.get("metric") if isinstance(slots.get("metric"), dict) else {}
    comp = slots.get("comparison") if isinstance(slots.get("comparison"), dict) else {}
    caveat = slots.get("caveat") if isinstance(slots.get("caveat"), dict) else {}
    es = {
        "kicker": esc(content.get("kicker", "SỐ LIỆU")),
        "title": esc(content.get("title", "")),
        "hook_text": esc(hook.get("text", "")),
        "metric_value": esc(metric.get("label", metric.get("text", ""))),
        "metric_desc": esc(metric.get("text", metric.get("heading", ""))),
        "comp_label": esc(comp.get("label", "So sánh")),
        "comp_text": esc(comp.get("text", "")),
        "caveat_head": esc(caveat.get("heading", "Điều cần lưu ý")),
        "caveat_text": esc(caveat.get("text", "")),
    }
    return slots, hook, metric, comp, caveat, es


def _resolve_evidence_timings(content: dict[str, Any], is_full: bool) -> tuple[float, float, float, float, float, float, float, float]:
    total = min(float(content.get("duration", 40.0)), 58.0) if not is_full else float(content.get("duration", 45.0))
    s1_dur = 8.0 if is_full else 10.0
    s2_start = 8.0 if is_full else 10.0
    s2_dur = 14.0 if is_full else 16.0
    s3_start = 22.0 if is_full else 20.0
    s3_dur = 14.0 if is_full else 15.0
    return total, s1_dur, s2_start, s2_dur, s3_start, s3_dur, 36.0, 9.0


def _build_evidence_css(is_full: bool, media_css: str) -> str:
    title_sz = "56px" if is_full else "48px"
    scene_sz = "34px" if is_full else "30px"
    val_sz = "112px" if is_full else "88px"
    return (
        "<style>\n"
        ":root { --accent: #3b82f6; }\n"
        "* { box-sizing: border-box; }\n"
        "body { margin:0;background:#08111f;color:#f1f1f1;font-family:'BeVietnamPro',Inter,system-ui,sans-serif; }\n"
        "#root { position:relative;width:1080px;height:1920px;overflow:hidden;background:#08111f; }\n"
        ".bg-fill { position:absolute;inset:0;background:radial-gradient(ellipse at 75% 25%,rgba(59,130,246,.14) 0%,transparent 58%),linear-gradient(160deg,#08111f 0%,#0d1b32 100%); }\n"
        ".clip { position:absolute;inset:0; }\n"
        ".scene-inner { display:flex;flex-direction:column;justify-content:center;align-items:center;width:100%;height:100%;padding:110px 70px 170px;text-align:center; }\n"
        ".kicker { font-size:22px;font-weight:700;letter-spacing:.3em;text-transform:uppercase;color:var(--accent);margin-bottom:24px;padding:6px 20px;border:2px solid var(--accent);border-radius:6px; }\n"
        f".title {{ font-size:{title_sz};font-weight:900;line-height:1.15;color:#fff;max-width:900px;margin:0 auto 40px; }}\n"
        f".scene-text {{ font-size:{scene_sz};font-weight:400;line-height:1.5;color:#d5deed;max-width:900px;margin:0; }}\n"
        ".metric-card { width:100%; max-width:820px; padding:58px 60px; border:1px solid rgba(130,180,255,.35); border-radius:16px; background:rgba(59,130,246,.10); }\n"
        f".metric-value {{ font-size:{val_sz};line-height:1;font-weight:900;color:var(--accent);margin:0 0 18px; }}\n"
        ".metric-label { font-size:28px;line-height:1.4;color:#d5deed;margin:0; }\n"
        ".comparison-card { width:100%; max-width:860px; text-align:left; padding:42px 48px; border-left:4px solid var(--accent); background:rgba(255,255,255,.04); }\n"
        ".comparison-label { font-size:26px; color:#91b8f4; margin-bottom:16px; }\n"
        ".comparison-text { font-size:36px; line-height:1.45; color:#fff; margin:0; }\n"
        ".caption { position:absolute;top:auto !important;bottom:96px !important;left:60px;right:60px;height:auto !important;min-height:56px;display:flex;align-items:center;justify-content:center;font-size:32px;font-weight:700;color:#fff;text-shadow:0 2px 12px rgba(0,0,0,.95);text-align:center;padding:14px 28px;background:rgba(0,0,0,0.75);border-radius:14px;backdrop-filter:blur(8px);z-index:100; }\n"
        f"{media_css}\n"
        f"{visual_layout_css()}\n"
        "</style>"
    )


def _build_evidence_caveat(is_full: bool, caveat_head: str, caveat_text: str, caveat_v: str, s4_start: float, s4_dur: float) -> tuple[str, str]:
    if not (is_full and caveat_text):
        return "", ""
    html = (
        f"    <section id=\"scene-caveat\" class=\"clip{caveat_v}\" data-start=\"{_fmt_time(s4_start)}\" data-duration=\"{_fmt_time(s4_dur)}\" data-track-index=\"4\">\n"
        "      <div class=\"scene-inner\">\n"
        f"        <span class=\"kicker\">{caveat_head}</span>\n"
        f"        <p class=\"scene-text\">{caveat_text}</p>\n"
        "      </div>\n"
        "    </section>\n"
    )
    tl = f"      tl.from('#scene-caveat .scene-inner', {{ opacity: 0, y: 40, duration: 0.6, ease: 'power2.out' }}, {_fmt_time(s4_start + 0.1)});\n"
    return html, tl


def _build_evidence_gsap(
    s2_start: float, s3_start: float, metric_tl: str, caveat_tl: str,
    media_tl: str, slot_v_tl: str, cap_tl: str,
) -> str:
    return (
        "<script>\n"
        "(function() {\n"
        "  window.__timelines = window.__timelines || {};\n"
        "  var tl = gsap.timeline({ paused: true });\n"
        "  tl.from('#scene-hook .scene-inner', { opacity: 0, y: 40, duration: 0.7, ease: 'power2.out' }, 0.1);\n"
        f"  tl.from('#scene-metric .scene-inner', {{ opacity: 0, y: 40, duration: 0.7, ease: 'power2.out' }}, {_fmt_time(s2_start + 0.1)});\n"
        f"{metric_tl}"
        f"  tl.from('#scene-comparison .scene-inner', {{ opacity: 0, y: 40, duration: 0.7, ease: 'power2.out' }}, {_fmt_time(s3_start + 0.1)});\n"
        f"{caveat_tl}"
        f"{media_tl}\n"
        f"{slot_v_tl}\n"
        f"{cap_tl}"
        "  window.__timelines.main = tl;\n"
        "})();\n"
        "</script>"
    )


def _build_evidence_html(content: dict[str, Any], variant: str) -> str:
    is_full = variant == "full"
    total, s1_dur, s2_start, s2_dur, s3_start, s3_dur, s4_start, s4_dur = _resolve_evidence_timings(content, is_full)
    slots, hook, metric, comp, caveat, es = _resolve_evidence_slots(content)

    _, captions = _resolve_template_captions(content, total, is_full)
    cap_html, cap_tl = _caption_elements(captions, track_index=10)

    hook_v, metric_v = _slot_has_visual(hook), _slot_has_visual(metric)
    comp_v, caveat_v = _slot_has_visual(comp), _slot_has_visual(caveat)

    metric_tl = f"      tl.from('#metric-value', {{ opacity: 0, scale: 0.82, duration: 0.8, ease: 'back.out(1.4)' }}, {_fmt_time(s2_start + 0.5)});\n"
    caveat_html, caveat_tl = _build_evidence_caveat(is_full, es["caveat_head"], es["caveat_text"], caveat_v, s4_start, s4_dur)

    media_html, media_tl, media_css = build_media_layer_elements(content.get("media", []), total)
    slot_v_html, slot_v_tl = _extract_slot_visuals(slots, total)
    css = _build_evidence_css(is_full, media_css)
    gsap = _build_evidence_gsap(s2_start, s3_start, metric_tl, caveat_tl, media_tl, slot_v_tl, cap_tl)
    audio_src = ASSET_NARRATION_FULL if is_full else ASSET_NARRATION_REELS

    return (
        "<!doctype html>\n"
        "<html lang=\"vi\">\n"
        "<head>\n"
        "  <meta charset=\"UTF-8\" />\n"
        "  <meta name=\"viewport\" content=\"width=1080, height=1920\" />\n"
        f"  <title>{es['title']} — news-evidence</title>\n"
        f"  <script src=\"{GSAP_CDN}\"></script>\n"
        f"  {css}\n"
        "</head>\n"
        "<body>\n"
        f"  <div id=\"root\" data-composition-id=\"main\" data-width=\"1080\" data-height=\"1920\" data-duration=\"{_fmt_time(total)}\">\n"
        "    <div class=\"bg-fill\"></div>\n"
        f"    <audio id=\"narration\" class=\"clip\" data-start=\"0\" data-duration=\"{_fmt_time(total)}\" data-track-index=\"0\" src=\"{audio_src}\"></audio>\n"
        f"    <audio id=\"music-bg\" class=\"clip\" data-start=\"0\" data-duration=\"{_fmt_time(total)}\" data-track-index=\"0\" src=\"assets/music-bg.mp3\"></audio>\n"
        f"{media_html}\n"
        f"{slot_v_html}\n"
        f"    <section id=\"scene-hook\" class=\"clip{hook_v}\" data-start=\"0\" data-duration=\"{_fmt_time(s1_dur)}\" data-track-index=\"2\">\n"
        "      <div class=\"scene-inner\">\n"
        f"        <span class=\"kicker\">{es['kicker']}</span>\n"
        f"        <h1 class=\"title\">{es['title']}</h1>\n"
        f"        <p class=\"scene-text\">{es['hook_text']}</p>\n"
        "      </div>\n"
        "    </section>\n"
        f"    <section id=\"scene-metric\" class=\"clip{metric_v}\" data-start=\"{_fmt_time(s2_start)}\" data-duration=\"{_fmt_time(s2_dur)}\" data-track-index=\"2\">\n"
        "      <div class=\"scene-inner\">\n"
        "        <div class=\"metric-card\">\n"
        f"          <p id=\"metric-value\" class=\"metric-value\">{es['metric_value']}</p>\n"
        f"          <p class=\"metric-label\">{es['metric_desc']}</p>\n"
        f"          <div class=\"comparison-label\">{es['comp_label']}</div>\n"
        f"          <p class=\"comparison-text\">{es['comp_text']}</p>\n"
        "        </div>\n"
        "      </div>\n"
        "    </section>\n"
        f"    <section id=\"scene-comparison\" class=\"clip{comp_v}\" data-start=\"{_fmt_time(s3_start)}\" data-duration=\"{_fmt_time(s3_dur)}\" data-track-index=\"3\">\n"
        "      <div class=\"scene-inner\">\n"
        f"        <span class=\"kicker\">{es['comp_label']}</span>\n"
        f"        <p class=\"scene-text\">{es['comp_text']}</p>\n"
        "      </div>\n"
        "    </section>\n"
        f"{caveat_html}"
        f"{cap_html}"
        "  </div>\n"
        f"  {gsap}\n"
        "</body>\n"
        "</html>\n"
    )


def _resolve_explainer_slots(content: dict[str, Any]) -> tuple[dict, dict, dict, dict, dict]:
    slots = content.get("slots") if isinstance(content.get("slots"), dict) else {}
    return (
        slots,
        slots.get("hook") if isinstance(slots.get("hook"), dict) else {},
        slots.get("capability") if isinstance(slots.get("capability"), dict) else {},
        slots.get("steps") if isinstance(slots.get("steps"), dict) else {},
        slots.get("limitations") if isinstance(slots.get("limitations"), dict) else {},
    )


def _resolve_explainer_timings(content: dict[str, Any], is_full: bool) -> tuple[float, float, float, float, float, float, float, float]:
    total = min(float(content.get("duration", 40.0)), 58.0) if not is_full else float(content.get("duration", 45.0))
    s1 = 8.0 if is_full else 10.0
    return total, s1, s1, (14.0 if is_full else 18.0), (22.0 if is_full else 28.0), (14.0 if is_full else 12.0), 36.0, 9.0


def _resolve_explainer_cta(content: dict[str, Any], e_title: str, e_kicker: str, narration: str) -> str:
    raw_cta = content.get("cta_text")
    if not raw_cta:
        sample = f"{e_title} {e_kicker} {narration}"
        is_vi = any(c in sample for c in "àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđĐ")
        raw_cta = "Bạn nghĩ sao? Hãy bình luận bên dưới 👇" if is_vi else "What do you think? Let me know below 👇"
    return esc(raw_cta)


def _build_explainer_css(is_full: bool, media_css: str) -> str:
    title_sz = "56px" if is_full else "48px"
    scene_sz = "34px" if is_full else "30px"
    cap_w = "820px" if is_full else "780px"
    cap_sz = "36px" if is_full else "32px"
    return f"""<style>
:root {{ --accent: #06d6a0; }}
* {{ box-sizing: border-box; }}
body {{ margin:0;background:#0a1410;color:#f1f1f1;font-family:'BeVietnamPro',Inter,system-ui,sans-serif; }}
#root {{ position:relative;width:1080px;height:1920px;overflow:hidden;background:#0a1410; }}
.bg-fill {{ position:absolute;inset:0;background:radial-gradient(ellipse at 30% 80%,rgba(6,214,160,.08) 0%,transparent 55%),linear-gradient(180deg,#0a1410 0%,#0d1f1a 100%); }}
.clip {{ position:absolute;inset:0; }}
.scene-inner {{ display:flex;flex-direction:column;justify-content:center;align-items:center;width:100%;height:100%;padding:110px 70px 170px;text-align:center; }}
.kicker {{ font-size:22px;font-weight:700;letter-spacing:.35em;text-transform:uppercase;color:var(--accent);margin-bottom:24px;padding:8px 24px;border:2px solid var(--accent);border-radius:6px; }}
.title {{ font-size:{title_sz};font-weight:900;line-height:1.15;color:#fff;max-width:900px;margin:0 auto 40px; }}
.scene-text {{ font-size:{scene_sz};font-weight:400;line-height:1.6;color:#c8d8d4;max-width:860px;margin:0; }}
.capability-card {{ width:100%;max-width:{cap_w};padding:40px 48px;border:1px solid rgba(6,214,160,.3);border-radius:14px;background:rgba(6,214,160,.07); }}
.capability-label {{ display:block;font-size:26px;font-weight:700;color:var(--accent);margin-bottom:14px; }}
.capability-text {{ font-size:{cap_sz};line-height:1.45;color:#fff;margin:0; }}
.caption {{ position:absolute;top:auto !important;bottom:96px !important;left:60px;right:60px;height:auto !important;min-height:56px;display:flex;align-items:center;justify-content:center;font-size:32px;font-weight:700;color:#fff;text-shadow:0 2px 12px rgba(0,0,0,.95);text-align:center;padding:14px 28px;background:rgba(0,0,0,0.75);border-radius:14px;backdrop-filter:blur(8px);z-index:100; }}
.limitation-box {{ width:100%;max-width:820px;padding:42px 48px;border:1px solid rgba(255,255,255,.12);border-left:4px solid var(--accent);border-radius:12px;background:rgba(255,255,255,.03);text-align:left; }}
.limitation-box p {{ font-size:28px;line-height:1.5;color:#c8d8d4;margin:0; }}
.steps-box {{ width:100%;max-width:820px; }}
.cta-banner {{ display:inline-flex;align-items:center;justify-content:center;margin-top:28px;padding:14px 32px;background:linear-gradient(135deg,rgba(6,214,160,0.2) 0%,rgba(6,214,160,0.08) 100%);border:1.5px solid var(--accent);border-radius:30px;font-size:24px;font-weight:700;color:#fff;letter-spacing:0.02em;box-shadow:0 8px 24px rgba(6,214,160,0.18); }}
{media_css}
{visual_layout_css()}
</style>"""


def _build_explainer_sfx(include_lim: bool, s2_start: float, s3_start: float, s4_start: float, total: float) -> str:
    sfx = (
        '    <audio class="clip sfx" data-start="0" data-duration="0.8" data-track-index="10" src="assets/sfx/whoosh-short.mp3" data-volume="0.22"></audio>\n'
        f'    <audio class="clip sfx" data-start="{_fmt_time(max(0.1, s2_start - 0.2))}" data-duration="0.8" data-track-index="11" src="assets/sfx/whoosh-short.mp3" data-volume="0.22"></audio>\n'
        f'    <audio class="clip sfx" data-start="{_fmt_time(s2_start + 0.4)}" data-duration="0.3" data-track-index="12" src="assets/sfx/pop.mp3" data-volume="0.16"></audio>\n'
        f'    <audio class="clip sfx" data-start="{_fmt_time(max(0.1, s3_start - 0.2))}" data-duration="0.8" data-track-index="13" src="assets/sfx/whoosh-short.mp3" data-volume="0.22"></audio>\n'
        f'    <audio class="clip sfx" data-start="{_fmt_time(s3_start + 0.4)}" data-duration="0.3" data-track-index="14" src="assets/sfx/click.mp3" data-volume="0.16"></audio>\n'
    )
    if include_lim:
        sfx += (
            f'    <audio class="clip sfx" data-start="{_fmt_time(max(0.1, s4_start - 0.2))}" data-duration="0.8" data-track-index="15" src="assets/sfx/whoosh-short.mp3" data-volume="0.22"></audio>\n'
            f'    <audio class="clip sfx" data-start="{_fmt_time(s4_start + 0.3)}" data-duration="0.3" data-track-index="16" src="assets/sfx/buzz.mp3" data-volume="0.24"></audio>\n'
        )
    sfx += f'    <audio class="clip sfx" data-start="{_fmt_time(max(1.0, total - 4.5))}" data-duration="0.8" data-track-index="17" src="assets/sfx/chime.mp3" data-volume="0.20"></audio>\n'
    return sfx


def _build_explainer_gsap(include_lim: bool, s2_start: float, s3_start: float, s4_start: float, total: float, media_tl: str, slot_v_tl: str, cap_tl: str) -> str:
    t_st = s4_start if include_lim else s3_start
    bgm_tl = (
        f'  tl.to("#music-bg", {{ volume: 0.18, duration: 1.0, ease: "power2.in" }}, {_fmt_time(max(0.5, t_st - 1.5))});\n'
        f'  tl.to("#music-bg", {{ volume: 0.06, duration: 0.5, ease: "power2.out" }}, {_fmt_time(t_st)});\n'
        f'  tl.to("#music-bg", {{ volume: 0.16, duration: 0.8, ease: "power2.out" }}, {_fmt_time(max(1.0, total - 4.5))});\n'
        f'  tl.to("#music-bg", {{ volume: 0, duration: 1.5, ease: "power2.in" }}, {_fmt_time(max(1.0, total - 1.5))});\n'
    )
    gsap = (
        "<script>\n"
        "(function() {\n"
        "  window.__timelines = window.__timelines || {};\n"
        "  var tl = gsap.timeline({ paused: true });\n"
        f"{bgm_tl}"
        f"  tl.fromTo('#scene-hook .scene-inner', {{ opacity: 0, y: 35, scale: 0.96 }}, {{ opacity: 1, y: 0, scale: 1.0, duration: 0.5, ease: 'power2.out' }}, 0.1);\n"
        f"  tl.to('#scene-hook .scene-inner', {{ opacity: 0, y: -24, scale: 0.96, duration: 0.28, ease: 'power2.in' }}, {_fmt_time(s2_start - 0.3)});\n"
        f"  tl.fromTo('#scene-capability .scene-inner', {{ opacity: 0, y: 35, scale: 0.96 }}, {{ opacity: 1, y: 0, scale: 1.0, duration: 0.5, ease: 'power2.out' }}, {_fmt_time(s2_start)});\n"
        f"  tl.fromTo('.capability-card', {{ opacity: 0, scale: 0.9 }}, {{ opacity: 1, scale: 1.0, duration: 0.7, ease: 'back.out(1.4)' }}, {_fmt_time(s2_start + 0.4)});\n"
        f"  tl.to('#scene-capability .scene-inner', {{ opacity: 0, y: -24, scale: 0.96, duration: 0.28, ease: 'power2.in' }}, {_fmt_time(s3_start - 0.3)});\n"
        f"  tl.fromTo('#scene-steps .scene-inner', {{ opacity: 0, y: 35, scale: 0.96 }}, {{ opacity: 1, y: 0, scale: 1.0, duration: 0.5, ease: 'power2.out' }}, {_fmt_time(s3_start)});\n"
    )
    if include_lim:
        gsap += (
            f"  tl.to('#scene-steps .scene-inner', {{ opacity: 0, y: -24, scale: 0.96, duration: 0.28, ease: 'power2.in' }}, {_fmt_time(s4_start - 0.3)});\n"
            f"  tl.fromTo('#scene-limitations .scene-inner', {{ opacity: 0, y: 35, scale: 0.96 }}, {{ opacity: 1, y: 0, scale: 1.0, duration: 0.5, ease: 'power2.out' }}, {_fmt_time(s4_start)});\n"
            f"  tl.fromTo('#cta-banner', {{ opacity: 0, y: 20, scale: 0.94 }}, {{ opacity: 1, y: 0, scale: 1.0, duration: 0.5, ease: 'back.out(1.7)' }}, {_fmt_time(s4_start + 1.2)});\n"
        )
    else:
        gsap += (
            f"  tl.fromTo('#cta-banner', {{ opacity: 0, y: 20, scale: 0.94 }}, {{ opacity: 1, y: 0, scale: 1.0, duration: 0.5, ease: 'back.out(1.7)' }}, {_fmt_time(s3_start + 1.2)});\n"
        )
    gsap += (
        f"{media_tl}\n"
        f"{slot_v_tl}\n"
        f"{cap_tl}"
        "  window.__timelines.main = tl;\n"
        "})();\n"
        "</script>"
    )
    return gsap


def _build_explainer_html(content: dict[str, Any], variant: str) -> str:
    is_full = variant == "full"
    total, s1_dur, s2_start, s2_dur, s3_start, s3_dur, s4_start, s4_dur = _resolve_explainer_timings(content, is_full)
    slots, hook, cap, steps, lim = _resolve_explainer_slots(content)

    e_kicker = esc(content.get("kicker", "HƯỚNG DẪN"))
    e_title = esc(content.get("title", ""))
    e_hook_text, e_cap_label, e_cap_text = esc(hook.get("text", "")), esc(cap.get("label", "")), esc(cap.get("text", ""))
    e_steps_text, e_lim_head, e_lim_text = esc(steps.get("text", "")), esc(lim.get("heading", "Hạn chế")), esc(lim.get("text", ""))

    narration_src, captions = _resolve_template_captions(content, total, is_full)
    narration = esc(narration_src)

    cap_html, cap_tl = _caption_elements(captions, track_index=10)
    audio_src = ASSET_NARRATION_FULL if is_full else ASSET_NARRATION_REELS
    include_lim = is_full and bool(e_lim_text)

    e_cta = _resolve_explainer_cta(content, e_title, e_kicker, narration)
    cta_banner_html = f'        <div id="cta-banner" class="cta-banner"><span>{e_cta}</span></div>\n'
    steps_cta = "" if include_lim else cta_banner_html

    media_html, media_tl, media_css = build_media_layer_elements(content.get("media", []), total)
    slot_v_html, slot_v_tl = _extract_slot_visuals(slots, total)
    hook_v, cap_v = _slot_has_visual(hook), _slot_has_visual(cap)
    steps_v, lim_v = _slot_has_visual(steps), _slot_has_visual(lim)

    css = _build_explainer_css(is_full, media_css)

    lim_section = ""
    if include_lim:
        lim_section = (
            f"    <section id=\"scene-limitations\" class=\"clip{lim_v}\" data-start=\"{_fmt_time(s4_start)}\" data-duration=\"{_fmt_time(s4_dur)}\" data-track-index=\"4\">\n"
            "      <div class=\"scene-inner\">\n"
            f"        <span class=\"kicker\">{e_lim_head}</span>\n"
            f"        <div class=\"limitation-box\"><p>{e_lim_text}</p></div>\n"
            f"{cta_banner_html}"
            "      </div>\n"
            "    </section>\n"
        )

    sfx_html = _build_explainer_sfx(include_lim, s2_start, s3_start, s4_start, total)
    gsap = _build_explainer_gsap(include_lim, s2_start, s3_start, s4_start, total, media_tl, slot_v_tl, cap_tl)

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
        f"    <audio id=\"music-bg\" class=\"clip\" data-start=\"0\" data-duration=\"{_fmt_time(total)}\" data-track-index=\"1\" src=\"assets/music-bg.mp3\" data-volume=\"0.12\" loop></audio>\n"
        f"{sfx_html}"
        f"{media_html}\n"
        f"{slot_v_html}\n"
        f"    <section id=\"scene-hook\" class=\"clip{hook_v}\" data-start=\"0\" data-duration=\"{_fmt_time(s1_dur)}\" data-track-index=\"2\">\n"
        "      <div class=\"scene-inner\">\n"
        f"        <span class=\"kicker\">{e_kicker}</span>\n"
        f"        <h1 class=\"title\">{e_title}</h1>\n"
        f"        <p class=\"scene-text\">{e_hook_text}</p>\n"
        "      </div>\n"
        "    </section>\n"
        f"    <section id=\"scene-capability\" class=\"clip{cap_v}\" data-start=\"{_fmt_time(s2_start)}\" data-duration=\"{_fmt_time(s2_dur)}\" data-track-index=\"3\">\n"
        "      <div class=\"scene-inner\">\n"
        "        <div class=\"capability-card\">\n"
        f"          <span class=\"capability-label\">{e_cap_label}</span>\n"
        f"          <p class=\"capability-text\">{e_cap_text}</p>\n"
        "        </div>\n"
        "      </div>\n"
        "    </section>\n"
        f"    <section id=\"scene-steps\" class=\"clip{steps_v}\" data-start=\"{_fmt_time(s3_start)}\" data-duration=\"{_fmt_time(s3_dur)}\" data-track-index=\"4\">\n"
        "      <div class=\"scene-inner\">\n"
        "        <span class=\"kicker\">CÁC BƯỚC</span>\n"
        f"        <p class=\"scene-text\">{e_steps_text}</p>\n"
        f"{steps_cta}"
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


def _render_package_html(package_id: str, content: dict[str, Any], variant: str) -> str:
    if package_id == "news-debate":
        return _build_debate_html(content, variant)
    if package_id == "news-evidence":
        return _build_evidence_html(content, variant)
    return _build_explainer_html(content, variant)


def _copy_template_sfx(project_dir: Path, dirs: list[str]) -> None:
    sfx_src = ROOT / "assets" / "audio" / "sfx"
    if not sfx_src.is_dir():
        return
    import shutil

    for cname in dirs:
        stgt = project_dir / cname / "assets" / "sfx"
        stgt.mkdir(parents=True, exist_ok=True)
        for sfile in sfx_src.glob("*.mp3"):
            shutil.copy2(sfile, stgt / sfile.name)


def materialize(package_id: str, content: dict[str, Any], project_dir: Path, variant: str) -> dict[str, Any]:
    if package_id not in ALLOWED_PACKAGES:
        raise ValueError(f"Unknown package: {package_id}")
    validate_content(content, package_id)

    do_full, do_reels = variant in {"full", "both"}, variant in {"short", "both"}
    full_html = _render_package_html(package_id, content, "full") if do_full else ""
    short_html = _render_package_html(package_id, content, "reels") if do_reels else ""

    for subdir, html in (("hyperframes", full_html), ("hyperframes_reels", short_html)):
        if html:
            out = project_dir / subdir / "index.html"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(html, encoding="utf-8")

    dirs = (["hyperframes"] if do_full else []) + (["hyperframes_reels"] if do_reels else [])
    _copy_template_sfx(project_dir, dirs)

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
