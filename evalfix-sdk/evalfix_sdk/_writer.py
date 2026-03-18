"""
evalfix_sdk/_writer.py

File backend: appends JSONL records to .evalfix/failures.jsonl.

Each record is one JSON object per line, terminated with newline.
The file is created (along with parent directories) on first write.
Writes are atomic at the line level via a per-file lock.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Dict, Any

# One lock per resolved file path keeps concurrent writers safe.
_locks: Dict[str, threading.Lock] = {}
_locks_meta = threading.Lock()


def write_to_file(record: Dict[str, Any], queue_file: str) -> None:
    """Append *record* as a JSON line to *queue_file*.

    Creates parent directories if they don't exist.
    Thread-safe: uses a per-file lock.
    """
    lock = _get_lock(queue_file)
    with lock:
        path = Path(queue_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, default=str) + "\n")


def read_all(queue_file: str) -> list:
    """Read and parse all JSONL records from *queue_file*.

    Returns an empty list if the file doesn't exist or can't be parsed.
    """
    path = Path(queue_file)
    if not path.exists():
        return []

    records = []
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass  # skip malformed lines
    except OSError:
        pass
    return records


def clear_file(queue_file: str) -> None:
    """Truncate the queue file after the CLI has ingested its contents."""
    lock = _get_lock(queue_file)
    with lock:
        path = Path(queue_file)
        if path.exists():
            path.write_text("", encoding="utf-8")


def _get_lock(queue_file: str) -> threading.Lock:
    with _locks_meta:
        if queue_file not in _locks:
            _locks[queue_file] = threading.Lock()
        return _locks[queue_file]
