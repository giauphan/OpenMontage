import { BookOpen, Terminal, Server, Boxes } from 'lucide-react';
import type { ExtensionInventory, ExtensionHit } from '../types';

/**
 * ExtensionDock —— 视频底部那一排扩展点：
 * skills / hooks / MCP 被 Claude Code 调用（虚线箭头向上）。
 * 这里同时体现视频里的关键对比：hook 是一次性的（1x），mod 是常驻的。
 */

const KIND_META = {
  skill: { icon: BookOpen, label: 'skills' },
  hook: { icon: Terminal, label: 'hooks' },
  mcp: { icon: Server, label: 'mcp' },
} as const;

export function ExtensionDock({
  inventory,
  recent,
}: {
  inventory: ExtensionInventory | null;
  recent: ExtensionHit[];
}) {
  const skills = inventory?.skills ?? [];
  const hooks = inventory?.hooks ?? [];
  const mcp = inventory?.mcp ?? [];

  // 最近命中的扩展（用于高亮）
  const hot = new Set(recent.slice(0, 8).map((r) => r.name));

  return (
    <div className="pipe-surface rounded-xl p-3.5">
      <div className="pipe-ext">
        {/* 虚线箭头：扩展层 → 上面的流水线 */}
        <div className="pipe-ext__arrow">▲ ▲ ▲</div>

        <div className="pipe-ext__grid">
          <Chip
            kind="skill"
            icon={BookOpen}
            names={skills.map((s) => s.name)}
            hot={hot}
            suffix={skills.length ? `${skills.length}` : '—'}
          />
          <Chip
            kind="hook"
            icon={Terminal}
            names={hooks.map((h) => h.name)}
            hot={hot}
            suffix="1x"
          />
          <Chip
            kind="mcp"
            icon={Server}
            names={mcp.length ? mcp.map((m) => m.name) : ['pipeline-mcp']}
            hot={hot}
            suffix={mcp.length ? `${mcp.length}` : 'in-proc'}
          />
        </div>

        <div className="flex items-center justify-center gap-1.5 mt-2.5">
          <Boxes size={11} className="text-[#6b6f7a]" />
          <span className="text-[10px] text-[color:var(--pipe-muted)]">
            由 Claude Code 调用
          </span>
        </div>
      </div>

      {/* hook vs mod 的对比说明 */}
      <div className="mt-2.5 pt-2.5 border-t border-[#22252c] space-y-1">
        <Row
          tag="hook"
          color="#8b8b93"
          text="一次性脚本 · 触发即退出（session 启动跑 1 次）"
        />
        <Row
          tag="mod"
          color="#2dd4bf"
          text="常驻进程 · 整段会话在线，所以能记住 / 出面板 / 做守卫"
        />
      </div>

      {recent.length > 0 && (
        <div className="mt-2.5 pt-2.5 border-t border-[#22252c]">
          <div className="pipe-title mb-1.5">recent extension calls</div>
          <div className="max-h-24 pipe-scroll">
            {recent.slice(0, 10).map((r) => (
              <div
                key={r.id}
                className="pipe-logline pipe-logline--info"
                title={r.detail ?? ''}
              >
                <span className="text-[#6b6f7a]">[{r.kind}]</span> {r.name}
                {r.once ? ' ·1x' : ''}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function Chip({
  kind,
  icon: Icon,
  names,
  hot,
  suffix,
}: {
  kind: keyof typeof KIND_META;
  icon: React.ComponentType<any>;
  names: string[];
  hot: Set<string>;
  suffix: string;
}) {
  const isHot = names.some((n) => hot.has(n));
  return (
    <div
      className={`pipe-chip ${isHot ? 'is-hot' : ''}`}
      title={names.length ? names.join('\n') : '暂无'}
    >
      <div className="flex items-center justify-center gap-1">
        <Icon size={10} className="text-[#8b8b93]" />
        <span className="pipe-chip__kind">{KIND_META[kind].label}</span>
      </div>
      <div className="pipe-chip__name mt-0.5 truncate">{names[0] ?? '—'}</div>
      <div className="pipe-chip__meta">
        {names.length > 1 ? `+${names.length - 1} · ` : ''}
        {suffix}
      </div>
    </div>
  );
}

function Row({ tag, color, text }: { tag: string; color: string; text: string }) {
  return (
    <div className="flex items-start gap-1.5">
      <span
        className="shrink-0 text-[9.5px] font-bold uppercase px-1.5 py-[1px] rounded"
        style={{ color, border: `1px solid ${color}55` }}
      >
        {tag}
      </span>
      <span className="text-[10px] leading-snug text-[color:var(--pipe-muted)]">{text}</span>
    </div>
  );
}
