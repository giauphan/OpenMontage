import type { Mod, ModVerdict, ModToolCallContext } from '../types.js';

/**
 * 取 Bash 工具里的命令串
 */
function commandOf(input: Record<string, unknown>): string | null {
  const raw = input?.command ?? input?.cmd ?? input?.command_line;
  return typeof raw === 'string' ? raw : null;
}

/**
 * force-push-guard
 *
 * 视频里 mod 演示的核心动作：工具调用经过 mod 时，
 * mod 把 `git push --force` 改写成 `git push --force-with-lease`，
 * 再交给工具执行 —— 即 "let it through" 之外的 "change it"。
 */
export function createForcePushGuard(): Mod {
  let rewriteCount = 0;

  const mod: Mod = {
    id: 'force-push-guard',
    name: 'Force Push Guard',
    description: '把 git push --force 改写为 --force-with-lease，避免覆盖他人提交',
    capabilities: {
      memory: false,
      livePanel: true,
      asksFirst: false,
      guard: true,
      gauge: false,
    },
    matchers: ['Bash'],

    onToolCall(ctx: ModToolCallContext): ModVerdict | null {
      const cmd = commandOf(ctx.input);
      if (!cmd) return null;

      // 只关心 git push
      if (!/\bgit\s+push\b/.test(cmd)) return null;

      // 已经是安全的写法
      if (/--force-with-lease/.test(cmd)) return null;

      // 命中 --force / -f
      const forced = /--force(?!=with-lease)|(?<![\w-])-f(?![\w-])/.test(cmd);
      if (!forced) return null;

      const rewritten = cmd
        .replace(/--force(?!-with-lease)/g, '--force-with-lease')
        .replace(/(?<![\w-])-f(?![\w-])/g, '--force-with-lease');

      rewriteCount += 1;

      ctx.emit({
        level: 'warn',
        message: `改写 force push → force-with-lease：「${cmd}」`,
      });

      return {
        decision: 'modify',
        reason: 'git push --force 会覆盖远端他人提交，已改为 --force-with-lease',
        updatedInput: { ...ctx.input, command: rewritten },
      };
    },

    panel() {
      return {
        title: 'Force Push Guard',
        metrics: [{ label: '已改写', value: rewriteCount }],
      };
    },
  };

  return mod;
}
