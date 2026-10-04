from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

from pydantic import BaseModel, Field


class SidecarSpec(BaseModel):
    executable: Path
    arguments: tuple[str, ...] = ()
    timeout_seconds: float = Field(default=10.0, gt=0, le=120)
    max_output_bytes: int = Field(default=262_144, gt=0, le=1_048_576)


class SidecarPolicy(BaseModel):
    executable: Path
    allowed_arguments: tuple[tuple[str, ...], ...] = ((),)


class SidecarResult(BaseModel):
    exit_code: int
    stdout: str
    stderr: str


class SidecarManager:
    def __init__(self, policies: list[SidecarPolicy]) -> None:
        if not policies:
            raise ValueError("at least one exact sidecar policy is required")
        self._policies = {
            policy.executable.resolve(strict=True): policy.allowed_arguments for policy in policies
        }

    async def run(self, spec: SidecarSpec) -> SidecarResult:
        executable = spec.executable.resolve(strict=True)
        allowed_arguments = self._policies.get(executable)
        if not executable.is_file() or allowed_arguments is None:
            raise PermissionError("sidecar executable is not exactly allowlisted")
        if spec.arguments not in allowed_arguments:
            raise PermissionError("sidecar arguments do not match an exact allowlisted command")
        try:
            completed = await asyncio.to_thread(
                subprocess.run,  # noqa: S603 - exact path is allowlisted
                [str(executable), *spec.arguments],
                capture_output=True,
                check=False,
                timeout=spec.timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            raise TimeoutError("sidecar exceeded its declared timeout") from None
        stdout = completed.stdout
        stderr = completed.stderr
        if len(stdout) + len(stderr) > spec.max_output_bytes:
            raise ValueError("sidecar output exceeded its declared limit")
        return SidecarResult(
            exit_code=completed.returncode,
            stdout=stdout.decode(errors="replace"),
            stderr=stderr.decode(errors="replace"),
        )
