import { Fragment } from 'react';
import type { StageState, ModActivity, StageId } from '../types';

/**
 * PipelineFlow —— 复刻视频里那条流水线：
 *
 *        prompt → model → [MOD] → tool call → screen
 *
 * - 粉色 = 核心（模型本体自带的环节）
 * - 青色 = mod（常驻、可拦截/改写工具调用的扩展层）
 * - 拦截时 tool call 会保持 idle —— 工具根本没被执行
 */

interface Props {
  stages: StageState[];
  modActivity?: ModActivity;
  running: boolean;
}

/** 哪些节点属于 mod 层 */
const MOD_STAGES: StageId[] = ['mod'];

const STAGE_HINT: Record<StageId, string> = {
  prompt: '用户消息进入',
  model: '模型推理 / 决定调用工具',
  mod: '常驻模块：放行 · 改写 · 拦截 · 先询问',
  tool: '工具真正执行',
  screen: '结果渲染到屏幕',
};

const VERDICT_TEXT: Record<string, string> = {
  allow: 'let it through',
  modify: 'changed it',
  deny: 'blocked',
  ask: 'asks first',
};

export function PipelineFlow({ stages, modActivity, running }: Props) {
  const ordered = stages.length
    ? stages
    : (['prompt', 'model', 'mod', 'tool', 'screen'] as StageId[]).map((id) => ({
        id,
        label: id === 'tool' ? 'tool call' : id,
        status: 'idle' as const,
        count: 0,
      }));

  return (
    <div className="pipe-surface rounded-xl p-3.5">
      {/* 标题行 */}
      <div className="flex items-center justify-between mb-3">
        <span className="pipe-title">pipeline</span>
        <span
          className="text-[10px] font-medium px-2 py-0.5 rounded-full"
          style={{
            color: running ? '#2dd4bf' : '#8b8b93',
            background: running ? 'rgba(45,212,191,0.12)' : 'rgba(255,255,255,0.04)',
          }}
        >
          {running ? '● running' : '○ idle'}
        </span>
      </div>

      {/* 垂直流水线 */}
      <div className="flex flex-col items-center">
        {ordered.map((stage, i) => {
          const isMod = MOD_STAGES.includes(stage.id);
          const next = ordered[i + 1];
          const flowing = !!next && next.status === 'active';

          return (
            <Fragment key={stage.id}>
              <StageNode stage={stage} isMod={isMod} modActivity={modActivity} />
              {i < ordered.length - 1 && (
                <div className={`pipe-link ${flowing ? 'is-lit' : ''}`}>
                  {flowing && <span className="pipe-link__packet" />}
                </div>
              )}
            </Fragment>
          );
        })}
      </div>

      {/* 图例 */}
      <div className="flex items-center justify-center gap-4 mt-3 pt-2.5 border-t border-[#22252c]">
        <Legend color="var(--pipe-core)" label="core" />
        <Legend color="var(--pipe-mod)" label="mod" />
      </div>
    </div>
  );
}

function StageNode({
  stage,
  isMod,
  modActivity,
}: {
  stage: StageState;
  isMod: boolean;
  modActivity?: ModActivity;
}) {
  const cls = [
    'pipe-node',
    isMod ? 'pipe-node--mod' : '',
    `is-${stage.status}`,
  ].join(' ');

  return (
    <div className={cls} title={STAGE_HINT[stage.id]}>
      <div className="flex items-center justify-between">
        <span className="pipe-node__label">{stage.label}</span>
        {stage.status === 'active' && <span className="pipe-node__dot" />}
      </div>

      {stage.detail && stage.status !== 'idle' && (
        <div className="pipe-node__detail">{stage.detail}</div>
      )}

      {isMod && modActivity && (
        <span className={`pipe-verdict pipe-verdict--${modActivity.decision}`}>
          {VERDICT_TEXT[modActivity.decision] ?? modActivity.decision}
          {modActivity.toolName ? ` · ${modActivity.toolName}` : ''}
        </span>
      )}

      {isMod && !modActivity && stage.status === 'idle' && (
        <div className="pipe-node__detail">常驻运行，逐条检查工具调用</div>
      )}
    </div>
  );
}

function Legend({ color, label }: { color: string; label: string }) {
  return (
    <span className="flex items-center gap-1.5">
      <span
        className="inline-block w-2.5 h-2.5 rounded-sm"
        style={{ background: color }}
      />
      <span className="text-[10px] text-[color:var(--pipe-muted)]">{label}</span>
    </span>
  );
}
