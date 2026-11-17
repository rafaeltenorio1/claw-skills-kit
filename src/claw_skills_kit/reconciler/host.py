from __future__ import annotations

import os
from pathlib import Path, PurePosixPath
from typing import Protocol


class HostError(Exception):
    """A path or operation the host refuses."""


class Host(Protocol):
    def read(self, path: str) -> bytes | None:
        """File content, or None if it does not exist."""

    def write(self, path: str, data: bytes) -> None:
        """Create or replace a file (atomically), creating parent directories."""

    def delete(self, path: str) -> None:
        """Remove a file if present and prune directories left empty."""

    def files(self, prefix: str = "") -> list[str]:
        """Sorted relative POSIX paths of every file under `prefix`."""


class LocalHost:
    TMP_SUFFIX = ".csk-tmp"

    def __init__(self, root: Path) -> None:
        self._root = Path(root).resolve()

    def _resolve(self, path: str) -> Path:
        pure = PurePosixPath(path)
        if pure.is_absolute() or ".." in pure.parts or not pure.parts:
            raise HostError(f"Path escapes the host root or is empty: {path!r}")
        return self._root.joinpath(*pure.parts)

    def read(self, path: str) -> bytes | None:
        target = self._resolve(path)
        return target.read_bytes() if target.is_file() else None

    def write(self, path: str, data: bytes) -> None:
        target = self._resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + self.TMP_SUFFIX)
        try:
            tmp.write_bytes(data)
            tmp.replace(target)
        finally:
            tmp.unlink(missing_ok=True)

    def delete(self, path: str) -> None:
        target = self._resolve(path)
        target.unlink(missing_ok=True)
        parent = target.parent
        while parent != self._root and parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir()
            parent = parent.parent

    def files(self, prefix: str = "") -> list[str]:
        base = self._resolve(prefix) if prefix else self._root
        if not base.is_dir():
            return []
        found = []
        for dirpath, _dirs, names in os.walk(base):
            for name in names:
                if name.endswith(self.TMP_SUFFIX):
                    continue
                found.append(Path(dirpath, name).relative_to(self._root).as_posix())
        return sorted(found)
