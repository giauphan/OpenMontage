import { z } from 'zod';
import { createSdkMcpServer, tool } from '@tencent-ai/agent-sdk';
import type { McpServerConfig } from '@tencent-ai/agent-sdk';
import { modRegistry } from './mods/registry.js';
import { pipelineStore } from './pipeline.js';
import { listSkills } from './skills.js';
import { listHookScripts } from './hooks.js';

/**
 * MCP 层
 *
 * 视频底部三个扩展点之一。这里用 SDK 自带的 createSdkMcpServer 建一个
 * 真正跑在进程内的 MCP server —— 模型可以真的调用它的工具，
 * 而不是只画一个图标。
 */

export interface McpDescriptor {
  name: string;
  status: 'connected' | 'pending' | 'failed';
  tools: string[];
  inProcess: boolean;
}

const servers = new Map<string, ReturnType<typeof createSdkMcpServer>>();

/**
 * 取（或创建）某个 session 的进程内 MCP server。
 * 工具直接读 pipeline / mod 的实时状态，所以模型能「问」流水线现在走到哪了。
 */
function serverFor(sessionId: string) {
  let s = servers.get(sessionId);
  if (s) return s;

  s = createSdkMcpServer({
    name: 'pipeline-mcp',
    version: '1.0.0',
    tools: [
      tool(
        'pipeline_status',
        '返回当前流水线各阶段状态与最近事件（prompt/model/mod/tool/screen）',
        { sessionId: z.string().optional().describe('会话 id，缺省为当前会话') },
        async ({ sessionId: sid }) => {
          const id = sid || sessionId;
          const snap = pipelineStore.get(id).snapshot();
          return {
            content: [
              {
                type: 'text' as const,
                text: JSON.stringify(snap.stages, null, 2),
              },
            ],
          };
        }
      ),
      tool(
        'mod_list',
        '列出所有常驻 mod 及其能力（memory / livePanel / asksFirst / guard / gauge）',
        { sessionId: z.string().optional() },
        async ({ sessionId: sid }) => {
          const id = sid || sessionId;
          const rt = modRegistry.peek(id);
          const info = rt ? rt.listInfo() : modRegistry.catalog();
          return {
            content: [{ type: 'text' as const, text: JSON.stringify(info, null, 2) }],
          };
        }
      ),
      tool(
        'extension_inventory',
        '列出扩展层：skills、一次性 hook 脚本、MCP server',
        {},
        async () => {
          const inventory = {
            skills: listSkills().map((s) => s.name),
            hooks: listHookScripts().map((h) => h.name),
            mcp: listMcpServers().map((m) => m.name),
          };
          return {
            content: [{ type: 'text' as const, text: JSON.stringify(inventory, null, 2) }],
          };
        }
      ),
    ],
  });

  servers.set(sessionId, s);
  return s;
}

/** 交给 query() 的 mcpServers 配置 */
export function mcpServersFor(sessionId: string): Record<string, McpServerConfig> {
  try {
    const s = serverFor(sessionId);
    return { 'pipeline-mcp': s as unknown as McpServerConfig };
  } catch (err) {
    console.error('[MCP] 创建进程内 MCP server 失败:', err);
    return {};
  }
}

/** 前端展示用 */
export function listMcpServers(): McpDescriptor[] {
  return Array.from(servers.entries()).map(([sessionId, s]) => ({
    name: s.name,
    status: 'connected' as const,
    tools: ['pipeline_status', 'mod_list', 'extension_inventory'],
    inProcess: true,
  }));
}

/** 记录一次 MCP 工具被调用（打点到底部扩展层） */
export function noteMcpHit(sessionId: string, name: string, detail?: string): void {
  pipelineStore.get(sessionId).hitExtension('mcp', name, detail);
}

export function disposeMcp(sessionId: string): void {
  servers.delete(sessionId);
}
