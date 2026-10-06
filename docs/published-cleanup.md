# Independent published-project cleanup

The hourly `:35 UTC` cron entry runs `scripts.cleanup_published_projects --apply`,
independently of daily generation. Previously, failures before stage 7 prevented
stale cleanup; the stale script also skipped active entries and checked eligibility
before reconciliation. Its deactivation call supplied no store, so even that
boundary could not reconcile scheduled records.

The new sweep inventories only immediate `cand_*` directories in `projects/`,
`projects_news/`, and `projects/instagram/`, including active queued candidates.
It resolves a single ISO release date from queue entries and/or publish metadata.
Conflicting, missing, malformed dates or unsafe paths are retained. PublishStore
supports keyed lookup, not enumeration: store-only dates are intentionally not
inferred. No dates are guessed from age, names, or the current day.

Apply passes an explicit store/date to the existing `deactivate_project` contract:
remote scheduled-publication reconciliation, all required routes verified,
matching media hashes, path/identity/duplicate checks, schedule lock, durable audit
before deletion, and queue removal afterward. No publishing is invoked. The cron
uses a separate nonblocking flock to prevent overlapping sweeps; canonical locking
still coordinates with publishers. Store construction failure blocks the sweep.
Retention is normal; `RETAINED` and the existing contract explain safety blocks.
Exceptions produce a nonzero sweep result. A false deactivation result can also
represent audit/deletion failure; inspect its preceding error in `cron_cleanup.log`.

## Inspection and deployment

From the checkout, `python3 -m scripts.cleanup_published_projects --dry-run`
(default mode) only reads existing evidence; it does not reconcile or delete.
Apply can perform remote status checks and update publication evidence, then delete
only eligible media. Runtime credentials are required, as for existing publishing.
Missing remote verification always retains media; dry-run eligibility can therefore
differ from a later apply after authoritative reconciliation.

This patch is task-branch-only. Do not switch the bind-mounted live checkout to the
task branch. After separate review/merge approval, update the deployment branch via
its normal fast-forward pull. Then install the revised crontab without restarting
an in-flight pipeline:

```sh
ssh -F /home/ubuntu/.ssh/ssh-sandbox-video -i /home/ubuntu/.ssh/tunnel_key sandbox-video docker exec openmontage_scheduler crontab /app/deploy/openmontage.cron
```

The container loads this same crontab on startup, so restarting the scheduler is
an alternative. Installing it enables actual hourly deletion; neither deployment
nor a live cleanup is part of isolated regression testing.

## Remaining retention work (not authorized by this sweep)

Failed/unpublished projects, recovery directories, and trash are never deleted by
age. A separate retention proposal should inventory size and ownership read-only,
define explicit operator-approved TTL/quarantine policy, protect active/retry and
in-flight work, specify recovery/export windows and durable deletion audits, and
prove behavior with isolated fixtures before enabling any deletion. Candidates
with store-only or ambiguous dates need an explicit identity/date recovery design,
not a broad historical scan or relaxed publication guards.
