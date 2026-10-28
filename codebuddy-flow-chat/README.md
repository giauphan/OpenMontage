# Web Agent

一个基于 CodeBuddy Agent SDK 构建的 Web Agent 应用模板。

## 特性

- 💬 **流式对话** - 实时显示 AI 回复
- 🔧 **工具调用** - 可视化展示 Agent 工具使用
- 🔒 **权限控制** - 支持多种权限模式
- 📝 **会话管理** - 多会话切换和持久化
- 🎨 **主题切换** - 支持深色/浅色主题
- 🤖 **自定义 Agent** - 创建和管理多个 Agent 配置
- 🌊 **流水线可视化** - 实时呈现 `prompt → model → mod → tool call → screen` 的执行链路
- 🧩 **Mod 拦截层** - 常驻模块在工具调用前放行 / 改写 / 拦截 / 先询问
- 🔌 **扩展层** - skills / hooks / MCP 真实接入并按次打点

## 技术栈

- **后端**: Node.js + Express + TypeScript
- **前端**: React 18 + TypeScript + Vite
- **UI**: TDesign React 组件库
- **AI**: CodeBuddy Agent SDK
- **数据库**: SQLite (better-sqlite3)

## 快速开始

### 1. 安装依赖

```bash
npm install
```

### 2. 启动开发服务器

```bash
npm run dev
```

这会同时启动前端（端口 5173）和后端（端口 3000）

### 3. 访问应用

打开浏览器访问 http://localhost:5173

## 项目结构

```
web-agent/
├── server/                    # 后端服务
│   ├── index.ts              # Express 服务器（mod 拦截点接在 canUseTool 上）
│   ├── db.ts                 # 数据库操作
│   ├── pipeline.ts           # 流水线追踪引擎（阶段状态 + SSE 广播）
│   ├── mods/                 # Mod 层
│   │   ├── types.ts          #   Mod 契约
│   │   ├── registry.ts       #   常驻注册表（按 session 养着 mod 实例）
│   │   └── builtin/          #   内置 mod
│   ├── skills/               # Skill 文件（markdown + frontmatter）
│   ├── hooks/
│   │   ├── index 见 hooks.ts # SDK 事件回调（一次性）
│   │   └── scripts/*.sh      # 一次性 shell 脚本
│   ├── skills.ts             # Skill 扫描与 system prompt 注入
│   ├── hooks.ts              # Hook 层
│   └── mcp.ts                # 进程内 MCP server
├── src/                      # 前端源码
│   ├── components/
│   │   ├── PipelineFlow.tsx  #   流水线图（核心节点粉、mod 节点青）
│   │   ├── ModPanel.tsx      #   mod 能力面板（memory/live panel/...）
│   │   ├── ExtensionDock.tsx #   skills / hooks / MCP 扩展坞
│   │   └── PipelineSidebar.tsx
│   ├── hooks/usePipeline.ts  # SSE 订阅
│   ├── components/           # React 组件
│   ├── pages/                # 页面组件
│   ├── types.ts              # 类型定义
│   ├── config.ts             # 应用配置
│   └── App.tsx               # 应用入口
├── data/                     # 数据存储
│   └── chat.db               # SQLite 数据库
├── package.json
├── tsconfig.json
├── vite.config.ts
├── README.md                 # 项目说明
└── DEVELOPMENT.md            # 二次开发指南
```

## 核心功能

### Agent SDK 集成

- 使用 `query()` API 发送消息并接收流式响应
- 使用 `unstable_v2_createSession()` 创建和管理 Agent 会话
- 使用 `unstable_v2_authenticate()` 处理身份认证
- 支持会话恢复（使用 `resume` 参数）

### 权限控制

支持四种权限模式：
- `default` - 每次工具调用需要确认
- `acceptEdits` - 自动接受编辑类操作
- `plan` - 计划模式（只读）
- `bypassPermissions` - 跳过所有权限检查

### 流式响应

使用 Server-Sent Events (SSE) 实现实时流式响应：
- 文本内容流式输出
- 工具调用实时展示
- 权限请求实时弹窗

### 数据持久化

使用 SQLite 存储：
- 会话信息和配置
- 消息历史记录
- Agent SDK 的 session_id（用于恢复对话）

## 流水线与 Mod

应用把一次请求的执行链路显式画出来：

```
prompt → model → [MOD] → tool call → screen
                    ↑
        skills / hooks / MCP
```

- **粉色** = 核心环节（模型自带）
- **青色** = mod（常驻扩展层，逐条检查工具调用）

### Mod vs Hook

| | hook | mod |
|---|---|---|
| 生命周期 | 触发一次即退出（`1x`） | 常驻整个 session |
| 状态 | 无跨调用状态 | 共享 `ModMemory` |
| 能做的 | 观测、打点 | 放行 / 改写 / 拦截 / 先询问、出实时面板、统计指标 |

### 内置 Mod

| id | 能力 | 行为 |
|---|---|---|
| `destructive-guard` | guard · asksFirst · livePanel · gauge | 拦下 `rm -rf /`、`mkfs`、fork 炸弹等；`git reset --hard` 等先询问 |
| `force-push-guard` | guard · livePanel | 把 `git push --force` 改写成 `--force-with-lease` |
| `session-memory` | memory · livePanel | 记住整段会话读写过的文件与命令 |
| `cost-gauge` | gauge · memory · livePanel | 统计调用次数、失败率、耗时、粗估 tokens |
| `live-audit` | livePanel · memory | 把流经的每次调用投到实时面板 |

### 拦截点

mod 接在 SDK 的 `canUseTool` 上 —— 也就是模型决定调用工具之后、工具真正执行之前。
多个 mod 依次表决，取最严厉的裁决：`deny` > `ask` > `modify` > `allow`。
返回 `null` 表示「不干预，原样放行」。

写一个新 mod：

```ts
// server/mods/builtin/my-mod.ts
export function createMyMod(): Mod {
  return {
    id: 'my-mod',
    name: 'My Mod',
    description: '一句话说明',
    capabilities: { memory: false, livePanel: true, asksFirst: false, guard: true, gauge: false },
    matchers: ['Bash'],
    onToolCall(ctx) {
      if (危险) return { decision: 'deny', reason: '为什么拦' };
      return { decision: 'modify', reason: '为什么改', updatedInput: { ...ctx.input, ... } };
    },
    panel: () => ({ title: 'My Mod', metrics: [], events: [] }),
  };
}
```

然后在 `server/mods/registry.ts` 的 `BUILTIN_FACTORIES` 里注册即可。

### 不用等模型也能看效果

右侧面板的「跑一次流转」按钮会把一次工具调用真的送过 mod 层
（真 mod、真裁决、真 pipeline 事件），用来直接观察四种裁决：

| 场景 | mod 的裁决 |
|---|---|
| `git push --force` | `modify` —— 改写成 `--force-with-lease` |
| `rm -rf /` | `deny` —— 拦下，**tool call 保持 idle（工具没被执行）** |
| `git reset --hard` | `ask` —— 先询问用户 |
| `Read 文件` | `allow` —— 原样放行 |

## API 端点

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/health` | GET | 健康检查 |
| `/api/pipeline/:id` | GET | 流水线快照 |
| `/api/pipeline/:id/stream` | GET | 流水线实时事件（SSE） |
| `/api/pipeline/:id/demo` | POST | 走一遍真实 mod 拦截（`scenario`） |
| `/api/mods/:id` | GET | 常驻 mod 列表 + 各自实时面板 |
| `/api/mods/:id/toggle` | POST | 启停某个 mod |
| `/api/extensions` | GET | skills / hooks / MCP / mods 清单 |
| `/api/check-login` | GET | 检查 CodeBuddy 登录状态 |
| `/api/models` | GET | 获取可用模型列表 |
| `/api/sessions` | GET | 获取所有会话 |
| `/api/sessions` | POST | 创建新会话 |
| `/api/sessions/:id` | GET | 获取单个会话 |
| `/api/sessions/:id` | PATCH | 更新会话 |
| `/api/sessions/:id` | DELETE | 删除会话 |
| `/api/chat` | POST | 发送消息（SSE 流式响应） |
| `/api/permission-response` | POST | 响应权限请求 |

## 环境要求

- Node.js 18+
- npm 或 yarn

## 配置

### 方式一：环境变量配置

创建 `.env` 文件：

```bash
PORT=3000
CODEBUDDY_API_KEY=your_api_key
CODEBUDDY_AUTH_TOKEN=your_auth_token
CODEBUDDY_BASE_URL=https://api.example.com
CODEBUDDY_INTERNET_ENVIRONMENT=external
```

### 方式二：使用 CodeBuddy CLI 登录

```bash
# 登录 CodeBuddy
codebuddy login

# 启动应用（会自动使用 CLI 的登录信息）
npm run dev
```

### 方式三：Web UI 配置

在应用的设置页面中配置环境变量（仅在当前服务器进程有效）。

## 开发

```bash
# 开发模式（同时启动前后端）
npm run dev

# 单独启动后端
npm run dev:server

# 单独启动前端
npm run dev:client

# 构建生产版本
npm run build

# 运行生产版本
npm start
```

## 二次开发

如果你想基于这个模板进行定制化开发，请查看 [DEVELOPMENT.md](./DEVELOPMENT.md) 获取详细指南，包括：

- 项目架构详解
- 核心功能实现原理
- 10+ 常见定制场景示例
- API 完整参考
- 调试和部署指南

## License

MIT
