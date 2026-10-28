/**
 * Mod 契约 —— 复刻视频中的 "mod" 概念
 *
 * 视频中的流水线： prompt → model → [MOD] → tool call → screen
 *
 * 与 hook 的本质区别：
 *   - hook  = 一次性的 shell/回调脚本，触发即退出（1x）
 *   - mod   = 常驻进程内模块，整个 session 期间一直运行，
 *             因此可以「记住」(memory)、渲染「实时面板」(live panel)、
 *             做「守卫」(guard)、「先询问」(asks first)、统计「仪表」(gauge)
 */

/** Mod 对一次工具调用给出的裁决 */
export type ModDecision =
  /** 放行：原样交给工具执行 */
  | 'allow'
  /** 改写：修改入参后再执行（视频里的 "change it"） */
  | 'modify'
  /** 拦截：直接拒绝执行（视频里的 "nope"） */
  | 'deny'
  /** 先询问：转交用户确认 */
  | 'ask';

/** Mod 声明的能力位 —— 对应视频右侧列出的 memory / live panel / asks first / guard / gauge */
export interface ModCapabilities {
  /** 跨整轮会话记住状态 */
  memory: boolean;
  /** 提供实时面板数据 */
  livePanel: boolean;
  /** 敏感操作前先询问用户 */
  asksFirst: boolean;
  /** 拦截/拒绝危险调用 */
  guard: boolean;
  /** 产出用量指标 */
  gauge: boolean;
}

/** 会话级共享记忆（所有 mod 共用一份，session 存活期间持续累积） */
export interface ModMemory {
  /** 写入一条记忆 */
  remember(key: string, value: unknown): void;
  /** 读取一条记忆 */
  recall<T = unknown>(key: string): T | undefined;
  /** 列出全部记忆键 */
  keys(): string[];
  /** 清空（会话结束时调用） */
  clear(): void;
}

/** 交给 mod 的一次工具调用上下文 */
export interface ModToolCallContext {
  toolName: string;
  input: Record<string, unknown>;
  toolUseId: string;
  sessionId: string;
  /** 第几轮（从 1 开始） */
  turn: number;
  /** 会话共享记忆 */
  memory: ModMemory;
  /** 向实时面板推送一条事件 */
  emit(note: ModPanelEvent): void;
}

/** 实时面板中的一条事件 */
export interface ModPanelEvent {
  level: 'info' | 'warn' | 'block' | 'ok';
  message: string;
  at?: number;
}

/** Mod 的裁决结果 */
export interface ModVerdict {
  decision: ModDecision;
  /** 给用户的简短理由（会显示在流水线与面板上） */
  reason?: string;
  /** decision = 'modify' 时的新入参 */
  updatedInput?: Record<string, unknown>;
}

/** 工具执行完成后回调（用于 gauge / memory） */
export interface ModToolResultContext extends ModToolCallContext {
  result: unknown;
  isError: boolean;
  durationMs: number;
}

/** 实时面板快照 */
export interface ModPanelSnapshot {
  /** 面板标题 */
  title: string;
  /** 关键指标行 */
  metrics?: Array<{ label: string; value: string | number }>;
  /** 最近事件（倒序） */
  events?: ModPanelEvent[];
  /** 记忆条目 */
  memory?: Array<{ key: string; value: string }>;
}

/** Mod 定义 */
export interface Mod {
  /** 唯一 id */
  id: string;
  /** 展示名 */
  name: string;
  /** 一句话说明 */
  description: string;
  /** 能力位 */
  capabilities: ModCapabilities;
  /** 匹配哪些工具（不填表示全部） */
  matchers?: string[];

  /** —— 生命周期：mod 常驻整个 session —— */
  onSessionStart?(ctx: { sessionId: string; memory: ModMemory }): void | Promise<void>;
  onSessionEnd?(ctx: { sessionId: string; memory: ModMemory }): void | Promise<void>;

  /** —— 拦截点：位于 model 与 tool call 之间 —— */
  onToolCall?(
    ctx: ModToolCallContext
  ): ModVerdict | null | undefined | Promise<ModVerdict | null | undefined>;

  /** 工具执行后 */
  onToolResult?(ctx: ModToolResultContext): void | Promise<void>;

  /** 实时面板快照 */
  panel?(): ModPanelSnapshot;
}

/** 运行时注册信息 */
export interface ModRuntimeInfo {
  id: string;
  name: string;
  description: string;
  capabilities: ModCapabilities;
  matchers?: string[];
  /** 已拦截次数 */
  interceptCount: number;
  /** 已改写次数 */
  modifyCount: number;
  /** 已拦截(deny)次数 */
  blockCount: number;
  /** 会话启动时间 */
  startedAt: number;
}
