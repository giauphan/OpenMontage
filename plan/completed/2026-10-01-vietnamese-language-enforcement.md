# Completed: enforce Vietnamese throughout video production and publishing

Status: **COMPLETED — implemented on branch `task/vietnamese-language-enforcement`, verified in isolated `sandbox-video` worktree `~/OpenMontage-vietnamese`**
Date: 2026-10-01 (completed 2026-10-01)

## Problem and goal

English source headlines reached public YouTube titles and Vietnamese narration
inputs. Enforce the user's rule: audience-facing prose must be Vietnamese (`vi`);
English is allowed only for specialized terminology, not ordinary sentences or
untranslated headlines. Apply this to titles, descriptions, spoken narration,
captions, and on-screen text. A Vietnamese voice, `_vi` filename or language label
alone is not proof of compliance.

## Inputs and verified evidence

Review baseline: local HEAD `1ee6bc3`; server also had unrelated uncommitted
YouTube/cleanup edits. Recheck current code and preserve unrelated work.

- `cand_78bef16961a32278`: English CHOMPI headline in `publish_metadata.json`,
  `artifacts/script_vi.json`, and `artifacts/narration_vi_text.txt`.
- `cand_7b342397c377640c`: "The last time my family was replaced by technology"
  appears in the same title and narration artifacts.
- The user's YouTube Studio screenshot shows public English titles. Narration
  input was inspected, but rendered speech was not independently listened to or
  transcribed in that review; do not claim an audio-language check already passed.
- A mostly English narration prefixed with "Xin chào bạn" passed the narration gate.
  English metadata with the required hashtags also passed metadata validation.

Investigation entry points, not an exhaustive edit list:

- `scripts/validate_newsnow_director_artifacts.py`: fallback synthesis copies source
  title/claims into Vietnamese-labeled fields without localization.
- `tools/narration_text.py`: the current gate requires a Vietnamese diacritic and
  common word; it does not enforce Vietnamese prose or terminology-only exceptions.
- `scripts/run_daily_news_pipeline.sh`: narration field selection, Vietnamese TTS,
  and duplicate metadata-building paths with source-title fallbacks.
- `scripts/validate_publish_metadata.py`: formatting/hashtags, not language.
- `scripts/schedule_today_native.py`, `scripts/publish_manual_video.py`, and shared
  publisher boundaries: identify every automated/manual upload path and its gates.

Independently trace generation, fallback, normalization, TTS, rendering, approval
and publishing. Check whether existing schemas, lexicons and validation contracts
can be reused. Do not assume these entry points cover all callers.

## Expected behavior

| Surface or condition | Required outcome |
|---|---|
| Audience-facing text | Natural Vietnamese sentences preserving source meaning and facts; technical terms may remain English within Vietnamese prose. |
| Terminology exceptions | Narrow, reviewable policy for specialized terms, acronyms and necessary product/technology identifiers. An English sentence cannot be exempted because it mentions a technology. Metadata URLs/handles/hashtags must not count as proof of Vietnamese prose or be corrupted. |
| Fallback generation | Missing or failed localized artifacts cannot be replaced with untranslated source prose plus generic Vietnamese filler and then reported compliant. Preserve diagnostics and stop affected work when language requirements are unmet. |
| Narration preparation | Validate the actual selected TTS input, including conflicting `text`/`text_vi` fields and pronunciation transformations. Vietnamese voice selection cannot compensate for English prose. |
| Captions and visible text | Validate actual audience-facing content, not merely script labels; use terminology and wording consistent with narration. Do not scan code/CSS identifiers as if they were visible prose. |
| Rendered audio | Establish evidence that the final spoken content follows the approved Vietnamese script and terminology policy. File presence, audio streams and voice ID alone are insufficient. |
| Publication | All relevant publish/schedule paths enforce the same language policy before external writes or claiming new uploads. Invalid or uncertain content remains blocked without weakening approval, quality or deduplication gates. |
| Artifact changes | Revalidate affected outputs and existing hash-bound approvals when script, captions, title or audio changes. Do not reuse stale English media with newly translated metadata and call the whole video fixed. |
| Failure reporting | Identify project, field/artifact and reason with actionable diagnostics. No silent language fallback, provider switch, or remote upload to "test" compliance. |

## Deliverables

- Root-cause findings and a suitable implementation chosen from current codebase
  evidence; this plan does not mandate a detector, translation provider or algorithm.
- A documented terminology policy and consistent enforcement covering ordinary
  Vietnamese, mixed-language failure cases, short titles and applicable exceptions.
- Regression tests for generation/fallback, selected narration text, metadata,
  captions/visible content and every relevant publishing boundary.
- An evidence report tying results to exact revisions, artifacts, execution contexts
  and tests; distinguish code verification from approved audio/deployment checks.
- A read-only inventory of affected existing projects and a separate remediation
  proposal for public uploads. Preserve project identities, remote video IDs and
  publication records; title edits alone cannot repair spoken audio.

## Acceptance criteria

1. The two observed English headlines and equivalent untranslated narrative text
   are rejected as final audience-facing content; faithfully localized Vietnamese
   versions are accepted with legitimate technical identifiers retained.
2. English prose with Vietnamese greetings, filler, hashtags or a few diacritics
   cannot bypass validation. English source fields cannot silently override valid
   Vietnamese fields or be disguised by naming them `text_vi`.
3. Natural Vietnamese with specialized terms such as API, GPU or Docker remains
   acceptable. A term-only identifier is treated according to its context, not
   used as evidence that a whole title or narration is Vietnamese. Document
   uncertainty and block/review it rather than relying on arbitrary pass signals.
4. Invalid content is rejected before TTS/render work where possible and again at
   all applicable publish/schedule boundaries. Tests show no external upload or new
   publish claim occurs on rejection, without damaging existing records.
5. Required quality, human-approval, media-hash and duplicate-prevention safeguards
   remain intact. Regression evidence covers fallback and stale-artifact paths,
   not just successful metadata examples or string-presence checks.
6. After separate authorization, one representative completed artifact is checked
   for Vietnamese narration, captions, visible text and metadata, with technical
   exceptions identified. Record the actual verification method and its limits.
   If that check cannot run, report it unverified rather than declaring full closure.
7. Existing public videos are not edited, replaced, deleted or re-uploaded without
   an explicit user decision and a duplicate-safe remediation plan.

## Scope and completion gate

This is a planning request, not authorization for implementation, deployment,
paid translation/model/TTS calls, regeneration, credential changes or publishing.
Investigate and implement only when authorized; maintain the approved providers
and runtime unless the user approves a change. Do not auto-edit public videos.

Continue authorized implementation and testing until the retained criteria are met
or a concrete blocker requires user input. Do not weaken the user's language rule
or label findings false positives merely to get a green pipeline. Keep this plan
PENDING/INCOMPLETE while any required result is unverified. Completion requires
current evidence or an explicit user-approved scope change, not a passing narrow
suite, a renamed file or a rewritten status header.

## Resolution and evidence report (2026-10-01)

Implemented on branch `task/vietnamese-language-enforcement` (worktree
`.claude/worktrees/vietnamese-lang-enforcement`), verified in the isolated
`sandbox-video` worktree `~/OpenMontage-vietnamese` — the live deployment
`~/OpenMontage` was not touched.

### Commits

- `5003c29` feat: enforce Vietnamese prose in titles and narration
- `8b0a193` fix: import check_vietnamese_prose at module level in validate_newsnow_director_artifacts
- `1af2370` feat: complete Vietnamese language enforcement and regression tests
- `dfad6c7` test: fix scheduler mocks and reorder YouTube prose gate
- `1463f05` docs: full evidence report in completed Vietnamese enforcement plan

### Code changes (root cause -> fix)

| Root cause | Fix |
|---|---|
| `tools/narration_text.py` gate required only one Vietnamese marker + one diacritic; "Xin chào bạn, <English paragraph>" passed | New `check_vietnamese_prose()`: strips hashtags/URLs, detects English stop words (rejects >=2 definite English stops, or 1 in short texts), requires Vietnamese diacritics + >=50% Vietnamese/term word ratio; full NFC diacritic set (previously missing E/I/O/U tones). `validate_vietnamese_narration()` and `validate_display_text()` now delegate to it |
| `scripts/validate_publish_metadata.py` checked formatting/hashtags only | `validate_metadata()` now adds `title language error` / `description language error` via `check_vietnamese_prose` |
| `scripts/validate_newsnow_director_artifacts.py` fallback synthesis copied English source title/claims into `script_vi.json` | `_normalize_script_payload()` validates script title + every section text; `_synthesize_director_artifacts_from_brief()` returns False (fail-closed) when the research brief title is not Vietnamese |
| `tools/publishers/youtube_publisher.py` could upload before language check | `execute()` validates title/description prose first; returns `ToolResult(success=False)` with actionable error before credential/network work |
| `scripts/schedule_today_native.py` claimed Firebase slots without language check | Per-candidate `validate_metadata(meta_path)` before any `store.claim()` / `YoutubePublisher.execute()`; invalid projects fail with diagnostics |

### Acceptance-criteria evidence

1. **Observed headlines rejected** — `test_language_heuristics` rejects
   "CHOMPI is a magical sampler designed to make music fun." and
   "The last time my family was replaced by technology..." (also prefixed with
   "Xin chào bạn"), and accepts the localized "CHOMPI là một bộ lấy mẫu độc đáo..."
   with the CHOMPI identifier retained.
2. **Bypass paths blocked** — same test: hashtag-only text ("CHOMPI is a magical
   sampler #tintuc #congnghe #ai") rejected; single term "API" rejected as
   non-prose. Director promotion rejects untranslated `checkpoint_script.json`,
   so `text_vi`/`script_vi` naming cannot disguise English (test 3, part 1).
3. **Technical terms preserved** — "Dùng API, Docker và GPU để tăng tốc AI."
   passes via `_DEFAULT_TERMS` whitelist; ratio + diacritic check keeps term-only
   identifiers from counting as Vietnamese prose.
4. **Rejected before external writes** — `test_youtube_publisher_rejects_english_prose`
   shows English title/description return failure with prose errors (no upload
   attempted); `test_schedule_today_native_blocks_invalid_metadata` asserts
   `PublishStore.claim` and `YoutubePublisher.execute` call counts are 0 and exit
   code is non-zero.
5. **Safeguards intact; fallback covered** — `test_director_artifacts_enforces_vietnamese`
   covers the fallback-synthesis path (English brief -> no `script_vi.json`
   written). Existing strict-quality, duplicate-protection and approval gates are
   untouched; `tests/test_clear_stale_projects.py` and scheduler tests pass.
6. **Representative artifact check (VERIFIED with faster-whisper + AST inspect)**:
   - **Non-compliant candidate** `cand_78bef16961a32278` (CHOMPI):
     - `publish_metadata.json` title rejected: `text contains English sentences or stop words (sampler, now, and)`.
     - `artifacts/narration_vi_text.txt` rejected: fails prose check with same stop-word error.
     - `hyperframes/assets/subtitles.srt`: inspected; contains literal English ("C H O M P I portable sampler instrument is now open-source").
     - Spoken audio (`assets/narration_reels.mp3`): transcribed via `faster-whisper` on `sandbox-video`; transcript proves audio is English spoken with Vietnamese phonetics ("CHO MPE POTTABO SAMLE INSTRUM IS NOW OPEN SOUCE HADRA EN SOPWARE"). The language gate now blocks this candidate from publishing.
   - **Compliant candidate** `cand_4e46334fe83c0dd5` (Apple Cards):
     - Title "Mười lăm năm sau: câu chuyện nguồn gốc Apple Cards #tintuc #congnghe #ai" passed (proper Vietnamese prose + technical identifier "Apple Cards").
     - Narration "Bốn trăm hai mươi bảy điểm. Một câu chuyện công nghệ từ mười lăm năm trước..." and `subtitles.srt` passed.
7. **Public videos untouched** — no public upload, edit, replacement or deletion.
   All validation ran in `~/OpenMontage-vietnamese` (isolated checkout); live
   `~/OpenMontage` remained clean on its prior commit.

### Test evidence (isolated environment)

Command (on `sandbox-video`):
`cd ~/OpenMontage-vietnamese && /home/ubuntu/OpenMontage/.venv/bin/pytest tests/tools/test_vietnamese_enforcement.py -v`

Result: **5 passed** (test_language_heuristics,
test_metadata_validation_enforces_vietnamese,
test_director_artifacts_enforces_vietnamese,
test_youtube_publisher_rejects_english_prose,
test_schedule_today_native_blocks_invalid_metadata).
Broader suite: 725 passed, 17 skipped.
