# Fix current last 2 focused H4 failures only

Use claude-haiku-4-5-20251001 only. Read AGENT_GUIDE.md first. Read/Edit/Write/Glob/Grep only. No shell, no commits, no settings/hooks, no paid calls. Supervisor runs tests. 10-minute cap. Write ONLY:
- tests/contracts/test_multishot_public_tool.py
- tests/contracts/test_multishot_session.py
- lib/multishot_session.py

Actual focused run: 2 failed, 8 passed.

1) test_multishot_public_tool.py: idea checkpoint setup is still invalid. Error: "Stage 'idea' with status 'completed' must include canonical artifact 'brief'". Fix by reading the Multishot tool checkpoint operation and passing artifacts exactly as it expects so write_checkpoint receives canonical artifact key brief. Do not make story assertion accept this setup failure. Assert idea checkpoint setup success before story test. If tool currently wraps artifacts incorrectly, fix tools/video/multishot.py only if absolutely needed, but keep scope minimal; otherwise only test payload.

2) test_multishot_session.py / lib/multishot_session.py: regenerate_shot still validates narrative shot_plan end_state against continuity_state and test mutates unsupported modifiers. Actual shot end_state schema is character/environment/props only. Production regenerate_shot must validate supplied end_state against the shot_plan end_state subschema, not continuity_state. Use schemas.multishot.load_schema("shot_plan") + jsonschema.validate(instance=end_state, schema=end_state_schema). Reject invalid narrative end_state. Test mutation should be valid: new_end_state["character"] = new_end_state["character"] + " with apron stained". Do not invent character_state/modifiers or continuity_state coercion.

Do not touch retry semantics or media validation. Do not claim tests ran. Report exact changes only.
