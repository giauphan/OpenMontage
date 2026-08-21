#!/usr/bin/env python3
import argparse
import json
import os
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from google_auth_oauthlib.flow import InstalledAppFlow
SCOPE = "https://www.googleapis.com/auth/youtube.upload"
TOKEN_PATH = Path.home() / ".openmontage" / "youtube_token.json"
STATE_PATH = Path.home() / ".openmontage" / "youtube_oauth_state.json"
REDIRECT_URI = "http://localhost:8080/"
def client_path():
    value = os.environ.get("YOUTUBE_CLIENT_SECRET_FILE")
    if not value or not Path(value).is_file():
        raise SystemExit("YOUTUBE_CLIENT_SECRET_FILE is missing or invalid")
    return Path(value)
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--code", help="OAuth code or redirected callback URL")
    args = parser.parse_args()
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    if args.code:
        if not STATE_PATH.is_file():
            raise SystemExit("OAuth state missing; run without --code first")
        state = json.loads(STATE_PATH.read_text())
        flow = InstalledAppFlow.from_client_secrets_file(str(client_path()), [SCOPE], state=state["state"])
        flow.redirect_uri = REDIRECT_URI
        flow.code_verifier = state["code_verifier"]
        code = parse_qs(urlparse(args.code).query).get("code", [args.code])[0]
        flow.fetch_token(code=code)
        TOKEN_PATH.write_text(flow.credentials.to_json())
        TOKEN_PATH.chmod(0o600)
        STATE_PATH.unlink(missing_ok=True)
        print(f"READY token={TOKEN_PATH}")
        return 0
    if TOKEN_PATH.is_file():
        try:
            token = json.loads(TOKEN_PATH.read_text())
        except (OSError, json.JSONDecodeError):
            token = {}
        if token.get("refresh_token"):
            print(f"READY token={TOKEN_PATH}")
            return 0
    flow = InstalledAppFlow.from_client_secrets_file(str(client_path()), [SCOPE])
    flow.redirect_uri = REDIRECT_URI
    authorization_url, state = flow.authorization_url(access_type="offline")
    STATE_PATH.write_text(json.dumps({"state": state, "code_verifier": flow.code_verifier}))
    STATE_PATH.chmod(0o600)
    print("LOGIN_REQUIRED")
    print(f"REDIRECT_URI={REDIRECT_URI}")
    print(authorization_url)
    return 2
if __name__ == "__main__":
    raise SystemExit(main())
