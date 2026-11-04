# Fresh-news quota backfill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore a three-video next-day social quota by refreshing only current, evidence-gated candidates from Gateway daily-news whenever the local NewsNow cache is stale.

**Architecture:** Extend the existing `DailyNewsGatewayClient` with a strict discovery refresh operation that validates Gateway-ranked candidates before atomically replacing `data/newsnow_feed.json`. Invoke it before strict generation, with the outstanding quota as the minimum candidate count. The strict publisher remains the only path that schedules projects; it fails closed and emits structured monitoring errors for unavailable or insufficient fresh news.

**Tech Stack:** Python 3, stdlib `urllib`/JSON/pathlib, Bash, pytest, Toolcase Gateway daily-news API.

**Spec:** `docs/superpowers/specs/2026-11-04-fresh-news-quota-backfill-design.md`

## Global Constraints

- Accept only Gateway discovery candidates with a canonical URL, non-empty ID/title, parseable publication timestamp, and age at or below `NEWS_MAX_SOURCE_AGE_HOURS`.
- Never use a stale local cache after Gateway refresh fails or returns too few eligible candidates.
- Preserve the fixed Agent Engineering niche, research/evidence gates, deduplication, and strict full-count scheduling gate.
- Leave the quota incomplete and heartbeat failed if fresh candidates cannot be acquired; never substitute evergreen or undated content.
- Use atomic cache replacement and preserve the previous cache on every refresh failure.
- Validate on an isolated server checkout before production activation; do not alter production cron without explicit authorization.

---

## File structure

- `tools/news/daily_news_gateway.py` — owns strict Gateway discovery, candidate validation, and atomic cache refresh.
- `tools/news/gateway_daily_news_feed.py` — exposes the refresh operation to pipeline callers without duplicating Gateway behavior.
- `scripts/run_strict_docker_publish.sh` — refreshes fresh-news input before generating the exact missing quota and reports typed preflight failures.
- `tests/tools/test_daily_news_gateway.py` — proves Gateway validation and cache safety using real client behavior with HTTP boundaries faked.
- `tests/test_strict_generation_singleflight.py` — proves strict generation invokes the refresh with the missing count and cannot proceed after refresh failure.
- `tests/test_strict_cron_retry.py` — proves a short next-day schedule retains the exact deficit contract and has no stale-cache completion shortcut.

### Task 1: Strict Gateway discovery refresh

**Files:**
- Modify: `tools/news/daily_news_gateway.py:DailyNewsGatewayClient`
- Modify: `tests/tools/test_daily_news_gateway.py`

**Interfaces:**
- Consumes: `DailyNewsGatewayClient.discover_candidates(base_url, limit, topics, sources)`.
- Produces: `DailyNewsGatewayClient.refresh_feed(output: Path | str, minimum: int, max_age_hours: float, base_url: str | None = None, topics: list[str] | None = None, sources: Sequence[str] | None = None) -> dict[str, Any]`.
- Returns: `{ "count": int, "tier": str, "output": str }` only after the atomically written cache contains at least `minimum` fresh candidates; otherwise raises `RuntimeError` without touching the current cache.

- [ ] **Step 1: Write the failing tests**

```python
def test_refresh_feed_writes_only_fresh_ranked_candidates(monkeypatch, tmp_path):
    client = DailyNewsGatewayClient("http://127.0.0.1:20129/custom/daily-news")
    monkeypatch.setattr(client, "discover_candidates", lambda **_: {
        "status": "ELIGIBLE", "tier": "tier_2_automated", "candidates": [{
            "candidate_id": "fresh-1", "canonical_url": "https://example.com/fresh",
            "title": "Fresh agent release", "published_at": "2026-11-04T05:00:00Z",
        }],
    })
    result = client.refresh_feed(tmp_path / "newsnow_feed.json", minimum=1,
                                 max_age_hours=24, reference_time=datetime(2026, 11, 4, 6, tzinfo=timezone.utc))
    assert result["count"] == 1
    assert json.loads((tmp_path / "newsnow_feed.json").read_text())[0]["id"] == "fresh-1"

def test_refresh_feed_rejects_stale_response_without_replacing_cache(monkeypatch, tmp_path):
    cache = tmp_path / "newsnow_feed.json"
    cache.write_text('[{"id":"previous"}]')
    client = DailyNewsGatewayClient()
    monkeypatch.setattr(client, "discover_candidates", lambda **_: {"status": "ELIGIBLE", "candidates": [{
        "candidate_id": "stale-1", "canonical_url": "https://example.com/stale",
        "title": "Old", "published_at": "2026-10-30T00:00:00Z",
    }]})
    with pytest.raises(RuntimeError, match="fresh"):
        client.refresh_feed(cache, minimum=1, max_age_hours=24,
                            reference_time=datetime(2026, 11, 4, tzinfo=timezone.utc))
    assert json.loads(cache.read_text()) == [{"id": "previous"}]
```

- [ ] **Step 2: Run the focused tests to verify they fail**

Run: `pytest tests/tools/test_daily_news_gateway.py -k 'refresh_feed' -v`

Expected: FAIL because `refresh_feed` does not exist.

- [ ] **Step 3: Implement the minimal refresh operation**

```python
def refresh_feed(self, output, minimum, max_age_hours, *, base_url=None,
                 topics=None, sources=None, reference_time=None):
    response = self.discover_candidates(base_url=base_url, limit=minimum,
                                        topics=topics, sources=list(sources or ()))
    items = _validated_fresh_candidates(response, max_age_hours, reference_time)
    if len(items) < minimum:
        raise RuntimeError(f"Gateway returned {len(items)} fresh candidates; need {minimum}")
    _atomic_write_json(_resolve_safe_output_path(output), items)
    return {"count": len(items), "tier": str(response.get("tier", "")), "output": str(output)}
```

Use timezone-aware ISO-8601 parsing; reject missing/future/unparseable timestamps and normalize `candidate_id`/`canonical_url` to the existing feed fields without inventing source facts.

- [ ] **Step 4: Run the focused tests to verify they pass**

Run: `pytest tests/tools/test_daily_news_gateway.py -k 'refresh_feed' -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/news/daily_news_gateway.py tests/tools/test_daily_news_gateway.py
git commit -m "feat(news): refresh fresh gateway candidates atomically"
```

### Task 2: Expose refresh through the feed compatibility layer

**Files:**
- Modify: `tools/news/gateway_daily_news_feed.py`
- Modify: `tests/tools/test_daily_news_gateway.py`

**Interfaces:**
- Consumes: `DailyNewsGatewayClient.refresh_feed(...)` from Task 1.
- Produces: `refresh_feed(base_url: str | None, output: Path | str, minimum: int, max_age_hours: float, topics: list[str] | None = None, sources: Sequence[str] | None = None) -> dict[str, Any]`.

- [ ] **Step 1: Write the failing façade test**

```python
def test_compatibility_refresh_delegates_exact_quota_and_freshness(monkeypatch, tmp_path):
    captured = {}
    monkeypatch.setattr(gateway_daily_news_feed.DailyNewsGatewayClient, "refresh_feed",
                        lambda self, **kwargs: captured.update(kwargs) or {"count": 2})
    result = gateway_daily_news_feed.refresh_feed(
        "http://127.0.0.1:20129/custom/daily-news", tmp_path / "feed.json",
        minimum=2, max_age_hours=24, topics=["agent_tool_use"])
    assert result == {"count": 2}
    assert captured["minimum"] == 2
    assert captured["max_age_hours"] == 24
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/tools/test_daily_news_gateway.py::test_compatibility_refresh_delegates_exact_quota_and_freshness -v`

Expected: FAIL because module-level `refresh_feed` is absent.

- [ ] **Step 3: Implement the thin façade**

```python
def refresh_feed(base_url, output, minimum, max_age_hours, topics=None, sources=None):
    return DailyNewsGatewayClient(base_url=base_url).refresh_feed(
        output=output, minimum=minimum, max_age_hours=max_age_hours,
        base_url=base_url, topics=topics, sources=sources,
    )
```

- [ ] **Step 4: Run the focused tests to verify they pass**

Run: `pytest tests/tools/test_daily_news_gateway.py -k 'refresh_feed or compatibility_refresh' -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/news/gateway_daily_news_feed.py tests/tools/test_daily_news_gateway.py
git commit -m "feat(news): expose strict gateway feed refresh"
```

### Task 3: Refresh before strict quota generation and monitor the outcome

**Files:**
- Modify: `scripts/run_strict_docker_publish.sh:newsnow_preflight`
- Modify: `tests/test_strict_generation_singleflight.py`

**Interfaces:**
- Consumes: module-level `gateway_daily_news_feed.refresh_feed`, `EXPECTED_SUCCESS_COUNT`, and valid `NEWS_MAX_SOURCE_AGE_HOURS`.
- Produces: a fresh `data/newsnow_feed.json` before `run_daily_news_pipeline.sh`; `pipeline_monitoring.py log-error` events with error types `GATEWAY_UNAVAILABLE` or `NO_ELIGIBLE_FRESH_NEWS`; non-zero strict-pipeline exit on refresh failure.

- [ ] **Step 1: Write the failing strict-pipeline tests**

```python
def test_strict_pipeline_refreshes_gateway_feed_for_exact_missing_quota(script_env, tmp_path):
    result = run_strict(script_env, expected_success_count=2,
                        gateway_discovery_candidates=two_fresh_candidates())
    assert result.returncode == 0
    assert read_refresh_invocation(tmp_path)["minimum"] == 2

def test_strict_pipeline_does_not_generate_from_stale_cache_when_gateway_refresh_fails(script_env, tmp_path):
    result = run_strict(script_env, expected_success_count=2,
                        gateway_error="connection refused", existing_feed_age_hours=72)
    assert result.returncode != 0
    assert "GATEWAY_UNAVAILABLE" in read_monitor_events(tmp_path)
    assert not generation_was_started(tmp_path)
```

- [ ] **Step 2: Run the targeted tests to verify they fail**

Run: `pytest tests/test_strict_generation_singleflight.py -k 'refreshes_gateway or stale_cache' -v`

Expected: FAIL because the strict pipeline does not currently force a Gateway refresh.

- [ ] **Step 3: Implement the pre-generation refresh**

In `run_strict_docker_publish.sh`, after freshness configuration validates and before Stage 3 generation:

```bash
if ! "$PY" -m tools.news.gateway_daily_news_feed refresh \
    --gateway-url "$DAILY_NEWS_GATEWAY_URL" --output "$ROOT/data/newsnow_feed.json" \
    --minimum "$TARGET_SUCCESS_COUNT" --max-age-hours "$NEWS_MAX_SOURCE_AGE_HOURS"; then
  "$PY" "$ROOT/scripts/pipeline_monitoring.py" log-error --stage preflight \
    --error-type GATEWAY_UNAVAILABLE --message "fresh Gateway discovery failed; stale cache rejected" || true
  fail "fresh Gateway discovery failed; refusing stale cache"
fi
```

Implement the corresponding argparse `refresh` command in the compatibility layer rather than embedding Python/heredoc logic in Bash. Select only the locked-niche topic families from `config/niches/us-ai-agent-engineering.locked.yaml`.

- [ ] **Step 4: Run the targeted tests to verify they pass**

Run: `pytest tests/test_strict_generation_singleflight.py -k 'refreshes_gateway or stale_cache' -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/run_strict_docker_publish.sh tools/news/gateway_daily_news_feed.py tests/test_strict_generation_singleflight.py
git commit -m "fix(cron): require fresh gateway news before quota generation"
```

### Task 4: Verify retry semantics and remote isolated execution

**Files:**
- Modify: `tests/test_strict_cron_retry.py`
- Modify: `deploy/openmontage.cron` only if a new explicit Gateway refresh environment variable is required.

**Interfaces:**
- Consumes: `retry_daily_pipeline.sh` exact deficit calculation and strict-pipeline fresh refresh from Task 3.
- Produces: evidence that a `1/3` schedule passes `EXPECTED_SUCCESS_COUNT=2`, does not report success until all two projects validate, and retains an alert on fresh-news failure.

- [ ] **Step 1: Write the failing retry regression test**

```python
def test_retry_with_one_of_three_scheduled_requires_two_fresh_gateway_projects(tmp_path):
    result = run_retry(schedule_with_projects("2026-11-05", 1), expected_success_count=3,
                       strict_runner_records_env=True)
    assert result.returncode == 0
    assert strict_runner_environment(tmp_path)["EXPECTED_SUCCESS_COUNT"] == "2"
    assert "1/3 projects scheduled" in result.stdout
```

- [ ] **Step 2: Run the regression test to verify it fails if the behavior is absent**

Run: `pytest tests/test_strict_cron_retry.py::test_retry_with_one_of_three_scheduled_requires_two_fresh_gateway_projects -v`

Expected: PASS if the existing exact-deficit contract already holds; otherwise FAIL, then adjust only the retry hand-off that violates it.

- [ ] **Step 3: Make the minimal retry/configuration change, if required**

Keep the existing behavior:

```bash
MISSING_COUNT=$((EXPECTED_SUCCESS_COUNT - SCHEDULED_COUNT))
export EXPECTED_SUCCESS_COUNT="$MISSING_COUNT"
exec "$ROOT/scripts/run_strict_docker_publish.sh"
```

Do not add a success path for stale cached candidates. If a deployment variable is needed, add it explicitly to `deploy/openmontage.cron` beside `EXPECTED_SUCCESS_COUNT=3`.

- [ ] **Step 4: Run the complete local contract suite**

Run: `pytest tests/tools/test_daily_news_gateway.py tests/test_strict_generation_singleflight.py tests/test_strict_cron_retry.py tests/test_strict_schedule_only.py -v`

Expected: PASS with no collection or assertion failures.

- [ ] **Step 5: Commit and remote-validate the exact revision**

```bash
git add tests/test_strict_cron_retry.py deploy/openmontage.cron
git commit -m "test(cron): cover fresh-news quota backfill"
git rev-parse HEAD
```

Synchronize this commit to `/home/ubuntu/OpenMontage-quota-test` on `sandbox-video`, run the same focused pytest suite there, inspect the scheduled container crontab and a dry-run/preflight against the Gateway, then report results. Do not fast-forward `/home/ubuntu/OpenMontage` or activate production cron without a separate explicit authorization.

## Self-review

- Spec coverage: Tasks 1–2 implement authoritative Gateway discovery and atomic fresh cache; Task 3 integrates strict generation and typed monitoring; Task 4 proves the `1/3 → 3/3` deficit path and isolates remote validation.
- Placeholder scan: no unresolved implementation markers or deferred-work language.
- Type consistency: `refresh_feed` uses `output`, `minimum`, `max_age_hours`, `base_url`, `topics`, and `sources` identically across its client, façade, and strict-pipeline callers.
