import importlib.util
import json
import stat
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

spec = importlib.util.spec_from_file_location(
    "youtube_auth_status", Path(__file__).resolve().parents[2] / "scripts/youtube_auth_status.py"
)
auth = importlib.util.module_from_spec(spec)
spec.loader.exec_module(auth)


@pytest.fixture
def setup(tmp_path, monkeypatch):
    token = tmp_path / "token.json"
    state = tmp_path / "state.json"
    def run(*args):
        monkeypatch.setattr(sys, "argv", ["auth", "--token-path", str(token), "--state-path", str(state), *args])
        return auth.main()
    return token, state, run


def test_callback_validates_state_and_origin():
    assert auth.callback_code("http://localhost:8080/?state=abc&code=123", "abc") == "123"
    for url in [
        "123", "http://localhost:8080/?state=wrong&code=123",
        "https://example.com/?state=abc&code=123",
        "http://localhost:8080/?state=abc&error=access_denied",
        "http://localhost:8080/?state=abc&code=1&code=2",
    ]:
        with pytest.raises(ValueError):
            auth.callback_code(url, "abc")


def test_private_write(tmp_path):
    path = tmp_path / "nested/token.json"
    auth.private_write(path, "first")
    auth.private_write(path, "second")
    assert path.read_text() == "second"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert list(path.parent.iterdir()) == [path]


def test_reauth_preserves_token(setup, monkeypatch):
    token, state, run = setup
    token.write_text('{"refresh_token":"existing"}')
    flow = Mock(code_verifier="verifier")
    flow.authorization_url.return_value = ("https://example.com/auth", "state")
    monkeypatch.setattr(auth, "client_path", lambda: Path("client.json"))
    monkeypatch.setattr(auth.InstalledAppFlow, "from_client_secrets_file", Mock(return_value=flow))
    assert run("--reauth") == 2
    assert json.loads(token.read_text())["refresh_token"] == "existing"
    assert json.loads(state.read_text())["code_verifier"] == "verifier"
    flow.authorization_url.assert_called_once_with(access_type="offline", prompt="consent")


def test_callback_backs_up_and_consumes_state(setup, monkeypatch):
    token, state, run = setup
    token.write_text("old token")
    state.write_text(json.dumps({"state": "abc", "code_verifier": "verifier"}))
    flow = Mock()
    flow.credentials.refresh_token = "new refresh"
    flow.credentials.to_json.return_value = '{"refresh_token":"new refresh"}'
    monkeypatch.setattr(auth, "client_path", lambda: Path("client.json"))
    monkeypatch.setattr(auth.InstalledAppFlow, "from_client_secrets_file", Mock(return_value=flow))
    monkeypatch.setattr(auth.getpass, "getpass", lambda _: "http://localhost:8080/?state=abc&code=123")
    assert run("--callback") == 0
    assert not state.exists()
    assert next(token.parent.glob("token.json.bak.*")).read_text() == "old token"
    flow.fetch_token.assert_called_once_with(code="123")


def test_bad_callback_keeps_token_and_state(setup):
    token, state, run = setup
    token.write_text("old token")
    state.write_text(json.dumps({"state": "abc", "code_verifier": "verifier"}))
    assert run("--code", "http://localhost:8080/?state=wrong&code=123") == 1
    assert token.read_text() == "old token"
    assert state.exists()


def test_verify_refreshes_without_client_file(setup, monkeypatch):
    token, state, run = setup
    token.write_text('{"refresh_token":"existing"}')
    creds = Mock()
    creds.to_json.return_value = '{"refresh_token":"existing","token":"fresh"}'
    monkeypatch.setattr(auth.Credentials, "from_authorized_user_info", Mock(return_value=creds))
    assert run("--verify") == 0
    creds.refresh.assert_called_once()
    assert json.loads(token.read_text())["token"] == "fresh"


def test_verify_failure_does_not_leak_or_replace(setup, monkeypatch, capsys):
    token, state, run = setup
    original = '{"refresh_token":"existing"}'
    token.write_text(original)
    creds = Mock()
    creds.refresh.side_effect = RuntimeError("secret-token-payload")
    monkeypatch.setattr(auth.Credentials, "from_authorized_user_info", Mock(return_value=creds))
    assert run("--verify") == 1
    assert token.read_text() == original
    assert "secret-token-payload" not in capsys.readouterr().out
