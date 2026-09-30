#!/usr/bin/env python3
"""Create or verify a YouTube upload token without uploading a video."""
import argparse
import getpass
import hmac
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPE = "https://www.googleapis.com/auth/youtube.upload"
TOKEN_PATH = Path.home() / ".openmontage" / "youtube_token.json"
STATE_PATH = Path.home() / ".openmontage" / "youtube_oauth_state.json"
REDIRECT_URI = "http://localhost:8080/"


def client_path():
    value = os.environ.get("YOUTUBE_CLIENT_SECRET_FILE")
    if not value or not Path(value).expanduser().is_file():
        raise SystemExit("YOUTUBE_CLIENT_SECRET_FILE is missing or invalid")
    return Path(value).expanduser()


def private_write(path, content):
    """Replace atomically, with private permissions from creation onward."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".")
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(content)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def callback_code(callback, state):
    parsed = urlparse(callback)
    expected = urlparse(REDIRECT_URI)
    if (parsed.scheme, parsed.netloc, parsed.path) != (
        expected.scheme, expected.netloc, expected.path
    ):
        raise ValueError("Paste the full localhost callback URL, not just the code")
    query = parse_qs(parsed.query)
    received = query.get("state", [])
    if len(received) != 1 or not hmac.compare_digest(received[0], state):
        raise ValueError("OAuth state mismatch; use the latest login link")
    if "error" in query:
        raise ValueError("Google did not approve access; restart with --reauth")
    codes = query.get("code", [])
    if len(codes) != 1:
        raise ValueError("Callback must contain exactly one authorization code")
    return codes[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--code", help="Full callback URL (prefer --callback to avoid shell history)")
    mode.add_argument("--callback", action="store_true", help="Prompt for a hidden callback URL")
    mode.add_argument("--reauth", action="store_true", help="New consent link; retain the existing token")
    mode.add_argument("--verify", action="store_true", help="Refresh with Google; never upload a video")
    parser.add_argument("--token-path", type=Path, default=TOKEN_PATH)
    parser.add_argument("--state-path", type=Path, default=STATE_PATH)
    args = parser.parse_args()
    token_path = args.token_path.expanduser()
    state_path = args.state_path.expanduser()

    try:
        if args.verify:
            creds = Credentials.from_authorized_user_info(json.loads(token_path.read_text()))
            if not creds.refresh_token:
                raise ValueError("No refresh token; restart with --reauth")
            creds.refresh(Request())
            if not creds.has_scopes([SCOPE]):
                raise ValueError("Upload scope missing; restart with --reauth")
            private_write(token_path, creds.to_json())
            print(f"VERIFIED token={token_path} refresh=ok upload_scope=ok (no upload performed)")
            return 0

        if args.code or args.callback:
            if not state_path.is_file():
                raise ValueError("OAuth state missing; run --reauth first")
            state = json.loads(state_path.read_text())
            callback = getpass.getpass("Paste full callback URL (hidden): ") if args.callback else args.code
            code = callback_code(callback.strip(), state["state"])
            flow = InstalledAppFlow.from_client_secrets_file(
                str(client_path()), [SCOPE], state=state["state"]
            )
            flow.redirect_uri = REDIRECT_URI
            flow.code_verifier = state["code_verifier"]
            flow.fetch_token(code=code)
            if not flow.credentials.refresh_token:
                raise ValueError("Google returned no refresh token; restart with --reauth")
            if token_path.is_file():
                stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
                private_write(token_path.with_name(token_path.name + ".bak." + stamp), token_path.read_text())
            private_write(token_path, flow.credentials.to_json())
            state_path.unlink(missing_ok=True)
            print(f"READY token={token_path}")
            return 0

        if not args.reauth and token_path.is_file():
            try:
                token = json.loads(token_path.read_text())
            except (OSError, json.JSONDecodeError):
                token = {}
            if token.get("refresh_token"):
                print(f"READY token={token_path} (cached; use --verify to test with Google)")
                return 0
        if not args.reauth and state_path.is_file():
            pending = json.loads(state_path.read_text())
            if pending.get("authorization_url"):
                print("LOGIN_REQUIRED")
                print(f"REDIRECT_URI={REDIRECT_URI}")
                print(pending["authorization_url"])
                return 2

        flow = InstalledAppFlow.from_client_secrets_file(str(client_path()), [SCOPE])
        flow.redirect_uri = REDIRECT_URI
        url, state = flow.authorization_url(access_type="offline", prompt="consent")
        private_write(state_path, json.dumps({
            "state": state, "code_verifier": flow.code_verifier, "authorization_url": url
        }))
        print("LOGIN_REQUIRED")
        print(f"REDIRECT_URI={REDIRECT_URI}")
        print(url)
        return 2
    except (EOFError, KeyboardInterrupt):
        print("Authorization cancelled; existing token retained")
        return 1
    except Exception as exc:
        # Provider exceptions may contain codes or tokens: never print their payloads.
        print(f"AUTH_FAILED ({type(exc).__name__}). Check paths, callback/state, consent and network; retry --reauth if needed.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
