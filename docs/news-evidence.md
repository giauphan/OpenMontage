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
default policy, network fetcher, auto-authoring, or pass-through flag.

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
