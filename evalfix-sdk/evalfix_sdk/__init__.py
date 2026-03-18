"""
evalfix_sdk — capture production LLM failures and feed them back to evalfix.

Minimal usage
-------------
    from evalfix_sdk import capture

    response = my_llm_call(prompt)
    if not looks_good(response):
        capture(
            input="What is 2+2?",
            output=response,
            expected="4",
            metadata={"user_id": "u123"},
        )

The first capture() call auto-detects your evalfix project directory and
starts a background writer thread.  Nothing is ever raised; if the SDK
can't write a record it drops it silently.

Full configuration
------------------
    import evalfix_sdk

    evalfix_sdk.configure(
        backend="file",           # "file" (default) or "http"
        queue_file="/path/to/.evalfix/failures.jsonl",
        # For HTTP backend:
        # api_url="https://...",
        # api_key="...",
        enabled=True,
    )
"""
from __future__ import annotations

import datetime
import uuid
from typing import Any, Dict, Optional

from ._config import configure, _get_config  # noqa: F401 — re-export configure
from ._queue import enqueue, start_drain_thread
from ._writer import write_to_file
from ._http import post_to_server

__all__ = ["capture", "configure"]
__version__ = "0.1.0"

# ── True once the background thread has been started ──────────────────────────
_thread_started = False


def capture(
    *,
    input: str,
    output: str,
    expected: Optional[str] = None,
    score: Optional[float] = None,
    tags: Optional[list] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """Capture a production LLM failure for later review.

    Parameters
    ----------
    input:    The user / system input that was sent to the LLM.
    output:   The actual LLM response.
    expected: What the correct response should have been (optional).
    score:    A numeric quality score 0–1 you computed yourself (optional).
    tags:     Free-form list of strings for filtering (optional).
    metadata: Any JSON-serialisable dict of extra context (optional).

    This function is designed to be called in hot paths:
    - Never raises an exception.
    - Returns immediately (enqueues; a daemon thread writes asynchronously).
    """
    try:
        _capture_inner(
            input=input,
            output=output,
            expected=expected,
            score=score,
            tags=tags or [],
            metadata=metadata or {},
        )
    except Exception:
        pass  # hard guarantee: never propagate


def _capture_inner(
    *,
    input: str,
    output: str,
    expected: Optional[str],
    score: Optional[float],
    tags: list,
    metadata: Dict[str, Any],
) -> None:
    global _thread_started

    cfg = _get_config()
    if not cfg.enabled:
        return

    record: Dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "captured_at": datetime.datetime.utcnow().isoformat() + "Z",
        "input": input,
        "output": output,
        "expected": expected,
        "score": score,
        "tags": tags,
        "metadata": metadata,
    }

    # Enqueue first so the caller returns fast.
    enqueue(record)

    # Start drain thread on first capture (idempotent).
    if not _thread_started:
        _thread_started = True
        _make_writer_fn(cfg)  # side-effect: starts thread


def _make_writer_fn(cfg) -> None:
    """Build the writer function for the configured backend and start drain."""
    if cfg.backend == "http" and cfg.api_url:
        def writer(record: Dict[str, Any]) -> None:
            post_to_server(record, cfg.api_url, cfg.api_key)
    else:
        queue_file = cfg._resolved_queue_file

        def writer(record: Dict[str, Any]) -> None:
            write_to_file(record, queue_file)

    start_drain_thread(writer)
