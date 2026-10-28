import { useState, useRef, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { GitFork } from 'lucide-react';
import { Model, Session, PermissionMode, CustomAgent, PermissionRequest } from '../types';
import { NewChatView } from '../components/NewChatView';
import { ChatMessages } from '../components/ChatMessages';
import { ChatInput } from '../components/ChatInput';
import { PipelineSidebar } from '../components/PipelineSidebar';
import { usePipeline } from '../hooks/usePipeline';

interface ChatPageProps {
  currentSession: Session | undefined;
  sessionId: string | null;
  models: Model[];
  selectedModel: string;
  agents: CustomAgent[];
  isLoading: boolean;
  inputValue: string;
  permissionRequest: PermissionRequest | null;
  permissionMode: PermissionMode;
  onSendMessage: (message: string, newChatOptions?: NewChatOptions, onNavigate?: (path: string) => void) => void;
  onStop: () => void;
  onInputChange: (value: string) => void;
  onModelChange: (modelId: string) => void;
  onPermissionAllow: () => void;
  onPermissionDeny: () => void;
  onPermissionModeChange: (mode: PermissionMode) => void;
}

interface NewChatOptions {
  agentId: string;
  cwd: string;
  permissionMode: PermissionMode;
}

export function ChatPage({
  currentSession,
  sessionId,
  models,
  selectedModel,
  agents,
  isLoading,
  inputValue,
  permissionRequest,
  permissionMode,
  onSendMessage,
  onStop,
  onInputChange,
  onModelChange,
  onPermissionAllow,
  onPermissionDeny,
  onPermissionModeChange,
}: ChatPageProps) {
  const navigate = useNavigate();
  const messagesEndRef = useRef<HTMLDivElement>(null);
  
  // 新对话页面状态
  const [newChatAgentId, setNewChatAgentId] = useState('default');
  const [newChatCwd, setNewChatCwd] = useState('');

  // 流水线面板
  const [pipelineOpen, setPipelineOpen] = useState(true);
  const pipeline = usePipeline(sessionId);

  // 自动滚动到底部
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [currentSession?.messages]);

  // 处理发送消息
  const handleSend = useCallback((message: string) => {
    if (!currentSession) {
      // 新对话
      onSendMessage(message, {
        agentId: newChatAgentId,
        cwd: newChatCwd,
        permissionMode: permissionMode,
      }, (path) => {
        // 重置新对话选项
        setNewChatAgentId('default');
        setNewChatCwd('');
        navigate(path);
      });
    } else {
      onSendMessage(message);
    }
  }, [currentSession, newChatAgentId, newChatCwd, permissionMode, onSendMessage, navigate]);

  const showNewChatView = !currentSession || currentSession.messages.length === 0;

  return (
    <div className="flex flex-1 min-h-0">
      {/* 聊天主列 */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* 流水线开关 */}
        <div className="flex items-center justify-end px-5 pt-2.5">
          <button
            onClick={() => setPipelineOpen((v) => !v)}
            className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[12px] transition"
            style={{
              color: pipelineOpen ? 'var(--td-brand-color)' : 'var(--td-text-color-secondary)',
              background: pipelineOpen ? 'var(--td-brand-color-light)' : 'transparent',
            }}
            title="显示 / 隐藏 prompt → model → mod → tool call → screen 流水线"
          >
            <GitFork size={13} />
            流水线
          </button>
        </div>

        {/* 消息区域 */}
        <div className="flex-1 overflow-y-auto p-6">
          {showNewChatView ? (
            <NewChatView
              agents={agents}
              models={models}
              selectedModel={selectedModel}
              newChatAgentId={newChatAgentId}
              newChatCwd={newChatCwd}
              newChatPermissionMode={permissionMode}
              onSelectModel={onModelChange}
              onSelectAgent={setNewChatAgentId}
              onSetCwd={setNewChatCwd}
              onSetPermissionMode={onPermissionModeChange}
            />
          ) : (
            <ChatMessages
              messages={currentSession!.messages}
              models={models}
              messagesEndRef={messagesEndRef}
              permissionRequest={permissionRequest}
              onPermissionAllow={onPermissionAllow}
              onPermissionDeny={onPermissionDeny}
            />
          )}
        </div>

        {/* 输入区域 */}
        <ChatInput
          inputValue={inputValue}
          selectedModel={selectedModel}
          models={models}
          isLoading={isLoading}
          permissionMode={permissionMode}
          onSend={handleSend}
          onStop={onStop}
          onChange={onInputChange}
          onModelChange={onModelChange}
          onPermissionModeChange={onPermissionModeChange}
        />
      </div>

      {/* 流水线侧栏 */}
      {pipelineOpen && (
        <aside
          className="w-[330px] shrink-0 border-l overflow-y-auto p-3 hidden lg:block"
          style={{ borderColor: 'var(--td-border-level-1-color)' }}
        >
          <PipelineSidebar
            snapshot={pipeline.snapshot}
            mods={pipeline.mods}
            intercepts={pipeline.intercepts}
            inventory={pipeline.inventory}
            connected={pipeline.connected}
            demoRunning={pipeline.demoRunning}
            onRunDemo={pipeline.runDemo}
            onToggleMod={pipeline.toggleMod}
          />
        </aside>
      )}
    </div>
  );
}
