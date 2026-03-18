"""
evalfix_sdk/_config.py

Config resolution order:
  1. Explicit configure() call
  2. Environment variables (EVALFIX_*)
  3. Auto-detection (look for .evalfix/ in cwd + parents)
  4. Defaults (file backend, cwd/.evalfix/failures.jsonl)
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class SDKConfig:
    # "file" or "http"
    backend: str = "file"

    # File backend — path to the JSONL queue file
    queue_file: Optional[str] = None

    # HTTP backend
    api_url: Optional[str] = None
    api_key: Optional[str] = None

    # Behaviour
    enabled: bool = True

    # Internal — resolved absolute path (populated by resolve())
    _resolved_queue_file: Optional[str] = field(default=None, repr=False)


# Module-level singleton, populated by configure() or lazily by _get_config()
_config: Optional[SDKConfig] = None


def configure(
    *,
    backend: str = "file",
    queue_file: Optional[str] = None,
    api_url: Optional[str] = None,
    api_key: Optional[str] = None,
    enabled: bool = True,
) -> None:
    """Explicitly configure the SDK.  Call once at application startup."""
    global _config
    _config = SDKConfig(
        backend=backend,
        queue_file=queue_file,
        api_url=api_url,
        api_key=api_key,
        enabled=enabled,
    )
    _resolve(_config)


def _get_config() -> SDKConfig:
    """Return config, building it lazily from env / auto-detection if needed."""
    global _config
    if _config is None:
        _config = _build_from_env()
        _resolve(_config)
    return _config


def _build_from_env() -> SDKConfig:
    cfg = SDKConfig(
        backend=os.environ.get("EVALFIX_BACKEND", "file"),
        queue_file=os.environ.get("EVALFIX_QUEUE_FILE"),
        api_url=os.environ.get("EVALFIX_API_URL"),
        api_key=os.environ.get("EVALFIX_API_KEY"),
        enabled=os.environ.get("EVALFIX_ENABLED", "1").lower() not in ("0", "false", "no"),
    )
    return cfg


def _resolve(cfg: SDKConfig) -> None:
    """Populate _resolved_queue_file by auto-detecting .evalfix/ if needed."""
    if cfg.queue_file:
        cfg._resolved_queue_file = str(Path(cfg.queue_file).expanduser().resolve())
        return

    # Walk up from cwd looking for an existing .evalfix/ directory.
    evalfix_dir = _find_evalfix_dir(Path.cwd())
    if evalfix_dir is None:
        # Fall back to cwd/.evalfix/
        evalfix_dir = Path.cwd() / ".evalfix"

    cfg._resolved_queue_file = str(evalfix_dir / "failures.jsonl")


def _find_evalfix_dir(start: Path) -> Optional[Path]:
    """Walk *start* and its parents looking for a .evalfix/ directory."""
    current = start.resolve()
    for _ in range(8):  # cap at 8 levels to avoid infinite loops
        candidate = current / ".evalfix"
        if candidate.is_dir():
            return candidate
        parent = current.parent
        if parent == current:
            break
        current = parent
    return None
