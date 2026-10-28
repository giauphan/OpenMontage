import type { Mod, ModVerdict, ModToolCallContext, ModPanelEvent } from '../types.js';

/**
 * destructive-guard
 *
 * 视频中 "nope" 那一格：mod 直接拦下模型想执行的危险命令，
 * 工具根本不会被调用。具备 guard + asksFirst 两项能力。
 */

interface Rule {
  /** 规则名 */
  name: string;
  /** 命中正则 */
  pattern: RegExp;
  /** 拦截理由 */
  reason: string;
  /** 直接拒绝，还是先询问用户 */
  action: 'deny' | 'ask';
}

const RULES: Rule[] = [
  {
    name: 'rm-root',
    pattern: /\brm\s+(-[a-zA-Z]*f[a-zA-Z]*\s+)*(\/|~|\/home|\/usr|\/etc|\/var)(\s|$|\*)/,
    reason: '删除系统根目录/家目录属于不可逆操作',
    action: 'deny',
  },
  {
    name: 'rm-force-star',
    pattern: /\brm\s+-[a-zA-Z]*r[a-zA-Z]*f[a-zA-Z]*\s+(\*|\.\/\*|\.\s*$)/,
    reason: '递归强制删除通配符目标风险过高',
    action: 'ask',
  },
  {
    name: 'mkfs',
    pattern: /\b(mkfs|mkfs\.[a-z0-9]+)\b/,
    reason: '格式化文件系统会销毁磁盘数据',
    action: 'deny',
  },
  {
    name: 'dd-disk',
    pattern: /\bdd\s+if=.*\bof=\/dev\/(sd|nvme|hd)/,
    reason: '直接写裸设备会覆盖磁盘',
    action: 'deny',
  },
  {
    name: 'fork-bomb',
    pattern: /:\s*\(\s*\)\s*\{[^}]*\|[^}]*&\s*\}\s*;?\s*:/,
    reason: 'fork 炸弹会拖垮机器',
    action: 'deny',
  },
  {
    name: 'chmod-777-root',
    pattern: /\bchmod\s+(-R\s+)?777\s+(\/|~|\/etc|\/usr|\/var)/,
    reason: '对系统目录开放 777 权限会带来安全漏洞',
    action: 'deny',
  },
  {
    name: 'curl-pipe-sh',
    pattern: /\b(curl|wget)\b[^\n|]*\|\s*(sudo\s+)?(bash|sh|zsh)\b/,
    reason: '下载即执行的管道脚本无法审计内容',
    action: 'ask',
  },
  {
    name: 'git-hard-reset',
    pattern: /\bgit\s+reset\s+--hard\b/,
    reason: 'git reset --hard 会丢弃未提交的改动',
    action: 'ask',
  },
  {
    name: 'git-clean-fd',
    pattern: /\bgit\s+clean\s+-[a-zA-Z]*f[a-zA-Z]*d?/,
    reason: 'git clean -f 会永久删除未跟踪文件',
    action: 'ask',
  },
  {
    name: 'drop-database',
    pattern: /\b(DROP\s+(DATABASE|TABLE)|TRUNCATE\s+TABLE)\b/i,
    reason: '删库/清表不可恢复',
    action: 'deny',
  },
];

function commandOf(input: Record<string, unknown>): string | null {
  const raw = input?.command ?? input?.cmd ?? input?.command_line;
  return typeof raw === 'string' ? raw : null;
}

export function createDestructiveGuard(): Mod {
  const events: ModPanelEvent[] = [];
  let blocked = 0;
  let asked = 0;

  const push = (e: ModPanelEvent) => {
    events.unshift({ ...e, at: Date.now() });
    if (events.length > 30) events.length = 30;
  };

  const mod: Mod = {
    id: 'destructive-guard',
    name: 'Destructive Guard',
    description: '拦截 rm -rf /、mkfs、fork 炸弹等不可逆命令，敏感操作先询问用户',
    capabilities: {
      memory: false,
      livePanel: true,
      asksFirst: true,
      guard: true,
      gauge: true,
    },
    matchers: ['Bash'],

    onToolCall(ctx: ModToolCallContext): ModVerdict | null {
      const cmd = commandOf(ctx.input);
      if (!cmd) return null;

      for (const rule of RULES) {
        if (rule.pattern.test(cmd)) {
          if (rule.action === 'deny') {
            blocked += 1;
            push({ level: 'block', message: `已拦截 [${rule.name}]：${cmd}` });
            return { decision: 'deny', reason: rule.reason };
          }
          asked += 1;
          push({ level: 'warn', message: `待确认 [${rule.name}]：${cmd}` });
          return { decision: 'ask', reason: rule.reason };
        }
      }
      return null;
    },

    panel() {
      return {
        title: 'Destructive Guard',
        metrics: [
          { label: '已拦截', value: blocked },
          { label: '待确认', value: asked },
        ],
        events: events.slice(0, 12),
      };
    },
  };

  return mod;
}
