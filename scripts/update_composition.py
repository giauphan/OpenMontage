import os
import re


def _replace_element(block, pattern, new_text, scene_id, selector):
    updated, count = re.subn(
        pattern,
        lambda match: f'{match.group(1)}{new_text}{match.group(2)}',
        block,
        count=1,
        flags=re.DOTALL,
    )
    if count != 1:
        raise ValueError(f'{scene_id}: expected one {selector}, found {count}')
    return updated


def _replace_bullets(block, bullet_texts, scene_id):
    index = 0

    def replace(match):
        nonlocal index
        if index >= len(bullet_texts):
            return match.group(0)
        new_text = bullet_texts[index]
        index += 1
        return f'{match.group(1)}{new_text}{match.group(2)}'

    updated = re.sub(
        r'(<div class="bullet">(?:(?!<div class="bullet">).)*?<span>).*?(</span>)',
        replace,
        block,
        flags=re.DOTALL,
    )
    if index != len(bullet_texts):
        raise ValueError(
            f'{scene_id}: expected at least {len(bullet_texts)} bullets, found {index}'
        )
    return updated


def _update_scene(block, scene_id, updates):
    if 'inner-html' in updates:
        if len(updates) != 1:
            raise ValueError(f'{scene_id}: inner-html cannot be combined with selectors')
        opening_end = block.find('>') + 1
        closing_start = block.rfind('</div>')
        if opening_end == 0 or closing_start == -1:
            raise ValueError(f'{scene_id}: malformed scene block')
        return f'{block[:opening_end]}{updates["inner-html"]}{block[closing_start:]}'

    selectors = {
        'hero-title': r'(<h1 class="hero-title">).*?(</h1>)',
        'scene-title': r'(<h1 class="scene-title[^\"]*">).*?(</h1>)',
        'scene-subtitle': r'(<div class="scene-subtitle">).*?(</div>)',
        'alert': r'(<div class="alert">).*?(</div>)',
        'warning-text': r'(<div class="warning-text">).*?(</div>)',
    }

    for selector, new_text in updates.items():
        if selector == 'bullets':
            block = _replace_bullets(block, new_text, scene_id)
            continue
        if selector not in selectors:
            raise ValueError(f'{scene_id}: unsupported selector {selector}')
        block = _replace_element(
            block, selectors[selector], new_text, scene_id, selector
        )
    return block


def update_composition(project_dir, new_title, scenes_updates, theme=None):
    index_path = os.path.join(project_dir, 'hyperframes', 'index.html')
    with open(index_path, 'r', encoding='utf-8') as file:
        content = file.read()

    content = content.replace('<html lang="en">', '<html lang="vi">', 1)
    if theme:
        variables = ';'.join(f'--{name}:{value}' for name, value in theme.items())
        content, theme_count = re.subn(
            r':root\{[^}]+\}', f':root{{{variables}}}', content, count=1
        )
        if theme_count != 1:
            raise ValueError(f'{index_path}: expected one :root theme, found {theme_count}')

    content, title_count = re.subn(
        r'<title>.*?</title>', f'<title>{new_title}</title>', content, count=1
    )
    if title_count != 1:
        raise ValueError(f'{index_path}: expected one title, found {title_count}')

    for scene_id, updates in scenes_updates.items():
        marker = f'<div id="{scene_id}"'
        start = content.find(marker)
        if start == -1:
            raise ValueError(f'{index_path}: missing {scene_id}')

        next_block = re.search(
            r'\n\s*<div id="(?:scene-\d+|caption-holder)"',
            content[start + len(marker):],
        )
        if next_block is None:
            raise ValueError(f'{index_path}: missing boundary after {scene_id}')

        end = start + len(marker) + next_block.start()
        updated = _update_scene(content[start:end], scene_id, updates)
        content = f'{content[:start]}{updated}{content[end:]}'

    with open(index_path, 'w', encoding='utf-8') as file:
        file.write(content)

    print(f'Updated {index_path} successfully!')


if __name__ == '__main__':
    print('Script helper ready')
