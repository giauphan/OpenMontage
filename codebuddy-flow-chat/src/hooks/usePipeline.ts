import { useState, useEffect, useCallback, useRef } from 'react';
import type {
  PipelineSnapshot,
  ModRuntime,
  InterceptRecord,
  ExtensionInventory,
} from '../types';

/**
 * 订阅流水线的实时状态。
 *
 * 数据来源两条：
 *  1. SSE  /api/pipeline/:sessionId/stream  —— 增量事件（节点点亮/熄灭）
 *  2. REST /api/pipeline/:sessionId         —— 切换会话时的全量快照
 */
export function usePipeline(sessionId: string | null) {
  const sid = sessionId || 'preview';

  const [snapshot, setSnapshot] = useState<PipelineSnapshot | null>(null);
  const [mods, setMods] = useState<ModRuntime[]>([]);
  const [intercepts, setIntercepts] = useState<InterceptRecord[]>([]);
  const [inventory, setInventory] = useState<ExtensionInventory | null>(null);
  const [connected, setConnected] = useState(false);
  const [demoRunning, setDemoRunning] = useState(false);

  // 事件到达时闪一下，用来驱动动画
  const [pulse, setPulse] = useState(0);
  const esRef = useRef<EventSource | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [snapRes, modRes] = await Promise.all([
        fetch(`/api/pipeline/${sid}`),
        fetch(`/api/mods/${sid}`),
      ]);
      if (snapRes.ok) setSnapshot(await snapRes.json());
      if (modRes.ok) {
        const m = await modRes.json();
        setMods(m.mods ?? []);
        setIntercepts(m.intercepts ?? []);
      }
    } catch {
      /* 后端未就绪时静默 */
    }
  }, [sid]);

  // 扩展层清单（全局，只拉一次）
  useEffect(() => {
    let alive = true;
    fetch('/api/extensions')
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (alive && d) setInventory(d);
      })
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, []);

  // 切会话 → 拉全量
  useEffect(() => {
    void refresh();
  }, [refresh]);

  // SSE 订阅
  useEffect(() => {
    const es = new EventSource(`/api/pipeline/${sid}/stream`);
    esRef.current = es;

    es.onopen = () => setConnected(true);
    es.onerror = () => setConnected(false);

    es.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data);
        if (data.type === 'pipeline_snapshot') {
          setSnapshot(data.snapshot);
        } else if (data.type === 'pipeline_event') {
          setConnected(true);
          setPulse((p) => p + 1);
          // 事件来了就顺手把 mod 面板也刷新一次
          void fetch(`/api/mods/${sid}`)
            .then((r) => (r.ok ? r.json() : null))
            .then((m) => {
              if (m) {
                setMods(m.mods ?? []);
                setIntercepts(m.intercepts ?? []);
              }
            })
            .catch(() => undefined);
        }
      } catch {
        /* ignore */
      }
    };

    return () => {
      es.close();
      esRef.current = null;
    };
  }, [sid]);

  /** 跑一次演示流转（真 mod、真裁决） */
  const runDemo = useCallback(
    async (scenario: string) => {
      setDemoRunning(true);
      try {
        await fetch(`/api/pipeline/${sid}/demo`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ scenario }),
        });
        await refresh();
      } catch {
        /* ignore */
      } finally {
        setDemoRunning(false);
      }
    },
    [sid, refresh]
  );

  /** 启停某个 mod */
  const toggleMod = useCallback(
    async (modId: string, enabled: boolean) => {
      try {
        const r = await fetch(`/api/mods/${sid}/toggle`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ modId, enabled }),
        });
        if (r.ok) await refresh();
      } catch {
        /* ignore */
      }
    },
    [sid, refresh]
  );

  return {
    snapshot,
    mods,
    intercepts,
    inventory,
    connected,
    pulse,
    demoRunning,
    runDemo,
    toggleMod,
    refresh,
  };
}
