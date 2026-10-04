import { CoreStatus } from "@/components/core-status";
import { GovernedWorkspace } from "@/components/governed-workspace";

const phases = [
  { label: "Phase 0–13", value: "安全可完成範圍", state: "已驗證" },
  { label: "桌面操作員", value: "Windows Hello source gate", state: "待可見啟用" },
  { label: "外部／LIVE", value: "OAuth、遠端與正式簽章", state: "停用" },
];

export default function CommandCenterPage() {
  return (
    <main className="shell">
      <header className="masthead">
        <div>
          <p className="eyebrow">LOCAL-FIRST CONTROL PLANE</p>
          <h1>KY-JARVIS</h1>
          <p className="subtitle">可稽核的個人情報與工作協調系統</p>
        </div>
        <div className="privacy-pill">
          <span aria-hidden="true" className="privacy-dot" />
          麥克風未啟用
        </div>
      </header>

      <section aria-labelledby="system-heading" className="hero-grid">
        <article className="hero-card">
          <p className="kicker">BALANCED / 32 GB</p>
          <h2 id="system-heading">本機優先，動作有據</h2>
          <p>
            核心服務預設只監聽 127.0.0.1。任何外部寫入、裝置配對、雲端語音或遠端存取都必須另行啟用並通過政策檢查。
          </p>
          <div className="hero-actions">
            <a href="#conversation-panel">開始本機對話</a>
            <span>Asia/Taipei · zh-TW</span>
          </div>
        </article>
        <CoreStatus />
      </section>

      <section aria-label="實作狀態" className="phase-grid">
        {phases.map((phase) => (
          <article className="phase-card" key={phase.label}>
            <p>{phase.label}</p>
            <h2>{phase.value}</h2>
            <span>{phase.state}</span>
          </article>
        ))}
      </section>

      <GovernedWorkspace />

      <section className="timeline" aria-labelledby="timeline-heading">
        <div className="section-heading">
          <div>
            <p className="eyebrow">AUDIT TIMELINE</p>
            <h2 id="timeline-heading">目前里程碑</h2>
          </div>
          <span>只顯示已驗證事實</span>
        </div>
        <ol>
          <li>
            <time>2026-09-02</time>
            <div>
              <strong>本機與單一 Android bounded QA</strong>
              <p>本機模型、雙向文字、真人 PTT、配對與一次 no-op 生物辨識簽章已有明確範圍的證據。</p>
            </div>
          </li>
          <li>
            <time>2026-09-03</time>
            <div>
              <strong>安全硬化與 unsigned packages</strong>
              <p>Windows Hello action grant、Windows／Android packages、掃描、SBOM、備份與隔離還原 gates 已驗證。</p>
            </div>
          </li>
          <li>
            <time>下一步</time>
            <div>
              <strong>只執行明確人工 Gate</strong>
              <p>可見 Windows Hello 啟用、durable state、正式簽章、LIVE providers 與剩餘實機矩陣仍不自動執行。</p>
            </div>
          </li>
        </ol>
      </section>
    </main>
  );
}
