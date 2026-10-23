from __future__ import annotations

import hashlib
import json
import multiprocessing
import os
import socket
import ssl
import time
from pathlib import Path

import pytest

import lib.news_source_capture as capture
from lib.news_source_capture import CaptureError, CapturePersistenceError, capture_source

HOST = "news.example"
URL = "https://news.example/story"
HTML = b"<html><head><title> Example headline </title><meta property='article:published_time' content='2025-03-04T12:30:00Z'></head><body><p>Story text.</p><script>secret()</script></body></html>"


def transport_for(*responses):
    responses = iter(responses)

    def transport(url, host):
        assert host in {"news.example", "other.example"}
        return next(responses)

    return transport


def response(body=HTML, *, status=200, content_type="text/html; charset=utf-8", location=None, extra=None):
    headers = {"content-type": content_type, **(extra or {})}
    return status, headers, body, location


def test_capture_writes_immutable_separate_pending_artifacts(tmp_path):
    result = capture_source(tmp_path, URL, {HOST}, _transport=transport_for(response()))
    out = tmp_path / "artifacts/news_source_capture"
    raw = out / result["raw_file"]
    extracted = out / result["extracted_file"]
    provenance = out / result["provenance_file"]

    assert raw.read_bytes() == HTML
    assert result["raw_sha256"] == hashlib.sha256(HTML).hexdigest()
    assert result["extracted_sha256"] == hashlib.sha256(extracted.read_bytes()).hexdigest()
    assert result["status"] == "pending_editorial_review"
    assert result["review_status"] == "pending"
    assert result["published_at"] == "2025-03-04T12:30:00Z"
    data = json.loads(extracted.read_text())
    assert data["title"] == "Example headline"
    assert "Story text." in data["text"]
    assert "secret" not in data["text"]
    saved_record = json.loads(provenance.read_text())
    assert saved_record["redirect_chain"] == [URL]
    assert saved_record == result
    assert not (tmp_path / "artifacts/news_evidence.json").exists()

    correction = capture_source(tmp_path, URL, {HOST}, _transport=transport_for(response(b"<p>Corrected source.</p>")))
    assert correction["raw_file"] != result["raw_file"]
    assert (out / result["raw_file"]).read_bytes() == HTML
    assert (out / correction["raw_file"]).read_bytes() == b"<p>Corrected source.</p>"
    assert extracted.is_file() and provenance.is_file()


def test_unknown_invalid_and_update_dates_keep_source_provenance(tmp_path):
    html = (b"<html><head><meta name='date' content='not a date'>"
            b"<meta property='article:modified_time' content='2025-03-05T10:00:00Z'>"
            b"<meta name='last-modified' content='2099-01-01T00:00:00Z'></head>"
            b"<body>Body.</body></html>")
    result = capture_source(tmp_path, URL, {HOST}, _transport=transport_for(response(html)))
    assert result["published_at"] is None
    assert result["published_at_raw"] == "not a date"
    assert result["published_at_source_key"] == "date"
    assert result["updated_at"] == "2025-03-05T10:00:00Z"
    assert result["date_metadata_raw"]["article:modified_time"] == "2025-03-05T10:00:00Z"
    assert "last-modified" not in result["date_metadata_raw"]


def test_plain_text_keeps_literal_angle_brackets(tmp_path):
    literal = b"Use <tag> literally; 2 < 3.\n"
    result = capture_source(tmp_path, URL, {HOST}, _transport=transport_for(response(literal, content_type="text/plain; charset=utf-8")))
    extracted = json.loads((tmp_path / result["capture_dir"] / result["extracted_file"]).read_text())
    assert extracted["text"] == literal.decode("utf-8")
    assert result["published_at"] is None
    assert result["updated_at"] is None


@pytest.mark.parametrize("body,content_type", [
    (b"invalid utf8: \xff", "text/plain"),
    (b"valid bytes", "text/plain; charset=x-unknown-capture-charset"),
])
def test_decode_failure_rejects_capture_without_final_artifacts(tmp_path, body, content_type):
    with pytest.raises(CaptureError, match="cannot be decoded"):
        capture_source(tmp_path, URL, {HOST}, _transport=transport_for(response(body, content_type=content_type)))
    assert not (tmp_path / "artifacts/news_source_capture").exists()
    assert not (tmp_path / "artifacts/news_evidence.json").exists()


def test_extracted_text_over_limit_is_rejected_without_truncation(tmp_path):
    with pytest.raises(CaptureError, match="without truncation"):
        capture_source(tmp_path, URL, {HOST}, _transport=transport_for(response(b"x" * 500_001, content_type="text/plain")))
    assert not (tmp_path / "artifacts/news_source_capture").exists()


@pytest.mark.parametrize("url", [
    "http://news.example/story", "https://user:pw@news.example/story",
    "https://news.example:444/story", "https://127.0.0.1/story",
    "https://news.example.evil/story", "https://news.example/story#fragment",
])
def test_rejects_unsafe_or_noncanonical_source_urls(tmp_path, url):
    with pytest.raises(CaptureError):
        capture_source(tmp_path, url, {HOST}, _transport=transport_for(response()))


def test_explicit_host_allowlist_is_required_and_exact(tmp_path):
    with pytest.raises(CaptureError):
        capture_source(tmp_path, URL, [], _transport=transport_for(response()))
    with pytest.raises(CaptureError):
        capture_source(tmp_path, "https://sub.news.example/story", {HOST}, _transport=transport_for(response()))


def test_redirect_requires_each_target_host_to_be_allowlisted(tmp_path):
    transport = transport_for(response(status=302, location="https://other.example/story"), response())
    with pytest.raises(CaptureError, match="allowlisted"):
        capture_source(tmp_path, URL, {HOST}, _transport=transport)
    assert not (tmp_path / "artifacts/news_source_capture").exists()


def test_allowed_redirect_chain_is_recorded(tmp_path):
    transport = transport_for(response(status=302, location="https://other.example/story"), response())
    result = capture_source(tmp_path, URL, {HOST, "other.example"}, _transport=transport)
    assert result["final_url"] == "https://other.example/story"
    assert result["redirect_chain"] == [URL, "https://other.example/story"]


@pytest.mark.parametrize("kwargs", [
    {"content_type": "application/pdf"},
    {"extra": {"content-encoding": "gzip"}},
])
def test_rejects_unaccepted_representation_without_artifacts(tmp_path, kwargs):
    with pytest.raises(CaptureError):
        capture_source(tmp_path, URL, {HOST}, _transport=transport_for(response(**kwargs)))
    assert not (tmp_path / "artifacts/news_source_capture").exists()


def test_rejects_oversized_body_without_artifacts(tmp_path):
    with pytest.raises(CaptureError, match="size"):
        capture_source(tmp_path, URL, {HOST}, _transport=transport_for(response(b"x" * (2_000_000 + 1))))
    assert not (tmp_path / "artifacts/news_source_capture").exists()


def test_persistence_failure_preserves_prior_bytes_without_ready_provenance(tmp_path, monkeypatch):
    original = capture._publish_artifact
    writes = 0

    def fail_on_provenance(path, data):
        nonlocal writes
        writes += 1
        if writes == 3:
            raise OSError("simulated provenance write error")
        return original(path, data)

    monkeypatch.setattr(capture, "_publish_artifact", fail_on_provenance)
    with pytest.raises(CapturePersistenceError) as raised:
        capture_source(tmp_path, URL, {HOST}, _transport=transport_for(response()))
    assert len(raised.value.partial_artifacts) == 2
    assert "no ready provenance" in str(raised.value)
    out = tmp_path / "artifacts/news_source_capture"
    assert len(list(out.glob("*.raw"))) == 1
    assert len(list(out.glob("*.extracted.json"))) == 1
    assert not list(out.glob("*.provenance.json"))


def _addrinfo(address, family=socket.AF_INET):
    sockaddr = (address, 443) if family == socket.AF_INET else (address, 443, 0, 0)
    return (family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", sockaddr)


def _exercise_direct_transport(monkeypatch, answers):
    class FakeSocket:
        def __init__(self):
            self.sent = b""
            self.closed = False

        def sendall(self, payload):
            self.sent += payload

        def close(self):
            self.closed = True

    class FakeTLSContext:
        check_hostname = True
        verify_mode = ssl.CERT_REQUIRED

        def wrap_socket(self, sock, *, server_hostname):
            observed["sni"] = server_hostname
            observed["verification"] = (self.check_hostname, self.verify_mode)
            return sock

    class FakeResponse:
        status = 200

        def __init__(self, sock):
            observed["request"] = sock.sent

        def begin(self):
            pass

        def getheaders(self):
            return [("Content-Type", "text/plain"), ("Content-Length", "2")]

        def read(self, amount):
            return b"ok"

    observed = {}
    fake_socket = FakeSocket()
    monkeypatch.setattr(capture.socket, "getaddrinfo", lambda *args, **kwargs: answers)
    monkeypatch.setattr(capture.socket, "create_connection", lambda target, timeout: observed.setdefault("target", (target, timeout)) and fake_socket)
    monkeypatch.setattr(capture.ssl, "create_default_context", FakeTLSContext)
    monkeypatch.setattr(capture.http.client, "HTTPResponse", FakeResponse)
    return observed, fake_socket


def test_direct_transport_pins_public_ip_and_preserves_tls_sni(monkeypatch):
    observed, fake_socket = _exercise_direct_transport(monkeypatch, [_addrinfo("8.8.8.8")])
    result = capture._request_pinned(URL, HOST)
    assert observed["target"][0] == ("8.8.8.8", 443)
    assert observed["sni"] == HOST
    assert observed["verification"] == (True, ssl.CERT_REQUIRED)
    assert b"Host: news.example\r\n" in observed["request"]
    assert result[2] == b"ok"
    assert fake_socket.closed


@pytest.mark.parametrize("answers", [
    [_addrinfo("8.8.8.8"), _addrinfo("127.0.0.1")],
    [_addrinfo("::1", socket.AF_INET6)],
    [_addrinfo("fe80::1", socket.AF_INET6)],
])
def test_direct_transport_denies_nonpublic_or_mixed_dns_before_connect(monkeypatch, answers):
    calls = []
    monkeypatch.setattr(capture.socket, "getaddrinfo", lambda *args, **kwargs: answers)
    monkeypatch.setattr(capture.socket, "create_connection", lambda *args, **kwargs: calls.append(args))
    with pytest.raises(CaptureError, match="non-public"):
        capture._request_pinned(URL, HOST)
    assert calls == []


def test_direct_transport_rejects_certificate_verification_failure(monkeypatch):
    class FakeSocket:
        closed = False

        def close(self):
            self.closed = True

    class RejectingContext:
        check_hostname = True
        verify_mode = ssl.CERT_REQUIRED

        def wrap_socket(self, sock, *, server_hostname):
            raise ssl.SSLCertVerificationError("certificate hostname mismatch")

    fake_socket = FakeSocket()
    real_default_context = ssl.create_default_context
    observed = {}

    def default_context():
        context = real_default_context()
        observed["check_hostname"] = context.check_hostname
        observed["verify_mode"] = context.verify_mode
        return RejectingContext()

    monkeypatch.setattr(capture.socket, "getaddrinfo", lambda *args, **kwargs: [_addrinfo("8.8.8.8")])
    monkeypatch.setattr(capture.socket, "create_connection", lambda *args, **kwargs: fake_socket)
    monkeypatch.setattr(capture.ssl, "create_default_context", default_context)
    with pytest.raises(CaptureError, match="HTTPS source request failed"):
        capture._request_pinned(URL, HOST)
    assert fake_socket.closed
    assert observed == {"check_hostname": True, "verify_mode": ssl.CERT_REQUIRED}


def test_allowlisted_redirect_to_private_dns_is_denied_before_connect(tmp_path, monkeypatch):
    target_url = "https://127.0.0.1/private"
    answers = {HOST: [_addrinfo("8.8.8.8")], "127.0.0.1": [_addrinfo("127.0.0.1")]}
    connections = []
    fake_socket = type("FakeSocket", (), {"sendall": lambda self, payload: None, "close": lambda self: None})()

    class FakeTLSContext:
        def wrap_socket(self, sock, *, server_hostname):
            return sock

    class RedirectResponse:
        status = 302

        def __init__(self, sock):
            pass

        def begin(self):
            pass

        def getheaders(self):
            return [("Location", target_url)]

        def read(self, amount):
            return b""

    monkeypatch.setattr(capture.socket, "getaddrinfo", lambda host, *args, **kwargs: answers[host])
    monkeypatch.setattr(capture.socket, "create_connection", lambda target, timeout: connections.append(target) or fake_socket)
    monkeypatch.setattr(capture.ssl, "create_default_context", FakeTLSContext)
    monkeypatch.setattr(capture.http.client, "HTTPResponse", RedirectResponse)
    monkeypatch.setattr(capture, "_bounded_request", lambda url, host, deadline: capture._request_pinned(url, host))
    with pytest.raises(CaptureError, match="non-public"):
        capture_source(tmp_path, URL, {HOST, "127.0.0.1"})
    assert connections == [("8.8.8.8", 443)]
    assert not (tmp_path / "artifacts/news_source_capture").exists()


def _sleeping_worker(connection, marker_path):
    Path(marker_path).write_text(str(os.getpid()), encoding="ascii")
    time.sleep(30)


def test_spawned_worker_timeout_is_bounded_and_child_is_reaped(tmp_path):
    before = {child.pid for child in multiprocessing.active_children()}
    marker = tmp_path / "worker.pid"
    started = time.monotonic()
    with pytest.raises(CaptureError, match="wall-time limit"):
        capture._supervise_worker(_sleeping_worker, (str(marker),), started + 3.0)
    elapsed = time.monotonic() - started
    assert marker.is_file()
    worker_pid = int(marker.read_text(encoding="ascii"))
    assert worker_pid > 0
    assert elapsed < 5.0
    assert {child.pid for child in multiprocessing.active_children()} <= before


def test_staged_provenance_failure_reports_preserved_temp_and_publishes_no_record(tmp_path, monkeypatch):
    original_link = capture.os.link

    def fail_provenance_link(source, destination):
        if str(destination).endswith(".provenance.json"):
            raise OSError("simulated publication failure")
        return original_link(source, destination)

    monkeypatch.setattr(capture.os, "link", fail_provenance_link)
    with pytest.raises(CapturePersistenceError) as raised:
        capture_source(tmp_path, URL, {HOST}, _transport=transport_for(response()))
    out = tmp_path / "artifacts/news_source_capture"
    assert len(list(out.glob("*.raw"))) == 1
    assert len(list(out.glob("*.extracted.json"))) == 1
    assert not list(out.glob("*.provenance.json"))
    staged_name = raised.value.partial_artifacts[-1]
    assert staged_name.endswith(".tmp")
    assert (out / staged_name).is_file()


def test_direct_transport_pins_public_ipv6(monkeypatch):
    observed, _ = _exercise_direct_transport(monkeypatch, [_addrinfo("2001:4860:4860::8888", socket.AF_INET6)])
    capture._request_pinned(URL, HOST)
    assert observed["target"][0] == ("2001:4860:4860::8888", 443)
    assert observed["sni"] == HOST


def test_symlink_output_path_is_rejected(tmp_path):
    elsewhere = tmp_path.parent / f"{tmp_path.name}-outside"
    elsewhere.mkdir()
    (tmp_path / "artifacts").symlink_to(elsewhere, target_is_directory=True)
    with pytest.raises(CaptureError, match="symlink"):
        capture_source(tmp_path, URL, {HOST}, _transport=transport_for(response()))
    assert list(elsewhere.iterdir()) == []
