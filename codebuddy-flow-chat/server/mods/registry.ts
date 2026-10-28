import type {
  Mod,
  ModMemory,
  ModVerdict,
  ModRuntimeInfo,
  ModPanelSnapshot,
  ModPanelEvent,
  ModToolResultContext,
} from './types.js';
import { createForcePushGuard } from './builtin/force-push-guard.js';
import { createDestructiveGuard } from './builtin/destructive-guard.js';
import { createSessionMemory } from './builtin/session-memory.js';
import { createCostGauge } from './builtin/cost-gauge.js';
import { createLiveAudit } from './builtin/live-audit.js';

/**
 * 会话级共享记忆的简单实现 —— 只要 session 还在，这份 Map 就一直在。
 */
class MemoryStore implements ModMemory {
  private store = new Map<string, unknown>();

  remember(key: string, value: unknown): void {
    this.store.set(key, value);
  }
  recall<T = unknown>(key: string): T | undefined {
    return this.store.get(key) as T | undefined;
  }
  keys(): string[] {
    return Array.from(this.store.keys());
  }
  clear(): void {
    this.store.clear();
  }
}

/** 一次拦截的完整记录（给 pipeline / 面板用） */
export interface InterceptRecord {
  toolName: string;
  toolUseId: string;
  at: number;
  /** 每个 mod 各自的表决 */
  votes: Array<{ modId: string; modName: string; verdict: ModVerdict | null }>;
  /** 最终裁决 */
  final: ModVerdict;
  /** 是否真的改写了入参 */
  changed: boolean;
  before?: string;
  after?: string;
}

/**
 * 一个 session 的 mod 运行时。
 *
 * 关键点：mod 实例在这里被「养着」—— 从 onSessionStart 一直到 onSessionEnd，
 * 中途所有工具调用都复用同一批实例，所以它们能记住东西、能持续往面板追加。
 * hook 则相反：每次触发都是新进程/新调用，跑完就走。
 */
class SessionRuntime {
  readonly sessionId: string;
  readonly memory = new MemoryStore();
  readonly startedAt = Date.now();
  private mods: Mod[] = [];
  private stats = new Map<string, { intercept: number; modify: number; block: number }>();
  private intercepts: InterceptRecord[] = [];
  private panelListeners = new Set<(e: ModPanelEvent & { modId: string }) => void>();
  /** 被禁用的 mod id */
  private disabled = new Set<string>();

  constructor(sessionId: string, factories: Array<() => Mod>) {
    this.sessionId = sessionId;
    this.mods = factories.map((f) => f());
    for (const m of this.mods) {
      this.stats.set(m.id, { intercept: 0, modify: 0, block: 0 });
    }
  }

  async start(): Promise<void> {
    for (const m of this.mods) {
      try {
        await m.onSessionStart?.({ sessionId: this.sessionId, memory: this.memory });
      } catch (err) {
        console.error(`[Mods] ${m.id} onSessionStart 失败:`, err);
      }
    }
  }

  async stop(): Promise<void> {
    for (const m of this.mods) {
      try {
        await m.onSessionEnd?.({ sessionId: this.sessionId, memory: this.memory });
      } catch {
        /* ignore */
      }
    }
    this.memory.clear();
  }

  isEnabled(modId: string): boolean {
    return !this.disabled.has(modId);
  }

  setEnabled(modId: string, enabled: boolean): void {
    if (enabled) this.disabled.delete(modId);
    else this.disabled.add(modId);
  }

  onPanelEvent(fn: (e: ModPanelEvent & { modId: string }) => void): () => void {
    this.panelListeners.add(fn);
    return () => this.panelListeners.delete(fn);
  }

  private emit(modId: string, e: ModPanelEvent): void {
    const payload = { ...e, at: e.at ?? Date.now(), modId };
    for (const fn of this.panelListeners) {
      try {
        fn(payload);
      } catch {
        /* ignore */
      }
    }
  }

  /**
   * 拦截点 —— model 与 tool call 之间。
   * 依次询问所有匹配的 mod，取「最严厉」的裁决作为最终结果。
   */
  async intercept(
    toolName: string,
    input: Record<string, unknown>,
    meta: { toolUseId: string; turn: number }
  ): Promise<InterceptRecord> {
    const votes: InterceptRecord['votes'] = [];
    let final: ModVerdict = { decision: 'allow' };
    let before: string | undefined;
    let after: string | undefined;
    let currentInput = { ...input };

    for (const mod of this.mods) {
      if (!this.isEnabled(mod.id)) continue;
      if (!mod.onToolCall) continue;
      if (mod.matchers && mod.matchers.length > 0 && !mod.matchers.includes(toolName)) continue;

      const s = this.stats.get(mod.id)!;
      s.intercept += 1;

      let verdict: ModVerdict | null = null;
      try {
        verdict =
          (await mod.onToolCall({
            toolName,
            input: currentInput,
            toolUseId: meta.toolUseId,
            sessionId: this.sessionId,
            turn: meta.turn,
            memory: this.memory,
            emit: (e) => this.emit(mod.id, e),
          })) ?? null;
      } catch (err) {
        console.error(`[Mods] ${mod.id} onToolCall 异常:`, err);
        verdict = null;
      }

      votes.push({ modId: mod.id, modName: mod.name, verdict });
      if (!verdict) continue;

      if (verdict.decision === 'deny') {
        s.block += 1;
        final = verdict;
        // deny 最严厉，立即生效
        break;
      }
      if (verdict.decision === 'ask' && final.decision !== 'deny') {
        final = verdict;
      }
      if (verdict.decision === 'modify') {
        s.modify += 1;
        if (before === undefined) before = safeStringify(input);
        currentInput = { ...currentInput, ...(verdict.updatedInput ?? {}) };
        after = safeStringify(currentInput);
        if (final.decision !== 'deny' && final.decision !== 'ask') {
          final = { ...verdict, updatedInput: currentInput };
        }
      }
    }

    const record: InterceptRecord = {
      toolName,
      toolUseId: meta.toolUseId,
      at: Date.now(),
      votes,
      final,
      changed: before !== undefined && before !== after,
      before,
      after,
    };

    this.intercepts.unshift(record);
    if (this.intercepts.length > 100) this.intercepts.length = 100;
    return record;
  }

  async notifyResult(ctx: Omit<ModToolResultContext, 'memory' | 'emit'>): Promise<void> {
    for (const mod of this.mods) {
      if (!this.isEnabled(mod.id)) continue;
      if (!mod.onToolResult) continue;
      try {
        await mod.onToolResult({
          ...ctx,
          memory: this.memory,
          emit: (e) => this.emit(mod.id, e),
        });
      } catch (err) {
        console.error(`[Mods] ${mod.id} onToolResult 异常:`, err);
      }
    }
  }

  /** 供前端渲染的 mod 列表 */
  listInfo(): ModRuntimeInfo[] {
    return this.mods.map((m) => {
      const s = this.stats.get(m.id)!;
      return {
        id: m.id,
        name: m.name,
        description: m.description,
        capabilities: m.capabilities,
        matchers: m.matchers,
        interceptCount: s.intercept,
        modifyCount: s.modify,
        blockCount: s.block,
        startedAt: this.startedAt,
      };
    });
  }

  listPanels(): Array<ModRuntimeInfo & { panel: ModPanelSnapshot }> {
    return this.mods.map((m) => {
      const s = this.stats.get(m.id)!;
      return {
        id: m.id,
        name: m.name,
        description: m.description,
        capabilities: m.capabilities,
        matchers: m.matchers,
        interceptCount: s.intercept,
        modifyCount: s.modify,
        blockCount: s.block,
        startedAt: this.startedAt,
        panel: m.panel?.() ?? { title: m.name },
      };
    });
  }

  recentIntercepts(n = 20): InterceptRecord[] {
    return this.intercepts.slice(0, n);
  }
}

/** 内置 mod 工厂清单 */
const BUILTIN_FACTORIES: Array<() => Mod> = [
  createDestructiveGuard,
  createForcePushGuard,
  createSessionMemory,
  createCostGauge,
  createLiveAudit,
];

class ModRegistry {
  private runtimes = new Map<string, SessionRuntime>();

  /** 取（或创建）某个 session 的 mod 运行时，并启动所有 mod */
  async forSession(sessionId: string): Promise<SessionRuntime> {
    let rt = this.runtimes.get(sessionId);
    if (!rt) {
      rt = new SessionRuntime(sessionId, BUILTIN_FACTORIES);
      this.runtimes.set(sessionId, rt);
      await rt.start();
      console.log(`[Mods] session ${sessionId} 启动 ${BUILTIN_FACTORIES.length} 个 mod（常驻）`);
    }
    return rt;
  }

  peek(sessionId: string): SessionRuntime | undefined {
    return this.runtimes.get(sessionId);
  }

  async endSession(sessionId: string): Promise<void> {
    const rt = this.runtimes.get(sessionId);
    if (!rt) return;
    await rt.stop();
    this.runtimes.delete(sessionId);
  }

  /** 静态清单（未启动也能展示有哪些 mod） */
  catalog(): Array<{ id: string; name: string; description: string }> {
    return BUILTIN_FACTORIES.map((f) => {
      const m = f();
      return { id: m.id, name: m.name, description: m.description };
    });
  }
}

function safeStringify(v: unknown): string {
  try {
    return JSON.stringify(v ?? {});
  } catch {
    return String(v);
  }
}

export const modRegistry = new ModRegistry();
export type { SessionRuntime };
