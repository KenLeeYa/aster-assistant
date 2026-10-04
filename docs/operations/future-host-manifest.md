# Future host dependency and model manifest

No item in this document has been installed for the future host. Record exact versions, hashes, license terms, and provenance when that host exists. Lock only versions that pass the target-host acceptance tests.

| Need | Component | OS | Purpose and source | Gate |
| --- | --- | --- | --- | --- |
| Required | Windows 11 + WSL2 and a supported Linux distribution | Windows/WSL | Host and Linux runtime; Microsoft WSL documentation | Verify virtualization, updates, memory, network mode, sleep behavior |
| Required | Python 3.12–3.14 and `uv` | WSL | Core dependencies from `pyproject.toml`/`uv.lock`; python.org and astral.sh | Re-resolve for Linux; no Windows wheel reuse |
| Required | PostgreSQL + pgvector | WSL | Durable state/vector store; postgresql.org and github.com/pgvector/pgvector | Backups, migrations, restart, dimensions |
| Required | Node 24 + pnpm 11 | Windows | Existing Next.js UI; nodejs.org and pnpm.io | Locked build, WebAuthn origin |
| Required | Rust toolchain/Tauri prerequisites | Windows | Existing desktop package; rust-lang.org and tauri.app | Signed Windows build and operator transport |
| Required | One local model runtime, initially Ollama | Windows **or** WSL | Inference; ollama.com | Single instance, cloud disabled, measured RAM/VRAM |
| Optional | Colibri gateway | Selected model host | Alternate provider; its upstream repository and license | Structured output, cancellation, timeout, error and resource contract; no automatic fallback to write actions |
| Optional | faster-whisper **or** whisper.cpp | WSL | Local STT; upstream project/license | Chinese recognition, latency, resource and privacy checks |
| Optional | sherpa-onnx | Selected audio host | Local TTS/KWS; upstream project/license | Voice quality, model license, explicit PTT baseline |
| Optional | Pipecat | WSL | Voice orchestration only if chained path becomes insufficient | No independent approval path |
| Optional | Android SDK | Development host | Future Android build; developer.android.com | Device matrix and signing |

Model records must include identifier, source URL, revision, license, checksum, quantization, RAM/VRAM footprint, context size, supported languages, and measured latency. The current `qwen3:8b` and `nomic-embed-text` are reference baselines, not fixed requirements for an unknown new host. Select one generation model at a time; keep speech and embedding resource budgets separate. Do not default to OpenWakeWord for Chinese wake words or turn on continuous listening. OpenClaw, Open WebUI, Agent Zero, and Letta Code are architectural references, not dependencies to install wholesale.

No OAuth client, API key, production certificate, secret, GPU driver, model, or service should be provisioned until the user supplies the target host and explicitly initiates that setup.
