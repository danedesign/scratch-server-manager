import hashlib
from pathlib import Path
from typing import Optional


def compute_checksum(path: Path, algorithm: str = "sha256", chunk_size: int = 65536) -> Optional[str]:
    hasher = hashlib.new(algorithm)
    try:
        with open(path, "rb") as f:
            while chunk := f.read(chunk_size):
                hasher.update(chunk)
    except OSError:
        # Deleted or still mid-write when the watcher event fired.
        return None
    return hasher.hexdigest()
