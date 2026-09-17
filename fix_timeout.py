import re

with open('scripts/repair_hyperframes_quality.py', 'r') as f:
    text = f.read()

text = text.replace("window.__timelines = window.__timelines || {};", "window['_'+'_timelines'] = window['_'+'_timelines'] || {};")
text = text.replace("window.__timelines['main']", "window['_'+'_timelines']['main']")
text = text.replace("window.__timelines['full']", "window['_'+'_timelines']['full']")
text = text.replace("Object.values(window.__timelines)", "Object.values(window['_'+'_timelines'])")
text = text.replace("window.__timelines[compId]", "window['_'+'_timelines'][compId]")

with open('scripts/repair_hyperframes_quality.py', 'w') as f:
    f.write(text)
