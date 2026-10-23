#!/usr/bin/env python3
"""YouTube OAuth2 Authentication Helper for OpenMontage.

Facilitates headless OAuth authentication for YouTube Data API v3:
  1. Generates the Google OAuth2 consent URL.
  2. Exchanges the authorization code (or redirected URL) for access/refresh tokens.
  3. Saves authorized credentials to ~/.openmontage/youtube_token.json.
  4. Inspects and displays the authenticated YouTube Channel ID and Title.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CLIENT_SECRET = ROOT / "client_secret_584301246057-c2egnopjerhf7t1cqg9om2h2i848a3r8.apps.googleusercontent.com.json"
DEFAULT_TOKEN_FILE = Path.home() / ".openmontage" / "youtube_token.json"
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def get_auth_url(client_secret_file: Path) -> tuple[InstalledAppFlow, str]:
    flow = InstalledAppFlow.from_client_secrets_file(str(client_secret_file), SCOPES)
    flow.redirect_uri = "http://localhost:8080/"
    auth_url, _ = flow.authorization_url(prompt="consent", access_type="offline")
    return flow, auth_url


def exchange_code(client_secret_file: Path, token_file: Path, code_or_url: str) -> dict:
    code = code_or_url.strip()
    if code.startswith("http"):
        parsed = urlsplit(code)
        query_params = parse_qs(parsed.query)
        code_candidates = query_params.get("code")
        if not code_candidates:
            raise ValueError(f"No 'code' query parameter found in URL: {code}")
        code = code_candidates[0]

    flow = InstalledAppFlow.from_client_secrets_file(str(client_secret_file), SCOPES)
    flow.redirect_uri = "http://localhost:8080/"
    flow.fetch_token(code=code)
    creds = flow.credentials

    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(creds.to_json(), encoding="utf-8")
    print(f"✅ Credentials successfully saved to {token_file}")

    # Inspect authenticated channel
    yt = build("youtube", "v3", credentials=creds)
    ch_resp = yt.channels().list(mine=True, part="id,snippet").execute()
    items = ch_resp.get("items", [])
    if items:
        cid = items[0].get("id")
        title = items[0].get("snippet", {}).get("title")
        print(f"\n📺 Authenticated Channel ID: {cid}")
        print(f"📺 Authenticated Channel Name: {title}\n")
        return {"channel_id": cid, "channel_title": title}
    else:
        print("⚠️ No channel found associated with this Google account.")
        return {}


def main():
    parser = argparse.ArgumentParser(description="YouTube OAuth2 Authenticator for OpenMontage")
    parser.add_argument("--secret-file", type=Path, default=DEFAULT_CLIENT_SECRET, help="Client secret JSON path")
    parser.add_argument("--token-file", type=Path, default=DEFAULT_TOKEN_FILE, help="Token output path")
    parser.add_argument("--code", type=str, help="Authorization code or redirected URL from browser")
    args = parser.parse_args()

    if args.code:
        try:
            exchange_code(args.secret_file, args.token_file, args.code)
        except Exception as exc:
            print(f"❌ Error exchanging code: {exc}", file=sys.stderr)
            sys.exit(1)
    else:
        flow, auth_url = get_auth_url(args.secret_file)
        print("\n=======================================================")
        print("  YOUTUBE OAUTH2 AUTHORIZATION")
        print("=======================================================\n")
        print("1. Open the following URL in your browser to sign in to your YouTube account:\n")
        print(f"   {auth_url}\n")
        print("2. After granting access, Google will redirect to http://localhost:8080/?code=...")
        print("3. Copy either the full redirected URL or the code parameter, and run:")
        print(f"   python3 scripts/auth_youtube.py --code \"<PASTE_URL_OR_CODE_HERE>\"\n")


if __name__ == "__main__":
    main()
