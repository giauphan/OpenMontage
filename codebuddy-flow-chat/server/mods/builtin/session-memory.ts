import type { Mod, ModMemory, ModToolResultContext } from '../types.js';

/**
 * session-memory
 *
 * 视频强调 mod "stays running" 所以能记住东西 —— 这个 mod 就是 memory 能力的示范：
 * 整个 session 期间持续累积「摸过哪些文件、跑过哪些命令、改过哪些工具调用」，
 * 并在实时面板里回显出来。
 */

interface RememberedFile {
  path: string;
  at: number;
  via: string;
}

export function createSessionMemory(): Mod {
  let memory: ModMemory | null = null;
  const FILES_KEY = 'memory:files';
  const CMDS_KEY = 'memory:commands';

  const mod: Mod = {
    id: 'session-memory',
    name: 'Session Memory',
    description: '整段会话持续记住读写过的文件与执行过的命令',
    capabilities: {
      memory: true,
      livePanel: true,
      asksFirst: false,
      guard: false,
      gauge: false,
    },

    onSessionStart(ctx: { memory: ModMemory }) {
      memory = ctx.memory;
      ctx.memory.remember(FILES_KEY, []);
      ctx.memory.remember(CMDS_KEY, []);
    },

    onToolResult(ctx: ModToolResultContext) {
      if (!memory) return;

      const files = (memory.recall<RememberedFile[]>(FILES_KEY) ?? []).slice();
      const path =
        (ctx.input?.file_path as string) ??
        (ctx.input?.path as string) ??
        (ctx.input?.notebook_path as string);

      if (typeof path === 'string' && path) {
        if (!files.some((f) => f.path === path)) {
          files.push({ path, at: Date.now(), via: ctx.toolName });
          memory.remember(FILES_KEY, files);
        }
      }

      if (ctx.toolName === 'Bash' && typeof ctx.input?.command === 'string') {
        const cmds = (memory.recall<string[]>(CMDS_KEY) ?? []).slice();
        cmds.push(ctx.input.command);
        memory.remember(CMDS_KEY, cmds.slice(-50));
      }
    },

    panel() {
      if (!memory) return { title: 'Session Memory', memory: [] };
      const files = memory.recall<RememberedFile[]>(FILES_KEY) ?? [];
      const cmds = memory.recall<string[]>(CMDS_KEY) ?? [];

      return {
        title: 'Session Memory',
        metrics: [
          { label: '记住的文件', value: files.length },
          { label: '记住的命令', value: cmds.length },
        ],
        memory: files.slice(-10).reverse().map((f) => ({
          key: f.path.split('/').pop() || f.path,
          value: `${f.via} · ${new Date(f.at).toLocaleTimeString('zh-CN')}`,
        })),
      };
    },
  };

  return mod;
}
