"""
Template selector: picks the best news template for a given research brief.

Deterministic scoring.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CATALOG_PATH = ROOT / "templates" / "news" / "catalog.json"

TOPIC_TEMPLATE_MAP: dict[str, str] = {
    "dispute": "news-debate",
    "quotation": "news-debate",
    "risk_debate": "news-debate",
    "opinion": "news-debate",
    "context": "news-debate",
    "metrics": "news-evidence",
    "comparison": "news-evidence",
    "quantitative": "news-evidence",
    "statistics": "news-evidence",
    "baseline": "news-evidence",
    "product_change": "news-explainer",
    "capability": "news-explainer",
    "how_it_works": "news-explainer",
    "limitations": "news-explainer",
    "technical": "news-explainer",
}

VIETNAMESE_KEYWORDS: dict[str, list[str]] = {
    "news-debate": ["tranh luận", "ý kiến", "rủi ro", "chuyên gia", "nhận định", "phát biểu"],
    "news-evidence": ["số liệu", "tăng", "giảm", "chỉ số", "đo lường", "so sánh", "phần trăm"],
    "news-explainer": ["hướng dẫn", "tính năng", "cập nhật", "sự kiện", "kỹ thuật", "công cụ"],
}

ENGLISH_KEYWORDS: dict[str, list[str]] = {
    "news-debate": ["dispute", "quote", "risk", "opinion", "statement", "expert"],
    "news-evidence": ["metric", "statistic", "number", "percentage", "baseline", "comparison"],
    "news-explainer": ["how", "guide", "feature", "step", "capability", "new", "technical"],
}

DEFAULT_FALLBACK = "news-explainer"
DEFAULT_VERSION = "1.0.0"


def load_catalog() -> dict:
    with CATALOG_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def select_template(brief: dict, catalog: dict | None = None) -> dict:
    if catalog is None:
        catalog = load_catalog()

    topic_tags = [str(t).lower() for t in brief.get("topic_tags", brief.get("tags", []))]
    title = str(brief.get("title", "")).lower()
    desc = str(brief.get("description", "")).lower()
    text = f"{title} {desc}"

    scored: list[tuple[int, str, str, list[str]]] = []

    for pkg in catalog.get("packages", []):
        pid = str(pkg.get("id"))
        ver = str(pkg.get("version", DEFAULT_VERSION))

        suitable_topics = [str(t).lower() for t in pkg.get("suitable_for", {}).get("topics", [])]

        score = 0
        reason_parts: list[str] = []

        for tag in topic_tags:
            expected = TOPIC_TEMPLATE_MAP.get(tag, "")
            if tag in suitable_topics and expected == pid:
                score += 10
                reason_parts.append(f"tag:{tag}")

        for kw in VIETNAMESE_KEYWORDS.get(pid, []):
            if kw in text:
                score += 5
                reason_parts.append(f"vn:{kw}")

        for kw in ENGLISH_KEYWORDS.get(pid, []):
            if kw in text:
                score += 3
                reason_parts.append(f"en:{kw}")

        scored.append((score, pid, ver, reason_parts))

    scored.sort(key=lambda x: (-x[0], x[1]))
    best_score, best_id, best_ver, best_reasons = scored[0] if scored else (0, DEFAULT_FALLBACK, DEFAULT_VERSION, [])

    if best_score <= 0:
        return {
            "template_id": DEFAULT_FALLBACK,
            "template_version": DEFAULT_VERSION,
            "reason": "no strong topic signal; defaulting to explainer",
        }

    return {
        "template_id": best_id,
        "template_version": best_ver,
        "reason": " | ".join(best_reasons[:3]) if best_reasons else "topic/keyword fit",
    }


def get_template_for_topic(topic_text: str, catalog: dict | None = None) -> str | None:
    brief = {"title": topic_text, "description": topic_text, "topic_tags": []}
    return select_template(brief, catalog=catalog).get("template_id")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Select news template for a brief")
    parser.add_argument("--brief", type=Path, required=True)
    args = parser.parse_args()

    brief = json.loads(args.brief.read_text(encoding="utf-8"))
    print(json.dumps(select_template(brief), indent=2, ensure_ascii=False))
