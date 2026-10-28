import { useState } from 'react';
import { Shield, Brain, Gauge, Activity, Hand, Power } from 'lucide-react';
import type { ModRuntime, ModCapabilities } from '../types';

/**
 * ModPanel —— 视频右侧那一列：
 * 每个 mod 常驻运行，并声明自己具备哪些能力
 * （memory / live panel / asks first / guard / gauge）。
 */

const CAP_META: Array<{
  key: keyof ModCapabilities;
  label: string;
  icon: React.ComponentType<any>;
  hint: string;
}> = [
  { key: 'memory', label: 'memory', icon: Brain, hint: '跨整段会话记住状态' },
  { key: 'livePanel', label: 'live panel', icon: Activity, hint: '持续输出实时面板' },
  { key: 'asksFirst', label: 'asks first', icon: Hand, hint: '敏感操作先问用户' },
  { key: 'guard', label: 'guard', icon: Shield, hint: '拦截危险调用' },
  { key: 'gauge', label: 'gauge', icon: Gauge, hint: '产出用量指标' },
];

export function ModPanel({
  mods,
  onToggle,
}: {
  mods: ModRuntime[];
  onToggle?: (modId: string, enabled: boolean) => void;
}) {
  const [enabled, setEnabled] = useState<Record<string, boolean>>({});

  const toggle = (id: string) => {
    const next = !(enabled[id] ?? true);
    setEnabled((p) => ({ ...p, [id]: next }));
    onToggle?.(id, next);
  };

  if (!mods.length) {
    return (
      <div className="pipe-surface rounded-xl p-3.5">
        <div className="pipe-title mb-2">mods</div>
        <div className="text-[11px] text-[color:var(--pipe-muted)]">
          会话开始后 mod 会常驻启动
        </div>
      </div>
    );
  }

  return (
    <div className="pipe-surface rounded-xl p-3.5">
      <div className="flex items-center justify-between mb-2.5">
        <span className="pipe-title">mods · resident</span>
        <span className="text-[10px] text-[color:var(--pipe-muted)]">{mods.length} 个</span>
      </div>

      <div className="flex flex-col gap-2">
        {mods.map((m) => {
          const on = enabled[m.id] ?? true;
          return (
            <div
              key={m.id}
              className="rounded-lg border border-[#24272e] bg-[#14161b] p-2.5"
              style={{ opacity: on ? 1 : 0.5 }}
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="text-[12.5px] font-semibold text-[#ececec] truncate">
                    {m.name}
                  </div>
                  <div className="text-[10.5px] text-[color:var(--pipe-muted)] leading-snug">
                    {m.description}
                  </div>
                </div>
                <button
                  onClick={() => toggle(m.id)}
                  title={on ? '停用这个 mod' : '启用这个 mod'}
                  className="shrink-0 p-1 rounded hover:bg-white/5"
                >
                  <Power
                    size={13}
                    className={on ? 'text-[#2dd4bf]' : 'text-[#6b6f7a]'}
                  />
                </button>
              </div>

              {/* 能力位 */}
              <div className="flex flex-wrap gap-1 mt-2">
                {CAP_META.map(({ key, label, icon: Icon, hint }) => {
                  const has = m.capabilities?.[key];
                  return (
                    <span
                      key={key}
                      className={`pipe-cap ${has ? 'is-on' : ''} inline-flex items-center gap-1`}
                      title={has ? hint : `${label}（未启用）`}
                    >
                      <Icon size={9} />
                      {label}
                    </span>
                  );
                })}
              </div>

              {/* 拦截统计 */}
              {(m.interceptCount > 0 || m.blockCount > 0 || m.modifyCount > 0) && (
                <div className="flex gap-3 mt-2 text-[10px] text-[color:var(--pipe-muted)]">
                  <span>检查 {m.interceptCount}</span>
                  {m.modifyCount > 0 && (
                    <span className="text-[#fbbf24]">改写 {m.modifyCount}</span>
                  )}
                  {m.blockCount > 0 && (
                    <span className="text-[#f87171]">拦截 {m.blockCount}</span>
                  )}
                </div>
              )}

              {/* 实时面板 */}
              {m.panel?.metrics && m.panel.metrics.length > 0 && (
                <div className="mt-2 pt-2 border-t border-[#22252c]">
                  {m.panel.metrics.map((mt) => (
                    <div className="pipe-metric" key={mt.label}>
                      <span>{mt.label}</span>
                      <b>{mt.value}</b>
                    </div>
                  ))}
                </div>
              )}

              {m.panel?.events && m.panel.events.length > 0 && (
                <div className="mt-1.5 pt-1.5 border-t border-[#22252c]">
                  {m.panel.events.slice(0, 4).map((e, i) => (
                    <div
                      key={`${e.at}-${i}`}
                      className={`pipe-logline pipe-logline--${e.level}`}
                      title={e.message}
                    >
                      {e.message}
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
