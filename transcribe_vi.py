import json, sys, os
from pathlib import Path
from tools.analysis.transcriber import Transcriber

payload = json.loads(sys.stdin.read())
sections = payload["sections"]
words = []
try:
    for section in sections:
        input_path = f"projects/newsnow-2026-08-09/hyperframes/assets/{section['id']}_vi.wav"
        print(f"Transcribing {input_path}...", file=sys.stderr)
        result = Transcriber().execute({"input_path": input_path, "model_size": "base", "language": "vi"})
        if not result.success:
            raise RuntimeError(f"Fail {input_path}: {result.error}")
        offset = float(section["start_seconds"])
        for word in result.data.get("word_timestamps", []):
            words.append({
                "word": word["word"].strip(),
                "start": round(offset + float(word["start"]), 3),
                "end": round(offset + float(word["end"]), 3),
            })
    print(json.dumps(words, ensure_ascii=False))
except Exception:
    import traceback
    traceback.print_exc(file=sys.stderr)
    sys.exit(1)
