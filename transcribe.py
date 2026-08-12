import json, sys
from tools.analysis.transcriber import Transcriber

payload = json.loads(sys.stdin.read())
sections = payload["sections"]
words = []
try:
    for section in sections:
        input_path = f"projects/newsnow-2026-08-09/hyperframes/assets/{section['id']}.mp3"
        print(f"Transcribing {input_path}...", file=sys.stderr)
        result = Transcriber().execute({"input_path": input_path, "model_size": "base"})
        if not result.success:
            raise RuntimeError(f"Fail {input_path}: {result.error}")
        offset = section["start_seconds"]
        for word in result.data.get("word_timestamps", []):
            words.append({
                "word": word["word"].strip(),
                "start": round(offset + word["start"], 2),
                "end": round(offset + word["end"], 2),
            })
    print(json.dumps(words))
except Exception:
    import traceback
    traceback.print_exc(file=sys.stderr)
    sys.exit(1)
