import asyncio
import sys

import uvicorn

from ky_jarvis_core.config import load_settings


def main() -> None:
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    settings = load_settings()
    uvicorn.run(
        "ky_jarvis_core.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )


if __name__ == "__main__":
    main()
