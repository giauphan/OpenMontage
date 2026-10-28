import type { Mod, ModMemory, ModToolResultContext, ModPanelEvent } from '../types.js';

/**
 * cost-gauge
 *
 * 视频右侧的 "gauge" —— 指标类 mod：统计工具调用次数、失败率、总耗时，
 * 用 ~4 chars/token 做粗估 token 数。常驻所以能跨轮累加。
 */

interface Stats {
  calls: number;
  errors: number;
  totalMs: number;
  chars: number;
  byTool: Record<string, number>;
}

const EMPTY: Stats = { calls: 0, errors: 0, totalMs: 0, chars: 0, byTool: {} };

export function createCostGauge(): Mod {
  let memory: ModMemory | null = null;
  const KEY = 'gauge:stats';
  const events: ModPanelEvent[] = [];

  const mod: Mod = {
    id: 'cost-gauge',
    name: 'Cost Gauge',
    description: '统计工具调用次数、失败率、耗时与粗估 token 用量',
    capabilities: {
      memory: true,
      livePanel: true,
      asksFirst: false,
      guard: false,
      gauge: true,
    },

    onSessionStart(ctx: { memory: ModMemory }) {
      memory = ctx.memory;
      ctx.memory.remember(KEY, { ...EMPTY, byTool: {} });
    },

    onToolResult(ctx: ModToolResultContext) {
      if (!memory) return;
      const stats = { ...(memory.recall<Stats>(KEY) ?? EMPTY) };
      stats.byTool = { ...stats.byTool };

      stats.calls += 1;
      if (ctx.isError) stats.errors += 1;
      stats.totalMs += ctx.durationMs;

      const size = (() => {
        try {
          return JSON.stringify(ctx.result ?? '').length;
        } catch {
          return 0;
        }
      })();
      stats.chars += size + JSON.stringify(ctx.input ?? {}).length;
      stats.byTool[ctx.toolName] = (stats.byTool[ctx.toolName] ?? 0) + 1;

      memory.remember(KEY, stats);

      events.unshift({
        level: ctx.isError ? 'warn' : 'ok',
        message: `${ctx.toolName} · ${ctx.durationMs}ms · ${size}B`,
        at: Date.now(),
      });
      if (events.length > 25) events.length = 25;
    },

    panel() {
      const stats = memory?.recall<Stats>(KEY) ?? EMPTY;
      const estTokens = Math.round(stats.chars / 4);
      const errRate = stats.calls ? Math.round((stats.errors / stats.calls) * 100) : 0;

      return {
        title: 'Cost Gauge',
        metrics: [
          { label: '工具调用', value: stats.calls },
          { label: '失败率', value: `${errRate}%` },
          { label: '总耗时', value: `${(stats.totalMs / 1000).toFixed(1)}s` },
          { label: '粗估 tokens', value: estTokens.toLocaleString('en-US') },
        ],
        events: events.slice(0, 10),
      };
    },
  };

  return mod;
}
