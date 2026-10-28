import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

/**
 * Skills 层
 *
 * 视频底部那一排：Claude Code 会去调用 skills / hooks / MCP。
 * 这里把磁盘上的 markdown skill 扫出来，既能通过 API 展示，
 * 也会被拼进 system prompt，让模型真的知道有这些 skill 可用。
 */

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

export interface SkillInfo {
  name: string;
  description: string;
  /** 相对路径，便于展示 */
  file: string;
  /** 正文行数（粗略体量） */
  lines: number;
}

export const SKILLS_DIR = path.join(__dirname, 'skills');

/** 解析 `---\nname: x\ndescription: y\n---` 形式的 frontmatter */
function parseFrontmatter(raw: string): { meta: Record<string, string>; body: string } {
  const meta: Record<string, string> = {};
  if (!raw.startsWith('---')) return { meta, body: raw };

  const end = raw.indexOf('\n---', 3);
  if (end === -1) return { meta, body: raw };

  const head = raw.slice(3, end);
  const body = raw.slice(end + 4).replace(/^\r?\n/, '');

  for (const line of head.split(/\r?\n/)) {
    const m = line.match(/^([A-Za-z_][\w-]*)\s*:\s*(.*)$/);
    if (m) meta[m[1]] = m[2].trim().replace(/^["']|["']$/g, '');
  }
  return { meta, body };
}

function readSkillsFrom(dir: string): SkillInfo[] {
  if (!fs.existsSync(dir)) return [];
  const out: SkillInfo[] = [];

  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    // 递归一层子目录（SKILL.md 惯例）
    if (entry.isDirectory()) {
      const nested = path.join(dir, entry.name, 'SKILL.md');
      if (fs.existsSync(nested)) {
        const raw = fs.readFileSync(nested, 'utf-8');
        const { meta, body } = parseFrontmatter(raw);
        out.push({
          name: meta.name || entry.name,
          description: meta.description || '',
          file: path.relative(__dirname, nested),
          lines: body.split('\n').length,
        });
      }
      continue;
    }

    if (!entry.name.endsWith('.md')) continue;
    const full = path.join(dir, entry.name);
    const raw = fs.readFileSync(full, 'utf-8');
    const { meta, body } = parseFrontmatter(raw);
    out.push({
      name: meta.name || entry.name.replace(/\.md$/, ''),
      description: meta.description || '',
      file: path.relative(__dirname, full),
      lines: body.split('\n').length,
    });
  }

  return out.sort((a, b) => a.name.localeCompare(b.name));
}

/** 列出全部可用 skill */
export function listSkills(): SkillInfo[] {
  // 只扫项目内的 skills/，避免把用户机器上的无关 skill 混进来
  return readSkillsFrom(SKILLS_DIR).filter((s) => !!s.name);
}

/** 拼进 system prompt 的 skill 清单片段 */
export function skillsPromptFragment(): string {
  const skills = listSkills();
  if (skills.length === 0) return '';

  const lines = skills.map((s) => `- ${s.name}: ${s.description}`).join('\n');
  return [
    '',
    '## Available skills',
    'You may invoke the following skills when they fit the request:',
    lines,
  ].join('\n');
}
