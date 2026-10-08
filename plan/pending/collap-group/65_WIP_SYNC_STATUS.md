# WIP preservation and source synchronization

Status: INCOMPLETE, NOT RELEASE-READY. This snapshot preserves current local implementation, tests, partial director docs, local-coding rules, task prompts, model-route blocker and daily-news release plan on task/multishot-recovery. It does not authorize main merge, deployment, cron activation, paid media generation or publication.

Latest executed multishot suite: 346 passed, 2 failed, 677 deselected (73.44s), in isolated server checkout. Both parameterized E2E tests fail continuity_state schema validation; fixture and integration review remains pending. Tests were not rerun solely for this Git snapshot.

Model provenance: CLI requests and summaries identify Haiku 4.5, but assistant events identify other models. No claim of verified Haiku authorship; see 60_MODEL_IDENTITY_BLOCKER.md. 59_REQUIREMENTS_EVIDENCE.md is an unfinished agent draft, not independently verified acceptance evidence; its task mappings and older test counts must not be treated as release approval. 61_DAILY_NEWS_RELEASE_PLAN.md defines outstanding work and human gates.

Synchronization target is /home/ubuntu/OpenMontage-multishot-recovery on sandbox-video, NOT stable /home/ubuntu/OpenMontage. Server-side source changes are exact synchronization of locally authored files only. Preserve remote dirty files before any fast-forward and abort on content mismatch or unrelated changes. The original local main checkout remains dirty by design; do not reset user work merely to make editor status clean.
