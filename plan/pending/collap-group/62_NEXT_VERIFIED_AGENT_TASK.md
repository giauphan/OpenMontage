# Next local implementation task: repair real multishot E2E coverage

SUPERVISOR GATE: Do not launch until the approved Haiku 4.5 route is verified. Initialization/modelUsage metadata alone is insufficient; current gateway assistant events contradict it. Never silently substitute a model. Follow 61_DAILY_NEWS_RELEASE_PLAN.md.

## Agent assignment
Read repository instructions. Implement locally only in /home/ubuntu/OpenMontage/.claude/worktrees/multishot-recovery. Preserve existing uncommitted work. Write scope ONLY tests/contracts/test_multishot_end_to_end.py. No Bash, SSH, test execution, paid calls, commits, credential/settings/hook edits or app-source changes. Supervisor executes tests remotely.

Goal: schema-valid public-tool two-shot/10-second and six-shot/30-second offline workflows traversing the actual checkpoints and human approval gates, generating real valid media via an injected offline provider, then finalizing and validating completion.

Evidence: last actual run had 346 passed and 2 failed. Both E2E cases fail the planning continuity_state schema due missing accepted_end_state_fingerprint. Review also found invented asset_manifest/edit_decisions fields, nonexistent asset paths and a finalize call missing the required profile.

Independently inspect the relevant schema/helper signatures and working test fixtures. Use initial_continuity rather than inventing state. Build manifests from actual generated results and real paths, provide an explicit profile matching test media, and use the real emitted render report for compose. Keep all checkpoints, explicit reviews and negative assertions; do not weaken validators or fake metadata. Assert literal accepted narrative continuity, ordered final duration, and no extra submit/cost entry on resume before acceptance.

Before first edit satisfy existing GateGuard evidence requirements. If blocked, present requested facts and retry once; never disable hooks. Use narrow reads and edit early. Cap at 25 turns / 15 minutes; if the task is blocked, report the exact missing interface rather than repeatedly reading files. Do not claim tests ran.

Return changed files, actual implemented behavior, remaining concerns and focused tests for supervisor.

## Supervisor verification
Review diff and model provenance, synchronize exact files to isolated remote test checkout, run the new E2E tests first, then multishot and full contract suites. Record real results and failures. Preserve stable checkout and production state. Passing these cases is NOT daily-news release approval.
