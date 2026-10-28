import { v4 as uuidv4 } from 'uuid';

/**
 * Pipeline 追踪引擎
 *
 * 复刻视频中的流水线结构：
 *
 *      prompt → model → [MOD] → tool call → screen
 *                          ↑
 *              skills / hooks / MCP（扩展层）
 *
 * 每一段流转都被记录成一条事件，通过 SSE 实时推给前端，
 * 前端据此点亮 / 熄灭对应节点。
 */

export type StageId = 'prompt' | 'model' | 'mod' | 'tool' | 'screen';
export type StageStatus = 'idle' | 'active' | 'done' | 'blocked';

export const STAGE_ORDER: StageId[] = ['prompt', 'model', 'mod', 'tool', 'screen'];

export const STAGE_LABELS: Record<StageId, string> = {
  prompt: 'prompt',
  model: 'model',
  mod: 'mod',
  tool: 'tool call',
  screen: 'screen',
};

export type EventKind =
  /** 进入该阶段 */
  | 'enter'
  /** 正常离开该阶段 */
  | 'exit'
  /** 被 mod / 权限拦下 */
  | 'blocked'
  /** 被 mod 改写后放行 */
  | 'modified'
  /** 转交用户确认 */
  | 'asked';

export interface PipelineEvent {
  id: string;
  runId: string;
  at: number;
  stage: StageId;
  kind: EventKind;
  label: string;
  detail?: string;
  /** 命中的 mod（mod 阶段才有） */
  modId?: string;
}

export interface StageState {
  id: StageId;
  label: string;
  status: StageStatus;
  detail?: string;
  at?: number;
  /** 本轮经过该阶段的次数 */
  count: number;
}

export interface PipelineRun {
  runId: string;
  sessionId: string;
  startedAt: number;
  endedAt?: number;
  stages: Record<StageId, StageState>;
  events: PipelineEvent[];
}

/** 扩展层的一次调用（skills / hooks / MCP） */
export interface ExtensionHit {
  id: string;
  kind: 'skill' | 'hook' | 'mcp';
  name: string;
  at: number;
  detail?: string;
  /** hook 是一次性的（1x），mod 是常驻的 —— 视频的核心对比 */
  once?: boolean;
}

export interface PipelineSnapshot {
  sessionId: string;
  runId?: string;
  running: boolean;
  stages: StageState[];
  events: PipelineEvent[];
  extensions: ExtensionHit[];
  /** 当前 mod 正在做什么（显示在 mod 节点上） */
  modActivity?: {
    toolName: string;
    decision: string;
    reason?: string;
    before?: string;
    after?: string;
  };
}

const MAX_EVENTS = 200;
const MAX_EXT = 60;

function freshStages(): Record<StageId, StageState> {
  const out = {} as Record<StageId, StageState>;
  for (const id of STAGE_ORDER) {
    out[id] = { id, label: STAGE_LABELS[id], status: 'idle', count: 0 };
  }
  return out;
}

class SessionPipeline {
  readonly sessionId: string;
  run: PipelineRun | null = null;
  extensions: ExtensionHit[] = [];
  modActivity: PipelineSnapshot['modActivity'];
  private listeners = new Set<(e: PipelineEvent) => void>();

  constructor(sessionId: string) {
    this.sessionId = sessionId;
  }

  subscribe(fn: (e: PipelineEvent) => void): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  beginRun(): PipelineRun {
    const run: PipelineRun = {
      runId: uuidv4(),
      sessionId: this.sessionId,
      startedAt: Date.now(),
      stages: freshStages(),
      events: [],
    };
    this.run = run;
    this.modActivity = undefined;
    return run;
  }

  endRun(): void {
    if (this.run) this.run.endedAt = Date.now();
  }

  private push(stage: StageId, kind: EventKind, label: string, detail?: string, modId?: string) {
    if (!this.run) this.beginRun();
    const run = this.run!;

    const ev: PipelineEvent = {
      id: uuidv4(),
      runId: run.runId,
      at: Date.now(),
      stage,
      kind,
      label,
      detail,
      modId,
    };
    run.events.push(ev);
    if (run.events.length > MAX_EVENTS) run.events.shift();

    const st = run.stages[stage];
    st.at = ev.at;
    st.detail = detail ?? label;
    st.count += 1;
    if (kind === 'enter') st.status = 'active';
    else if (kind === 'blocked') st.status = 'blocked';
    else if (kind === 'exit') st.status = st.status === 'blocked' ? 'blocked' : 'done';
    else if (kind === 'modified' || kind === 'asked') st.status = 'active';

    for (const fn of this.listeners) {
      try {
        fn(ev);
      } catch {
        /* ignore */
      }
    }
    return ev;
  }

  enter(stage: StageId, label?: string, detail?: string, modId?: string): PipelineEvent {
    return this.push(stage, 'enter', label ?? STAGE_LABELS[stage], detail, modId);
  }
  exit(stage: StageId, label?: string, detail?: string): PipelineEvent {
    return this.push(stage, 'exit', label ?? STAGE_LABELS[stage], detail);
  }
  blocked(stage: StageId, label: string, detail?: string, modId?: string): PipelineEvent {
    return this.push(stage, 'blocked', label, detail, modId);
  }
  modified(stage: StageId, label: string, detail?: string, modId?: string): PipelineEvent {
    return this.push(stage, 'modified', label, detail, modId);
  }
  asked(stage: StageId, label: string, detail?: string, modId?: string): PipelineEvent {
    return this.push(stage, 'asked', label, detail, modId);
  }

  hitExtension(kind: ExtensionHit['kind'], name: string, detail?: string, once = false): void {
    this.extensions.unshift({
      id: uuidv4(),
      kind,
      name,
      at: Date.now(),
      detail,
      once,
    });
    if (this.extensions.length > MAX_EXT) this.extensions.length = MAX_EXT;
  }

  setModActivity(a: PipelineSnapshot['modActivity']): void {
    this.modActivity = a;
  }

  snapshot(): PipelineSnapshot {
    const stages = this.run
      ? STAGE_ORDER.map((id) => ({ ...this.run!.stages[id] }))
      : STAGE_ORDER.map((id) => ({ id, label: STAGE_LABELS[id], status: 'idle' as const, count: 0 }));

    return {
      sessionId: this.sessionId,
      runId: this.run?.runId,
      running: !!this.run && !this.run.endedAt,
      stages,
      events: this.run ? this.run.events.slice(-80) : [],
      extensions: this.extensions.slice(0, 30),
      modActivity: this.modActivity,
    };
  }
}

class PipelineStore {
  private sessions = new Map<string, SessionPipeline>();

  get(sessionId: string): SessionPipeline {
    let p = this.sessions.get(sessionId);
    if (!p) {
      p = new SessionPipeline(sessionId);
      this.sessions.set(sessionId, p);
    }
    return p;
  }

  remove(sessionId: string): void {
    this.sessions.delete(sessionId);
  }
}

export const pipelineStore = new PipelineStore();
export type { SessionPipeline };
