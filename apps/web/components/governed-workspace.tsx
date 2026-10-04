"use client";

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import Image from "next/image";
import QRCode from "qrcode";
import {
  loadOperatorStatus,
  OperatorStatus,
  registerDesktopOperator,
  requestOperatorGrant,
} from "@/lib/operator-authorization";

const API = "http://127.0.0.1:8765/api/v1";
const intentHeaders = {
  "Content-Type": "application/json",
  "X-KY-JARVIS-Intent": "ui-v1",
};

function encodePcm16(chunks: Float32Array[], inputSampleRate: number): ArrayBuffer {
  const sourceLength = chunks.reduce((total, chunk) => total + chunk.length, 0);
  const source = new Float32Array(sourceLength);
  let offset = 0;
  for (const chunk of chunks) {
    source.set(chunk, offset);
    offset += chunk.length;
  }
  const targetSampleRate = 16_000;
  const ratio = inputSampleRate / targetSampleRate;
  const output = new Int16Array(Math.floor(source.length / ratio));
  for (let index = 0; index < output.length; index += 1) {
    const sample = Math.max(-1, Math.min(1, source[Math.floor(index * ratio)] ?? 0));
    output[index] = sample < 0 ? sample * 0x8000 : sample * 0x7fff;
  }
  return output.buffer as ArrayBuffer;
}

type Memory = {
  id: string;
  content: string;
  memory_type: string;
  source_type: string;
  status: string;
  authority: number;
  injection_signals: string[];
};

type Connector = {
  name: string;
  state: string;
  reason?: string;
};

type ProjectPlan = {
  project_id: string;
  title: string;
  requirements: { id: string; statement: string }[];
  decisions: { id: string; title: string; rationale: string; status: string }[];
  work_items: { id: string; title: string; source_requirement_ids: string[] }[];
  risks: string[];
  approval_required: boolean;
};

type ScheduleProposal = {
  id: string;
  work_item_id: string;
  timezone: string;
  blocks: { start: string; end: string }[];
  requires_approval: boolean;
};

type ApprovalRequest = {
  id: string;
  title: string;
  reason: string;
  target: string;
  risk_level: string;
  side_effects: string[];
  rollback_method: string;
  expires_at: string;
  state: "pending" | "approved" | "denied" | "expired" | "consumed";
  tool_name: string;
  preview: Record<string, unknown>;
};

type Device = {
  id: string;
  display_name: string;
  trust_state: string;
  last_seen_at: string | null;
};

type PairingOffer = {
  session_id: string;
  one_time_secret: string;
  comparison_code: string;
  server_fingerprint: string;
  expires_at: string;
};

type ChatReply = {
  summary: string;
  steps: string[];
  requires_approval: boolean;
  route: string;
};

type AgentRun = {
  run_id: string;
  status: "running" | "completed" | "failed" | "cancelled";
  started_at: string;
  finished_at: string | null;
  error: string | null;
  result: ChatReply | null;
};

type VoiceTurnResponse = {
  transcript: { text: string; confidence: number | null };
  reply: ChatReply;
};

type MobileCommand = {
  id: string;
  device_id: string;
  title: string;
  body: string;
  state: string;
  created_at: string;
  acknowledged_at: string | null;
};

export function GovernedWorkspace() {
  const [memories, setMemories] = useState<Memory[]>([]);
  const [connectors, setConnectors] = useState<Connector[]>([]);
  const [memoryText, setMemoryText] = useState("");
  const [projectText, setProjectText] = useState("");
  const [plan, setPlan] = useState<ProjectPlan | null>(null);
  const [schedule, setSchedule] = useState<ScheduleProposal | null>(null);
  const [approvals, setApprovals] = useState<ApprovalRequest[]>([]);
  const [approvalTokens, setApprovalTokens] = useState<Record<string, string>>({});
  const [operatorStatus, setOperatorStatus] = useState<OperatorStatus | null>(null);
  const [operatorEnrollmentSecret, setOperatorEnrollmentSecret] = useState("");
  const [devices, setDevices] = useState<Device[]>([]);
  const [pairing, setPairing] = useState<PairingOffer | null>(null);
  const [pairingQr, setPairingQr] = useState<string | null>(null);
  const [comparisonCode, setComparisonCode] = useState("");
  const [chatText, setChatText] = useState("");
  const [chatReply, setChatReply] = useState<ChatReply | null>(null);
  const [agentRun, setAgentRun] = useState<AgentRun | null>(null);
  const runStream = useRef<EventSource | null>(null);
  const [isRecording, setIsRecording] = useState(false);
  const [ttsEnabled, setTtsEnabled] = useState(false);
  const pttHeld = useRef(false);
  const audioContext = useRef<AudioContext | null>(null);
  const microphoneStream = useRef<MediaStream | null>(null);
  const microphoneProcessor = useRef<ScriptProcessorNode | null>(null);
  const audioChunks = useRef<Float32Array[]>([]);
  const pttTimeout = useRef<number | null>(null);
  const [commandTitle, setCommandTitle] = useState("Windows 測試訊息");
  const [commandBody, setCommandBody] = useState("");
  const [commands, setCommands] = useState<MobileCommand[]>([]);
  const [connectionState, setConnectionState] = useState<"checking" | "online" | "offline">("checking");
  const [notice, setNotice] = useState("等待核心資料");

  const refresh = useCallback(async () => {
    try {
      const [memoryResponse, connectorResponse, deviceResponse, commandResponse, approvalResponse] = await Promise.all([
        fetch(`${API}/memories`, { cache: "no-store" }),
        fetch(`${API}/connectors`, { cache: "no-store" }),
        fetch(`${API}/devices`, { cache: "no-store" }),
        fetch(`${API}/mobile/commands`, { cache: "no-store" }),
        fetch(`${API}/approvals`, { cache: "no-store" }),
      ]);
      if (!memoryResponse.ok || !connectorResponse.ok || !deviceResponse.ok || !commandResponse.ok || !approvalResponse.ok) {
        throw new Error("Core unavailable");
      }
      setMemories((await memoryResponse.json()) as Memory[]);
      setConnectors((await connectorResponse.json()) as Connector[]);
      setDevices((await deviceResponse.json()) as Device[]);
      setCommands((await commandResponse.json()) as MobileCommand[]);
      setApprovals((await approvalResponse.json()) as ApprovalRequest[]);
      setConnectionState("online");
      setNotice("資料已同步；外部寫入仍需核准");
    } catch {
      setConnectionState("offline");
      setNotice("核心未啟動；介面維持唯讀離線狀態");
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void Promise.all([
      fetch(`${API}/memories`, { cache: "no-store", signal: controller.signal }),
      fetch(`${API}/connectors`, { cache: "no-store", signal: controller.signal }),
      fetch(`${API}/devices`, { cache: "no-store", signal: controller.signal }),
      fetch(`${API}/mobile/commands`, { cache: "no-store", signal: controller.signal }),
      fetch(`${API}/approvals`, { cache: "no-store", signal: controller.signal }),
    ])
      .then(async ([memoryResponse, connectorResponse, deviceResponse, commandResponse, approvalResponse]) => {
        if (!memoryResponse.ok || !connectorResponse.ok || !deviceResponse.ok || !commandResponse.ok || !approvalResponse.ok) {
          throw new Error("Core unavailable");
        }
        setMemories((await memoryResponse.json()) as Memory[]);
        setConnectors((await connectorResponse.json()) as Connector[]);
        setDevices((await deviceResponse.json()) as Device[]);
        setCommands((await commandResponse.json()) as MobileCommand[]);
        setApprovals((await approvalResponse.json()) as ApprovalRequest[]);
        setConnectionState("online");
        setNotice("資料已同步；外部寫入仍需核准");
      })
      .catch(() => {
        if (!controller.signal.aborted) setConnectionState("offline");
        if (!controller.signal.aborted) setNotice("核心未啟動；介面維持唯讀離線狀態");
      });
    return () => controller.abort();
  }, []);

  useEffect(() => () => {
    runStream.current?.close();
    if (pttTimeout.current !== null) window.clearTimeout(pttTimeout.current);
    microphoneProcessor.current?.disconnect();
    microphoneStream.current?.getTracks().forEach((track) => track.stop());
    void audioContext.current?.close();
  }, []);

  useEffect(() => {
    void loadOperatorStatus()
      .then(setOperatorStatus)
      .catch(() => setOperatorStatus(null));
  }, []);

  async function operatorAuthorizedFetch(
    method: "POST" | "DELETE",
    path: string,
    body: Record<string, unknown>,
  ) {
    const grant = await requestOperatorGrant({ method, path, body });
    const request: RequestInit = {
      method,
      headers: {
        ...intentHeaders,
        "X-KY-JARVIS-Operator-Grant": grant,
      },
    };
    if (method !== "DELETE") request.body = JSON.stringify(body);
    return fetch(`${API}${path.slice("/api/v1".length)}`, request);
  }

  async function enrollDesktopOperator() {
    const secret = operatorEnrollmentSecret;
    setOperatorEnrollmentSecret("");
    try {
      const status = await registerDesktopOperator(secret);
      setOperatorStatus(status);
      setNotice("Windows Hello 操作員已註冊；高影響桌面動作會逐次要求驗證");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Windows Hello 註冊失敗");
    }
  }

  async function proposeMemory(event: FormEvent) {
    event.preventDefault();
    const response = await fetch(`${API}/memories`, {
      method: "POST",
      headers: intentHeaders,
      body: JSON.stringify({
        memory_type: "preference",
        content: memoryText,
        source_type: "user_message",
      }),
    });
    if (!response.ok) {
      setNotice("記憶草稿建立失敗");
      return;
    }
    setMemoryText("");
    await refresh();
  }

  async function forgetMemory(id: string) {
    let response: Response;
    try {
      response = await operatorAuthorizedFetch("DELETE", `/api/v1/memories/${id}`, {});
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Windows Hello 驗證失敗");
      return;
    }
    setNotice(response.ok ? "記憶已標記刪除並保留稽核軌跡" : "刪除失敗");
    await refresh();
  }

  async function approveMemory(id: string) {
    let response: Response;
    try {
      response = await operatorAuthorizedFetch(
        "POST",
        `/api/v1/memories/${id}/approve`,
        {},
      );
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Windows Hello 驗證失敗");
      return;
    }
    setNotice(response.ok ? "記憶候選已由 Windows Hello 操作員核准" : "核准失敗");
    await refresh();
  }

  async function previewProject(event: FormEvent) {
    event.preventDefault();
    const response = await fetch(`${API}/projects/preview`, {
      method: "POST",
      headers: intentHeaders,
      body: JSON.stringify({
        request: projectText,
        source_message_id: crypto.randomUUID(),
      }),
    });
    if (!response.ok) {
      setNotice("計畫預覽建立失敗");
      return;
    }
    setPlan((await response.json()) as ProjectPlan);
    setSchedule(null);
    setNotice("僅建立預覽；尚未建立外部工作項目");
  }

  async function previewSchedule() {
    const workItem = plan?.work_items[0];
    if (!workItem) return;
    const earliest = new Date();
    const deadline = new Date(earliest.getTime() + 7 * 24 * 60 * 60 * 1000);
    const response = await fetch(`${API}/schedules/preview`, {
      method: "POST",
      headers: intentHeaders,
      body: JSON.stringify({
        work_item_id: workItem.id,
        duration_minutes: 60,
        earliest: earliest.toISOString(),
        deadline: deadline.toISOString(),
        busy: [],
        timezone: "Asia/Taipei",
      }),
    });
    if (!response.ok) {
      setNotice("無法在期限內建立無衝突排程");
      return;
    }
    setSchedule((await response.json()) as ScheduleProposal);
    setNotice("排程僅為內部預覽；Calendar 尚未寫入");
  }

  async function requestCalendarApproval() {
    const block = schedule?.blocks[0];
    if (!schedule || !block || !plan) return;
    const response = await fetch(`${API}/tool-executions`, {
      method: "POST",
      headers: intentHeaders,
      body: JSON.stringify({
        tool_name: "calendar.create.fake",
        payload: {
          title: plan.title,
          start: block.start,
          end: block.end,
          timezone: schedule.timezone,
        },
        idempotency_key: `schedule-${schedule.id}`,
        reason: "使用者要求將審查過的時段寫入 fake Calendar fixture",
        originating_request: plan.requirements[0]?.statement ?? plan.title,
        rollback_method: "刪除 fake provider event",
      }),
    });
    if (!response.ok) {
      setNotice("無法建立工具核准請求");
      return;
    }
    const created = (await response.json()) as {
      approval: ApprovalRequest;
      decision_token: string;
    };
    setApprovalTokens((current) => ({
      ...current,
      [created.approval.id]: created.decision_token,
    }));
    setNotice("工具執行已暫停，等待 approval inbox 決定");
    await refresh();
  }

  async function resumeToolApproval(approval: ApprovalRequest, approved: boolean) {
    const token = approvalTokens[approval.id];
    if (!token) {
      setNotice("此核准 token 不在目前瀏覽器工作階段，保持 fail-closed");
      return;
    }
    const path = `/api/v1/tool-executions/${approval.id}/resume`;
    const body = { token, approved };
    let response: Response;
    try {
      response = await operatorAuthorizedFetch("POST", path, body);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Windows Hello 驗證失敗");
      return;
    }
    if (!response.ok) {
      setNotice("核准已失效、內容改變或已被使用");
      return;
    }
    setApprovalTokens((current) => {
      const next = { ...current };
      delete next[approval.id];
      return next;
    });
    setNotice(approved ? "核准已消耗，fake provider 僅執行一次" : "工具執行已拒絕");
    await refresh();
  }

  async function startStreamingChat(event: FormEvent) {
    event.preventDefault();
    setNotice("Windows 本機模型串流已啟動…");
    setChatReply(null);
    const response = await fetch(`${API}/runs`, {
      method: "POST",
      headers: intentHeaders,
      body: JSON.stringify({ message: chatText, thread_id: "web-main" }),
    });
    if (!response.ok) {
      const error = (await response.json().catch(() => ({}))) as { detail?: string };
      setNotice(error.detail ?? "本機模型回覆失敗");
      return;
    }
    const started = (await response.json()) as AgentRun;
    setAgentRun(started);
    setChatText("");
    runStream.current?.close();
    const source = new EventSource(`${API}/runs/${started.run_id}/events`);
    runStream.current = source;
    source.onmessage = (message) => {
      const update = JSON.parse(message.data) as AgentRun;
      setAgentRun(update);
      if (update.status === "completed") {
        if (update.result) setChatReply(update.result);
        setNotice("Windows 已取得本機模型回覆");
        source.close();
      } else if (update.status === "failed" || update.status === "cancelled") {
        setNotice(update.status === "cancelled" ? "本機模型執行已取消" : "本機模型執行失敗");
        source.close();
      }
    };
    source.onerror = () => {
      source.close();
      setNotice("串流中斷；可用 run history 查詢最終狀態");
    };
  }

  async function cancelStreamingRun() {
    if (!agentRun || agentRun.status !== "running") return;
    const response = await fetch(`${API}/runs/${agentRun.run_id}/cancel`, {
      method: "POST",
      headers: intentHeaders,
    });
    setNotice(response.ok ? "已要求取消本機模型執行" : "執行已完成，無法取消");
  }

  async function startDesktopPtt() {
    if (isRecording || !navigator.mediaDevices?.getUserMedia) return;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
      });
      if (!pttHeld.current) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      const context = new AudioContext();
      const source = context.createMediaStreamSource(stream);
      const processor = context.createScriptProcessor(4096, 1, 1);
      audioChunks.current = [];
      processor.onaudioprocess = (event) => {
        if (pttHeld.current) audioChunks.current.push(new Float32Array(event.inputBuffer.getChannelData(0)));
      };
      source.connect(processor);
      processor.connect(context.destination);
      audioContext.current = context;
      microphoneStream.current = stream;
      microphoneProcessor.current = processor;
      setIsRecording(true);
      setNotice("麥克風只在按住期間擷取；放開即送出 final audio");
      pttTimeout.current = window.setTimeout(() => {
        pttHeld.current = false;
        void stopDesktopPtt();
      }, 30_000);
    } catch {
      pttHeld.current = false;
      setNotice("麥克風權限未允許；文字對話仍可使用");
    }
  }

  async function stopDesktopPtt() {
    if (pttTimeout.current !== null) window.clearTimeout(pttTimeout.current);
    pttTimeout.current = null;
    const context = audioContext.current;
    const chunks = audioChunks.current;
    microphoneProcessor.current?.disconnect();
    microphoneStream.current?.getTracks().forEach((track) => track.stop());
    microphoneProcessor.current = null;
    microphoneStream.current = null;
    audioContext.current = null;
    audioChunks.current = [];
    setIsRecording(false);
    if (context) await context.close();
    if (!context || chunks.length === 0) return;
    const pcm16 = encodePcm16(chunks, context.sampleRate);
    setNotice("本機 STT 與 bounded agent 處理中…");
    const response = await fetch(`${API}/voice-turns`, {
      method: "POST",
      headers: {
        ...intentHeaders,
        "Content-Type": "application/octet-stream",
        "X-Audio-Sample-Rate": "16000",
        "X-Audio-Locale": "zh-TW",
      },
      body: new Blob([pcm16], { type: "application/octet-stream" }),
    });
    if (!response.ok) {
      const error = (await response.json().catch(() => ({}))) as { detail?: string };
      setNotice(error.detail ?? "桌面語音處理失敗；可繼續使用文字");
      return;
    }
    const turn = (await response.json()) as VoiceTurnResponse;
    setChatReply(turn.reply);
    setNotice(`Final transcript：${turn.transcript.text}`);
    if (ttsEnabled && "speechSynthesis" in window) {
      window.speechSynthesis.cancel();
      const utterance = new SpeechSynthesisUtterance(turn.reply.summary);
      utterance.lang = "zh-TW";
      window.speechSynthesis.speak(utterance);
    }
  }

  async function sendMobileCommand(event: FormEvent) {
    event.preventDefault();
    const target = devices.find((device) => device.trust_state === "trusted");
    if (!target) {
      setNotice("沒有可派送的受信任 Android 裝置");
      return;
    }
    const response = await fetch(`${API}/mobile/commands`, {
      method: "POST",
      headers: intentHeaders,
      body: JSON.stringify({
        device_id: target.id,
        title: commandTitle,
        body: commandBody,
        idempotency_key: crypto.randomUUID(),
      }),
    });
    if (!response.ok) {
      setNotice("手機訊息派送失敗");
      return;
    }
    setCommandBody("");
    setNotice("訊息已排入受信任手機 channel，等待顯示回執");
    await refresh();
  }

  async function beginPairing() {
    const body = { server_fingerprint: "development-loopback-core-api" };
    let response: Response;
    try {
      response = await operatorAuthorizedFetch(
        "POST",
        "/api/v1/device-pairings",
        body,
      );
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Windows Hello 驗證失敗");
      return;
    }
    if (!response.ok) {
      setNotice("無法建立配對工作階段");
      return;
    }
    const offer = (await response.json()) as PairingOffer;
    const query = new URLSearchParams({
      session_id: offer.session_id,
      secret: offer.one_time_secret,
      comparison_code: offer.comparison_code,
      fingerprint: offer.server_fingerprint,
      expires_at: offer.expires_at,
    });
    setPairing(offer);
    setPairingQr(
      await QRCode.toDataURL(`kyjarvis://pair?${query.toString()}`, {
        errorCorrectionLevel: "H",
        margin: 1,
        width: 240,
      }),
    );
    setNotice("配對 QR 已建立；五分鐘後失效且只能使用一次");
  }

  async function confirmDevice(deviceId: string) {
    const body = { comparison_code: comparisonCode };
    let response: Response;
    try {
      response = await operatorAuthorizedFetch(
        "POST",
        `/api/v1/devices/${deviceId}/confirm`,
        body,
      );
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Windows Hello 驗證失敗");
      return;
    }
    setNotice(response.ok ? "桌面已確認；請回手機領取一次性 session" : "比對碼不符或已失效");
    if (response.ok) {
      setComparisonCode("");
      setPairing(null);
      setPairingQr(null);
      await refresh();
    }
  }

  async function revokeDevice(deviceId: string) {
    let response: Response;
    try {
      response = await operatorAuthorizedFetch(
        "DELETE",
        `/api/v1/devices/${deviceId}`,
        {},
      );
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Windows Hello 驗證失敗");
      return;
    }
    setNotice(response.ok ? "裝置、token family 與待處理授權已撤銷" : "撤銷失敗");
    await refresh();
  }

  return (
    <section className="workspace" aria-labelledby="workspace-heading">
      <div className="section-heading">
        <div>
          <p className="eyebrow">GOVERNED WORKSPACE</p>
          <h2 id="workspace-heading">記憶、計畫與連接器</h2>
        </div>
        <span aria-live="polite">{notice}</span>
      </div>

      <nav className="workspace-nav" aria-label="工作區導覽">
        <a href="#conversation-panel">對話與任務</a>
        <a href="#memory-panel">記憶</a>
        <a href="#project-panel">專案</a>
        <a href="#approval-panel">待核准</a>
        <a href="#device-panel">裝置</a>
      </nav>
      {connectionState !== "online" && (
        <div className="connection-banner" role="status">
          {connectionState === "checking" ? "正在載入工作區…" : "核心離線；畫面資料可能已過期，操作暫停。"}
          <button type="button" onClick={() => void refresh()}>重新檢查</button>
        </div>
      )}
      <div className="workspace-grid">
        <article className="workspace-panel" id="conversation-panel">
          <div className="panel-title">
            <div>
              <p className="kicker">LOCAL CONVERSATION</p>
              <h3>Windows 本機對話</h3>
            </div>
            <span>結構化 · 不直接執行工具</span>
          </div>
          <form onSubmit={startStreamingChat}>
            <label htmlFor="chat">傳給本機模型</label>
            <textarea
              id="chat"
              onChange={(event) => setChatText(event.target.value)}
              placeholder="例如：為今天的雙向 QA 建立安全檢查步驟"
              required
              value={chatText}
            />
            <button disabled={agentRun?.status === "running"} type="submit">啟動串流對話</button>
            {agentRun?.status === "running" && (
              <button className="quiet" onClick={() => void cancelStreamingRun()} type="button">
                取消執行
              </button>
            )}
          </form>
          <div className="plan-preview">
            <button
              aria-pressed={isRecording}
              onPointerCancel={() => {
                pttHeld.current = false;
                void stopDesktopPtt();
              }}
              onPointerDown={(event) => {
                event.currentTarget.setPointerCapture(event.pointerId);
                pttHeld.current = true;
                void startDesktopPtt();
              }}
              onPointerUp={() => {
                pttHeld.current = false;
                void stopDesktopPtt();
              }}
              type="button"
            >
              {isRecording ? "錄音中，放開送出" : "按住說話"}
            </button>
            <label>
              <input
                checked={ttsEnabled}
                onChange={(event) => setTtsEnabled(event.target.checked)}
                type="checkbox"
              />
              明確啟用 Windows TTS 朗讀摘要
            </label>
            <span className={isRecording ? "warning" : ""}>
              麥克風：{isRecording ? "使用中" : "關閉"} · wake word：停用
            </span>
          </div>
          {agentRun && (
            <p aria-live="polite">
              Run {agentRun.run_id.slice(0, 8)} · {agentRun.status}
              {agentRun.error ? ` · ${agentRun.error}` : ""}
            </p>
          )}
          {chatReply && (
            <div className="plan-preview">
              <strong>{chatReply.summary}</strong>
              <ol>{chatReply.steps.map((step) => <li key={step}>{step}</li>)}</ol>
              {chatReply.requires_approval && <span className="warning">後續動作需另行核准</span>}
            </div>
          )}
        </article>

        <article className="workspace-panel">
          <div className="panel-title">
            <div>
              <p className="kicker">WINDOWS → ANDROID</p>
              <h3>安全手機訊息</h3>
            </div>
            <span>前景同步 + 顯示回執</span>
          </div>
          <form onSubmit={sendMobileCommand}>
            <label htmlFor="command-title">標題</label>
            <input
              id="command-title"
              onChange={(event) => setCommandTitle(event.target.value)}
              required
              value={commandTitle}
            />
            <label htmlFor="command-body">只顯示內容，不執行指令</label>
            <textarea
              id="command-body"
              onChange={(event) => setCommandBody(event.target.value)}
              placeholder="輸入要在已配對手機上顯示的 QA 訊息"
              required
              value={commandBody}
            />
            <button
              disabled={!devices.some((device) => device.trust_state === "trusted")}
              type="submit"
            >
              傳送到手機
            </button>
          </form>
          <ul className="record-list">
            {commands.slice(-5).reverse().map((command) => (
              <li key={command.id}>
                <div>
                  <strong>{command.title}</strong>
                  <p>{command.state} · {command.acknowledged_at ? "手機已顯示" : "等待回執"}</p>
                </div>
              </li>
            ))}
          </ul>
        </article>

        <article className="workspace-panel" id="memory-panel">
          <div className="panel-title">
            <div>
              <p className="kicker">MEMORY</p>
              <h3>可追溯記憶</h3>
            </div>
            <span>{memories.length} 筆</span>
          </div>
          <form onSubmit={proposeMemory}>
            <label htmlFor="memory">新增偏好或規則草稿</label>
            <textarea
              id="memory"
              onChange={(event) => setMemoryText(event.target.value)}
              placeholder="例如：所有操作說明使用台灣繁體中文"
              required
              value={memoryText}
            />
            <button type="submit">提出記憶</button>
          </form>
          {connectionState === "online" && memories.length === 0 && <p>尚無已保存的記憶。</p>}
          <ul className="record-list">
            {memories.map((memory) => (
              <li key={memory.id}>
                <div>
                  <strong>{memory.content}</strong>
                  <p>
                    {memory.memory_type} · {memory.status} · {memory.source_type}
                  </p>
                  {memory.injection_signals.length > 0 && (
                    <span className="warning">偵測到不可信指令片段，未升格為權威</span>
                  )}
                </div>
                {memory.status === "candidate" && (
                  <button onClick={() => void approveMemory(memory.id)} type="button">
                    核准記憶
                  </button>
                )}
                {memory.status !== "deleted" && (
                  <button className="quiet" onClick={() => void forgetMemory(memory.id)} type="button">
                    忘記
                  </button>
                )}
              </li>
            ))}
          </ul>
        </article>

        <article className="workspace-panel" id="project-panel">
          <div className="panel-title">
            <div>
              <p className="kicker">PROJECT PREVIEW</p>
              <h3>需求到 WBS</h3>
            </div>
            <span>不寫入外部服務</span>
          </div>
          <form onSubmit={previewProject}>
            <label htmlFor="project">描述要完成的工作</label>
            <textarea
              id="project"
              onChange={(event) => setProjectText(event.target.value)}
              placeholder="描述功能、限制與驗收條件"
              required
              value={projectText}
            />
            <button type="submit">產生審查預覽</button>
          </form>
          {plan && (
            <div className="plan-preview">
              <strong>{plan.title}</strong>
              <p>需求：{plan.requirements.map((item) => item.statement).join("；")}</p>
              <p>決策草案：{plan.decisions.map((item) => item.title).join("；")}</p>
              <ol>
                {plan.work_items.map((item) => (
                  <li key={item.id}>
                    {item.title}
                    <small>來源需求 {item.source_requirement_ids.join(", ")}</small>
                  </li>
                ))}
              </ol>
              <button onClick={() => void previewSchedule()} type="button">建立一小時排程預覽</button>
              <span className="warning">等待核准，Plane 同步維持 pending/disabled</span>
            </div>
          )}
          {schedule && (
            <div className="plan-preview">
              <strong>Calendar-style 預覽 · {schedule.timezone}</strong>
              <ol>
                {schedule.blocks.map((block) => (
                  <li key={block.start}>
                    {new Date(block.start).toLocaleString("zh-TW", { timeZone: schedule.timezone })}
                    {" → "}
                    {new Date(block.end).toLocaleString("zh-TW", { timeZone: schedule.timezone })}
                  </li>
                ))}
              </ol>
              <button onClick={() => void requestCalendarApproval()} type="button">
                送到 fake Calendar 核准佇列
              </button>
              <span className="warning">requires approval · 尚未寫入外部行事曆</span>
            </div>
          )}
          <div className="connector-strip">
            {connectors.map((connector) => (
              <span key={connector.name}>
                {connector.name}: <strong>{connector.state}</strong>
              </span>
            ))}
          </div>
        </article>

        <article className="workspace-panel" id="approval-panel">
          <div className="panel-title">
            <div>
              <p className="kicker">APPROVAL INBOX</p>
              <h3>高影響動作核准</h3>
            </div>
            <span>{approvals.filter((item) => item.state === "pending").length} 待處理</span>
          </div>
          <div className="plan-preview">
            <strong>Windows Hello 操作員</strong>
            {operatorStatus?.registered ? (
              <p>已註冊；核准、配對、確認與撤銷都會逐次要求 Windows Hello。</p>
            ) : (
              <>
                <p>
                  尚未註冊。先執行 scripts/copy-operator-enrollment-secret.ps1，
                  再貼上一次性本機註冊密碼。
                </p>
                <label htmlFor="operator-enrollment-secret">本機註冊密碼</label>
                <input
                  autoComplete="off"
                  id="operator-enrollment-secret"
                  onChange={(event) => setOperatorEnrollmentSecret(event.target.value)}
                  type="password"
                  value={operatorEnrollmentSecret}
                />
                <button
                  disabled={!operatorStatus?.configured || !operatorEnrollmentSecret}
                  onClick={() => void enrollDesktopOperator()}
                  type="button"
                >
                  註冊 Windows Hello
                </button>
              </>
            )}
            {!operatorStatus && (
              <span className="warning">Core 尚未提供操作員狀態；更新後需重新啟動本機服務。</span>
            )}
          </div>
          {connectionState === "online" && approvals.length === 0 && <p>目前沒有待處理的核准。</p>}
          <ul className="record-list">
            {approvals.slice(-5).reverse().map((approval) => (
              <li key={approval.id}>
                <div>
                  <strong>{approval.title}</strong>
                  <p>{approval.risk_level} · {approval.state} · {approval.target}</p>
                  <small>{approval.reason}</small>
                  <small>動作內容：{JSON.stringify(approval.preview)}</small>
                  <small>到期：{new Date(approval.expires_at).toLocaleString("zh-TW")}</small>
                  <small>回復：{approval.rollback_method}</small>
                </div>
                {approval.state === "pending" && approvalTokens[approval.id] ? (
                  <div>
                    <button onClick={() => void resumeToolApproval(approval, true)} type="button">
                      核准一次
                    </button>
                    <button className="quiet" onClick={() => void resumeToolApproval(approval, false)} type="button">
                      拒絕
                    </button>
                  </div>
                ) : approval.state === "pending" ? (
                  <span className="warning">需回到原始請求工作階段決定</span>
                ) : null}
              </li>
            ))}
          </ul>
        </article>

        <article className="workspace-panel" id="device-panel">
          <div className="panel-title">
            <div>
              <p className="kicker">ANDROID PAIRING</p>
              <h3>一次性裝置配對</h3>
            </div>
            <span>桌面確認 + P-256 proof</span>
          </div>
          <button type="button" onClick={() => void beginPairing()}>
            建立五分鐘 QR
          </button>
          <button className="quiet" type="button" onClick={() => void refresh()}>
            重新整理裝置
          </button>
          {pairing && pairingQr && (
            <div className="pairing-card">
              <Image
                src={pairingQr}
                alt="KY-JARVIS 一次性裝置配對 QR"
                width={240}
                height={240}
                unoptimized
              />
              <strong>比對碼：{pairing.comparison_code}</strong>
              <small>到期：{new Date(pairing.expires_at).toLocaleString("zh-TW")}</small>
              <span className="warning">只確認同時顯示相同代碼與預期名稱的手機。</span>
            </div>
          )}
          {connectionState === "online" && devices.length === 0 && <p>尚無已配對裝置。</p>}
          <ul className="record-list">
            {devices.map((device) => (
              <li key={device.id}>
                <div>
                  <strong>{device.display_name}</strong>
                  <p>{device.trust_state}</p>
                </div>
                {device.trust_state === "pending" ? (
                  <div>
                    <label htmlFor={`code-${device.id}`}>六位數比對碼</label>
                    <input
                      id={`code-${device.id}`}
                      inputMode="numeric"
                      maxLength={6}
                      onChange={(event) => setComparisonCode(event.target.value.replace(/\D/g, ""))}
                      value={comparisonCode}
                    />
                    <button
                      disabled={!/^\d{6}$/.test(comparisonCode)}
                      onClick={() => void confirmDevice(device.id)}
                      type="button"
                    >
                      確認裝置
                    </button>
                  </div>
                ) : (
                  <button className="quiet" onClick={() => void revokeDevice(device.id)} type="button">
                    撤銷
                  </button>
                )}
              </li>
            ))}
          </ul>
        </article>
      </div>
    </section>
  );
}
