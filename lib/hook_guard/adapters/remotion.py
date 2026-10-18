"""Remotion hook adapter for materializing title card assets and injecting overlays."""

from __future__ import annotations

import copy
import hashlib
from pathlib import Path
from typing import Any, Optional

from PIL import Image, ImageDraw, ImageFont

from lib.hook_guard.adapters.base import BaseHookAdapter
from lib.hook_guard.config import PlatformProfile


class RemotionHookAdapter(BaseHookAdapter):
    """Adapter for Remotion composition runtime."""

    def materialize_asset(
        self,
        candidate: dict[str, Any],
        project_dir: Path | str,
        video_metadata: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        pdir = Path(project_dir)
        cand_id = candidate.get("id", "c1")
        images_dir = pdir / "assets" / "images"
        images_dir.mkdir(parents=True, exist_ok=True)

        text = str(candidate.get("text", "")).strip()
        asset_id = f"hook_{cand_id}"
        asset_filename = f"{asset_id}.png"
        asset_path = images_dir / asset_filename

        meta = video_metadata or {}
        res = meta.get("resolution", "1080x1920")
        w, h = 1080, 1920
        if "x" in res:
            try:
                parts = res.split("x")
                w, h = int(parts[0]), int(parts[1])
            except ValueError:
                pass

        # Create transparent RGBA image
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # Draw a semi-transparent rounded pill/box in upper safe zone
        is_vertical = h > w
        box_w = int(w * 0.88 if is_vertical else w * 0.70)
        box_h = int(h * 0.14 if is_vertical else h * 0.16)
        box_x = (w - box_w) // 2
        box_y = int(h * 0.15 if is_vertical else h * 0.10)

        # Background pill with soft dark tint
        draw.rounded_rectangle(
            [box_x, box_y, box_x + box_w, box_y + box_h],
            radius=24,
            fill=(15, 20, 30, 225),
            outline=(255, 255, 255, 60),
            width=2,
        )

        # Render text wrapped
        font_size = int(box_h * 0.28)
        try:
            # Try system font or default
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
        except Exception:
            font = ImageFont.load_default()

        # Simple wrap
        words = text.split()
        lines = []
        cur_line = []
        for word in words:
            test_line = " ".join(cur_line + [word])
            bbox = draw.textbbox((0, 0), test_line, font=font)
            if bbox[2] - bbox[0] > (box_w - 40) and cur_line:
                lines.append(" ".join(cur_line))
                cur_line = [word]
            else:
                cur_line.append(word)
        if cur_line:
            lines.append(" ".join(cur_line))

        total_text_h = len(lines) * (font_size + 8)
        text_y = box_y + (box_h - total_text_h) // 2
        for line in lines:
            line_bbox = draw.textbbox((0, 0), line, font=font)
            line_w = line_bbox[2] - line_bbox[0]
            text_x = box_x + (box_w - line_w) // 2
            draw.text((text_x, text_y), line, font=font, fill=(255, 255, 255, 255))
            text_y += font_size + 8

        img.save(asset_path, "PNG")

        return {
            "id": asset_id,
            "type": "image",
            "path": str(asset_path),
            "source_tool": "hook_guard",
            "scene_id": "scene-1",
            "metadata": {
                "is_hook": True,
                "text": text,
                "intent": candidate.get("intent"),
            },
        }

    def apply_overlay(
        self,
        edl: dict[str, Any],
        candidate: dict[str, Any],
        asset: dict[str, Any],
        profile: Optional[PlatformProfile] = None,
    ) -> dict[str, Any]:
        mutated = copy.deepcopy(edl)
        window = candidate.get("window", {})
        start_sec = float(window.get("start_seconds", 0.0))
        end_sec = float(window.get("end_seconds", 2.5))

        top_margin = profile.safe_zones.top_margin_pct if profile else 0.15
        side_margin = profile.safe_zones.side_margin_pct if profile else 0.08
        width_pct = max(0.5, 1.0 - (side_margin * 2))

        overlay_item = {
            "asset_id": asset["id"],
            "start_seconds": round(start_sec, 2),
            "end_seconds": round(end_sec, 2),
            "position": {
                "x": round(side_margin, 3),
                "y": round(top_margin, 3),
                "width": round(width_pct, 3),
                "height": 0.15,
            },
            "animation": "fade",
            "opacity": 1.0,
        }

        if "overlays" not in mutated or not isinstance(mutated["overlays"], list):
            mutated["overlays"] = []

        mutated["overlays"].append(overlay_item)
        return mutated
