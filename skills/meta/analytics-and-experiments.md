# Proposed Skill: US/CA Audience Analytics & Content Experiment Design

**Invoke:** after real uploads are authorized and observable; prior to release, generate only experiment design.  
**Inputs:** own YouTube Analytics exports, format/topic/creative labels, actual costs and authoring time, experiment dates.  
**Outputs:** hypothesis ledger, descriptive metrics (with denominators), experiment recommendation and uncertainties.

## Data to collect
- Format (Short vs long-form); title/hook variant, thumbnail, runtime, story type; claim/visual QA result, production cost and time.
- YouTube top geographies by watch time (US, Canada, Vietnam, other), geography data suppression, impression sources, Shorts shown in feed + viewed/swiped, avg view duration, retention graph (opening, middle, payoff), subscribers, returning viewers.
- RPM/revenue ONLY when available from monetized channel, never substitute online average CPM as channel-specific projected revenue.
- Timezone-aware scheduled and actual release times, and whether a slot was changed mid-pilot.

## Fair experiments
1. Predefine hypothesis: "Demonstration-first hooks retain viewers better than vague product announcements"; describe objective measure and format.
2. Do not mix a Short's viewed/swiped with a long-form video's CTR. Avoid interpreting tiny differences with very small samples.
3. Compare analogous video age/format/topic and acquisition source. Mark confounding news topic trend and external sharing.
4. Choose 2–3 meaningful angles per week, not high-volume template spam. Track whether edits improved retention, not only initial views.
5. Hypothesis "US-first content succeeds" requires real US/CA audience share and satisfaction signals over multiple eligible releases. Phoenix server location is not independent evidence.
6. Every decision indicates `observed / weak evidence / needs more samples` and alternative explanations.

## Example weekly review
```yaml
week: 1
samples:
  shorts: 4
  longform: 1
geography:
  us_watch_time_share: null
  ca_watch_time_share: null
  note: "YouTube may limit geographic reporting for small samples"
format_learnings: []
production_failures: []
cost_per_approved_video: null
next_actions:
  - "Check first 3s value evidence; do not infer ranking boost from upload IP"
confidence: LOW
```

Never assert a channel is viable or US traction proven from one lucky Short. No automated deletion/reuploading of underperformers.
