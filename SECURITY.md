# Security policy

## Current posture

KY-JARVIS is a pre-production, local-first reference implementation. Credential-free architecture and automated desktop/mobile gates are verified through Phase 13. External providers, public ingress, production signing and silent privilege changes remain disabled.

## Enforced controls

- Core services and PostgreSQL bind to loopback by default; non-loopback configuration fails validation unless an explicit mode is selected.
- Mutation requests require an allowed Origin when present and an explicit X-KY-JARVIS-Intent header.
- Memory approval/deletion, desktop approval decision/resume and device pairing begin/confirm/revoke require a Windows Hello/WebAuthn platform assertion with user verification. Core issues only a 90-second, single-use grant bound to the canonical method/path/body hash; intent headers alone receive 401.
- Imported/web/tool content is untrusted data. Memory provenance, authority, candidate approval, supersession and injection signals are preserved.
- R0–R5 policy separates read-only from consequential work. Approval tokens bind a canonical action hash, nonce, expiry, actor and single use.
- Gateway requests use typed schemas, idempotency, egress allowlists, DNS/IP checks, redirect denial, response limits and sanitized results.
- File access uses resolved allowlisted roots. Sidecars require an exact resolved executable and an exact approved argument tuple; arbitrary interpreter arguments are rejected.
- Audit records form a redacted hash chain; sensitive shapes are removed from structured logs.
- Database credentials are generated outside the repository. Source and examples contain identifiers only.
- Desktop enrollment bootstrap material is random, stored only under a user/SYSTEM ACL outside the repository, withheld from the Web process and never logged. Windows Hello private-key material never enters Core; only public credential metadata is persisted.
- Android uses one non-exportable P-256 device/session key plus a separate per-use strong-biometric P-256 approval key, an AES-GCM token vault, short access sessions, rotating refresh families, reuse detection and revocation.
- The desktop confirm response does not expose mobile tokens. Tokens are claimed once by the phone after device-key proof.
- No reusable OpenAI/server credential, private key, test secret or cleartext production endpoint is embedded in APK/AAB.
- Microphone and assistant role require visible user action. There is no boot receiver, always-on microphone or hidden background capture.
- Android content uses `FLAG_SECURE`; the foreground-recording notification is lock-screen secret, and permanent/transient/duck audio-focus loss all stop capture without submission.
- Raw audio retention is disabled; stale consequential offline commands require fresh approval.
- Realtime client-secret issuance requires a trusted device, a configured non-zero hard budget and an available concurrency slot. Provider outage returns a secret-free local fallback; reusable API keys are rejected from the mobile boundary.
- Private-remote/hybrid modes require explicit LAN, gateway and TLS-identity configuration. Push adapters carry wake metadata only, and worker heartbeat expiry becomes `offline` rather than a false execution claim.
- Voice request bodies are read incrementally and rejected as soon as the configured byte cap is crossed.
- Gitleaks and Trivy gates, locked dependencies, SBOMs, checksums, per-file backup checksums and isolated restore tests are provided. Retention defaults to disabled; pruning requires explicit confirmation and accepts only direct, non-reparse, exact-timestamp directories with a recognized KY-JARVIS manifest. Optional daily backup registration is current-user, limited, owner-marked and explicit. Active restore requires a separate explicit switch, stopped writers, zero live database clients and a fresh safety backup; old data is retained rather than silently dropped.
- Python formatting is enforced by Ruff in local tests and CI. Android builds enforce ktlint, Detekt, JVM tests and warnings-as-errors lint before packaging without a suppression baseline. Instrumentation is never an implicit ADB side effect: only an exact, explicitly selected emulator may run it, and physical devices are rejected.
- Model pulls are never a bootstrap/startup side effect: installed models are detected first and every missing-model download needs explicit confirmation. Launch-at-login likewise requires an explicit current-user action, refuses to replace/remove foreign shortcuts and never requests elevation.

## Phase 9 security review

Codex Security Standard Scan `eb5a5d02-3863-4072-b1f6-c9fe27d84c53` reviewed the locked Phase 8 revision `90360d9171fad445ecfa2764c865258d475463c0`. Coverage was partial because Android had not yet entered the locked revision and an independent delegated baseline was unavailable. It reported one Medium and two Low findings:

- Medium, source remediation completed after the scan; live activation pending: protected desktop approval and device routes now reject intent-only callers and require a user-verified Windows Hello assertion that yields an expiring, one-use action-bound grant. Regression tests cover intent-only denial, QR-visible self-confirm denial, wrong-action use, expiry and replay. The running pre-hardening Core was intentionally not restarted during phone-free work, so one visible local enrollment/restart remains in `MANUAL_ACTIONS.md`.
- Low, remediated after the scan: broad sidecar interpreter arguments were replaced with exact command/argument policies.
- Low, remediated after the scan: undeclared voice bodies now stop streaming at the configured byte limit.

The canonical manifest, findings, coverage, report and SARIF remain immutable under `reports/scans/codex-security-phase9/`; the post-scan remediation is recorded separately and does not rewrite that locked result. Durable approval/device/idempotency transactions and service-level isolation still block non-loopback/LIVE Production use even after local Windows Hello enrollment.

The supported Pilot WebAuthn page origin is exactly `http://localhost:3000`. HTTP `127.0.0.1` is not a valid WebAuthn RP origin for this design. The packaged Tauri HTTP custom-protocol origin also remains fail-closed; enabling Tauri's HTTPS custom protocol without simultaneously providing a trusted HTTPS Core would create a mixed-content failure, so packaged operator transport remains a Production gate.

## Phase 13 mobile review

- API 36 emulator execution passed 9/9 instrumented cases after a no-snapshot cold boot: Keystore/vault, assistant metadata/settings, PTT press-release, bidirectional UI, worker refresh and immutable mobile-approval detail.
- The merged Release manifest enforces minSdk 29/targetSdk 37, `allowBackup=false`, cleartext off, non-debuggable output, no boot receiver or broad SMS/contact/storage/location permissions, and an exact exported-component allowlist.
- Release APK/AAB archive scanning found no debug package/endpoint, test marker, OpenAI environment variable or reusable `sk-` key shape. Both artifacts are intentionally unsigned Pilot outputs.
- Netty 4.1.137, Commons Lang 3.18 and HttpClient/HttpMime 4.5.13 remove the earlier Android runtime dependency findings. Current all-severity scanning retains three LOW findings on `logback-core 1.3.16`, which Gradle locks only to the ktlint build configuration and does not resolve in `releaseRuntimeClasspath`; it is not packaged in the APK/AAB. Full-repository scanning also retains one Medium for Linux-only GTK `glib 0.18.5` in Cargo.lock; it is not compiled into the verified Windows or Android target and requires an upstream Tauri GTK dependency transition before a Linux release.
- One bounded physical strong-biometric approval now passes on the current Android 36 device: the visible system prompt authenticated the user, Core verified the device-bound P-256 signature, and an unregistered no-op tool kept `result=null` with no external execution. Biometric denial, lock-screen microphone behavior, Bluetooth routing, network switching and wider OEM/API compatibility remain NOT RUN and are not inferred from this pass.

## Explicitly disabled until manual gates

- LIVE Google/Plane/GitHub/Gmail/Drive/Microsoft/n8n credentials and writes.
- LIVE OpenAI Realtime and provider spend.
- Internet-exposed Core API, private-remote TLS identity and FCM server credential.
- Android production signing/distribution and physical-device compatibility claims beyond the recorded single-device bounded evidence.
- Windows and Android production code signing. The local Tauri EXE and NSIS installer are intentionally unsigned Pilot artifacts.

## Reporting

Do not include credentials, customer data or signing material in a report. Provide a minimal reproduction, affected revision, impact and redacted evidence to the owner through a private channel.

No public supported release exists. A BLOCKED or NOT RUN check is never treated as PASS; current evidence is in reports/security_report.md and reports/verification_report.md.
