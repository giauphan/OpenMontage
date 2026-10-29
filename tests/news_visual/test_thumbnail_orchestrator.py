"""Unit and contract tests for ThumbnailOrchestrator."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from PIL import Image

from lib.news_visual.thumbnail_orchestrator import (
    MAX_THUMBNAIL_SIZE_BYTES,
    ThumbnailOrchestrator,
    ThumbnailResult,
)
from lib.news_visual.thumbnail_planner import ThumbnailPlan


def test_synthetic_fallback_generation(tmp_path: Path):
    plan = ThumbnailPlan(
        title="Test Title",
        headline="TEST HEADLINE",
        prompt="Test prompt",
        negative_prompt="Test neg",
        aspect_ratio="9:16",
        target_dimensions=(1080, 1920),
        headline_position="upper_third",
        theme_color="#FFDD00",
    )
    out = tmp_path / "thumb.png"
    result_path = ThumbnailOrchestrator._create_synthetic_fallback(plan, out)
    assert result_path.is_file()
    with Image.open(result_path) as img:
        assert img.size == (1080, 1920)
        assert img.format == "PNG"


def test_headline_compositing(tmp_path: Path):
    base_img = tmp_path / "base.png"
    img = Image.new("RGB", (1080, 1920), (20, 20, 30))
    img.save(base_img)

    comp_path = ThumbnailOrchestrator._composite_headline(
        image_path=base_img,
        headline="AI REVOLUTION",
        position="upper_third",
        theme_color="#00FFFF",
    )
    assert comp_path.is_file()
    with Image.open(comp_path) as res_img:
        assert res_img.size == (1080, 1920)


def test_generate_thumbnail_with_mock_muse(tmp_path: Path):
    proj_dir = tmp_path / "project_1"
    proj_dir.mkdir()

    # Pre-create metadata
    meta_file = proj_dir / "publish_metadata.json"
    meta_file.write_text(json.dumps({"id": "proj_1", "title": "AI Model Release"}), encoding="utf-8")

    def mock_muse_execute(inputs):
        out_p = Path(inputs["output_path"])
        out_p.parent.mkdir(parents=True, exist_ok=True)
        img = Image.new("RGB", (1080, 1920), (50, 80, 120))
        img.save(out_p)
        res = MagicMock()
        res.success = True
        res.error = None
        res.data = {"output_path": str(out_p)}
        return res

    with patch("tools.graphics.muse_gateway_image.MuseGatewayImage.execute", side_effect=mock_muse_execute):
        res = ThumbnailOrchestrator.generate_thumbnail(
            project_dir=proj_dir,
            title="Claude 3.7 Released #ai",
            format_type="short",
        )

        assert isinstance(res, ThumbnailResult)
        assert res.success is True
        assert res.thumbnail_status == "THUMBNAIL_READY"
        assert res.thumbnail_path is not None
        assert Path(res.thumbnail_path).is_file()
        assert res.metadata["width"] == 1080
        assert res.metadata["height"] == 1920

        # Check metadata update
        updated_meta = json.loads(meta_file.read_text(encoding="utf-8"))
        assert "thumbnail_path" in updated_meta
        assert updated_meta["thumbnail_path"] == res.thumbnail_path


def test_generate_thumbnail_with_injected_port(tmp_path: Path):
    """Verify Clean Architecture dependency injection via ImageGeneratorPort Protocol."""
    proj_dir = tmp_path / "project_injected"
    proj_dir.mkdir()

    class FakeImageGenerator:
        def __init__(self):
            self.calls = []

        def execute(self, inputs):
            self.calls.append(inputs)
            out = Path(inputs["output_path"])
            out.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (1080, 1920), (100, 150, 200)).save(out)
            res = MagicMock()
            res.success = True
            res.error = None
            res.data = {"output_path": str(out)}
            return res

    fake_gen = FakeImageGenerator()
    res = ThumbnailOrchestrator.generate_thumbnail(
        project_dir=proj_dir,
        title="Custom Model Architecture",
        format_type="short",
        image_generator=fake_gen,
    )

    assert res.success is True
    assert res.thumbnail_status == "THUMBNAIL_READY"
    assert len(fake_gen.calls) == 1
    assert fake_gen.calls[0]["aspect_ratio"] == "9:16"
    assert "Custom Model Architecture" in fake_gen.calls[0]["prompt"]


def test_generate_thumbnail_rejects_oversized_file(tmp_path: Path, monkeypatch):
    proj_dir = tmp_path / "project_2"
    proj_dir.mkdir()

    thumb_file = proj_dir / "thumbnails" / "thumbnail.png"
    thumb_file.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (1080, 1920), (10, 10, 10))
    img.save(thumb_file)

    # Mock stat to return size > 50MB
    original_stat = Path.stat

    def mock_stat(self, *args, **kwargs):
        st = original_stat(self, *args, **kwargs)
        if self.name == "thumbnail.png":
            mock_st = MagicMock(spec=st)
            mock_st.st_size = MAX_THUMBNAIL_SIZE_BYTES + 1024
            mock_st.st_mode = st.st_mode
            return mock_st
        return st

    monkeypatch.setattr(Path, "stat", mock_stat)

    res = ThumbnailOrchestrator.generate_thumbnail(
        project_dir=proj_dir,
        title="Oversized Thumbnail Video",
        format_type="short",
    )
    assert res.success is False
    assert res.thumbnail_status == "THUMBNAIL_FAILED"
    assert "exceeds YouTube 2MB limit" in res.error


def test_generate_thumbnail_rejects_corrupt_file(tmp_path: Path):
    proj_dir = tmp_path / "project_3"
    proj_dir.mkdir()

    corrupt_file = proj_dir / "thumbnails" / "thumbnail.png"
    corrupt_file.parent.mkdir(parents=True, exist_ok=True)
    corrupt_file.write_bytes(b"not an image at all garbage bytes")

    # Mock dispatch to say it succeeded writing the corrupt file
    with patch.object(ThumbnailOrchestrator, "_dispatch_muse", return_value={"success": True, "error": None}), \
         patch.object(ThumbnailOrchestrator, "_composite_headline", side_effect=Exception("Cannot read image")):
        res = ThumbnailOrchestrator.generate_thumbnail(
            project_dir=proj_dir,
            title="Corrupt File Video",
            format_type="short",
            allow_fallback=False,
        )
        assert res.success is False
        assert res.thumbnail_status == "THUMBNAIL_FAILED"
        assert "Corrupt thumbnail image" in res.error
