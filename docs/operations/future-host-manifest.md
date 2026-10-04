# Future host dependency and model manifest

No item in this document has been installed for the future host. Record exact versions, hashes, license terms, and provenance when that host exists. Lock only versions that pass the target-host acceptance tests.

## Version and source policy

The repository locks application dependencies in `uv.lock`, `pnpm-lock.yaml`, and the Rust/Android lockfiles. Host packages are deliberately unpinned until the target machine, Linux distribution, and driver stack are known. At setup, record the installed version, upstream release URL, package checksum or digest, license URL and redistribution terms, and host acceptance result for **each** selected component and model. Do not treat an example version as an approved host version. Optional components remain disabled unless selected and accepted separately.

Official upstream sources and license entry points:

| Component | Official source and licensing entry point | Selection |
| --- | --- | --- |
| Windows 11 / WSL2 | [Microsoft WSL](https://learn.microsoft.com/windows/wsl/install), [Microsoft software terms](https://www.microsoft.com/useterms/) | Required host; use the host's licensed Windows version |
| Linux distribution | Record the selected distribution's official release and license pages | Required inside WSL; distribution undecided |
| Python / uv | [Python releases](https://www.python.org/downloads/), [Python license](https://docs.python.org/3/license.html), [uv releases and license](https://github.com/astral-sh/uv) | Required; Python range follows `pyproject.toml` |
| PostgreSQL / pgvector | [PostgreSQL releases and license](https://www.postgresql.org/about/licence/), [pgvector releases and license](https://github.com/pgvector/pgvector) | Required; choose compatible major versions together |
| Node.js / pnpm | [Node.js releases and license](https://github.com/nodejs/node), [pnpm releases and license](https://github.com/pnpm/pnpm) | Required; check `.nvmrc` and `packageManager` |
| Rust / Tauri | [Rust releases and license](https://github.com/rust-lang/rust), [Tauri prerequisites and license](https://v2.tauri.app/start/prerequisites/) | Required only when building desktop package |
| Ollama | [Ollama releases and license](https://github.com/ollama/ollama) | Initial local inference choice; one runtime instance |
| Colibri | [Colibri releases and license](https://github.com/JustVugg/colibri) | Optional alternative provider; check upstream license before use |
| faster-whisper / whisper.cpp | [faster-whisper](https://github.com/SYSTRAN/faster-whisper), [whisper.cpp](https://github.com/ggml-org/whisper.cpp) | Optional STT alternatives; select at most one initially |
| sherpa-onnx / Pipecat | [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx), [Pipecat](https://github.com/pipecat-ai/pipecat) | Optional speech components |
| Android SDK | [Android SDK](https://developer.android.com/studio), [Android SDK license information](https://developer.android.com/studio/terms) | Optional development host only |

Model weights have their own licenses, which can differ from a runtime's license. Review the exact model revision and license before download or redistribution.

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
