"""Template provenance and caption-display verification for news templates.

Shared by the materializer, the director-artifact validator, the pipeline, and
the scheduler. The core idea is that a self-declared ``template_id`` label inside
arbitrary generated HTML is not trusted on its own: the current composition bytes
are re-hashed and compared against the recorded provenance, and visible on-screen
captions are verified to be Vietnamese prose.

Provenance lives at ``<project>/template_provenance.json``:

    template_id                 one of ALLOWED_PACKAGES
    template_version            catalog version for that package
    content_instance_sha256    sha256 of the validated content instance
    full_html_sha256           sha256 of hyperframes/index.html
    reels_html_sha256          sha256 of hyperframes_reels/index.html
    composition_source_sha256  binding of both composition files
    variant                     full | short | both
    caption_display_verified   whether visible captions were verified Vietnamese
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from tools.narration_text import check_vietnamese_prose
except Exception:  # pragma: no cover - narration_text always present in repo
    def check_vietnamese_prose(text: str) -> list[str]:  # type: ignore
        return []

CATALOG_PATH = ROOT / "templates" / "news" / "catalog.json"
PROVENANCE_FILE = "template_provenance.json"
FULL_HTML = "hyperframes/index.html"
REELS_HTML = "hyperframes_reels/index.html"

ALLOWED_PACKAGES = ("news-debate", "news-evidence", "news-explainer")

_VIET_DIACRITICS = set(
    "àáảãạăắẳẵặâấầẩẫậèéẻẽẹêếềểễệìíỉĩịôốồổỗộơớờởỡợùúủũụưứừửữựỳýỷỹỵđ"
)
_DATA_LABEL_RE = re.compile(r"[0-9%+\-×]|\+\d|−\d")
_CAPTION_RE = re.compile(
    r'<div[^>]*class="[^"]*\bcaption\b[^"]*"[^>]*>(.*?)</div>',
    re.DOTALL,
)
_TAG_RE = re.compile(r"<[^>]+>")


def _sha256(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def load_catalog() -> dict[str, Any]:
    if not CATALOG_PATH.is_file():
        raise FileNotFoundError(f"template catalog not found: {CATALOG_PATH}")
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def get_package(catalog: dict[str, Any], template_id: str) -> dict[str, Any] | None:
    for pkg in catalog.get("packages", []):
        if pkg.get("id") == template_id:
            return pkg
    return None


def composition_source_sha256(full_html: str | None, reels_html: str | None) -> str:
    """Bind both composition files into a single hash for downstream checks."""
    parts = []
    if full_html is not None:
        parts.append(_sha256(full_html))
    if reels_html is not None:
        parts.append(_sha256(reels_html))
    return _sha256("|".join(parts))


def _caption_texts(html: str | None) -> list[str]:
    if not html:
        return []
    out = []
    for m in _CAPTION_RE.finditer(html):
        text = _TAG_RE.sub("", m.group(1)).strip()
        out.append(text)
    return out


def _is_viet_diacritic(text: str) -> bool:
    return any(ch in _VIET_DIACRITICS for ch in text)


def _is_data_label(text: str) -> bool:
    """Metric/number/percentage labels are acceptable without Vietnamese prose."""
    stripped = text.strip()
    if not stripped:
        return False
    return bool(_DATA_LABEL_RE.search(stripped))


def caption_display_verified(full_html: str | None, reels_html: str | None) -> tuple[bool, list[str]]:
    """Non-mutating static check that visible captions exist and are Vietnamese.

    Captions in the templated path are static HTML (not JS-injected), so a static
    scan is sufficient to establish display-language compliance. Returns
    ``(ok, reasons)``.
    """
    reasons: list[str] = []
    any_caption = False

    for name, html in (("full", full_html), ("reels", reels_html)):
        if html is None:
            continue
        caps = _caption_texts(html)
        if not caps:
            reasons.append(f"{name}: no visible caption elements found")
            continue
        any_caption = True
        for i, text in enumerate(caps):
            if not text:
                reasons.append(f"{name}: caption {i} is empty")
                continue
            if _is_data_label(text) or _is_viet_diacritic(text):
                continue
            errors = check_vietnamese_prose(text)
            if errors:
                reasons.append(f"{name}: caption {i} not Vietnamese ({errors[0]})")

    if not any_caption:
        reasons.append("no visible captions in any present composition")
    return (not reasons), reasons


def verify_project_provenance(
    project_dir: Path,
    catalog: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Re-hash current composition bytes and validate the recorded provenance.

    Returns ``{"ok", "reasons", "template_id", "composition_source_sha256",
    "caption_display_verified"}``.
    """
    reasons: list[str] = []

    prov_path = Path(project_dir) / PROVENANCE_FILE
    if not prov_path.is_file():
        return {
            "ok": False,
            "reasons": [f"{PROVENANCE_FILE} missing"],
            "template_id": None,
            "composition_source_sha256": None,
            "caption_display_verified": False,
        }
    try:
        prov = json.loads(prov_path.read_text(encoding="utf-8"))
    except Exception as exc:  # malformed provenance is a hard failure
        return {
            "ok": False,
            "reasons": [f"unparseable {PROVENANCE_FILE}: {exc}"],
            "template_id": None,
            "composition_source_sha256": None,
            "caption_display_verified": False,
        }

    template_id = prov.get("template_id")
    if catalog is None:
        try:
            catalog = load_catalog()
        except FileNotFoundError:
            catalog = {"packages": []}

    if template_id not in ALLOWED_PACKAGES:
        reasons.append(f"unknown template_id {template_id!r} (not in approved set)")
    else:
        pkg = get_package(catalog, template_id)
        if pkg is not None and pkg.get("version") and prov.get("template_version") != pkg.get("version"):
            reasons.append(
                f"template_version {prov.get('template_version')!r} does not match catalog {pkg.get('version')!r}"
            )

    def _read(rel: str) -> str | None:
        p = Path(project_dir) / rel
        if not p.is_file():
            return None
        try:
            return p.read_text(encoding="utf-8")
        except Exception:
            return None

    full_html = _read(FULL_HTML)
    reels_html = _read(REELS_HTML)

    full_hash = prov.get("full_html_sha256")
    reels_hash = prov.get("reels_html_sha256")

    if full_hash:
        if full_html is None:
            reasons.append("full composition file missing but hash recorded")
        elif _sha256(full_html) != full_hash:
            reasons.append("full composition hash mismatch (stale or tampered)")
    if reels_hash:
        if reels_html is None:
            reasons.append("reels composition file missing but hash recorded")
        elif _sha256(reels_html) != reels_hash:
            reasons.append("reels composition hash mismatch (stale or tampered)")

    expected_comp_hash = composition_source_sha256(full_html, reels_html)
    recorded_comp_hash = prov.get("composition_source_sha256")
    if recorded_comp_hash and recorded_comp_hash != expected_comp_hash:
        reasons.append("composition_source_sha256 mismatch (stale or tampered)")

    cap_ok, cap_reasons = caption_display_verified(full_html, reels_html)
    reasons.extend(cap_reasons)
    if not cap_ok:
        reasons.append("caption display not verified")

    ok = not reasons and cap_ok
    return {
        "ok": ok,
        "reasons": reasons,
        "template_id": template_id,
        "composition_source_sha256": expected_comp_hash,
        "caption_display_verified": cap_ok,
    }


def record_provenance(
    project_dir: Path,
    template_id: str,
    template_version: str,
    content: dict[str, Any],
    full_html: str | None,
    reels_html: str | None,
    variant: str,
) -> dict[str, Any]:
    """Write a fresh, self-consistent provenance record and return it."""
    cap_ok, _ = caption_display_verified(full_html, reels_html)
    provenance = {
        "template_id": template_id,
        "template_version": template_version,
        "content_instance_sha256": _sha256(json.dumps(content, sort_keys=True, ensure_ascii=False)),
        "full_html_sha256": _sha256(full_html) if full_html is not None else None,
        "reels_html_sha256": _sha256(reels_html) if reels_html is not None else None,
        "composition_source_sha256": composition_source_sha256(full_html, reels_html),
        "variant": variant,
        "caption_display_verified": cap_ok,
    }
    path = Path(project_dir) / PROVENANCE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(provenance, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return provenance
