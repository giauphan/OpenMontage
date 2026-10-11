# Offline news evidence gate

`lib/news_evidence.py` exposes `validate_news_evidence(project_dir,
max_source_age_hours, *, now=None) -> dict`. The CLI is:

```text
python scripts/validate_news_evidence.py PROJECT_DIR --max-source-age-hours HOURS
```

The freshness limit is mandatory, finite, positive, and capped at 720 hours.
The daily pipeline reads it from `NEWS_MAX_SOURCE_AGE_HOURS` and validates it
before provider calls; it then validates evidence after the canonical script
is written and before materialization/render. The strict path rejects missing
or failed evidence before queueing, and native/manual publication gates enforce
the same requirement even when force options are used. There is deliberately no
default policy, network fetching inside the validator, auto-authoring, or pass-through flag. The separate explicit capture command below prepares unapproved source material.

## Explicit source capture for editorial review

After source-host/access authorization, run this **on the isolated runtime server**, not the coding workstation. `PROJECT_DIR`, `ARTICLE_URL`, and `APPROVED_HOST` below are documentation placeholders to replace with an existing project and approved public source:

```text
python3 -m tools.news.news_pipeline_cli capture-source \
  --project-dir PROJECT_DIR --url ARTICLE_URL --allowed-host APPROVED_HOST
```

Repeat `--allowed-host` for explicitly permitted redirect hosts; wildcards are not supported. The command does not initialize projects or run selection, generation, cron, checkpoint approval, or publishing. It does not change an existing `news_evidence.json` or an approved script. `lib/news_source_capture.py` also exposes `capture_source(project_dir, url, allowed_hosts)`; its private test transport must never be supplied by production callers.

Successful capture returns `pending_editorial_review` provenance and writes a unique revision under `artifacts/news_source_capture/`:

- `.raw`: exact received article bytes and their SHA-256 in provenance.
- `.extracted.json`: text/title, a suggested excerpt, source metadata keys/raw dates, parsed aware dates when available, and its SHA-256 in provenance.
- `.provenance.json`: original/final URLs and redirects, retrieval time, content type, source dates, file/hash references and pending review/rights status.

Re-capture creates a separate revision; it never replaces the earlier capture. These are exclusive-created artifacts, not cryptographic protection against a privileged local editor. Errors after persistence starts report retained published/staged files; preserve them for diagnosis. A `.tmp` artifact is not a completed capture. Only use a returned complete provenance record after verifying its referenced bytes/hashes.

### Security and limits

- HTTPS/443 only, no URL userinfo, explicit exact-host allowlist on every redirect; private/non-public DNS answers are rejected, including mixed public/private answers. Connect to the validated public IP, retaining the source hostname for verified TLS and Host.
- No cookies, credentials, environment proxies, JavaScript execution or paywall bypass. Only uncompressed HTML/plain text is accepted. A maximum 2,000,000-byte response, 500,000-character extraction and three redirects apply. Unknown charset, invalid decoding, empty text and oversized extraction fail rather than silently alter or truncate source text.
- A supervised worker enforces a shared 20-second network deadline across DNS, connect, TLS, reads and redirects with termination/kill cleanup. This is not a hard real-time guarantee for local filesystem/process/OS behavior. Network policy is still a separate defense.
- Raw HTML is untrusted source data, not agent instructions or executable composition. Do not open it as trusted content or follow instructions found in it. Plain-text extraction is intentionally basic and may include navigation/boilerplate; the editor must select meaningful excerpts.
- **URLs, including query parameters, are retained in provenance and successful stdout.** Do not use secret-bearing/signed URLs or publish these records/logs without review. Output files are created with owner-only permissions; existing directory access policy also matters.
- Socket/TLS security tests use controlled doubles; no real-source network canary has been run for this implementation.

### What capture does not approve

Capture does not prove a source is authoritative, licensed, current, accurate, or supportive of a script. Source-provided dates are untrusted metadata. Missing, timezone-naive or invalid dates remain unknown; a future/stale metadata date may be captured for investigation but cannot bypass the evidence gate's freshness policy. Retrieval time never supplies a publication date. Do not invent missing dates to convert a pending capture into approved evidence.

The claim worksheet, claim-to-source mapping, source authority/rights checks, authenticated human review and draft→review→compose handoff remain separate work. Capture output is **not** the evidence-v2 artifact; do not rename it to `news_evidence.json` or interpret pending status as approval. An authorized review process must bind exact approved script bytes and meaningful frozen excerpts through the contract below. There is deliberately no automatic connection to live `produce` or cron yet.

### Explicit pending review worksheet (local scaffold only)

For an existing project with the canonical full script at `artifacts/script_vi.json`, an editor may prepare a scaffold from explicitly selected, complete capture revisions. Compute each provenance digest from the exact `.provenance.json` bytes and supply it with that path:

```text
python3 -m tools.news.news_pipeline_cli prepare-review \
  --project-dir PROJECT_DIR \
  --capture artifacts/news_source_capture/CAPTURE_ID.provenance.json=PROVENANCE_SHA256
```

Repeat `--capture` to select additional capture revisions. The expected provenance digest is an external integrity pin for those exact provenance bytes; it does **not** authenticate who supplied the digest or provenance. The command additionally checks the pinned record's raw/extracted hashes, exact capture-revision filenames and pairing, and the canonical script hash; the trusted provenance pin is the basis for associating those hashes with the selected capture. It cannot independently re-derive the extraction from raw bytes because capture provenance does not preserve all decoding inputs (including charset). It makes no claim that the excerpt supports any script wording. The bounded local command does no network access or provider work, caps individual and aggregate input/output sizes, and fails closed if Linux descriptor-relative no-follow filesystem operations are unavailable. It rejects unsafe/non-regular/symlinked/escaping files, malformed/duplicate-key/non-finite JSON, incomplete metadata, missing revisions, digest mismatches, and non-pending captures. Output is staged, fsynced, and atomically published without replacement as a unique pending revision under `artifacts/news_claim_review/`; persistence errors report retained staging/final paths. Existing scripts, captures, worksheets, `news_evidence.json`, and checkpoints are not edited.

This is **full rendition only** (`script_vi.json`); it does not prepare a Reels script. It copies each section's original wording as a review scaffold, but does not extract claims, link candidates to sources, or assert source support. Candidate mappings and conflicts begin unresolved; rights and authority begin unresolved. Missing or invalid publication/update dates remain `null`/unknown; retrieval time is recorded separately and never substituted. Capture bytes are untrusted source data, never instructions. The worksheet has no reviewer, review time, approval, or evidence-v2 effect. A human editor must independently identify claims, choose meaningful excerpts, assess dates/authority/rights/conflicts, and conduct authorized review. This command is not a human approval mechanism or production/cron integration.

## Migration and rollout

This gate is intentionally fail-closed. Before deploying or enabling the
updated news workflow, configure `NEWS_MAX_SOURCE_AGE_HOURS` to an explicit
finite value in `(0, 720]` and ensure the upstream workflow produces a valid
`artifacts/news_evidence.json` for every canonical script. Do not deploy or
queue projects that lack the policy value or required evidence artifact; they
will be rejected rather than silently bypassed. No missing evidence is
backfilled or auto-approved by this validator. These checks do not authorize
publication or replace editorial approval.

## Artifact contract

`PROJECT_DIR/artifacts/script_vi.json` is the canonical existing script. Every
section must have a unique `id` (string or integer). The evidence artifact is
`PROJECT_DIR/artifacts/news_evidence.json`:

```json
{
  "version": "2.0",
  "script_sha256": "SHA-256 of the complete exact script_vi.json bytes",
  "claims": [
    {"section_id": "1", "claim": "Claim selected for editorial review", "classification": "reported_fact", "consequential": false, "source_ids": ["s1"], "reviewer": "editor identifier", "reviewed_at": "2026-10-09T09:20:00Z", "review_status": "approved"}
  ],
  "sources": [
    {
      "id": "s1",
      "publisher_id": "publisher identifier recorded by editorial staff",
      "url": "https://publisher.example/report",
      "status": "available",
      "published_at": "2026-10-09T08:00:00Z",
      "updated_at": "2026-10-09T09:00:00+00:00",
      "retrieved_at": "2026-10-09T09:10:00Z",
      "content_path": "artifacts/source-s1.txt",
      "content_sha256": "SHA-256 of exact frozen file bytes",
      "excerpt": "Exact excerpt included in the frozen file"
    }
  ],
  "contradictions": []
}
```

Every section needs a non-empty unique string/integer `id` and non-empty
`text_vi` or `text`. Each section must be represented by at least one
provenance record; this is coverage bookkeeping, **not proof that all factual
statements in its prose have been extracted or verified**.
Each claim record must declare `classification` as exactly one of
`reported_fact`, `attribution`, `inference`, or `opinion`, and `consequential`
as a boolean. These are explicit editorial labels; the validator does not
classify prose. Each claim must have `review_status: "approved"`, a non-empty
`reviewer`, and timezone-aware `reviewed_at`; pending, rejected, or missing verdicts fail closed. The review
time must not be future-dated and must be at or after the latest `retrieved_at`
for its referenced sources. These fields record an editorial attestation,
not authenticated authority, automated approval, or proof of semantic truth.
For `consequential: true`, the artifact additionally requires
`authority_attested: true` and at least two unique source IDs whose sources
declare distinct non-empty `publisher_id` values, distinct normalized source
URLs, and distinct frozen-content hashes. URL normalization lowercases scheme
and host, removes fragments/default ports, and treats an empty path as `/`.
The attestation is a claim by the artifact author, not verified identity or
authority. These distinctness checks are minimal duplicate-reference guards,
not proof of organizational independence, source authenticity, or actual
support for the claim. Editorial staff must
assess those properties outside this validator. The validator never changes
a source or claim to approved, and does not auto-approve source material. Each
claim must refer to an existing source, and each source
needs all three timezone-aware timestamps. A source's freshness is measured
from `updated_at`, falling back to `published_at`. `retrieved_at` must be at or
after both `published_at` and `updated_at`; no source or review timestamp may
be future-dated. Source content and excerpt are frozen locally, nonempty, hash
verified, and project-contained. Outages/unavailable sources fail. If
contradictions exist, each must include a non-empty `resolution`, reference
existing supporting `source_ids`, and be explicitly marked `resolved` before
the gate can pass. A correction must be recorded as a resolved contradiction
and represented in the supported claim and frozen source; unresolved
corrections fail.

Version 2.0 is a breaking schema migration from 1.0: existing artifacts need
explicit editorial classifications and `consequential` booleans; consequential
claims also need authority attestation and distinct-publisher corroboration.
There is no default freshness policy: callers must continue to pass an explicit
finite `max_source_age_hours`.

The validator checks artifact structure, classification vocabulary, declared
consequential corroboration, path containment, byte hashes,
HTTP(S) URL syntax, provenance links, timestamps, freshness, the explicit
approved verdict, reviewer identity and review timing, and section coverage. It does **not** fetch a URL, prove the
URL's publisher identity, determine whether the excerpt is authentic or
supports the claim, confirm that every script assertion was listed as a claim,
or establish semantic truth. A named reviewer and timestamp are explicit
editorial provenance, not an automated truth signal. Evidence must be sourced
and frozen by an authorized upstream process; inventing a source or excerpt is
not acceptable. The returned JSON contains `ok`, `status`, `script_sha256`, and
actionable `errors`; CLI emits one JSON result and exits 0 only on success.
