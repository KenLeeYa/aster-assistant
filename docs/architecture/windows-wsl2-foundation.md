# Aster: Windows + WSL2 foundation

Status: design and contract baseline; no target-host deployment has been verified.
The product and Python import names remain KY-JARVIS for compatibility. Aster is the proposed product name, and `aster-assistant` the proposed private repository name.

## Placement and trust boundaries

| Boundary | Responsibility |
| --- | --- |
| Windows endpoint | Tauri/Web command center, push-to-talk capture, playback, Windows Hello, and a future narrowly scoped executor. |
| WSL2 core | FastAPI, LangGraph, PostgreSQL/pgvector, governed memory, approvals, audit, scheduling, and STT if selected. |
| Model runtime | One instance of Ollama on Windows **or** WSL2. The host is configurable; cloud AI remains off by default. Colibri is a future optional provider, never a replacement for governance. |
| Android | Future paired endpoint using the same Core policy path. |

Windows-to-WSL localhost forwarding must be verified on the target host. WSL-to-Windows localhost depends on networking mode. Do not widen Core's bind address or CORS to solve connectivity. LAN or Internet access is a separate reviewed deployment gate. No Linux process may execute arbitrary Windows shell commands: an endpoint executor must accept a typed, allowlisted request bound to device identity, action hash, expiry, idempotency key, and an approved grant. It returns a receipt for Core audit.

## Durable state gate

`ApplicationServices` now selects SQL-backed approval, audit, device-trust, and governed-memory mappings when `database_url` is configured. These use the existing tables, so no duplicate migration is needed for their current columns. Approval state changes use compare-and-swap transitions; the audit chain verifies at startup and appends to the database before reporting success; device revocation and memory deletion cannot be reversed by their mappings. Tool execution uses a durable reservation keyed by tool name and idempotency key. A completed result can be replayed from its receipt, while an interrupted reservation stops automatic retry pending reconciliation. The existing reference/memory mode remains for isolated tests without a database. Local SQLite contracts and Python tests pass; the future WSL/PostgreSQL host has not been tested.

This is not a full durable transaction boundary. Project plans, mobile token families, worker presence, and jobs are still process-local or incompletely wired. A Core restart retains memory, device trust, approval, audit, and execution receipt records, but process-local sessions fail closed; without a stable token-pepper secret, an old approval token cannot verify after restart and must be reissued. Approval writes and audit append are not yet one transaction, and external side effects cannot be atomically committed with the database. Before enabling consequential real connectors, implement a transactional outbox, receipt reconciliation, and restart/revocation tests against the actual target host. Never silently replay an uncertain action.

The Windows Hello RP ID/origin is currently localhost-specific. Keep that origin while the UI remains on Windows localhost and verify the browser-to-WSL API path. If the UI origin changes, perform explicit re-enrollment and review TLS, CORS, and origin checks before enabling consequential actions.

## Availability and recovery

Start order: Windows startup task launches the named WSL distribution; WSL service manager starts PostgreSQL, Core, and the chosen model runtime; Core readiness must pass before the UI offers actions. This is a future manual setup sequence, not an installed service. WSL systemd units alone do not guarantee instance lifetime. On sleep, shutdown, network loss, or Windows endpoint absence, mark Windows capabilities offline, stop dispatch, and require fresh approval for stale consequential actions. Back up the database, WSL filesystem, config metadata, and signing/public-key metadata with checksums; rehearse restore without replacing active data.

Store Linux project and database files inside the WSL Linux filesystem rather than `/mnt/c`. Set WSL memory/CPU limits only after measuring the target machine. Do not start a second container engine or model instance merely to implement this split.

## Migration gates

1. Add repository ports and migrations for durable governance state; demonstrate restart, replay, revocation, and recovery contracts with disposable fixtures.
2. Validate Windows-to-WSL API, WebAuthn origin, Ollama placement, PTT latency, and fail-closed offline behavior on the new host.
3. Add the restricted Windows executor, then test action-hash-bound approval and idempotent receipts. Only after that consider Android or private remote access.

`private-remote` and `hybrid-gateway` remain disabled; neither is established by a successful localhost test.
