"use client";

import { useEffect, useState } from "react";

type HealthState = "checking" | "online" | "degraded" | "offline";
type ReadyPayload = { ready?: boolean; checks?: Record<string, string> };

const labels: Record<HealthState, string> = {
  checking: "正在檢查服務",
  online: "核心服務就緒",
  degraded: "核心服務需要處理",
  offline: "無法連線核心服務",
};

export function CoreStatus() {
  const [state, setState] = useState<HealthState>("checking");
  const [checks, setChecks] = useState<Record<string, string>>({});
  const [checkedAt, setCheckedAt] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    let current: AbortController | null = null;
    const refresh = async () => {
      current?.abort();
      current = new AbortController();
      try {
        const response = await fetch("http://127.0.0.1:8765/ready", {
          cache: "no-store",
          signal: current.signal,
        });
        if (!response.ok) throw new Error(`Core returned ${response.status}`);
        const payload = (await response.json()) as ReadyPayload;
        if (active) {
          setChecks(payload.checks ?? {});
          setState(payload.ready === true ? "online" : "degraded");
          setCheckedAt(new Date().toLocaleTimeString("zh-TW"));
        }
      } catch {
        if (active && !current.signal.aborted) {
          setState("offline");
          setCheckedAt(new Date().toLocaleTimeString("zh-TW"));
        }
      }
    };
    void refresh();
    const interval = window.setInterval(() => void refresh(), 30_000);
    return () => {
      active = false;
      window.clearInterval(interval);
      current?.abort();
    };
  }, []);

  return (
    <aside className="status-card" aria-live="polite" aria-label="服務健康狀態">
      <div className={`status-orb status-${state}`} aria-hidden="true"><span /></div>
      <div>
        <p className="kicker">CORE API</p>
        <h2>{labels[state]}</h2>
        <p>127.0.0.1:8765</p>
        {checkedAt && <p>上次檢查：{checkedAt}</p>}
      </div>
      <dl>
        <div><dt>資料庫</dt><dd>{state === "offline" ? "無法確認" : checks.database ?? "檢查中"}</dd></div>
        <div><dt>Ollama</dt><dd>{state === "offline" ? "無法確認" : checks.ollama ?? "檢查中"}</dd></div>
        <div><dt>Colibri</dt><dd>{state === "offline" ? "無法確認" : checks.colibri ?? "檢查中"}</dd></div>
        <div><dt>雲端 AI</dt><dd>預設停用</dd></div>
      </dl>
    </aside>
  );
}
