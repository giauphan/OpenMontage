"""Unit tests for extracted _compose helper modules."""

from __future__ import annotations

from pathlib import Path
import pytest

from tools.video._compose.asset_resolution import (
    is_image,
    build_asset_lookup,
    resolve_cuts,
    cuts_to_cinematic_scenes,
)


class TestAssetResolutionExtract:
    """Test asset resolution pure functions."""

    def test_is_image(self):
        assert is_image("photo.png")
        assert is_image(Path("photo.JPG"))
        assert is_image("banner.webp")
        assert not is_image("clip.mp4")
        assert not is_image("audio.wav")
        assert not is_image("")

    def test_build_asset_lookup(self):
        manifest = {
            "assets": [
                {"id": "a1", "path": "/path/to/a1.png", "type": "image"},
                {"id": "a2", "path": "/path/to/a2.mp4", "type": "video"},
            ]
        }
        lookup = build_asset_lookup(manifest)
        assert len(lookup) == 2
        assert lookup["a1"]["path"] == "/path/to/a1.png"
        assert lookup["a2"]["type"] == "video"
        assert build_asset_lookup(None) == {}
        assert build_asset_lookup({}) == {}

    def test_resolve_cuts(self):
        manifest = {
            "assets": [
                {"id": "asset_hero", "path": "/media/hero.mp4"},
            ]
        }
        cuts = [
            {"id": "c1", "source": "asset_hero", "duration": 3.0},
            {"id": "c2", "source": "/direct/path.mp4", "duration": 2.0},
        ]
        resolved = resolve_cuts(cuts, manifest)
        assert len(resolved) == 2
        assert resolved[0]["source"] == "/media/hero.mp4"
        assert resolved[1]["source"] == "/direct/path.mp4"
        assert resolve_cuts([]) == []

    def test_cuts_to_cinematic_scenes(self):
        cuts = [
            {
                "id": "c1",
                "type": "title",
                "text": "Introduction",
                "in_seconds": 0.0,
                "out_seconds": 2.5,
            },
            {
                "id": "c2",
                "type": "video",
                "source": "/path/clip.mp4",
                "in_seconds": 1.0,
                "out_seconds": 5.0,
                "speed": 2.0,
                "transition_in": "cut",
                "transition_out": "none",
            },
        ]
        scenes = cuts_to_cinematic_scenes(cuts)
        assert len(scenes) == 2

        # Scene 1: title
        assert scenes[0]["kind"] == "title"
        assert scenes[0]["text"] == "Introduction"
        assert scenes[0]["startSeconds"] == 0.0
        assert scenes[0]["durationSeconds"] == 2.5

        # Scene 2: video with speed 2.0 (4.0s / 2.0 = 2.0s duration)
        assert scenes[1]["kind"] == "video"
        assert scenes[1]["src"] == "/path/clip.mp4"
        assert scenes[1]["startSeconds"] == 2.5
        assert scenes[1]["durationSeconds"] == 2.0
        assert scenes[1]["fadeInFrames"] == 0
        assert scenes[1]["fadeOutFrames"] == 0
