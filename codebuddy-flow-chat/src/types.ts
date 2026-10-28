/**
 * 类型定义
 */

export type PermissionMode = 'default' | 'acceptEdits' | 'plan' | 'bypassPermissions';

export interface Model {
  modelId: string;
  name: string;
  description?: string;
}

export interface ToolCall {
  id: string;
  name: string;
  input?: Record<string, unknown>;
  status: 'running' | 'completed' | 'error';
  result?: string;
  isError?: boolean;
}

/**
 * 内容块类型 - 支持文字和工具调用按顺序排列
 */
export type ContentBlock = 
  | { type: 'text'; text: string }
  | { type: 'tool_use'; toolCall: ToolCall };

export interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;  // 保留用于兼容，存储纯文本摘要
  model?: string;
  timestamp: Date;
  isStreaming?: boolean;
  toolCalls?: ToolCall[];  // 保留用于兼容
  contentBlocks?: ContentBlock[];  // 新增：按顺序排列的内容块
}

export interface Session {
  id: string;
  title: string;
  model: string;
  agentId?: string;
  cwd?: string;
  permissionMode?: PermissionMode;
  createdAt: Date;
  messages: Message[];
}

export interface CustomAgent {
  id: string;
  name: string;
  description?: string;
  systemPrompt: string;
  icon?: string;
  color?: string;
  permissionMode?: PermissionMode;
  createdAt: Date;
  updatedAt: Date;
}

// Agent 是 CustomAgent 的别名
export type Agent = CustomAgent;

export type Theme = 'light' | 'dark';

/**
 * 权限请求 - 用于工具调用确认
 */
export interface PermissionRequest {
  requestId: string;
  toolUseId: string;
  toolName: string;
  input: Record<string, unknown>;
  sessionId: string;
  timestamp: number;
}

/**
 * 权限响应
 */
export interface PermissionResponse {
  requestId: string;
  behavior: 'allow' | 'deny';
  message?: string;
}

/* ============================================================
 * 流水线（pipeline）—— prompt → model → mod → tool call → screen
 * ========================================================== */

export type StageId = 'prompt' | 'model' | 'mod' | 'tool' | 'screen';
export type StageStatus = 'idle' | 'active' | 'done' | 'blocked';
export type EventKind = 'enter' | 'exit' | 'blocked' | 'modified' | 'asked';

/** mod 层：core 节点是模型本体，mod 节点是用户扩展 */
export type NodeLayer = 'core' | 'mod';

export interface PipelineEvent {
  id: string;
  runId: string;
  at: number;
  stage: StageId;
  kind: EventKind;
  label: string;
  detail?: string;
  modId?: string;
}

export interface StageState {
  id: StageId;
  label: string;
  status: StageStatus;
  detail?: string;
  at?: number;
  count: number;
}

export interface ExtensionHit {
  id: string;
  kind: 'skill' | 'hook' | 'mcp';
  name: string;
  at: number;
  detail?: string;
  once?: boolean;
}

export interface ModActivity {
  toolName: string;
  decision: 'allow' | 'modify' | 'deny' | 'ask';
  reason?: string;
  before?: string;
  after?: string;
}

export interface PipelineSnapshot {
  sessionId: string;
  runId?: string;
  running: boolean;
  stages: StageState[];
  events: PipelineEvent[];
  extensions: ExtensionHit[];
  modActivity?: ModActivity;
}

/** mod 能力位 —— 对应视频右侧 memory / live panel / asks first / guard / gauge */
export interface ModCapabilities {
  memory: boolean;
  livePanel: boolean;
  asksFirst: boolean;
  guard: boolean;
  gauge: boolean;
}

export interface ModPanelEvent {
  level: 'info' | 'warn' | 'block' | 'ok';
  message: string;
  at?: number;
}

export interface ModPanelSnapshot {
  title: string;
  metrics?: Array<{ label: string; value: string | number }>;
  events?: ModPanelEvent[];
  memory?: Array<{ key: string; value: string }>;
}

export interface ModRuntime {
  id: string;
  name: string;
  description: string;
  capabilities: ModCapabilities;
  matchers?: string[];
  interceptCount: number;
  modifyCount: number;
  blockCount: number;
  startedAt: number;
  panel?: ModPanelSnapshot;
}

export interface InterceptRecord {
  toolName: string;
  toolUseId: string;
  at: number;
  votes: Array<{ modId: string; modName: string; verdict: { decision: string; reason?: string } | null }>;
  final: { decision: string; reason?: string };
  changed: boolean;
  before?: string;
  after?: string;
}

/** 扩展层清单 */
export interface ExtensionInventory {
  skills: Array<{ name: string; description: string; file: string; lines: number }>;
  hooks: Array<{ name: string; kind: 'once' }>;
  mcp: Array<{ name: string; status: string; tools: string[]; inProcess: boolean }>;
  mods: Array<{ id: string; name: string; description: string }>;
}
