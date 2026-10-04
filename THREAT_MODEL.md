# Threat model

Status: Phase 13 desktop/mobile review plus phone-free desktop hardening complete, 2026-09-03. Re-review before enabling a LIVE connector, remote ingress, provider credential, Linux target or signed release.

## Assets

- Requirements, decisions, memories, projects, schedules and authoritative user intent.
- OAuth/provider secrets, mobile sessions, device keys and signing material.
- Local files inside approved roots and any external write authority.
- Approval payloads, audit evidence, backups, transcripts and generated artifacts.

## Trust boundaries

1. User input versus imported/external content.
2. Browser/mobile caller versus Core API.
3. Model/agent output versus policy and typed gateway.
4. Windows process versus Docker and sidecars.
5. Loopback worker versus optional private remote gateway.
6. Server credentials versus device-bound short sessions.

## Threats and controls

| Threat | Main impact | Implemented control | Remaining validation |
|---|---|---|---|
| Indirect prompt injection / memory poisoning | External text becomes authority | provenance, authority levels, candidate gate, injection signals, schema/tool boundary | adversarial LIVE connector corpus |
| Secret leakage | account/provider compromise | external secret files, redacted logs/audit, gitleaks, Trivy, APK byte scan | formal release-secret inventory |
| Local/LAN exposure | unauthorized caller | loopback default, host/origin/intent validation, disabled remote config | TLS/private-network deployment test |
| Unauthenticated local HTTP caller | authoritative memory change, self-approval or unauthorized device trust | Windows Hello/WebAuthn UV; 120-second bounded challenge; 90-second single-use grant bound to exact method/path/body; intent-only and QR-visible self-confirm tests denied | visible local enrollment/restart; durable approval/device/idempotency transactions and service isolation before non-loopback/LIVE use |
| SSRF/redirect abuse | metadata/internal service access | scheme/host allowlist, DNS/IP rejection, redirects off, size limits | connector-specific LIVE tests |
| Path/junction escape | file access outside scope | canonical resolved roots and file limits | broader Windows junction matrix |
| Approval substitution/replay | wrong or duplicate action | canonical hash, nonce, expiry, one use, idempotency, audit | persistence-backed multi-process test |
| Malicious sidecar/tool metadata | command execution | exact executable plus exact argument policy, shell disabled, timeout/output cap, typed registry | packaged-sidecar integration |
| Device/token theft | mobile remote control | Keystore key, encrypted vault, short access, rotating family, reuse detection, revoke | rooted/backup restore and physical loss drill |
| Pairing interception | attacker claims session | five-minute secret, fingerprint, comparison code, signed challenge, one-time phone claim | two-device physical test |
| Voice replay/bystander action | consequential action approved by speech | deliberate final submission, visible confirmation, biometric signature, no speech-only approval | physical mic/lock-screen/Bluetooth matrix |
| Lock-screen or focus-loss capture | transcript/recording exposed outside deliberate PTT | secure activity window, secret recording notification, showWhenLocked/turnScreenOn false, any negative audio-focus change cancels without submit | physical locked-device and Bluetooth route test |
| Exported Android entry misuse | hostile app invokes pairing, assistant, tile or widget surface | strict expiring pairing URI parser, one-time secret/comparison code/device proof, system BIND permissions, generated exported-component allowlist | hostile-app/deep-link and two-device physical test |
| Oversized chunked audio | Core memory exhaustion | incremental request streaming, byte cap before STT, duration and semaphore limits | remote ingress load test remains disallowed until authenticated gateway exists |
| Realtime policy override | phone widens model/tool access | backend-owned broker, trusted-device check, non-zero hard budget, concurrency/duration cap, versioned narrow-intent codec, no direct MCP route, secret-free local fallback | bounded LIVE credential/WebRTC smoke |
| Offline false execution | user believes stale action ran | registered worker heartbeat expires to offline, AES-GCM expiring queue, stale consequential reapproval, wake-only push | network-switch device test |
| Dependency/image compromise | build/runtime execution | locks, pinned DB digest, SBOM, gitleaks/Trivy and CI; Android release runtime has no current finding and ktlint/Detekt are enforced before package | three LOW ktlint-only `logback-core` findings; Linux-only GTK glib upgrade plus provenance/signing for public release |
| Model-registry substitution or unexpected large download | untrusted model execution, disk/network exhaustion | installed-model detection first; Ollama must be available; every missing-model pull needs explicit `-ConfirmDownload`; bootstrap/startup never download models | immutable model provenance/hash policy before Production refreshes |
| Unwanted login persistence | code runs at user login without informed action | registration requires explicit `-Confirm`, writes only current-user Startup, uses an owner marker, refuses foreign shortcut overwrite/removal and never elevates | user-visible review after checkout moves or packaged startup replaces source startup |
| Backup expiry scope escape or unwanted scheduled deletion | unrelated or recent data loss | retention disabled by default; preview-first explicit confirmation; exact direct-child/timestamp/manifest ownership checks; reparse/root/repository rejection; daily task is current-user limited, owner-marked and opt-in | user-visible daily-task run plus recovery drill on disposable data |
| Backup corruption/leak or unsafe restore | data loss or exposure | per-file SHA-256 manifest, known-secret/reparse exclusion, isolated default restore, explicit active-data switch, stopped writers/zero-client gate, fresh safety backup, staged name swap retaining prior DB, side-by-side file recovery | encrypted off-device recovery drill and application-level confirmed active-swap exercise |
| Debug/release leakage | production exposes loopback or key | release cleartext=false, R8, byte scan, unsigned status explicit | signed release and Play/App distribution review |

## Residual risks

- The reference API domain stores are currently process-local; approval/device state is not suitable for multi-process or crash-safe Production use until repository adapters are wired.
- One Android 36 physical device has current fresh-pairing, bidirectional-text and strong-biometric no-op approval evidence plus historical bounded foreground PTT, voice and default-assistant evidence; one API 36 emulator currently passes 9 instrumented cases. Biometric denial, lock-screen, Bluetooth, rooted-device and broader OEM/API-level behavior remain unproven.
- Local `qwen3:8b`, `nomic-embed-text` and `faster-whisper small` have bounded evidence. LIVE provider quality, spend and outage behavior remain unmeasured because reusable cloud credentials stay disabled.
- Tauri release EXE and NSIS packaging pass locally, but both are unsigned Pilot artifacts.
- The packaged Tauri HTTP custom-protocol origin cannot use this WebAuthn flow. It fails closed until a trusted HTTPS Core transport or narrowly scoped native bridge is implemented and packaged; the standalone localhost Command Center remains the supported Pilot operator surface.
- Standard Scan coverage is partial: Android was absent from its locked Phase 8 target and no independent delegated baseline was available. Its Medium desktop-operator finding is remediated in current source/contracts with Windows Hello action grants, but the live pre-hardening Core was not restarted during this phone-free pass. Non-loopback and LIVE writes remain blocked by the pending visible enrollment plus durable transactional repositories and service isolation.
- Full-repository all-severity dependency scanning retains one Medium Linux-only `glib 0.18.5` lock entry. It is absent from the Windows target graph, but must be upgraded with the upstream Tauri/GTK chain before claiming a Linux release.
- The Android lockfile also records three LOW advisories for `logback-core 1.3.16` in the ktlint build-tool configuration. Gradle dependency evidence shows it is absent from `releaseRuntimeClasspath`; it remains tracked until the upstream ktlint toolchain moves to a fixed compatible logger.

## Non-goals

- No public Internet endpoint or router/firewall automation.
- No Accessibility Service, Notification Listener, SMS, contacts, call logs, broad storage, device admin or hidden API use.
- No autonomous payment, order, transfer or trade.
- No always-on or boot-launched microphone.
