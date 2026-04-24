"""Centralized upload limits (size, and future: file-type, count).

All ingestion paths (direct upload, connector sync, bucket pull) should import
from here rather than hard-coding thresholds.
"""
from dataclasses import dataclass
from typing import Iterable, List, Tuple

from utils.env_utils import get_env_float

MAX_UPLOAD_SIZE_MB: float = get_env_float("MAX_UPLOAD_SIZE_MB", 1.0)
MAX_UPLOAD_SIZE_BYTES: int = int(MAX_UPLOAD_SIZE_MB * 1024 * 1024)


@dataclass
class SkippedFile:
    filename: str
    size_bytes: int
    reason: str = "file_too_large"


class FileTooLargeError(ValueError):
    """Raised when a single file exceeds the configured upload size limit."""

    def __init__(self, filename: str, size_bytes: int):
        self.filename = filename
        self.size_bytes = size_bytes
        self.limit_bytes = MAX_UPLOAD_SIZE_BYTES
        super().__init__(
            f"File '{filename}' is {format_size(size_bytes)}, "
            f"exceeds limit of {format_size(MAX_UPLOAD_SIZE_BYTES)}"
        )


def format_size(n_bytes: int) -> str:
    if n_bytes is None:
        return "unknown"
    if n_bytes < 1024:
        return f"{n_bytes} B"
    if n_bytes < 1024 * 1024:
        return f"{n_bytes / 1024:.1f} KB"
    return f"{n_bytes / (1024 * 1024):.2f} MB"


def is_within_size_limit(size_bytes: int) -> bool:
    if size_bytes is None or size_bytes < 0:
        # Unknown size — don't preemptively reject; the safeguard at download
        # time will catch oversized content.
        return True
    return size_bytes <= MAX_UPLOAD_SIZE_BYTES


def check_file_size(filename: str, size_bytes: int) -> None:
    """Raise FileTooLargeError if size exceeds the configured limit."""
    if size_bytes is not None and size_bytes > MAX_UPLOAD_SIZE_BYTES:
        raise FileTooLargeError(filename, size_bytes)


def partition_by_size(
    files: Iterable[Tuple[str, int]],
) -> Tuple[List[Tuple[str, int]], List[SkippedFile]]:
    """Split an iterable of (filename, size_bytes) tuples into (ok, skipped)."""
    ok: List[Tuple[str, int]] = []
    skipped: List[SkippedFile] = []
    for filename, size_bytes in files:
        if is_within_size_limit(size_bytes):
            ok.append((filename, size_bytes))
        else:
            skipped.append(SkippedFile(filename=filename, size_bytes=size_bytes))
    return ok, skipped
