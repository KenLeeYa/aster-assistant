from __future__ import annotations

import os
from pathlib import Path

# Playwright must not inherit a developer's live database, operator credential,
# provider flag, or local YAML configuration. These changes affect only this
# short-lived child process.
for variable_name in tuple(os.environ):
    if variable_name.startswith("KY_JARVIS_"):
        os.environ.pop(variable_name)

repository_root = Path(__file__).resolve().parents[2]
os.environ["LOCALAPPDATA"] = str(repository_root / "artifacts" / "playwright-localappdata")

import uvicorn  # noqa: E402
from ky_jarvis_core.config import Settings  # noqa: E402
from ky_jarvis_core.main import create_app  # noqa: E402

settings = Settings(
    allowed_web_origins=["http://127.0.0.1:3100", "http://localhost:3000"],
    database_url=None,
    enable_android_app=False,
    enable_cloud_ai=False,
    enable_google_calendar=False,
    enable_gmail=False,
    enable_google_drive=False,
    enable_lan_access=False,
    enable_microsoft_graph=False,
    enable_n8n=False,
    enable_openai_realtime=False,
    enable_plane=False,
    enable_push_notifications=False,
    enable_remote_gateway=False,
    enable_windows_executor=False,
    ollama_model=None,
    operator_bootstrap_secret=None,
    operator_credential_path=None,
)

if __name__ == "__main__":
    uvicorn.run(create_app(settings), host="127.0.0.1", port=8765)
