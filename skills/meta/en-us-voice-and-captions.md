# Proposed Skill: Native-Sounding en-US Voice & Caption QA

**Input:** approved en-US script, glossary, performance instructions, source claim ledger, narrator/voice provider capability.  
**Output:** spoken script, narration WAV/MP3, aligned captions, pronunciation report, voice-to-image synchronization ledger.

## Procedure
1. Pick en-US voice matching audience/pacing; do not use Vietnamese phonetic transliteration. Preserve brand names, proper nouns, APIs, acronyms and model IDs verbatim in onscreen text.
2. Build a pronunciation guide *from reliable language references* and verified product brand guidelines for ambiguous terms. Do not confidently invent IPA; request native human or listen-and-compare when uncertain. Test short sample before paying for full generation.
3. Provide punctuation and breaths for natural spoken prosody; convert written complex sentences into conversational English without changing claim semantics. Avoid overly robotic cadence and faux dramatic hype.
4. Separate narration scripts by output format (Short and long-form); do not create 60-second Shorts by mechanically chopping full narration while keeping mismatched captions or incomplete payoff.
5. Generate voice from approved script hash; transcribe final audio; align captions on actual per-rendition audio bytes. ASR is imperfect; flag proper names/negations/numbers for manual review.
6. Validate duration, clip/silence, steady intelligibility relative to music, intelligible consonants, cut endings, start delay, caption timing, captions vs overlays and 9:16 safe area. Never mark audio correct solely because FFprobe reports an audio stream.
7. If voices are synthesized or synthetic media realistic, ensure appropriate platform disclosure decision—not generic automatic labels for all script assistance.

## Strict checks
- Language ID `en` consistent with `en-US` scripted content; no VI narration text/TTS voice/SSML.
- Known important tokens (product/model names, prices, percentages, release dates, version numbers and negation) agree script ↔ audio ↔ subtitles ↔ onscreen labels.
- Every clip fully decodes and is audible; no unexplained narration gaps.
- Caption word/sentence segmentation readable, synchronized and placed safely; speech captions are not a translation of a different edition.
- Pronunciation uncertainty = sample and manual review, not auto-pass.

## Suggested audit artifact
```yaml
locale: en-US
script_sha256: "<hash>"
voice_id: "<existing provider actual chosen voice>"
audio_sha256: "<hash>"
caption_sha256: "<hash>"
pronunciation_exceptions: []
critical_token_mismatches: []
start_end_silence_ok: null
caption_timing_ok: null
mixed_language_detected: null
human_voice_review: pending
verdict: BLOCKED
```

Never output `PASS` while null/pending mandatory fields remain.
