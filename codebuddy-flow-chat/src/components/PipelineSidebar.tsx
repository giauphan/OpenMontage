import { useState } from 'react';
import { Play, Loader2, Radio, GitCompare } from 'lucide-react';
import { PipelineFlow } from './PipelineFlow';
import { ModPanel } from './ModPanel';
import { ExtensionDock } from './ExtensionDock';
import type { PipelineSnapshot, ModRuntime, InterceptRecord, ExtensionInventory } from '../types';

/**
 * 右侧流水线面板：把流程图、mod 面板、扩展层串在一起。
 */

const SCENARIOS: Array<{ id: string; label: string; hint: string; tone: string }> = [
  { id: 'force-push', label: 'git push --force', hint: 'mod 会改写成 --force-with-lease', tone: '#fbbf24' },
  { id: 'rm-root', label: 'rm -rf /', hint: 'mod 会直接拦下，工具不执行', tone: '#f87171' },
  { id: 'hard-reset', label: 'git reset --hard', hint: 'mod 会先询问用户', tone: '#93c5fd' },
  { id: 'safe-read', label: 'Read 文件', hint: '安全调用，原样放行', tone: '#2dd4bf' },
];

interface Props {
  snapshot: PipelineSnapshot | null;
  mods: ModRuntime[];
  intercepts: InterceptRecord[];
  inventory: ExtensionInventory | null;
  connected: boolean;
  demoRunning: boolean;
  onRunDemo: (scenario: string) => void;
  onToggleMod: (modId: string, enabled: boolean) => void;
}

export function PipelineSidebar({
  snapshot,
  mods,
  intercepts,
  inventory,
  connected,
  demoRunning,
  onRunDemo,
  onToggleMod,
}: Props) {
  const [showLog, setShowLog] = useState(true);

  return (
    <div className="flex flex-col gap-3 pipe-scroll pr-1">
      {/* 状态条 */}
      <div className="flex items-center justify-between px-1">
        <span className="text-[12px] font-semibold" style={{ color: 'var(--td-text-color-primary)' }}>
          流水线
        </span>
        <span className="flex items-center gap-1 text-[10px]" style={{ color: 'var(--td-text-color-secondary)' }}>
          <Radio size={10} className={connected ? 'text-[#2dd4bf]' : 'text-[#8b8b93]'} />
          {connected ? 'live' : 'offline'}
        </span>
      </div>

      {/* 流程图 */}
      <PipelineFlow
        stages={snapshot?.stages ?? []}
        modActivity={snapshot?.modActivity}
        running={!!snapshot?.running}
      />

      {/* 演示一次流转 */}
      <div className="pipe-surface rounded-xl p-3.5">
        <div className="pipe-title mb-2">跑一次流转（走真实 mod）</div>
        <div className="flex flex-col gap-1.5">
          {SCENARIOS.map((s) => (
            <button
              key={s.id}
              disabled={demoRunning}
              onClick={() => onRunDemo(s.id)}
              title={s.hint}
              className="flex items-center justify-between px-2.5 py-1.5 rounded-lg border border-[#24272e] bg-[#14161b] hover:border-[#3a3d46] transition disabled:opacity-50"
            >
              <span
                className="font-mono text-[11px]"
                style={{ color: s.tone }}
              >
                {s.label}
              </span>
              {demoRunning ? (
                <Loader2 size={12} className="animate-spin text-[#8b8b93]" />
              ) : (
                <Play size={11} className="text-[#8b8b93]" />
              )}
            </button>
          ))}
        </div>
      </div>

      {/* mod 面板 */}
      <ModPanel mods={mods} onToggle={onToggleMod} />

      {/* 扩展层 */}
      <ExtensionDock inventory={inventory} recent={snapshot?.extensions ?? []} />

      {/* 拦截明细 */}
      {interceptList(intercepts, showLog, setShowLog)}
    </div>
  );
}

function interceptList(
  intercepts: InterceptRecord[],
  showLog: boolean,
  setShowLog: (v: boolean) => void
) {
  if (!intercepts.length) return null;

  return (
    <div className="pipe-surface rounded-xl p-3.5">
      <button
        className="flex items-center justify-between w-full mb-2"
        onClick={() => setShowLog(!showLog)}
      >
        <span className="pipe-title flex items-center gap-1.5">
          <GitCompare size={11} /> interceptions
        </span>
        <span className="text-[10px] text-[color:var(--pipe-muted)]">
          {intercepts.length}
        </span>
      </button>

      {showLog && (
        <div className="flex flex-col gap-2 max-h-56 pipe-scroll">
          {intercepts.map((r) => (
            <div key={r.toolUseId} className="rounded-lg border border-[#24272e] bg-[#14161b] p-2">
              <div className="flex items-center justify-between">
                <span className="font-mono text-[11px] text-[#ececec]">{r.toolName}</span>
                <span className={`pipe-verdict pipe-verdict--${r.final.decision}`}>
                  {r.final.decision}
                </span>
              </div>

              {r.final.reason && (
                <div className="text-[10px] text-[color:var(--pipe-muted)] mt-1 leading-snug">
                  {r.final.reason}
                </div>
              )}

              {r.changed && r.before && r.after && (
                <div className="mt-1.5 font-mono text-[10px] space-y-0.5">
                  <div className="text-[#f87171] line-through break-all">- {r.before}</div>
                  <div className="text-[#2dd4bf] break-all">+ {r.after}</div>
                </div>
              )}

              <div className="mt-1.5 flex flex-wrap gap-1">
                {r.votes
                  .filter((v) => v.verdict)
                  .map((v) => (
                    <span key={v.modId} className="text-[9.5px] text-[color:var(--pipe-muted)]">
                      {v.modName} → {v.verdict?.decision}
                    </span>
                  ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
