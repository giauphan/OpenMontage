import re

with open('scripts/repair_hyperframes_quality.py', 'r') as f:
    text = f.read()

new_scale_code = """        scale_code = (
            f"\\n<script>\\n"
            f"// __repair_scale_injected\\n"
            f"(function() {{\\n"
            f"  window.__timelines = window.__timelines || {{}};\\n"
            f"  var _r_tl = (typeof tl !== 'undefined') ? tl : (window.__timelines['main'] || window.__timelines['full'] || Object.values(window.__timelines)[0]);\\n"
            f"  if (!_r_tl && typeof gsap !== 'undefined') {{\\n"
            f"      _r_tl = gsap.timeline();\\n"
            f"      var cidMatch = document.querySelector('[data-composition-id]');\\n"
            f"      var compId = cidMatch ? cidMatch.getAttribute('data-composition-id') : 'main';\\n"
            f"      window.__timelines[compId] = _r_tl;\\n"
            f"  }}\\n"
            f"  if (_r_tl) {{\\n"
            f"    try {{ _r_tl.timeScale(Math.min(1.0, {root_duration:.3f} / {target:.3f})); }} catch (e) {{}}\\n"
            f"    try {{ _r_tl.duration({target:.3f}); }} catch (e) {{}}\\n"
            f"    try {{\\n"
            f"      _r_tl.fromTo('{root_selector}', {{scale: 1.0}}, {{scale: 1.12, transformOrigin: '50% 50%', force3D: true, duration: 1.6, yoyo: true, repeat: {cycles}, ease: 'sine.inOut'}}, 0);\\n"
            f"    }} catch (e) {{}}\\n"
            f"  }}\\n"
            f"}})();\\n"
            f"</script>\\n"
        )"""

old_code_regex = r'scale_code\s*=\s*\(\s*f"\\n<script>\\n".*?f"</script>\\n"\s*\)'
text = re.sub(old_code_regex, new_scale_code.strip(), text, flags=re.DOTALL)

with open('scripts/repair_hyperframes_quality.py', 'w') as f:
    f.write(text)
