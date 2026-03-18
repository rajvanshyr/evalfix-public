"""
evalfix_sdk/_http.py

HTTP backend: POST failures directly to an evalfix server.

Uses only stdlib (urllib) so there are zero required dependencies.
Falls back silently on any error.
"""
from __future__ import annotations

import json
import urllib.request
import urllib.error
from typing import Dict, Any, Optional


def post_to_server(
    record: Dict[str, Any],
    api_url: str,
    api_key: Optional[str] = None,
    timeout: float = 5.0,
) -> None:
    """POST *record* as JSON to *api_url*.

    Raises on HTTP errors so the queue's try/except can catch and drop.
    """
    payload = json.dumps(record, default=str).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "evalfix-sdk/0.1.0",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    req = urllib.request.Request(
        url=api_url,
        data=payload,
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        _ = resp.read()  # consume response to allow connection reuse
