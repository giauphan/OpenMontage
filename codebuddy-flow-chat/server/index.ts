import express from "express";
import { query, unstable_v2_createSession, unstable_v2_authenticate, PermissionResult, CanUseTool } from "@tencent-ai/agent-sdk";
import { v4 as uuidv4 } from "uuid";
import path from "path";
import { fileURLToPath } from "url";
import { exec } from "child_process";
import { promisify } from "util";
import * as db from "./db.js";

// —— 流水线 / mod / 扩展层 ——
import { pipelineStore } from "./pipeline.js";
import { modRegistry } from "./mods/registry.js";
import { buildSdkHooks, runSessionStartScripts, listHookScripts } from "./hooks.js";
import { listSkills, skillsPromptFragment } from "./skills.js";
import { mcpServersFor, listMcpServers, noteMcpHit } from "./mcp.js";

const execAsync = promisify(exec);

/** 工具入参的一行预览 */
function safePreview(input: Record<string, unknown> | undefined): string | undefined {
  if (!input) return undefined;
  const raw =
    (input.command as string) ??
    (input.file_path as string) ??
    (input.path as string) ??
    (input.pattern as string);
  if (typeof raw === 'string') return raw.replace(/\s+/g, ' ').slice(0, 120);
  try {
    return JSON.stringify(input).slice(0, 120);
  } catch {
    return undefined;
  }
}

// 待处理的权限请求
interface PendingPermission {
  resolve: (result: PermissionResult) => void;
  reject: (error: Error) => void;
  toolName: string;
  input: Record<string, unknown>;
  sessionId: string;
  timestamp: number;
}

const pendingPermissions = new Map<string, PendingPermission>();

// 权限请求超时时间（5分钟）
const PERMISSION_TIMEOUT = 5 * 60 * 1000;

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const app = express();
const PORT = process.env.PORT || 3000;

// Middleware
app.use(express.json());

// 缓存可用模型列表
let cachedModels: Array<{ modelId: string; name: string; description?: string }> = [];
const defaultModel = "claude-sonnet-4";

// 健康检查
app.get("/api/health", (req, res) => {
  res.json({ status: "ok", timestamp: new Date().toISOString() });
});

// 登录方式类型
type LoginMethod = 'env' | 'cli' | 'none';

interface LoginStatusResponse {
  isLoggedIn: boolean;
  method?: LoginMethod;
  envConfigured?: boolean;
  cliConfigured?: boolean;
  error?: string;
  apiKey?: string; // 脱敏后的 API Key
  envVars?: {
    apiKey?: string;
    authToken?: string;
    internetEnv?: string;
    baseUrl?: string;
  };
}

// 检查 CodeBuddy CLI 登录状态
app.get("/api/check-login", async (req, res) => {
  const response: LoginStatusResponse = {
    isLoggedIn: false,
    envConfigured: false,
    cliConfigured: false,
    envVars: {},
  };
  
  // 1. 检查环境变量
  const apiKey = process.env.CODEBUDDY_API_KEY;
  const authToken = process.env.CODEBUDDY_AUTH_TOKEN;
  const internetEnv = process.env.CODEBUDDY_INTERNET_ENVIRONMENT;
  const baseUrl = process.env.CODEBUDDY_BASE_URL;
  
  if (apiKey || authToken) {
    response.envConfigured = true;
    // 脱敏显示
    if (apiKey) {
      response.envVars!.apiKey = apiKey.slice(0, 8) + '****' + apiKey.slice(-4);
      response.apiKey = response.envVars!.apiKey;
    }
    if (authToken) {
      response.envVars!.authToken = authToken.slice(0, 8) + '****' + authToken.slice(-4);
    }
    if (internetEnv) {
      response.envVars!.internetEnv = internetEnv;
    }
    if (baseUrl) {
      response.envVars!.baseUrl = baseUrl;
    }
  }
  
  // 2. 使用 unstable_v2_authenticate 检查登录状态（更可靠）
  try {
    let needsLogin = false;
    
    const result = await unstable_v2_authenticate({
      environment: 'external',
      onAuthUrl: async (authState) => {
        // 如果执行到这个回调，说明未登录
        needsLogin = true;
        console.log('[Check Login] 需要登录，认证 URL:', authState.authUrl);
        // 将认证 URL 返回给前端（如果需要）
        response.error = '未登录，请先登录 CodeBuddy CLI';
      }
    });
    
    // 如果没有触发 onAuthUrl 回调，说明已登录
    if (!needsLogin && result?.userinfo) {
      response.isLoggedIn = true;
      response.cliConfigured = true;
      
      // 判断登录方式
      if (response.envConfigured) {
        response.method = 'env';
      } else {
        response.method = 'cli';
      }
      
      console.log('[Check Login] 已登录用户:', result.userinfo.userName);
    } else if (!needsLogin) {
      // result 存在但没有 userinfo，仍然认为已登录
      response.isLoggedIn = true;
      response.cliConfigured = true;
      response.method = response.envConfigured ? 'env' : 'cli';
    }
  } catch (error: any) {
    console.error("[Check Login] SDK Error:", error);
    
    // 如果有环境变量配置，仍然认为是登录状态
    if (response.envConfigured) {
      response.isLoggedIn = true;
      response.method = 'env';
    } else {
      response.error = error?.message || String(error);
      response.method = 'none';
    }
  }
  
  res.json(response);
});

// 保存环境变量配置
app.post("/api/save-env-config", (req, res) => {
  const { apiKey, authToken, internetEnv, baseUrl } = req.body;
  
  if (!apiKey && !authToken) {
    return res.status(400).json({ error: '请至少配置 API Key 或 Auth Token' });
  }
  
  const configuredVars: string[] = [];
  
  // 设置环境变量（仅在当前进程有效）
  if (apiKey) {
    process.env.CODEBUDDY_API_KEY = apiKey;
    configuredVars.push('CODEBUDDY_API_KEY');
  }
  if (authToken) {
    process.env.CODEBUDDY_AUTH_TOKEN = authToken;
    configuredVars.push('CODEBUDDY_AUTH_TOKEN');
  }
  if (internetEnv) {
    process.env.CODEBUDDY_INTERNET_ENVIRONMENT = internetEnv;
    configuredVars.push('CODEBUDDY_INTERNET_ENVIRONMENT');
  }
  if (baseUrl) {
    process.env.CODEBUDDY_BASE_URL = baseUrl;
    configuredVars.push('CODEBUDDY_BASE_URL');
  }
  
  // 清除模型缓存，以便重新获取
  cachedModels = [];
  
  res.json({ 
    success: true, 
    message: `已设置: ${configuredVars.join(', ')}`,
    note: '环境变量仅在当前服务器进程有效，重启后需要重新设置'
  });
});

// 获取可用模型列表
app.get("/api/models", async (req, res) => {
  try {
    if (cachedModels.length === 0) {
      console.log("[Models] Creating session to fetch available models...");
      
      const session = await unstable_v2_createSession({ 
        cwd: process.cwd()
      });
      
      console.log("[Models] Session created, calling getAvailableModels()...");
      const models = await session.getAvailableModels();
      console.log("[Models] Got", models.length, "models");
      
      if (models && Array.isArray(models)) {
        cachedModels = models;
      }
    }
    
    res.json({ 
      models: cachedModels.length > 0 ? cachedModels : [
        { modelId: "claude-sonnet-4", name: "Claude Sonnet 4" }
      ],
      defaultModel 
    });
  } catch (error: any) {
    console.error("[Models] Error:", error);
    res.json({
      models: [
        { modelId: "claude-sonnet-4", name: "Claude Sonnet 4" },
        { modelId: "claude-opus-4", name: "Claude Opus 4" }
      ],
      defaultModel,
      error: error?.message || String(error)
    });
  }
});

// ============= 会话 API =============

// 获取所有会话（包含消息数量）
app.get("/api/sessions", (req, res) => {
  try {
    const sessions = db.getAllSessions();
    const sessionsWithMessages = sessions.map(session => {
      const messages = db.getMessagesBySession(session.id);
      return {
        ...session,
        messageCount: messages.length
      };
    });
    res.json({ sessions: sessionsWithMessages });
  } catch (error: any) {
    console.error("[Sessions] Error:", error);
    res.status(500).json({ error: error?.message || "获取会话失败" });
  }
});

// 获取单个会话及其消息
app.get("/api/sessions/:sessionId", (req, res) => {
  try {
    const { sessionId } = req.params;
    const session = db.getSession(sessionId);
    
    if (!session) {
      return res.status(404).json({ error: "会话不存在" });
    }
    
    const messages = db.getMessagesBySession(sessionId);
    
    // 解析 tool_calls JSON
    const parsedMessages = messages.map(msg => ({
      ...msg,
      tool_calls: msg.tool_calls ? JSON.parse(msg.tool_calls) : null
    }));
    
    res.json({ session, messages: parsedMessages });
  } catch (error: any) {
    console.error("[Session] Error:", error);
    res.status(500).json({ error: error?.message || "获取会话失败" });
  }
});

// 创建新会话
app.post("/api/sessions", (req, res) => {
  try {
    const { model = defaultModel, title = "新对话" } = req.body;
    const now = new Date().toISOString();
    
    const session = db.createSession({
      id: uuidv4(),
      title,
      model,
      sdk_session_id: null,
      created_at: now,
      updated_at: now
    });
    
    res.json({ session });
  } catch (error: any) {
    console.error("[Create Session] Error:", error);
    res.status(500).json({ error: error?.message || "创建会话失败" });
  }
});

// 更新会话
app.patch("/api/sessions/:sessionId", (req, res) => {
  try {
    const { sessionId } = req.params;
    const { title, model } = req.body;
    
    const success = db.updateSession(sessionId, { title, model });
    
    if (!success) {
      return res.status(404).json({ error: "会话不存在" });
    }
    
    res.json({ success: true });
  } catch (error: any) {
    console.error("[Update Session] Error:", error);
    res.status(500).json({ error: error?.message || "更新会话失败" });
  }
});

// 删除会话
app.delete("/api/sessions/:sessionId", (req, res) => {
  try {
    const { sessionId } = req.params;
    const success = db.deleteSession(sessionId);
    
    if (!success) {
      return res.status(404).json({ error: "会话不存在" });
    }
    
    res.json({ success: true });
  } catch (error: any) {
    console.error("[Delete Session] Error:", error);
    res.status(500).json({ error: error?.message || "删除会话失败" });
  }
});

// ============= 流水线 / Mod / 扩展层 API =============

/**
 * 流水线实时流（SSE）
 * 前端的 PipelineFlow 面板挂在这里，收到事件就点亮对应节点。
 */
app.get("/api/pipeline/:sessionId/stream", (req, res) => {
  const { sessionId } = req.params;

  res.setHeader("Content-Type", "text/event-stream");
  res.setHeader("Cache-Control", "no-cache");
  res.setHeader("Connection", "keep-alive");
  res.setHeader("X-Accel-Buffering", "no");

  const pipe = pipelineStore.get(sessionId);

  // 先推一份全量快照
  res.write(`data: ${JSON.stringify({ type: "pipeline_snapshot", snapshot: pipe.snapshot() })}\n\n`);

  // 订阅后续增量事件
  const off = pipe.subscribe((ev) => {
    res.write(`data: ${JSON.stringify({ type: "pipeline_event", event: ev })}\n\n`);
  });

  // 扩展层命中也推一份（skills / hooks / MCP）
  const heartbeat = setInterval(() => {
    res.write(`data: ${JSON.stringify({ type: "pipeline_snapshot", snapshot: pipe.snapshot() })}\n\n`);
  }, 4000);

  req.on("close", () => {
    off();
    clearInterval(heartbeat);
  });
});

/** 流水线快照 */
app.get("/api/pipeline/:sessionId", (req, res) => {
  const { sessionId } = req.params;
  res.json(pipelineStore.get(sessionId).snapshot());
});

/** 当前 session 的常驻 mod 列表 + 各自的实时面板 */
app.get("/api/mods/:sessionId", (req, res) => {
  const { sessionId } = req.params;
  const rt = modRegistry.peek(sessionId);
  res.json({
    started: !!rt,
    mods: rt ? rt.listPanels() : [],
    intercepts: rt ? rt.recentIntercepts(20) : [],
  });
});

/** 启停某个 mod */
app.post("/api/mods/:sessionId/toggle", (req, res) => {
  const { sessionId } = req.params;
  const { modId, enabled } = req.body as { modId: string; enabled: boolean };
  const rt = modRegistry.peek(sessionId);
  if (!rt) return res.status(404).json({ error: "会话尚未启动 mod" });
  rt.setEnabled(modId, !!enabled);
  res.json({ success: true, mods: rt.listInfo() });
});

/** 扩展层清单：skills / hooks / MCP */
app.get("/api/extensions", (_req, res) => {
  res.json({
    skills: listSkills(),
    hooks: listHookScripts(),
    mcp: listMcpServers(),
    mods: modRegistry.catalog(),
  });
});

/**
 * 演示一次流转 —— 把一次工具调用真的送过 mod 层。
 * 走的完全是真实链路：真 mod、真裁决、真 pipeline 事件。
 * 用途：不必等模型发话，也能看到 prompt→model→mod→tool call→screen 跑起来。
 */
app.post("/api/pipeline/:sessionId/demo", async (req, res) => {
  const { sessionId } = req.params;
  const scenario = (req.body?.scenario as string) || "force-push";

  const SCENARIOS: Record<string, { toolName: string; input: Record<string, unknown> }> = {
    "force-push": { toolName: "Bash", input: { command: "git push --force origin main" } },
    "rm-root": { toolName: "Bash", input: { command: "rm -rf /" } },
    "hard-reset": { toolName: "Bash", input: { command: "git reset --hard HEAD~3" } },
    "safe-read": { toolName: "Read", input: { file_path: "server/mods/registry.ts" } },
  };

  const picked = SCENARIOS[scenario] ?? SCENARIOS["force-push"];
  const pipe = pipelineStore.get(sessionId);
  const rt = await modRegistry.forSession(sessionId);

  pipe.beginRun();
  pipe.enter("prompt", `演示：${scenario}`);
  pipe.exit("prompt", "交给模型");
  pipe.enter("model", `决定调用 ${picked.toolName}`);
  pipe.exit("model", `tool_use → ${picked.toolName}`);

  const toolUseId = `demo-${Date.now()}`;
  pipe.enter("mod", `mod 检查 ${picked.toolName}`);

  const record = await rt.intercept(picked.toolName, picked.input, { toolUseId, turn: 1 });

  const decision = record.final.decision;
  if (decision === "deny") {
    pipe.blocked("mod", `拦截 ${picked.toolName}`, record.final.reason, record.votes[0]?.modId);
  } else if (decision === "modify") {
    pipe.modified("mod", `改写 ${picked.toolName}`, record.final.reason, record.votes[0]?.modId);
  } else if (decision === "ask") {
    pipe.asked("mod", `先询问 ${picked.toolName}`, record.final.reason, record.votes[0]?.modId);
  } else {
    pipe.exit("mod", "放行");
  }

  pipe.setModActivity({
    toolName: picked.toolName,
    decision,
    reason: record.final.reason,
    before: record.before,
    after: record.after,
  });

  if (decision === "allow" || decision === "modify") {
    pipe.enter("tool", `${picked.toolName} 执行中`);
    pipe.exit("tool", "执行完成");
    await rt.notifyResult({
      toolName: picked.toolName,
      input: record.final.updatedInput ?? picked.input,
      toolUseId,
      sessionId,
      turn: 1,
      result: decision === "modify" ? "(已改写后执行)" : "ok",
      isError: false,
      durationMs: 120,
    });
    pipe.enter("screen", "结果回传屏幕");
    pipe.exit("screen", "渲染完成");
  } else {
    pipe.enter("screen", decision === "deny" ? "被拦截，无结果" : "等待用户确认");
    pipe.exit("screen", "渲染完成");
  }

  pipe.endRun();
  res.json({ ok: true, decision, record });
});

// ============= 聊天 API =============

// 权限响应 API
app.post("/api/permission-response", (req, res) => {
  const { requestId, behavior, message } = req.body;
  
  console.log(`[Permission] Response received: requestId=${requestId}, behavior=${behavior}`);
  
  const pending = pendingPermissions.get(requestId);
  if (!pending) {
    console.log(`[Permission] Request not found: ${requestId}`);
    return res.status(404).json({ error: "权限请求不存在或已超时" });
  }
  
  // 清除请求
  pendingPermissions.delete(requestId);
  
  if (behavior === 'allow') {
    pending.resolve({
      behavior: 'allow',
      updatedInput: pending.input
    });
  } else {
    pending.resolve({
      behavior: 'deny',
      message: message || '用户拒绝了此操作'
    });
  }
  
  res.json({ success: true });
});

// 发送消息并获取流式响应
app.post("/api/chat", async (req, res) => {
  const { sessionId, message, model, systemPrompt, cwd, permissionMode } = req.body;
  
  // 请求日志
  console.log(`\n[Chat] ========== 新请求 ==========`);
  console.log(`[Chat] SessionId: ${sessionId}`);
  console.log(`[Chat] Model: ${model}`);
  console.log(`[Chat] Message: ${message?.slice(0, 100)}${message?.length > 100 ? '...' : ''}`);
  console.log(`[Chat] CWD: ${cwd || 'default'}`);

  if (!message) {
    console.log(`[Chat] 错误: 消息为空`);
    return res.status(400).json({ error: "消息不能为空" });
  }

  // 获取或创建会话
  let session = sessionId ? db.getSession(sessionId) : null;
  const now = new Date().toISOString();
  
  if (!session) {
    // 创建新会话
    console.log(`[Chat] 创建新会话`);
    session = db.createSession({
      id: sessionId || uuidv4(),
      title: message.slice(0, 30) + (message.length > 30 ? '...' : ''),
      model: model || defaultModel,
      sdk_session_id: null,  // 稍后从 SDK 获取
      created_at: now,
      updated_at: now
    });
  } else {
    console.log(`[Chat] 使用现有会话, SDK Session: ${session.sdk_session_id || 'none'}`);
  }

  const selectedModel = model || session.model;
  
  // 获取 SDK session ID（用于恢复对话）
  const sdkSessionId = session.sdk_session_id;

  // 创建用户消息 ID 和助手消息 ID
  const userMessageId = uuidv4();
  const assistantMessageId = uuidv4();

  // 保存用户消息到数据库
  try {
    db.createMessage({
      id: userMessageId,
      session_id: session.id,
      role: 'user',
      content: message,
      model: null,
      created_at: now,
      tool_calls: null
    });
    console.log(`[Chat] 用户消息已保存: ${userMessageId}`);
  } catch (dbError: any) {
    console.error(`[Chat] 保存用户消息失败:`, dbError);
    return res.status(500).json({ error: "保存消息失败", detail: dbError?.message });
  }

  // 设置 SSE 头
  res.setHeader("Content-Type", "text/event-stream");
  res.setHeader("Cache-Control", "no-cache");
  res.setHeader("Connection", "keep-alive");

  // 默认系统提示词
  const defaultSystemPrompt = "你是一个专业的AI助手，善于帮助用户解决各种问题。请用简洁清晰的方式回答问题。";

  // 把可用 skills 拼进 system prompt —— 让模型真的知道可以调用这些 skill
  const finalSystemPrompt = (systemPrompt || defaultSystemPrompt) + skillsPromptFragment();

  // 工作目录：优先使用请求中的 cwd，否则使用当前目录
  const workingDir = cwd || process.cwd();

  try {
    console.log(`[Chat] 调用 SDK query...`);
    console.log(`[Chat] - Model: ${selectedModel}`);
    console.log(`[Chat] - Resume: ${sdkSessionId || 'none'}`);
    console.log(`[Chat] - CWD: ${workingDir}`);
    console.log(`[Chat] - PermissionMode: ${permissionMode || 'default'}`);

    // ① 流水线开跑：prompt 进入
    const pipe = pipelineStore.get(session.id);
    pipe.beginRun();
    pipe.enter('prompt', message.slice(0, 120));
    pipe.exit('prompt', '交给模型');

    // ② mod 常驻启动（同一 session 复用同一批实例，所以能记住东西）
    const modRuntime = await modRegistry.forSession(session.id);

    // ③ 一次性 hook 脚本（1x，跑完就退出）
    void runSessionStartScripts(session.id);

    // ④ 进程内 MCP server
    const mcpConfig = mcpServersFor(session.id);

    // 记录本轮可用 skills（打点到扩展层）
    const skills = listSkills();
    for (const s of skills) {
      pipe.hitExtension('skill', s.name, s.description);
    }

    const toolStartedAt = new Map<string, number>();
    let modTurn = 0;

    /**
     * canUseTool = 视频里 model 与 tool call 之间的拦截点。
     * 所有 mod 在这里依次表决，取最严厉的裁决。
     */
    const canUseTool: CanUseTool = async (toolName, input, options) => {
      console.log(`[Mod] 拦截点 ${toolName}`);

      pipe.enter('mod', `检查 ${toolName}`, safePreview(input));
      const record = await modRuntime.intercept(toolName, input, {
        toolUseId: options.toolUseID,
        turn: ++modTurn,
      });
      const verdict = record.final;

      pipe.setModActivity({
        toolName,
        decision: verdict.decision,
        reason: verdict.reason,
        before: record.before,
        after: record.after,
      });

      // mod 直接拦下 —— 工具根本不会被执行
      if (verdict.decision === 'deny') {
        pipe.blocked('mod', `拦截 ${toolName}`, verdict.reason, record.votes[0]?.modId);
        pipe.enter('screen', `已拦截：${verdict.reason ?? '被 mod 拒绝'}`);
        pipe.exit('screen', '渲染完成');
        return { behavior: 'deny', message: verdict.reason ?? '被 mod 拦截' };
      }

      let finalInput = input;
      if (verdict.decision === 'modify' && verdict.updatedInput) {
        finalInput = { ...input, ...verdict.updatedInput };
        pipe.modified('mod', `改写 ${toolName}`, verdict.reason, record.votes[0]?.modId);
      } else if (verdict.decision === 'ask') {
        pipe.asked('mod', `先询问 ${toolName}`, verdict.reason, record.votes[0]?.modId);
      } else {
        pipe.exit('mod', '放行');
      }

      // bypassPermissions：mod 放行即执行
      if (permissionMode === 'bypassPermissions') {
        pipe.enter('tool', `${toolName} 执行中`);
        toolStartedAt.set(options.toolUseID, Date.now());
        return { behavior: 'allow', updatedInput: finalInput };
      }

      // 其余模式：把（可能被改写过的）调用交给用户确认
      const requestId = uuidv4();
      const permissionRequest = {
        requestId,
        toolUseId: options.toolUseID,
        toolName,
        input: finalInput,
        // 让前端知道这是 mod 的裁决还是普通权限请求
        modDecision: verdict.decision,
        modReason: verdict.reason,
        sessionId: session.id,
        timestamp: Date.now()
      };

      res.write(`data: ${JSON.stringify({
        type: "permission_request",
        ...permissionRequest
      })}\n\n`);

      return new Promise<PermissionResult>((resolve, reject) => {
        const pending: PendingPermission = {
          resolve: (result) => {
            if (result.behavior === 'allow') {
              pipe.enter('tool', `${toolName} 执行中`);
              toolStartedAt.set(options.toolUseID, Date.now());
            } else {
              pipe.blocked('mod', `用户拒绝 ${toolName}`, '用户拒绝执行');
            }
            resolve(result);
          },
          reject,
          toolName,
          input: finalInput,
          sessionId: session.id,
          timestamp: Date.now()
        };

        pendingPermissions.set(requestId, pending);

        setTimeout(() => {
          if (pendingPermissions.has(requestId)) {
            pendingPermissions.delete(requestId);
            console.log(`[Permission] Request timeout: ${requestId}`);
            resolve({ behavior: 'deny', message: '权限请求超时' });
          }
        }, PERMISSION_TIMEOUT);
      });
    };

    // 使用 Query API 发送消息
    const stream = query({
      prompt: message,
      options: {
        cwd: workingDir,
        model: selectedModel,
        maxTurns: 10,
        systemPrompt: finalSystemPrompt,
        permissionMode: permissionMode || 'default',
        canUseTool,
        hooks: buildSdkHooks(session.id),
        ...(Object.keys(mcpConfig).length > 0 ? { mcpServers: mcpConfig } : {}),
        ...(sdkSessionId ? { resume: sdkSessionId } : {})  // 使用 resume 恢复对话
      }
    });

    let fullResponse = "";
    let toolCalls: Array<{ 
      id: string; 
      name: string; 
      input?: Record<string, unknown>;
      status: string; 
      result?: string;
      isError?: boolean;
    }> = [];
    let newSdkSessionId: string | null = null;  // 用于存储 SDK 返回的 session_id

    // 发送会话ID和消息ID
    res.write(`data: ${JSON.stringify({ 
      type: "init", 
      sessionId: session.id, 
      userMessageId, 
      assistantMessageId,
      model: selectedModel 
    })}\n\n`);

    // 当前正在执行的工具 ID（用于匹配 tool_result）
    let currentToolId: string | null = null;
    let modelEntered = false;

    // 处理流式响应
    for await (const msg of stream) {
      console.log("[Stream] Message type:", msg.type, msg);
      
      // 处理 system 消息，获取 SDK 的 session_id
      if (msg.type === "system" && (msg as any).subtype === "init") {
        newSdkSessionId = (msg as any).session_id;
        console.log(`[Stream] Got SDK session_id: ${newSdkSessionId}`);
        
        // 保存 SDK session_id 到数据库（如果是新的）
        if (newSdkSessionId && newSdkSessionId !== sdkSessionId) {
          db.updateSession(session.id, { sdk_session_id: newSdkSessionId });
          console.log(`[Stream] Saved SDK session_id to database`);
        }
      } else if (msg.type === "assistant") {
        const content = msg.message.content;

        if (typeof content === "string") {
          // 模型开始出字 → 点亮 model 节点
          if (!modelEntered) {
            pipe.enter('model', '模型推理中');
            modelEntered = true;
          }
          fullResponse += content;
          res.write(`data: ${JSON.stringify({ type: "text", content })}\n\n`);
        } else if (Array.isArray(content)) {
          for (const block of content) {
            if (block.type === "text") {
              if (!modelEntered) {
                pipe.enter('model', '模型推理中');
                modelEntered = true;
              }
              fullResponse += block.text;
              res.write(`data: ${JSON.stringify({ type: "text", content: block.text })}\n\n`);
            } else if (block.type === "tool_use") {
              // 模型决定调用工具 → model 阶段结束，接下来交给 mod 拦截点
              pipe.exit('model', `决定调用 ${block.name}`);
              modelEntered = false;
              currentToolId = block.id || uuidv4();
              const toolInput = (block as any).input || {};
              console.log(`[Stream] Tool use: id=${currentToolId}, name=${block.name}`);
              console.log(`[Stream] Tool input:`, JSON.stringify(toolInput, null, 2));
              
              const toolCall = { 
                id: currentToolId, 
                name: block.name, 
                input: toolInput,
                status: "running" 
              };
              toolCalls.push(toolCall);
              res.write(`data: ${JSON.stringify({ 
                type: "tool", 
                id: toolCall.id,
                name: toolCall.name,
                input: toolCall.input,
                status: toolCall.status
              })}\n\n`);
            }
          }
        }
      } else if ((msg as any).type === "tool_result") {
        // 处理工具结果（独立的消息类型）
        const msgAny = msg as any;
        const toolId = msgAny.tool_use_id || currentToolId;
        const isError = msgAny.is_error || false;
        const content = msgAny.content;
        
        console.log(`[Stream] Tool result: tool_use_id=${toolId}, is_error=${isError}`);
        console.log(`[Stream] Tool result content type:`, typeof content);
        console.log(`[Stream] Tool result content:`, typeof content === 'string' ? content.slice(0, 500) : JSON.stringify(content, null, 2)?.slice(0, 500));
        
        const tool = toolCalls.find(t => t.id === toolId) || toolCalls[toolCalls.length - 1];
        if (tool) {
          tool.status = isError ? "error" : "completed";
          tool.isError = isError;
          tool.result = typeof content === 'string' 
            ? content 
            : JSON.stringify(content);

          // 工具执行完毕 → 结果回到屏幕
          pipe.exit('tool', `${tool.name} 返回`);
          pipe.enter('screen', isError ? `${tool.name} 出错` : `${tool.name} 结果回传`);
          pipe.exit('screen', '渲染完成');

          // 让常驻 mod 感知结果（gauge 统计、memory 记录都在这里发生）
          const startedAt = toolStartedAt.get(tool.id);
          void modRuntime.notifyResult({
            toolName: tool.name,
            input: tool.input ?? {},
            toolUseId: tool.id,
            sessionId: session.id,
            turn: toolCalls.length,
            result: tool.result,
            isError: !!isError,
            durationMs: startedAt ? Date.now() - startedAt : 0,
          });

          res.write(`data: ${JSON.stringify({ 
            type: "tool_result", 
            toolId: tool.id, 
            content: tool.result,
            isError: isError
          })}\n\n`);
        }
        currentToolId = null;
      } else if (msg.type === "result") {
        // 收尾：模型最后的文字也属于 screen
        if (modelEntered) {
          pipe.exit('model', '最终回复');
          pipe.enter('screen', '最终回复渲染到屏幕');
          pipe.exit('screen', '渲染完成');
        }
        pipe.endRun();
        // 完成时确保所有工具都标记为完成
        toolCalls.forEach(tool => {
          if (tool.status === "running") {
            tool.status = "completed";
            res.write(`data: ${JSON.stringify({ type: "tool_result", toolId: tool.id, content: tool.result || "已完成" })}\n\n`);
          }
        });
        res.write(`data: ${JSON.stringify({
          type: "done",
          duration: (msg as any).duration_ms,
          cost: (msg as any).total_cost_usd,
        })}\n\n`);
      }
    }

    // 保存助手消息到数据库
    db.createMessage({
      id: assistantMessageId,
      session_id: session.id,
      role: 'assistant',
      content: fullResponse,
      model: selectedModel,
      created_at: new Date().toISOString(),
      tool_calls: toolCalls.length > 0 ? JSON.stringify(toolCalls) : null
    });

    // 更新会话标题（如果是第一条消息）
    const messages = db.getMessagesBySession(session.id);
    if (messages.length <= 2) {
      db.updateSession(session.id, { 
        title: message.slice(0, 30) + (message.length > 30 ? '...' : ''),
        model: selectedModel
      });
    }

    console.log(`[Chat] 请求完成 ✓`);
    res.end();
  } catch (error: any) {
    console.error(`\n[Chat] ========== 错误 ==========`);
    console.error(`[Chat] Error Name:`, error?.name);
    console.error(`[Chat] Error Message:`, error?.message);
    console.error(`[Chat] Error Code:`, error?.code);
    console.error(`[Chat] Error Stack:`, error?.stack);
    console.error(`[Chat] Full Error:`, JSON.stringify(error, null, 2));
    
    const errorMessage = error?.message || "处理请求时发生错误";
    res.write(`data: ${JSON.stringify({ type: "error", message: errorMessage })}\n\n`);
    res.end();
  }
});

// 启动服务器
app.listen(PORT, () => {
  console.log(`
╔════════════════════════════════════════════╗
║                                            ║
║     ◉ API 服务器已启动                      ║
║                                            ║
║     地址: http://localhost:${PORT}            ║
║     数据库: SQLite (data/chat.db)          ║
║                                            ║
╚════════════════════════════════════════════╝
  `);
});
