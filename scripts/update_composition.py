import os
import sys
import json
import re

def update_composition(project_dir, new_title, scenes_updates):
    index_path = os.path.join(project_dir, 'hyperframes', 'index.html')
    with open(index_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # 1. Replace Title
    content = re.sub(r'<title>.*?</title>', f'<title>{new_title}</title>', content)

    # 2. Update Scenes
    for scene_id, updates in scenes_updates.items():
        # Find scene block
        pattern = rf'(<div id="{scene_id}".*?>)(.*?)(</div>)'

        # Helper to update texts inside scene block
        def replace_scene(match):
            opening = match.group(1)
            inner = match.group(2)
            closing = match.group(3)

            for selector, new_text in updates.items():
                if selector == 'hero-title':
                    inner = re.sub(r'(<h1 class="hero-title">).*?(</h1>)', rf'\1{new_text}\2', inner)
                elif selector == 'scene-title':
                    inner = re.sub(r'(<h1 class="scene-title.*?>).*?(</h1>)', rf'\1{new_text}\2', inner)
                elif selector == 'scene-subtitle':
                    inner = re.sub(r'(<div class="scene-subtitle">).*?(</div>)', rf'\1{new_text}\2', inner)
                elif selector == 'alert':
                    inner = re.sub(r'(<div class="alert">).*?(</div>)', rf'\1{new_text}\2', inner)
                elif selector == 'warning-text':
                    inner = re.sub(r'(<div class="warning-text">).*?(</div>)', rf'\1{new_text}\2', inner)
                elif selector == 'bullets':
                    # Replace spans inside bullet items
                    for idx, bullet_text in enumerate(new_text):
                        # Replace (idx+1)-th bullet span
                        parts = inner.split('<div class="bullet">')
                        if len(parts) > idx + 1:
                            parts[idx+1] = re.sub(r'(<span>).*?(</span>)', rf'\1{bullet_text}\2', parts[idx+1], count=1)
                            inner = '<div class="bullet">'.join(parts)

            return opening + inner + closing

        content = re.sub(rf'<div id="{scene_id}".*?</div>(?=  <div id="scene-|\n  <div id="caption-holder")', replace_scene, content, flags=re.DOTALL)

    with open(index_path, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"Updated {index_path} successfully!")

if __name__ == '__main__':
    print("Script helper ready")
