"""Bridges Claude's raw research draft into a strict OpenMontage research_brief artifact."""

import datetime
import json
from pathlib import Path
from typing import Any, Dict

from jsonschema import Draft7Validator


class NewsResearchBridge:
    """Transforms a Claude-selected news candidate and draft into a valid research_brief."""

    def __init__(self, schema_path: Path | str | None = None) -> None:
        base_dir = Path(__file__).resolve().parents[1]
        self.schema_path = Path(schema_path) if schema_path else base_dir / "schemas/artifacts/research_brief.schema.json"

        with self.schema_path.open("r", encoding="utf-8") as f:
            self.schema = json.load(f)
        self.validator = Draft7Validator(self.schema)

    def build_brief(
        self,
        candidate: Dict[str, Any],
        agent_draft: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Construct a validated research_brief; missing evidence raises instead of being invented."""
        draft = agent_draft.get("research_draft")
        if not isinstance(draft, dict):
            raise ValueError("research_draft must be an object")

        landscape = draft.get("landscape")
        audience = draft.get("audience_insights")
        if not isinstance(landscape, dict) or not isinstance(audience, dict):
            raise ValueError("research_draft missing landscape or audience_insights")

        existing_content = landscape.get("existing_content")
        saturated_angles = landscape.get("saturated_angles")
        underserved_gaps = landscape.get("underserved_gaps")
        data_points = draft.get("data_points")
        common_questions = audience.get("common_questions")
        misconceptions = audience.get("misconceptions")
        knowledge_level = audience.get("knowledge_level")
        angles = draft.get("angles_discovered")
        raw_sources = draft.get("sources")

        if not isinstance(existing_content, list):
            existing_content = []
        if len(existing_content) < 3:
            raise ValueError(
                "BLOCKED: research incomplete; fewer than three supplied existing_content records"
            )

        if not isinstance(data_points, list):
            data_points = []
        if len(data_points) < 3:
            raise ValueError(
                "BLOCKED: research incomplete; fewer than three supplied source-backed data_points"
            )

        if not isinstance(common_questions, list):
            common_questions = []
        if len(common_questions) < 3:
            raise ValueError(
                "BLOCKED: research incomplete; fewer than three supplied common_questions"
            )

        if not isinstance(angles, list):
            angles = []
        if len(angles) < 3:
            raise ValueError(
                "BLOCKED: research incomplete; fewer than three supplied angles_discovered"
            )
        if not isinstance(raw_sources, list):
            raise ValueError("research sources must be an array")
        if not isinstance(saturated_angles, list) or not isinstance(underserved_gaps, list):
            raise ValueError("landscape angle fields must be arrays")
        if not underserved_gaps:
            raise ValueError("BLOCKED: research incomplete; no supplied underserved_gaps")
        if not isinstance(misconceptions, list) or not isinstance(knowledge_level, str):
            raise ValueError("audience_insights fields are incomplete")

        sources = []
        seen_urls = set()
        if not isinstance(raw_sources, list):
            raw_sources = []
        for source in raw_sources:
            if not isinstance(source, dict):
                continue
            url = source.get("url")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            normalized_source = {
                "url": url,
                "title": self._require_string(source.get("title") or "Source", "research source title"),
                "used_for": self._require_string(source.get("used_for") or "Research evidence", "research source used_for"),
            }
            if "reliability" in source and isinstance(source["reliability"], str):
                normalized_source["reliability"] = self._require_string(
                    source["reliability"], "research source reliability"
                )
            sources.append(normalized_source)

        normalized_existing_content = []
        for item in existing_content:
            if not isinstance(item, dict):
                raise ValueError("each existing_content entry must be an object")
            normalized_item = {
                "title": self._require_string(item.get("title"), "existing_content title"),
                "source": self._require_string(item.get("source"), "existing_content source"),
                "angle": self._require_string(item.get("angle"), "existing_content angle"),
                "what_it_covers": self._require_string(
                    item.get("what_it_covers"), "existing_content what_it_covers"
                ),
            }
            for field in ("url", "what_it_misses", "engagement_signal"):
                if field in item:
                    normalized_item[field] = self._require_string(
                        item[field], f"existing_content {field}"
                    )
            normalized_existing_content.append(normalized_item)
            source_url = normalized_item.get("url")
            if source_url and source_url not in seen_urls:
                seen_urls.add(source_url)
                sources.append({
                    "url": source_url,
                    "title": normalized_item["title"],
                    "used_for": "Supplied existing-content reference",
                })

        normalized_data_points = []
        for item in data_points:
            if not isinstance(item, dict):
                raise ValueError("each data_point must be an object")
            source_url = self._require_string(item.get("source_url"), "data_point source_url")
            normalized_item = {
                "claim": self._require_string(item.get("claim"), "data_point claim"),
                "source_url": source_url,
                "credibility": self._require_string(item.get("credibility"), "data_point credibility"),
            }
            for field in ("source_name", "surprise_factor", "usable_as"):
                if field in item:
                    normalized_item[field] = self._require_string(item[field], f"data_point {field}")
            normalized_data_points.append(normalized_item)
            if source_url not in seen_urls:
                seen_urls.add(source_url)
                sources.append({
                    "url": source_url,
                    "title": self._require_string(item.get("source_name") or source_url, "data_point source title"),
                    "used_for": "Supplied data-point reference",
                })

        if len(sources) < 5:
            raise ValueError(
                "BLOCKED: research incomplete; fewer than five supplied source records (unique URLs)"
            )

        normalized_questions = [
            self._require_string(question, "audience common_question")
            for question in common_questions
        ]
        normalized_misconceptions = []
        for item in misconceptions:
            if not isinstance(item, dict):
                raise ValueError("each misconception must be an object")
            normalized_item = {
                "myth": self._require_string(item.get("myth"), "misconception myth"),
                "reality": self._require_string(item.get("reality"), "misconception reality"),
            }
            if "source" in item:
                normalized_item["source"] = self._require_string(
                    item["source"], "misconception source"
                )
            normalized_misconceptions.append(normalized_item)

        normalized_angles = []
        for item in angles:
            if not isinstance(item, dict):
                raise ValueError("each angle must be an object")
            raw_type = self._require_string(item.get("type"), "angle type")
            if raw_type not in {"trending", "evergreen", "contrarian", "narrative", "data_driven"}:
                angle_type = "data_driven" if "tech" in raw_type or "data" in raw_type else "trending"
            else:
                angle_type = raw_type
            normalized_item = {
                "name": self._require_string(item.get("name"), "angle name"),
                "hook": self._require_string(item.get("hook"), "angle hook"),
                "type": angle_type,
                "why_now": self._require_string(item.get("why_now"), "angle why_now"),
            }
            if "grounded_in" in item:
                grounded_in = item["grounded_in"]
                if not isinstance(grounded_in, list):
                    raise ValueError("angle grounded_in must be an array")
                normalized_item["grounded_in"] = [
                    self._require_string(value, "angle grounded_in entry")
                    for value in grounded_in
                ]
            normalized_angles.append(normalized_item)

        brief = {
            "version": "1.0",
            "topic": self._require_string(candidate.get("title"), "candidate title"),
            "research_date": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d"),
            "landscape": {
                "existing_content": normalized_existing_content,
                "saturated_angles": [
                    self._require_string(angle, "saturated_angle")
                    for angle in saturated_angles
                ],
                "underserved_gaps": [
                    self._require_string(gap, "underserved_gap")
                    for gap in underserved_gaps
                ],
            },
            "data_points": normalized_data_points,
            "audience_insights": {
                "common_questions": normalized_questions,
                "misconceptions": normalized_misconceptions,
                "knowledge_level": self._require_string(
                    knowledge_level, "audience knowledge_level"
                ),
            },
            "angles_discovered": normalized_angles,
            "sources": sources,
            "metadata": {
                "candidate_id": candidate["candidate_id"],
                "content_hash": candidate["content_hash"],
                "source_feed": candidate.get("raw_provenance", {}).get("source_feed", "newsnow"),
            },
        }

        self.validator.validate(brief)
        return brief

    @staticmethod
    def _require_string(value: Any, field: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field} must be a non-empty string")
        return value.strip()
