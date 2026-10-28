import type { Mod, ModMemory, ModToolCallContext, ModPanelEvent } from '../types.js';

/**
 * live-audit
 *
 * 视频中 "live panel" 那一格：mod 常驻运行，把流经它的每一次工具调用
 * 实时投到右侧面板上。这就是 hook 做不到、而 mod 能做到的地方 ——
 * hook 是一次性的，没有可以持续追加的面板。
 */

export function createLiveAudit(): Mod {
  let memory: ModMemory | null = null;
  const KEY = 'audit:log';

  const mod: Mod = {
    id: 'live-audit',
    name: 'Live Audit',
    description: '把流经 mod 的每一次工具调用实时投射到右侧面板',
    capabilities: {
      memory: true,
      livePanel: true,
      asksFirst: false,
      guard: false,
      gauge: false,
    },

    onSessionStart(ctx: { memory: ModMemory }) {
      memory = ctx.memory;
      ctx.memory.remember(KEY, []);
    },

    // live-audit 只看不改：一律返回 null（= 不干预，原样放行）
    onToolCall(ctx: ModToolCallContext) {
      if (!memory) return null;
      const log = (memory.recall<ModPanelEvent[]>(KEY) ?? []).slice();
      const preview = describe(ctx.toolName, ctx.input);
      log.unshift({ level: 'info', message: preview, at: Date.now() });
      memory.remember(KEY, log.slice(0, 60));
      return null;
    },

    panel() {
      const log = memory?.recall<ModPanelEvent[]>(KEY) ?? [];
      return {
        title: 'Live Audit',
        metrics: [{ label: '流经调用', value: log.length }],
        events: log.slice(0, 15),
      };
    },
  };

  return mod;
}

/** 生成一行人类可读的调用摘要 */
function describe(toolName: string, input: Record<string, unknown>): string {
  if (toolName === 'Bash' && typeof input.command === 'string') {
    return `$ ${truncate(input.command, 90)}`;
  }
  const target =
    (input.file_path as string) ?? (input.path as string) ?? (input.pattern as string);
  if (typeof target === 'string') {
    return `${toolName} → ${truncate(target, 70)}`;
  }
  return `${toolName}`;
}

function truncate(s: string, n: number): string {
  const oneLine = s.replace(/\s+/g, ' ').trim();
  return oneLine.length > n ? `${oneLine.slice(0, n)}…` : oneLine;
}
