"""Orchestrator for generating, compositing, and verifying YouTube thumbnails via Muse."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Protocol, Tuple, runtime_checkable

from PIL import Image, ImageDraw, ImageFont

from lib.news_visual.thumbnail_planner import ThumbnailPlan, ThumbnailPlanner

logger = logging.getLogger(__name__)

# YouTube hard limit for thumbnails (updated Sept 2026: 50MB)
MAX_THUMBNAIL_SIZE_BYTES = 50 * 1024 * 1024


@runtime_checkable
class ImageGeneratorPort(Protocol):
    """Outbound port abstraction for text-to-image generation adapters."""

    def execute(self, inputs: Dict[str, Any]) -> Any:
        ...


@dataclass
class ThumbnailResult:
    """Structured result of thumbnail generation."""

    success: bool
    thumbnail_path: Optional[str]
    thumbnail_status: str  # "THUMBNAIL_READY", "THUMBNAIL_FAILED"
    aspect_ratio: str
    error: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class ThumbnailOrchestrator:
    """Orchestrates Muse image generation, typography layout, verification, and metadata sync."""

    SYSTEM_FONTS = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    ]

    @classmethod
    def _get_font(cls, size: int) -> ImageFont.ImageFont:
        """Resolve a bold TrueType font with graceful fallback to default."""
        for font_path in cls.SYSTEM_FONTS:
            if Path(font_path).is_file():
                try:
                    return ImageFont.truetype(font_path, size=size)
                except Exception:
                    continue
        return ImageFont.load_default()

    @classmethod
    def _composite_headline(
        cls,
        image_path: Path,
        headline: str,
        position: str = "upper_third",
        theme_color: str = "#FFDD00",
        output_path: Optional[Path] = None,
    ) -> Path:
        """Composite high-contrast headline overlay onto the thumbnail."""
        out = output_path or image_path
        with Image.open(image_path) as img:
            img = img.convert("RGBA")
            width, height = img.size

            overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            draw = ImageDraw.Draw(overlay)

            font_size = max(36, int(width * 0.065))
            font = cls._get_font(font_size)

            # Measure text
            bbox = draw.textbbox((0, 0), headline, font=font)
            text_w = bbox[2] - bbox[0]
            text_h = bbox[3] - bbox[1]

            # Calculate position
            pad_x = int(font_size * 0.6)
            pad_y = int(font_size * 0.4)
            badge_w = text_w + pad_x * 2
            badge_h = text_h + pad_y * 2

            x0 = (width - badge_w) // 2
            if position == "top":
                y0 = int(height * 0.08)
            elif position == "upper_third":
                y0 = int(height * 0.18)
            else:  # center
                y0 = (height - badge_h) // 2

            # Draw semi-transparent dark badge backing with rounded corners
            badge_box = [x0, y0, x0 + badge_w, y0 + badge_h]
            draw.rounded_rectangle(
                badge_box,
                radius=int(font_size * 0.3),
                fill=(10, 10, 18, 220),
                outline=theme_color,
                width=max(2, int(width * 0.003)),
            )

            # Draw headline text with high contrast
            text_pos = (x0 + pad_x, y0 + pad_y)
            draw.text(text_pos, headline, font=font, fill=(255, 255, 255, 255))

            # Merge and save as RGB PNG/JPEG
            combined = Image.alpha_composite(img, overlay).convert("RGB")
            out.parent.mkdir(parents=True, exist_ok=True)
            combined.save(out, format="PNG", quality=95)

        return out

    @classmethod
    def _dispatch_muse(
        cls,
        prompt: str,
        aspect_ratio: str,
        output_path: Path,
        submission_key: str,
        generator: Optional[ImageGeneratorPort] = None,
    ) -> Dict[str, Any]:
        """Dispatch generation request using injected port or discovered ToolRegistry adapter."""
        if generator is not None:
            try:
                res = generator.execute({
                    "prompt": prompt,
                    "aspect_ratio": aspect_ratio,
                    "model": "muse-image",
                    "output_path": str(output_path),
                    "submission_key": f"om-thumb-{submission_key[:24]}",
                })
                return {"success": res.success, "error": res.error, "data": res.data}
            except Exception as e:
                return {"success": False, "error": str(e)}

        try:
            from tools.tool_registry import ToolRegistry

            registry = ToolRegistry()
            registry.discover()
            if "muse_gateway_image" in registry._tools:
                tool_obj = registry._tools["muse_gateway_image"]
                tool_instance = tool_obj() if isinstance(tool_obj, type) else tool_obj
                res = tool_instance.execute({
                    "prompt": prompt,
                    "aspect_ratio": aspect_ratio,
                    "model": "muse-image",
                    "output_path": str(output_path),
                    "submission_key": f"om-thumb-{submission_key[:24]}",
                })
                return {"success": res.success, "error": res.error, "data": res.data}
        except Exception as e:
            logger.warning(f"ToolRegistry muse dispatch failed: {e}")

        # Direct instantiation fallback
        try:
            from tools.graphics.muse_gateway_image import MuseGatewayImage

            tool = MuseGatewayImage()
            res = tool.execute({
                "prompt": prompt,
                "aspect_ratio": aspect_ratio,
                "model": "muse-image",
                "output_path": str(output_path),
                "submission_key": f"om-thumb-{submission_key[:24]}",
            })
            return {"success": res.success, "error": res.error, "data": res.data}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    @classmethod
    def _create_synthetic_fallback(
        cls,
        plan: ThumbnailPlan,
        output_path: Path,
    ) -> Path:
        """Create a high-quality stylized gradient thumbnail when external gateway is unavailable."""
        width, height = plan.target_dimensions
        img = Image.new("RGB", (width, height), (15, 20, 35))
        draw = ImageDraw.Draw(img)

        # Draw deep stylized gradient & tech geometry
        for y in range(height):
            ratio = y / height
            r = int(10 + 25 * ratio)
            g = int(15 + 40 * ratio)
            b = int(35 + 80 * ratio)
            draw.line([(0, y), (width, y)], fill=(r, g, b))

        # Accent circle / visual anchor
        cx, cy = width // 2, int(height * 0.48)
        rad = int(min(width, height) * 0.28)
        draw.ellipse([cx - rad, cy - rad, cx + rad, cy + rad], outline=plan.theme_color, width=4)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(output_path, format="PNG")
        return output_path

    @classmethod
    def generate_thumbnail(
        cls,
        project_dir: Path | str,
        title: str,
        topic: str = "",
        format_type: str = "short",
        custom_headline: Optional[str] = None,
        output_path: Optional[Path | str] = None,
        add_headline_overlay: bool = True,
        theme_color: str = "#FFDD00",
        allow_fallback: bool = True,
        image_generator: Optional[ImageGeneratorPort] = None,
    ) -> ThumbnailResult:
        """Main entry point to generate and verify a YouTube thumbnail using Muse."""
        pdir = Path(project_dir).expanduser().resolve()
        plan = ThumbnailPlanner.plan_thumbnail(
            title=title,
            topic=topic,
            format_type=format_type,
            custom_headline=custom_headline,
            theme_color=theme_color,
        )

        # Determine target file path
        if output_path:
            out_file = Path(output_path).expanduser().resolve()
        else:
            thumb_dir = pdir / "thumbnails"
            thumb_dir.mkdir(parents=True, exist_ok=True)
            out_file = thumb_dir / "thumbnail.png"

        # Deterministic submission key
        sub_key = hashlib.sha256(f"{pdir.name}:{plan.prompt}".encode("utf-8")).hexdigest()

        # Step 1: Generate base image via Muse Gateway or injected adapter
        muse_res = cls._dispatch_muse(
            prompt=plan.prompt,
            aspect_ratio=plan.aspect_ratio,
            output_path=out_file,
            submission_key=sub_key,
            generator=image_generator,
        )

        used_fallback = False
        if not (muse_res.get("success") and out_file.is_file()):
            if allow_fallback:
                logger.info("Muse generation unavailable; using stylized thumbnail fallback.")
                cls._create_synthetic_fallback(plan, out_file)
                used_fallback = True
            else:
                err = muse_res.get("error") or "Muse image generation failed"
                return ThumbnailResult(
                    success=False,
                    thumbnail_path=None,
                    thumbnail_status="THUMBNAIL_FAILED",
                    aspect_ratio=plan.aspect_ratio,
                    error=err,
                )

        # Step 2: Overlay typography if enabled
        if add_headline_overlay and plan.headline:
            try:
                cls._composite_headline(
                    image_path=out_file,
                    headline=plan.headline,
                    position=plan.headline_position,
                    theme_color=plan.theme_color,
                    output_path=out_file,
                )
            except Exception as e:
                logger.warning(f"Typography composite failed ({e}); retaining raw image.")

        # Step 3: Verification
        if not out_file.is_file():
            return ThumbnailResult(
                success=False,
                thumbnail_path=None,
                thumbnail_status="THUMBNAIL_FAILED",
                aspect_ratio=plan.aspect_ratio,
                error="Thumbnail file does not exist after generation",
            )

        file_size = out_file.stat().st_size
        if file_size > MAX_THUMBNAIL_SIZE_BYTES:
            return ThumbnailResult(
                success=False,
                thumbnail_path=str(out_file),
                thumbnail_status="THUMBNAIL_FAILED",
                aspect_ratio=plan.aspect_ratio,
                error=f"Thumbnail size ({file_size} bytes) exceeds YouTube 50MB limit",
            )

        try:
            with Image.open(out_file) as img:
                w, h = img.size
                img_format = img.format
        except Exception as e:
            return ThumbnailResult(
                success=False,
                thumbnail_path=str(out_file),
                thumbnail_status="THUMBNAIL_FAILED",
                aspect_ratio=plan.aspect_ratio,
                error=f"Corrupt thumbnail image: {e}",
            )

        # Step 4: Sync to publish_metadata.json if present
        meta_file = pdir / "publish_metadata.json"
        if meta_file.is_file():
            try:
                with meta_file.open("r", encoding="utf-8") as f:
                    meta_data = json.load(f)
                meta_data["thumbnail_path"] = str(out_file)
                meta_data["thumbnail"] = str(out_file)
                with meta_file.open("w", encoding="utf-8") as f:
                    json.dump(meta_data, f, indent=2, ensure_ascii=False)
            except Exception as e:
                logger.warning(f"Could not update {meta_file}: {e}")

        return ThumbnailResult(
            success=True,
            thumbnail_path=str(out_file),
            thumbnail_status="THUMBNAIL_READY",
            aspect_ratio=plan.aspect_ratio,
            metadata={
                "width": w,
                "height": h,
                "format": img_format,
                "size_bytes": file_size,
                "headline": plan.headline,
                "prompt": plan.prompt,
                "used_fallback": used_fallback,
            },
        )
