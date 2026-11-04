# Fresh-news quota backfill design

## Purpose

Keep the required three-video daily publication quota supplied with current,
evidence-backed Agent Engineering stories. A stale local `newsnow_feed.json`
must not make the scheduler repeatedly attempt generation with unusable input.

## Scope

The production pipeline will use the Toolcase Gateway `daily-news` module as
the authoritative source of ranked current candidates. It will retain the
existing evidence, niche, validation, and platform scheduling gates.

This change does not permit evergreen or undated material to fill a quota.
When no fresh, eligible candidates exist, the pipeline remains failed and
observable rather than publishing a partial or weak batch.

## Design

1. A small gateway refresh adapter will call `POST
   /custom/daily-news/api/v1/discover`, requesting enough candidates for the
   outstanding quota and the configured Agent Engineering taxonomy.
2. The adapter will validate the response shape, candidate identity, canonical
   URL, publication timestamp, and freshness before atomically replacing the
   locally cached feed. It will record discovery tier and diagnostics for the
   pipeline monitor.
3. `run_strict_docker_publish.sh` will refresh the cache before candidate
   production whenever the next-day quota is short. It will not use a stale
   cache after a failed refresh.
4. `retry_daily_pipeline.sh` remains the quota controller: it counts
   next-day schedule entries, calculates the exact deficit, and invokes the
   strict pipeline only for that deficit. A successful run can only reach the
   scheduler after the full requested number validates.
5. Monitoring will distinguish `gateway_unavailable`, `no_eligible_fresh_news`,
   and `generation_failed`, while retaining the current `RUN_FAILED` heartbeat
   alert for an incomplete quota.

## Failure behavior

- Gateway unavailable: do not accept the old cache merely because it exists;
  emit a structured preflight error and leave the daily quota incomplete.
- Gateway has fewer eligible items: emit a structured no-eligible-news error;
  do not schedule a partial result as a completed quota.
- Generation/validation fails: retain the queue and evidence, fail closed, and
  allow the next retry checkpoint to try a newly refreshed feed.

## Tests and verification

- Gateway-response tests cover valid refresh, bad response rejection, stale
  timestamp rejection, and atomic-cache preservation on failure.
- Strict-pipeline tests show a short `1/3` schedule refreshing candidates and
  reaching `3/3` only after all missing projects validate.
- Retry tests verify it passes the precise deficit and does not suppress a
  retry just because a stale cache is present.
- Remote validation uses an isolated server checkout synchronized to the exact
  Git revision. Production cron is activated only after those checks pass and
  the user authorizes activation.
