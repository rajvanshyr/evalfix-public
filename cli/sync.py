"""
cli/sync.py

Bridges a ProjectSpec (folder on disk) to the DB records that the existing
evaluator and optimizer services expect.

Call sync_project(spec) inside a Flask app context.  It upserts:

    Project  →  Prompt  →  PromptVersion  →  TestCases

and returns a SyncResult with the IDs the commands need.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from app.extensions import db
from app.models.project import Project
from app.models.prompt import Prompt
from app.models.prompt_version import PromptVersion
from app.models.test_case import TestCase

from cli.project import ProjectSpec, TestSpec


# ---------------------------------------------------------------------------
# SDK failure ingestion
# ---------------------------------------------------------------------------

def _ingest_sdk_queue(spec: ProjectSpec) -> int:
    """Drain the evalfix-sdk failure queue into the DB as test cases.

    Reads .evalfix/failures.jsonl (written by evalfix_sdk.capture() in
    production), converts each record to a TestCase, then clears the file.
    Returns the number of failures ingested.

    Silently no-ops if evalfix-sdk is not installed or the file is missing.
    """
    try:
        from evalfix_sdk._writer import read_all, clear_file
    except ImportError:
        return 0

    try:
        # Always use the spec's own .evalfix/ directory, not the auto-detected one.
        from pathlib import Path as _Path
        queue_file = str(_Path(spec.path) / ".evalfix" / "failures.jsonl")

        records = read_all(queue_file)
        if not records:
            return 0

        # We need the prompt_id — resolve it the same way sync_project does
        # but without re-running the full sync.  We look up (or create) the
        # project + prompt records, then upsert test cases from the failures.
        cli_key = f"cli:{spec.path}"
        project = Project.query.filter_by(description=cli_key).first()
        if project is None:
            return 0  # project hasn't been synced yet

        prompt = Prompt.query.filter_by(project_id=project.id, name="main").first()
        if prompt is None:
            return 0

        existing = {
            tc.name: tc
            for tc in TestCase.query.filter_by(prompt_id=prompt.id).all()
        }

        ingested = 0
        for rec in records:
            if not rec.get("input") or not rec.get("output"):
                continue

            # Derive a stable name from the record id so re-ingestion is safe.
            rec_id = rec.get("id", "")
            name = f"captured:{rec_id[:8]}" if rec_id else f"captured:{ingested}"

            if name in existing:
                continue  # already ingested this record

            tc = TestCase(
                prompt_id=prompt.id,
                name=name,
                description=rec.get("expected") or "Production failure capture",
                input_variables={"input": rec["input"]},
                expected_output=rec.get("expected") or rec["output"],
                eval_method="llm_judge",
                eval_config={
                    "actual_output": rec["output"],
                    "captured_score": rec.get("score"),
                    "tags": rec.get("tags", []),
                    "metadata": rec.get("metadata", {}),
                },
                source="sdk",
            )
            db.session.add(tc)
            ingested += 1

        if ingested:
            db.session.commit()

        clear_file(queue_file)
        return ingested

    except Exception:
        return 0


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------

@dataclass
class SyncResult:
    project_id: str
    prompt_id: str
    version_id: str
    test_case_ids: list[str] = field(default_factory=list)
    version_created: bool = False       # True when prompt.txt changed → new version minted
    sdk_failures_ingested: int = 0      # Number of failures ingested from evalfix-sdk queue


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def sync_project(spec: ProjectSpec) -> SyncResult:
    """Upsert all DB records for *spec*.  Must run inside a Flask app context."""
    project        = _upsert_project(spec)
    prompt         = _upsert_prompt(spec, project.id)

    # Ingest production failures captured via evalfix-sdk before running evals.
    sdk_ingested = _ingest_sdk_queue(spec)

    version, new   = _upsert_version(spec, prompt)
    test_case_ids  = _upsert_test_cases(spec, prompt.id)

    return SyncResult(
        project_id=project.id,
        prompt_id=prompt.id,
        version_id=version.id,
        test_case_ids=test_case_ids,
        version_created=new,
        sdk_failures_ingested=sdk_ingested,
    )


# ---------------------------------------------------------------------------
# Upsert helpers
# ---------------------------------------------------------------------------

def _upsert_project(spec: ProjectSpec) -> Project:
    # Keyed on absolute path stored as "cli:<path>" in description.
    # This means two different folders with the same name stay separate.
    cli_key = f"cli:{spec.path}"
    project = Project.query.filter_by(description=cli_key).first()
    if project is None:
        project = Project(name=spec.name, description=cli_key)
        db.session.add(project)
        db.session.flush()
    return project


def _upsert_prompt(spec: ProjectSpec, project_id: str) -> Prompt:
    prompt = Prompt.query.filter_by(project_id=project_id, name="main").first()
    if prompt is None:
        prompt = Prompt(
            project_id=project_id,
            name="main",
            description=f"CLI prompt for {spec.name}",
        )
        db.session.add(prompt)
        db.session.flush()
    return prompt


def _upsert_version(spec: ProjectSpec, prompt: Prompt) -> tuple[PromptVersion, bool]:
    """Return (version, created).

    Only mints a new PromptVersion when prompt.txt content has changed.
    Running evalfix run twice on an unchanged prompt reuses the same version.
    """
    chat_content = _to_chat_content(spec.prompt)

    # Check whether the current active version already has this exact content.
    if prompt.current_version_id:
        current = db.session.get(PromptVersion, prompt.current_version_id)
        if current and current.content == chat_content:
            # Nothing changed — update model/params in place so config.yaml
            # changes still take effect without creating a new version.
            current.model = spec.model
            current.parameters = {
                "temperature": spec.temperature,
                "max_tokens":  spec.max_tokens,
            }
            db.session.flush()
            return current, False

    # Prompt content changed (or no version exists yet) — mint a new version.
    existing_count = PromptVersion.query.filter_by(prompt_id=prompt.id).count()

    version = PromptVersion(
        prompt_id=prompt.id,
        version_number=existing_count + 1,
        content_type="chat",
        content=chat_content,
        model=spec.model,
        parameters={
            "temperature": spec.temperature,
            "max_tokens":  spec.max_tokens,
        },
        source="cli",
        status="active",
    )
    db.session.add(version)
    db.session.flush()

    # Archive the previous active version.
    if prompt.current_version_id:
        old = db.session.get(PromptVersion, prompt.current_version_id)
        if old:
            old.status = "archived"

    prompt.current_version_id = version.id
    db.session.flush()

    return version, True


def _upsert_test_cases(spec: ProjectSpec, prompt_id: str) -> list[str]:
    """Upsert one TestCase per TestSpec.

    Test cases are keyed on the test id from evals.yaml (stored in the
    name column).  Existing cases are updated when their definition changes;
    new cases are inserted; cases removed from evals.yaml are left alone
    (they stay in the DB for historical runs).
    """
    existing: dict[str, TestCase] = {
        tc.name: tc
        for tc in TestCase.query.filter_by(prompt_id=prompt_id).all()
    }

    ids: list[str] = []
    for test in spec.tests:
        expected_output, eval_config = _eval_fields(test)

        if test.id in existing:
            tc = existing[test.id]
            tc.input_variables = {"input": test.input}
            tc.expected_output = expected_output
            tc.eval_method     = test.eval_method
            tc.eval_config     = eval_config
            tc.description     = test.expected
        else:
            tc = TestCase(
                prompt_id=prompt_id,
                name=test.id,
                description=test.expected,
                input_variables={"input": test.input},
                expected_output=expected_output,
                eval_method=test.eval_method,
                eval_config=eval_config,
                source="cli",
            )
            db.session.add(tc)

        db.session.flush()
        ids.append(tc.id)

    db.session.commit()
    return ids


# ---------------------------------------------------------------------------
# Translation helpers
# ---------------------------------------------------------------------------

def _to_chat_content(prompt_text: str) -> str:
    """Wrap a plain system prompt into the chat JSON the evaluator expects.

    The evaluator calls str.format(**input_variables) on each message's
    content, so the user turn uses {input} as the placeholder for the test
    case's input field.
    """
    messages = [
        {"role": "system", "content": prompt_text},
        {"role": "user",   "content": "{input}"},
    ]
    return json.dumps(messages)


def _eval_fields(test: TestSpec) -> tuple[str, dict]:
    """Return (expected_output, eval_config) for a TestSpec.

    grader → DB eval_method mapping is handled by TestSpec.eval_method.
    Here we decide what to put in expected_output and eval_config.

    semantic  →  expected_output = behaviour description (judge reads it)
    exact     →  expected_output = literal string to match
    contains  →  expected_output = substring to look for
    regex     →  expected_output = pattern; also stored in eval_config
    """
    if test.grader == "semantic":
        return test.expected, {}

    if test.grader in ("exact", "contains"):
        return test.expected_output or test.expected, {}

    if test.grader == "regex":
        pattern = test.expected_output or test.expected
        return pattern, {"pattern": pattern}

    # Unreachable after ProjectSpec validation, but be safe.
    return test.expected, {}
