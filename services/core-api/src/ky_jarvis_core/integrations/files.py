from __future__ import annotations

from pathlib import Path


class PathBoundaryError(PermissionError):
    pass


class LocalFileConnector:
    def __init__(self, allowed_roots: list[Path]) -> None:
        if not allowed_roots:
            raise ValueError("at least one allowed root is required")
        self._roots = tuple(root.resolve(strict=True) for root in allowed_roots)

    def resolve_allowed(self, candidate: Path) -> Path:
        resolved = candidate.resolve(strict=True)
        if not any(resolved == root or resolved.is_relative_to(root) for root in self._roots):
            raise PathBoundaryError("resolved path escapes every allowed root")
        return resolved

    def read_text(self, candidate: Path, *, max_bytes: int = 1_048_576) -> str:
        resolved = self.resolve_allowed(candidate)
        if not resolved.is_file():
            raise ValueError("path is not a regular file")
        if resolved.stat().st_size > max_bytes:
            raise ValueError("file exceeds connector read limit")
        return resolved.read_text(encoding="utf-8")

    def inventory(self, root: Path) -> tuple[Path, ...]:
        resolved_root = self.resolve_allowed(root)
        if not resolved_root.is_dir():
            raise ValueError("inventory target is not a directory")
        safe_files: list[Path] = []
        for candidate in resolved_root.rglob("*"):
            if candidate.is_file():
                try:
                    safe_files.append(self.resolve_allowed(candidate))
                except PathBoundaryError:
                    continue
        return tuple(sorted(set(safe_files)))
