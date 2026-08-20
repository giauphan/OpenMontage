#!/usr/bin/env python3
import json
import os
from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow
SCOPE = "https://www.googleapis.com/auth/youtube.upload"
TOKEN_PATH = Path.home() / ".openmontage" / "youtube_token.json"
REDIRECT_URI = "http://localhost:8080/"
def main():
    client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET_FILE")
    if not client_secret:
        print("YOUTUBE_CLIENT_SECRET_FILE is not configured")
        return 1
    secret_path = Path(client_secret)
    if not secret_path.is_file():
        print(f"YOUTUBE_CLIENT_SECRET_FILE does not exist: {secret_path}")
        return 1
    if TOKEN_PATH.is_file():
        try:
            token = json.loads(TOKEN_PATH.read_text())
        except (OSError, json.JSONDecodeError):
            token = {}
        if token.get("refresh_token"):
            print(f"READY token={TOKEN_PATH}")
            return 0
    flow = InstalledAppFlow.from_client_secrets_file(str(secret_path), [SCOPE])
    flow.redirect_uri = REDIRECT_URI
    authorization_url, _ = flow.authorization_url(access_type="offline", include_granted_scopes="true", prompt="consent")
    print("LOGIN_REQUIRED")
    print(f"REDIRECT_URI={REDIRECT_URI}")
    print(authorization_url)
    return 2
if __name__ == "__main__":
    raise SystemExit(main())
