from __future__ import annotations

import hashlib
from collections.abc import Mapping


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def revision_of(files: Mapping[str, bytes]) -> str:
    """One hash for a set of files: sha256 over sorted `path NUL file-hash LF` lines."""
    digest = hashlib.sha256()
    for path in sorted(files):
        digest.update(f"{path}\0{sha256_hex(files[path])}\n".encode())
    return digest.hexdigest()
