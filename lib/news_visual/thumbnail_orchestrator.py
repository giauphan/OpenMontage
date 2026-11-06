"""Orchestrator for generating, compositing, and verifying YouTube thumbnails via Muse."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Protocol, Tuple, runtime_checkable

from PIL import Image, ImageDraw, ImageFont

from lib.news_visual.thumbnail_planner import ThumbnailPlan, ThumbnailPlanner

logger = logging.getLogger(__name__)

# YouTube official limit for thumbnails: Under 2MB (https://support.google.com/youtube/answer/72431)
MAX_THUMBNAIL_SIZE_BYTES = 2 * 1024 * 1024


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
    def _wrap_headline(cls, headline: str, font: ImageFont.ImageFont, max_width: int, draw: ImageDraw.ImageDraw) -> list[str]:
        """Wrap headline text so each line fits within max_width."""
        words = [w.strip() for w in headline.split() if w.strip()]
        if not words:
            return []
        lines = []
        cur_line = []
        for word in words:
            test_line = " ".join(cur_line + [word])
            bbox = draw.textbbox((0, 0), test_line, font=font)
            if (bbox[2] - bbox[0]) <= max_width or not cur_line:
                cur_line.append(word)
            else:
                lines.append(" ".join(cur_line))
                cur_line = [word]
        if cur_line:
            lines.append(" ".join(cur_line))
        return lines

    @classmethod
    def _composite_headline(
        cls,
        image_path: Path,
        headline: str,
        position: str = "body_center",
        theme_color: str = "#FFDD00",
        output_path: Optional[Path] = None,
    ) -> Path:
        """Composite high-contrast, multi-line headline overlay in body center avoiding text cutoff."""
        out = output_path or image_path
        with Image.open(image_path) as img:
            img = img.convert("RGBA")
            width, height = img.size

            overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            draw = ImageDraw.Draw(overlay)

            # Generous margins to strictly avoid text cutoff:
            # 1. Outer canvas margin: at least 15% on both left and right (max badge width = 70%)
            # 2. Inner badge padding: at least 5.5% of width or 0.95 * font_size
            # Resulting in total horizontal clearance of >= 20% on both left and right!
            canvas_margin_x = int(width * 0.15)
            max_badge_w = width - (canvas_margin_x * 2)

            font_size = max(34, int(width * 0.055))
            pad_x = max(int(font_size * 0.95), int(width * 0.055))
            pad_y = max(int(font_size * 0.55), int(height * 0.015))
            max_text_width = max_badge_w - (pad_x * 2)

            font = cls._get_font(font_size)
            lines = cls._wrap_headline(headline, font, max_text_width, draw)

            # Dynamically reduce font size if text spans > 3 lines or exceeds width
            while (
                len(lines) > 3
                or any(
                    (draw.textbbox((0, 0), l, font=font)[2] - draw.textbbox((0, 0), l, font=font)[0])
                    > max_text_width
                    for l in lines
                )
            ) and font_size > 18:
                font_size -= 2
                pad_x = max(int(font_size * 0.95), int(width * 0.055))
                pad_y = max(int(font_size * 0.55), int(height * 0.015))
                max_text_width = max_badge_w - (pad_x * 2)
                font = cls._get_font(font_size)
                lines = cls._wrap_headline(headline, font, max_text_width, draw)

            if not lines:
                lines = [headline]

            # Measure all lines
            line_dims = []
            max_line_w = 0
            total_text_h = 0
            line_spacing = int(font_size * 0.28)
            for l in lines:
                bbox = draw.textbbox((0, 0), l, font=font)
                lw = bbox[2] - bbox[0]
                lh = bbox[3] - bbox[1]
                line_dims.append((lw, lh))
                max_line_w = max(max_line_w, lw)
                total_text_h += lh
            total_text_h += line_spacing * (len(lines) - 1)

            # Calculate badge dimensions with safe padding
            badge_w = min(max_badge_w, max_line_w + pad_x * 2)
            badge_h = total_text_h + pad_y * 2

            # Horizontal centering on canvas (guarantees >= 10% outer margin left & right)
            x0 = (width - badge_w) // 2

            # Vertical positioning in safe body center (avoiding top overlay & bottom caption zone)
            if position in ("body_center", "center"):
                y0 = int(height * 0.44 - badge_h / 2)
            elif position == "top":
                y0 = int(height * 0.12)
            elif position == "upper_third":
                y0 = int(height * 0.24)
            else:
                y0 = (height - badge_h) // 2

            # Safe vertical clamping
            safe_top = int(height * 0.10)
            safe_bottom = height - badge_h - int(height * 0.16)
            y0 = max(safe_top, min(y0, safe_bottom))

            # Draw dark background badge with rounded corners
            badge_box = [x0, y0, x0 + badge_w, y0 + badge_h]
            draw.rounded_rectangle(
                badge_box,
                radius=int(font_size * 0.40),
                fill=(12, 14, 22, 230),
                outline=theme_color,
                width=max(3, int(width * 0.0035)),
            )

            # Draw centered text lines (each line is centered within badge, keeping full pad_x margin)
            curr_y = y0 + pad_y
            for idx, line in enumerate(lines):
                lw, lh = line_dims[idx]
                line_x = max(x0 + pad_x, min(x0 + (badge_w - lw) // 2, x0 + badge_w - pad_x - lw))
                draw.text((line_x, curr_y), line, font=font, fill=(255, 255, 255, 255))
                curr_y += lh + line_spacing

            # Composite and save adhering to YouTube specs (https://support.google.com/youtube/answer/72431)
            combined = Image.alpha_composite(img, overlay).convert("RGB")
            out.parent.mkdir(parents=True, exist_ok=True)
            if out.suffix.lower() in (".jpg", ".jpeg"):
                combined.save(out, format="JPEG", quality=92, optimize=True)
            else:
                combined.save(out, format="PNG", optimize=True)
                if out.stat().st_size > MAX_THUMBNAIL_SIZE_BYTES:
                    try:
                        q_img = combined.quantize(colors=256, method=Image.Quantize.MEDIANCUT)
                        q_img.save(out, format="PNG", optimize=True)
                    except Exception:
                        pass
                if out.stat().st_size > MAX_THUMBNAIL_SIZE_BYTES:
                    combined.save(out.with_suffix(".jpg"), format="JPEG", quality=92, optimize=True)

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

        # Extract context text from project artifacts if available
        context_text = ""
        artifacts_dir = pdir / "artifacts"
        if artifacts_dir.is_dir():
            for sf in sorted(artifacts_dir.glob("script*.json")):
                try:
                    sd = json.loads(sf.read_text(encoding="utf-8"))
                    sections = sd.get("sections", [])
                    if sections:
                        context_text = " ".join([s.get("text", "") for s in sections[:2]])
                        break
                except Exception:
                    pass
            if not context_text:
                rb_file = artifacts_dir / "research_brief.json"
                if rb_file.is_file():
                    try:
                        rb = json.loads(rb_file.read_text(encoding="utf-8"))
                        context_text = f"{rb.get('topic', '')} {rb.get('angle', '')}"
                    except Exception:
                        pass

        plan = ThumbnailPlanner.plan_thumbnail(
            title=title,
            topic=topic,
            format_type=format_type,
            custom_headline=custom_headline,
            theme_color=theme_color,
            context_text=context_text,
        )

        # Determine target file path
        if output_path:
            out_file = Path(output_path).expanduser().resolve()
        else:
            thumb_dir = pdir / "thumbnails"
            thumb_dir.mkdir(parents=True, exist_ok=True)
            out_file = thumb_dir / "thumbnail.png"

        # Fresh submission key to avoid stale gateway retry cache
        sub_key = hashlib.sha256(f"{pdir.name}:{plan.prompt}:{time.time()}".encode("utf-8")).hexdigest()

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
                logger.info(f"Muse generation unavailable ({muse_res.get('error')}); using stylized thumbnail fallback.")
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
                error=f"Thumbnail size ({file_size} bytes) exceeds YouTube 2MB limit (https://support.google.com/youtube/answer/72431)",
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

        # Step 4: Sync to publish_metadata.json if present and not yet cryptographically locked
        meta_file = pdir / "publish_metadata.json"
        has_signed_approval = (pdir / "approval.json").is_file() or (pdir / "artifacts" / "approval.json").is_file()
        if meta_file.is_file() and not has_signed_approval:
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
