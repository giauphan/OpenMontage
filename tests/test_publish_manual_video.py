import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]

def test_publish_manual_video_skips_duplicates_and_avoids_facebook(tmp_path: Path):
    from scripts.publish_manual_video import publish_batch
    
    project_dir = tmp_path / "projects" / "cand_A"
    project_dir.mkdir(parents=True)
    
    (project_dir / "publish_metadata.json").write_text(json.dumps({
        "id": "cand_A",
        "title": "T",
        "description": "D",
        "yt_shorts": "renders/final_reels_vi_9x16.mp4",
        "ig_reels": "renders/final_reels_vi_9x16.mp4",
        "fb_video": "renders/final_full_vi_9x16.mp4",
        "topic": "topic_abc"
    }))
    
    renders_dir = project_dir / "renders"
    renders_dir.mkdir()
    (renders_dir / "final_full_vi_9x16.mp4").touch()
    (renders_dir / "final_reels_vi_9x16.mp4").touch()

    artifacts_dir = project_dir / "artifacts"
    artifacts_dir.mkdir()
    (artifacts_dir / "narration_vi_text.txt").write_text("Chào mọi người hôm nay chúng ta có tin tức mới.", encoding="utf-8")
    
    # Store that claims to have already scheduled / published everything
    class DummyStore:
        def __init__(self):
            self.claims = []
        def claim(self, *, platform, **kwargs):
            self.claims.append(platform)
            return "key123", False, {"status": "published"}
        def unclaim(self, *args, **kwargs):
            pass
            
    store = DummyStore()

    with patch("scripts.publish_manual_video.YoutubePublisher") as mock_yt_pub_class, \
         patch("scripts.publish_manual_video.MetaPublisher") as mock_meta_pub_class, \
         patch("scripts.publish_manual_video.validate_video", return_value=[]), \
         patch("scripts.publish_manual_video.validate_vietnamese_narration", return_value=[]), \
         patch("scripts.publish_manual_video.FB_PAGE_ID", "dummy_fb"), \
         patch("scripts.publish_manual_video.IG_ACCOUNT_ID", "dummy_ig"), \
         patch("scripts.publish_manual_video.YT_ACCOUNT", "dummy_yt"), \
         patch("builtins.open", MagicMock(return_value=MagicMock())):
        
        # Test 1: By default, without MULTI_PLATFORM=1, only youtube is used
        metadata = json.loads((project_dir / "publish_metadata.json").read_text())
        results = publish_batch(metadata, project_dir, store)
        
        assert "youtube" in store.claims
        assert "instagram" not in store.claims
        assert "facebook" not in store.claims
        assert mock_yt_pub_class.return_value.execute.call_count == 0
        assert mock_meta_pub_class.return_value.execute.call_count == 0
        
        # Reset and mock MULTI_PLATFORM
        store.claims.clear()
        
        with patch.dict("os.environ", {"MULTI_PLATFORM": "1", "FACEBOOK_PUBLISH_ENABLED": "0"}):
            results = publish_batch(metadata, project_dir, store)
            
            # Since FB is disabled via env var, only YouTube and Instagram are claimed
            assert "youtube" in store.claims
            assert "instagram" in store.claims
            assert "facebook" not in store.claims
            
            # Execution is bounded by the claimed=False above
            assert mock_yt_pub_class.return_value.execute.call_count == 0
            assert mock_meta_pub_class.return_value.execute.call_count == 0

