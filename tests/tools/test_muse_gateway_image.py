"""Mock, fault injection, and contract tests for tools.graphics.muse_gateway_image."""
from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from PIL import Image
import requests

from tools.graphics.muse_gateway_image import MuseGatewayImage
from tools.tool_registry import ToolRegistry


def make_test_png(width: int = 100, height: int = 177) -> bytes:
    """Create a minimal valid PNG image bytes."""
    buf = io.BytesIO()
    img = Image.new("RGB", (width, height), color=(15, 23, 42))
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def test_png_bytes():
    return make_test_png()


def test_muse_gateway_tool_discovered_in_registry():
    """Verify ToolRegistry discovers muse_gateway_image automatically."""
    registry = ToolRegistry()
    registry.discover()
    assert "muse_gateway_image" in registry._tools
    tool_cls = registry._tools["muse_gateway_image"]
    assert tool_cls.capability == "image_generation"
    assert tool_cls.provider == "muse"


def test_request_validation_empty_prompt():
    tool = MuseGatewayImage()
    res = tool.execute({"prompt": "   "})
    assert not res.success
    assert res.data.get("error_code") == "INVALID_INPUT"


def test_request_validation_invalid_aspect_ratio():
    tool = MuseGatewayImage()
    res = tool.execute({"prompt": "A valid prompt", "aspect_ratio": "4:5"})
    assert not res.success
    assert res.data.get("error_code") == "INVALID_ASPECT_RATIO"


def test_external_calls_gate_blocks_by_default(monkeypatch):
    monkeypatch.setenv("MUSE_GATEWAY_EXTERNAL_CALLS_ALLOWED", "0")
    tool = MuseGatewayImage()
    res = tool.execute({"prompt": "Valid conceptual prompt"})
    assert not res.success
    assert res.data.get("error_code") == "EXTERNAL_CALLS_DISABLED"


def test_gateway_409_approval_required(test_png_bytes, monkeypatch):
    """Gateway returns 409 when Muse browser scoped approval is pending."""
    tool = MuseGatewayImage()
    tool._allow_offline_mock = True

    mock_resp = MagicMock()
    mock_resp.status_code = 409
    mock_resp.text = "Approval pending in Gateway browser"
    tool._session.post = MagicMock(return_value=mock_resp)

    res = tool.execute({"prompt": "Conceptual illustration of coding agent memory"})
    assert not res.success
    assert res.data.get("error_code") == "APPROVAL_REQUIRED"
    assert res.data.get("approval_required") is True


def test_gateway_400_bad_request():
    tool = MuseGatewayImage()
    tool._allow_offline_mock = True

    mock_resp = MagicMock()
    mock_resp.status_code = 400
    mock_resp.text = "Invalid prompt content"
    tool._session.post = MagicMock(return_value=mock_resp)

    res = tool.execute({"prompt": "Invalid prompt"})
    assert not res.success
    assert res.data.get("error_code") == "INVALID_REQUEST"


def test_gateway_401_403_auth_policy_block():
    tool = MuseGatewayImage()
    tool._allow_offline_mock = True

    mock_resp = MagicMock()
    mock_resp.status_code = 403
    tool._session.post = MagicMock(return_value=mock_resp)

    res = tool.execute({"prompt": "Forbidden prompt"})
    assert not res.success
    assert res.data.get("error_code") == "AUTH_FAILED"


def test_gateway_connection_refusal():
    tool = MuseGatewayImage()
    tool._allow_offline_mock = True
    tool._session.post = MagicMock(side_effect=requests.exceptions.ConnectionError("Connection refused"))

    res = tool.execute({"prompt": "Valid prompt"})
    assert not res.success
    assert res.data.get("error_code") == "GATEWAY_CONNECT_FAILED"


def test_successful_async_job_and_poll_completion(tmp_path: Path, test_png_bytes, monkeypatch):
    """Happy path: 200 submitting -> 200 completed -> content download -> atomic write."""
    monkeypatch.setenv("MUSE_GATEWAY_POLL_INTERVAL_SECONDS", "0.01")
    tool = MuseGatewayImage()
    tool._allow_offline_mock = True

    # 1. Post create-image
    create_resp = MagicMock()
    create_resp.status_code = 200
    create_resp.json.return_value = {
        "id": "image-uuid-1234",
        "status": "submitting",
        "model": "muse-image",
    }
    tool._session.post = MagicMock(return_value=create_resp)

    # 2. Polling response
    poll_resp = MagicMock()
    poll_resp.status_code = 200
    poll_resp.json.return_value = {
        "id": "image-uuid-1234",
        "status": "completed",
        "image_url": "http://127.0.0.1:20129/muse-ai/v1/images/image-uuid-1234/content",
    }

    # 3. Content response
    content_resp = MagicMock()
    content_resp.status_code = 200
    content_resp.iter_content.return_value = [test_png_bytes]

    def mock_get(url, *args, **kwargs):
        if "content" in url:
            return content_resp
        return poll_resp

    tool._session.get = MagicMock(side_effect=mock_get)

    out_file = tmp_path / "art_output.png"
    res = tool.execute({
        "prompt": "Conceptual illustration of coding agent session memory loss",
        "aspect_ratio": "9:16",
        "output_path": str(out_file),
    })

    assert res.success is True
    assert res.data["gateway_job_id"] == "image-uuid-1234"
    assert res.data["provider"] == "muse"
    assert res.data["model"] == "muse-image"
    assert res.data["width"] == 100
    assert res.data["height"] == 177
    assert res.data["mime"] == "image/png"
    assert out_file.is_file()
    assert out_file.stat().st_size == len(test_png_bytes)


def test_polling_timeout_fails_closed(monkeypatch):
    """Async job never completes before deadline."""
    monkeypatch.setenv("MUSE_GATEWAY_POLL_INTERVAL_SECONDS", "0.01")
    monkeypatch.setenv("MUSE_GATEWAY_JOB_DEADLINE_SECONDS", "0.05")
    tool = MuseGatewayImage()
    tool._allow_offline_mock = True

    create_resp = MagicMock()
    create_resp.status_code = 200
    create_resp.json.return_value = {"id": "image-uuid-forever", "status": "submitting"}
    tool._session.post = MagicMock(return_value=create_resp)

    poll_resp = MagicMock()
    poll_resp.status_code = 200
    poll_resp.json.return_value = {"id": "image-uuid-forever", "status": "submitting"}
    tool._session.get = MagicMock(return_value=poll_resp)

    res = tool.execute({"prompt": "Prompt that hangs"})
    assert not res.success
    assert res.data.get("error_code") == "JOB_TIMEOUT"


def test_ssrf_protection_rejects_link_local_and_aws_metadata(monkeypatch):
    """Enforce strict SSRF protection: reject AWS metadata endpoint 169.254.169.254."""
    tool = MuseGatewayImage()
    assert not tool._is_safe_remote_url("http://169.254.169.254/latest/meta-data")
    assert not tool._is_safe_remote_url("http://192.168.1.10/private")
    assert not tool._is_safe_remote_url("http://10.0.0.1/internal")
    assert not tool._is_safe_remote_url("http://evil-external-host.com/image.png")

    # Localhost and explicitly allowlisted hosts pass
    assert tool._is_safe_remote_url("http://127.0.0.1:20129/muse-ai/v1/images/1/content")
    assert tool._is_safe_remote_url("http://localhost:20129/content")

    monkeypatch.setenv("MUSE_GATEWAY_ALLOWED_REDIRECT_HOSTS", "cdn.muse.ai,assets.trusted.com")
    assert tool._is_safe_remote_url("https://cdn.muse.ai/images/123.png")
    assert not tool._is_safe_remote_url("http://cdn.muse.ai/images/123.png")  # non-HTTPS rejected


def test_mime_spoofing_html_svg_rejected(tmp_path: Path):
    """Reject HTML or SVG files masquerading as bitmap images."""
    tool = MuseGatewayImage()
    html_bytes = b"<html><head><title>502 Bad Gateway</title></head><body>Error</body></html>"
    err, meta = tool._verify_image_bytes(html_bytes)
    assert err is not None
    assert "HTML/SVG/text" in err

    svg_bytes = b"<svg xmlns='http://www.w3.org/2000/svg'><rect width='10' height='10'/></svg>"
    err, meta = tool._verify_image_bytes(svg_bytes)
    assert err is not None
    assert "HTML/SVG/text" in err


def test_corrupt_bytes_rejected():
    tool = MuseGatewayImage()
    corrupt_bytes = b"\x89PNG\r\n\x1a\n" + b"\xff" * 100  # Corrupt image header with sufficient bytes
    err, meta = tool._verify_image_bytes(corrupt_bytes)
    assert err is not None
    assert "verification failed" in err.lower()
