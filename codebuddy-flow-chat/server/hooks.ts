import fs from 'fs';
import path from 'path';
import { exec } from 'child_process';
import { promisify } from 'util';
import { fileURLToPath } from 'url';
import type { HookEvent, HookCallbackMatcher, HookInput, HookJSONOutput } from '@tencent-ai/agent-sdk';
import { pipelineStore } from './pipeline.js';

/**
 * Hooks 层
 *
 * 视频里的对比很关键：
 *   hook  = 一次性脚本，触发即退出（hook.sh · 1x）
 *   mod   = 常驻进程，整个 session 都在
 *
 * 这里两个都提供：
 *   1. SDK 事件回调（PreToolUse / PostToolUse / SessionStart / Stop …）—— 每次事件触发一次
 *   2. scripts/ 下的 shell 脚本 —— session 启动时跑一次就结束
 */

const execAsync = promisify(exec);

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

export const HOOK_SCRIPTS_DIR = path.join(__dirname, 'hooks', 'scripts');

/** 已经跑过的 session（保证 "1x"） */
const ranOnce = new Set<string>();

/**
 * 构造交给 SDK 的 hooks 配置。
 * 注意：这些都是「一次性」回调 —— 不保存跨调用状态，正是 hook 与 mod 的分界。
 */
export function buildSdkHooks(sessionId: string): Partial<Record<HookEvent, HookCallbackMatcher[]>> {
  const pipe = pipelineStore.get(sessionId);

  const cb = (stage: Parameters<typeof pipe.enter>[0], label: string) => {
    return async (input: HookInput): Promise<HookJSONOutput> => {
      const detail = describeHookInput(input);
      pipe.enter(stage, label, detail);
      pipe.hitExtension('hook', input.hook_event_name, detail, true /* 1x */);
      // hook 不拦截，只是观测 —— 拦截交给 mod
      return { continue: true, suppressOutput: true };
    };
  };

  return {
    UserPromptSubmit: [
      { hooks: [cb('prompt', 'prompt 进入流水线') as never] },
    ],
    PreToolUse: [
      { hooks: [cb('tool', 'hook: PreToolUse') as never] },
    ],
    PostToolUse: [
      { hooks: [cb('screen', 'hook: PostToolUse') as never] },
    ],
    SessionStart: [
      {
        hooks: [
          (async () => {
            pipe.hitExtension('hook', 'SessionStart', 'session 启动，跑一次性脚本', true);
            void runSessionStartScripts(sessionId);
            return { continue: true, suppressOutput: true };
          }) as never,
        ],
      },
    ],
    Stop: [
      { hooks: [cb('screen', 'hook: Stop') as never] },
    ],
  };
}

function describeHookInput(input: HookInput): string | undefined {
  const anyInput = input as { tool_name?: string; prompt?: string; message?: string };
  if (typeof anyInput.tool_name === 'string') return anyInput.tool_name;
  if (typeof anyInput.prompt === 'string') return anyInput.prompt.slice(0, 120);
  if (typeof anyInput.message === 'string') return anyInput.message.slice(0, 120);
  return undefined;
}

/**
 * 执行 scripts/ 下的一次性 shell 脚本。
 * 一个 session 只跑一次 —— 与常驻 mod 形成对照。
 */
export async function runSessionStartScripts(sessionId: string): Promise<
  Array<{ script: string; ok: boolean; output: string }>
> {
  if (ranOnce.has(sessionId)) return [];
  ranOnce.add(sessionId);

  if (!fs.existsSync(HOOK_SCRIPTS_DIR)) return [];

  const scripts = fs
    .readdirSync(HOOK_SCRIPTS_DIR)
    .filter((f) => f.endsWith('.sh'))
    .sort();

  const results: Array<{ script: string; ok: boolean; output: string }> = [];
  const pipe = pipelineStore.get(sessionId);

  for (const script of scripts) {
    const full = path.join(HOOK_SCRIPTS_DIR, script);
    try {
      const { stdout, stderr } = await execAsync(`bash "${full}"`, {
        timeout: 10_000,
        env: { ...process.env, CBC_SESSION_ID: sessionId },
      });
      const output = (stdout || stderr || '').trim().slice(0, 400);
      results.push({ script, ok: true, output });
      pipe.hitExtension('hook', script, output || '(无输出)', true);
      console.log(`[Hooks] 1x ${script} → ok`);
    } catch (err) {
      const output = err instanceof Error ? err.message : String(err);
      results.push({ script, ok: false, output });
      pipe.hitExtension('hook', script, `失败: ${output.slice(0, 200)}`, true);
      console.error(`[Hooks] 1x ${script} → 失败`, output);
    }
  }

  return results;
}

/** 列出磁盘上的 hook 脚本（供前端展示） */
export function listHookScripts(): Array<{ name: string; kind: 'once' }> {
  if (!fs.existsSync(HOOK_SCRIPTS_DIR)) return [];
  return fs
    .readdirSync(HOOK_SCRIPTS_DIR)
    .filter((f) => f.endsWith('.sh'))
    .sort()
    .map((f) => ({ name: f, kind: 'once' as const }));
}

/** 清理一次性标记（会话删除时） */
export function resetHookOnce(sessionId: string): void {
  ranOnce.delete(sessionId);
}
