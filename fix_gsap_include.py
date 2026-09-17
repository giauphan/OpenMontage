with open('scripts/repair_hyperframes_quality.py', 'r') as f:
    text = f.read()

# Add GSAP injection in patch_html if missing
target = "    html = repair_missing_composition_assets(path, html)"
replacement = """    html = repair_missing_composition_assets(path, html)

    # Ensure GSAP CDN script is always present in HTML
    if "gsap.min.js" not in html and "gsap" not in html:
        gsap_tag = '<script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>'
        if "</head>" in html:
            html = html.replace("</head>", f"  {gsap_tag}\\n</head>", 1)
        elif "<head>" in html:
            html = html.replace("<head>", f"<head>\\n  {gsap_tag}", 1)
        else:
            html = f"{gsap_tag}\\n" + html"""

text = text.replace(target, replacement)

with open('scripts/repair_hyperframes_quality.py', 'w') as f:
    f.write(text)
