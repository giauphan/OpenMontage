# YouTube upload authorization

An API key cannot upload videos. Use a Desktop OAuth client with YouTube Data API
v3 enabled and the `youtube.upload` scope. If the consent app is in Testing, add
the signing-in account as a test user. Testing refresh tokens generally expire
after seven days for this scope.

## One-time local login

Run these commands in the environment where the client JSON is available. Local
login is an explicit exception to the normal remote execution workflow. Install
`google-auth-oauthlib` in an isolated Python environment if necessary.

```sh
export YOUTUBE_CLIENT_SECRET_FILE="/absolute/path/to/client_secret.json"
python3 scripts/youtube_auth_status.py --reauth
```

Exit code 2 means login is required, not a script failure. Open the printed link
in your browser and approve access. This manual flow does not start a listener.
A connection-refused page at `http://localhost:8080/` is expected after approval.
Copy the full callback address and enter it privately:

```sh
python3 scripts/youtube_auth_status.py --callback
python3 scripts/youtube_auth_status.py --verify
```

Do not post the callback URL or credentials in chat. `--callback` hides input and
avoids placing the code in shell history. The callback's origin and OAuth state
are checked before exchange. Bare codes are no longer accepted by `--code`.
`--reauth` preserves the existing token until authorization succeeds; replacement
creates a timestamped private backup. Starting another login invalidates the
previous pending local state. `--token-path` and `--state-path` support isolated
local sessions. Keep the same options throughout a session.

The default token is `~/.openmontage/youtube_token.json`. A plain invocation
checks cached presence only; `--verify` actually refreshes with Google and checks
the recorded upload scope, without uploading a video. This does not establish
channel upload eligibility or available quota.

## Transfer to the server

For this deployment, `/home/ubuntu/.openmontage` is mounted into the worker at
`/root/.openmontage`. Back up the current server token first. Transfer the local
token to a private staging location using SCP, set mode 600, then atomically
replace the server token after verification. Never put tokens in Git or build
images. Protect backups as credentials too.

Verify inside the existing worker:

```sh
docker exec -w /app openmontage_worker python3 scripts/youtube_auth_status.py --verify
```

No container rebuild is needed when `/home/ubuntu/OpenMontage` is bind-mounted at
`/app`; use the updated checkout. No video is uploaded by any command above.

## Troubleshooting

- A 403 on consent needs the actual Google error; test-user, organization and
  app-policy restrictions are not fixed by switching Docker to local execution.
- A stalled `accounts.google.com` page is before the callback. Inspect failed
  requests or try a clean browser session. An `aria-hidden` console warning alone
  is not an OAuth failure.
- A failed exchange retains the working token and pending state. Codes are
  single-use and short-lived; request a new link if the code expires.
- `AUTH_FAILED` deliberately omits provider exception payloads, which may contain
  credentials. Check paths, network and consent settings without logging secrets.
