"""
evalfix_sdk/_queue.py

In-memory queue + background daemon thread that drains to the writer.

Design goals:
- capture() enqueues and returns immediately (never blocks caller)
- Daemon thread means it dies automatically when the process exits
- If the writer fails, entries are dropped silently (never propagate to caller)
"""
from __future__ import annotations

import queue
import threading
from typing import TYPE_CHECKING, Callable, Dict, Any

if TYPE_CHECKING:
    pass

# Bounded at 10 000 entries; if full, new captures are dropped silently.
_Q: "queue.Queue[Dict[str, Any]]" = queue.Queue(maxsize=10_000)
_started = False
_lock = threading.Lock()


def enqueue(record: Dict[str, Any]) -> None:
    """Put *record* on the queue.  Drops silently if the queue is full."""
    try:
        _Q.put_nowait(record)
    except queue.Full:
        pass  # drop — never raise


def start_drain_thread(writer_fn: Callable[[Dict[str, Any]], None]) -> None:
    """Start the background drain thread (idempotent)."""
    global _started
    with _lock:
        if _started:
            return
        _started = True

    t = threading.Thread(
        target=_drain_loop,
        args=(writer_fn,),
        daemon=True,
        name="evalfix-drain",
    )
    t.start()


def drain_all(writer_fn: Callable[[Dict[str, Any]], None]) -> int:
    """Drain everything currently in the queue synchronously.

    Called by the CLI at sync time to flush captured failures before
    the eval run starts.  Returns the number of records written.
    """
    count = 0
    while True:
        try:
            record = _Q.get_nowait()
        except queue.Empty:
            break
        try:
            writer_fn(record)
            count += 1
        except Exception:
            pass  # drop — never raise
        finally:
            _Q.task_done()
    return count


def _drain_loop(writer_fn: Callable[[Dict[str, Any]], None]) -> None:
    """Background loop: block on queue, write each record."""
    while True:
        try:
            record = _Q.get(timeout=1.0)
        except queue.Empty:
            continue
        try:
            writer_fn(record)
        except Exception:
            pass  # drop — never raise
        finally:
            try:
                _Q.task_done()
            except Exception:
                pass
