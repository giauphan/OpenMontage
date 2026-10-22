Mode: Templated News Generation (en-US / US Market)

Generate the required templated director artifacts for {{PROJECT_DIR}}.

Target Audience & Cultural Localization:
- Audience: United States technology professionals, developers, and tech enthusiasts.
- Editorial Standard: Follow skills/meta/cultural-localization-en-us.md and skills/meta/audience-and-culture-us.md.

Author the following three required JSON artifacts:

1. artifacts/script_en_US.json
Must be a flat JSON file at {{PROJECT_DIR}}/artifacts/script_en_US.json.
Schema keys: version (1.0), title, total_duration_seconds, sections (array of: id, text, start_seconds, end_seconds).
Content: 100% natural, idiomatic American English. Rich spoken-word narration, 180-240 spoken words total (minimum 60s). Every section MUST be a complete, grammatically sound sentence.
Base all script content strictly on {{PROJECT_DIR}}/artifacts/research_brief.json. Never invent numbers or citations.

2. artifacts/template_selection.json
Must be a flat JSON file at {{PROJECT_DIR}}/artifacts/template_selection.json.
Format:
{
  "template_id": "news-explainer",
  "template_version": "1.0.0",
  "reason": "Explaining the architecture and operational mechanism of local AI hardware."
}
Allowed template_id values: "news-explainer", "news-evidence", "news-debate".

3. artifacts/template_content.json
Must be a schema-valid content instance matching the chosen template package at {{PROJECT_DIR}}/artifacts/template_content.json.
Required keys:
- template: matches template_id (e.g. "news-explainer")
- template_version: "1.0.0"
- variant: "full"
- title: English headline (min 3 chars)
- duration: total duration in seconds (>= 60)
- narration: full English narration text
- slots: dictionary of slot content matching the template package slots (e.g. hook, concept/capability, mechanism/steps, takeaway). Each slot requires: heading, text, start, end.
- Optional media / visual elements: verified local assets, SVG diagrams, or authentic source photos.
