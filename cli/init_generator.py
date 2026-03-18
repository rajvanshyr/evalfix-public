"""
cli/init_generator.py

Calls Claude to generate a starter evals.yaml from a system prompt and
optional example interactions.  Returns a YAML string ready to write to disk.
"""

from __future__ import annotations

import json
import re

import anthropic

META_PROMPT = """\
You are an expert at writing evaluation suites for LLM-powered applications.

Given a system prompt and optional example interactions, generate a diverse
eval suite that covers:
- Happy paths (normal expected usage)
- Edge cases (unusual but valid inputs)
- Failure modes (inputs likely to trip up the prompt)
- Boundary conditions (ambiguous or tricky inputs)

Rules:
- Generate between 6 and 10 test cases
- Each test id must be snake_case and descriptive (e.g. book_appointment_morning)
- The `expected` field describes the BEHAVIOUR you want, not the exact output
- Only set `expected_output` when you want an exact or substring match
- Use `grader: semantic` for most tests (behaviour checks via LLM judge)
- Use `grader: contains` when a specific word/phrase must appear
- Use `grader: exact` only when the output must match precisely
- Use `grader: regex` for structured outputs (dates, numbers, codes)
- Be specific in the `expected` field — vague descriptions make bad evals

Return ONLY valid YAML in this exact format, no markdown fences, no commentary:

tests:
  - id: example_test_id
    input: "user message here"
    expected: "what the assistant should do"
    grader: semantic

  - id: another_test
    input: "another message"
    expected: "expected behaviour"
    grader: contains
    expected_output: "specific phrase"
"""


def generate(
    prompt: str,
    examples: list[str],
    model: str = "claude-sonnet-4-6",
    api_key: str | None = None,
) -> str:
    """Return a YAML string for evals.yaml.

    Args:
        prompt:   The system prompt from prompt.txt.
        examples: List of example user messages (may be empty).
        model:    Claude model to use for generation.
        api_key:  Anthropic API key (reads from env if not supplied).
    """
    user_content = _build_user_message(prompt, examples)

    client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()

    response = client.messages.create(
        model=model,
        max_tokens=2048,
        system=META_PROMPT,
        messages=[{"role": "user", "content": user_content}],
    )

    raw = response.content[0].text.strip()
    return _clean_yaml(raw)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_user_message(prompt: str, examples: list[str]) -> str:
    parts = [f"System prompt:\n\"\"\"\n{prompt}\n\"\"\""]

    if examples:
        formatted = "\n".join(f"  - {e}" for e in examples if e.strip())
        parts.append(f"Example user interactions:\n{formatted}")
    else:
        parts.append("No example interactions provided — infer likely usage from the prompt.")

    return "\n\n".join(parts)


def _clean_yaml(raw: str) -> str:
    """Strip markdown code fences if Claude wrapped the output anyway."""
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        # Drop first and last fence lines
        inner = lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
        # Also strip a leading "yaml" language tag
        if inner and inner[0].strip().lower() == "yaml":
            inner = inner[1:]
        raw = "\n".join(inner).strip()
    return raw
