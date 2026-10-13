# Kids 3D Cartoon Production Profile

Use this when a multi-shot project selects `production_profile.id = "kids-3d-cartoon"` with `version = "v1"`.

## Creative contract

- Use original stylized CGI characters only; do not imitate copyrighted characters or franchise-specific likenesses.
- Default framing is 16:9 landscape unless the request explicitly says otherwise.
- Keep a simple beginning / middle / end story arc with readable emotional beats.
- Preserve character masters and shot keyframes across the full render revision.
- Favor warm lighting, soft shadows, rounded shapes, expressive poses, and clear silhouettes.
- Avoid dark, gritty, scary, uncanny, photorealistic, or cluttered art direction.

## Required editorial review fields

The request may include `kids_editorial_review`; when present, treat it as creator-supplied review data, not agent guesswork:

- `originality`
- `beginning_middle_end`
- `age_appropriate`
- `unsafe_imitation_risk`
- `audio_intelligibility`
- `rights_licenses`
- `made_for_kids_decision`
- optional `reviewer`
- optional `notes`

Never guess the Made-for-Kids decision. Use `creator_must_decide` until the creator declares it.

## Prompting defaults

Combine the style playbook `styles/kids-3d-cartoon.yaml` with provider-specific prompt compilers. Good prompts name:

1. subject and locked character identity,
2. scene action,
3. camera movement,
4. warm lighting,
5. stylized 3D CGI look,
6. continuity constraints from prior shots,
7. explicit negatives for morphing, jitter, dark lighting, and copyrighted likenesses.
