"""
cli/project.py

Reads and writes the on-disk project format:

    my-project/
        prompt.txt      current system prompt
        evals.yaml      test suite definition
        config.yaml     model settings
        tools.json      optional tool definitions
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import yaml


# ---------------------------------------------------------------------------
# Grader type mapping  (folder format → DB eval_method)
# ---------------------------------------------------------------------------

GRADER_TO_EVAL_METHOD: dict[str, str] = {
    "semantic": "llm_judge",
    "exact":    "exact",
    "contains": "contains",
    "regex":    "regex",
}

DEFAULT_GRADER = "semantic"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class TestSpec:
    id: str
    input: str
    expected: str                   # expected behaviour description
    grader: str = DEFAULT_GRADER    # semantic | exact | contains | regex
    expected_output: str | None = None  # optional literal expected output

    @property
    def eval_method(self) -> str:
        """Translate the folder-format grader name to the DB eval_method."""
        return GRADER_TO_EVAL_METHOD.get(self.grader, "llm_judge")

    @classmethod
    def from_dict(cls, data: dict) -> "TestSpec":
        grader = data.get("grader", DEFAULT_GRADER)
        if grader not in GRADER_TO_EVAL_METHOD:
            raise ProjectSpecError(
                f"Unknown grader '{grader}' in test '{data.get('id', '?')}'. "
                f"Valid options: {', '.join(GRADER_TO_EVAL_METHOD)}"
            )
        return cls(
            id=str(data["id"]),
            input=str(data["input"]),
            expected=str(data["expected"]),
            grader=grader,
            expected_output=data.get("expected_output"),
        )


@dataclass
class ProjectSpec:
    path: Path
    prompt: str
    tests: list[TestSpec]
    config: dict = field(default_factory=dict)
    tools: list[dict] | None = None

    # ------------------------------------------------------------------
    # Factories
    # ------------------------------------------------------------------

    @classmethod
    def load(cls, directory: str | Path) -> "ProjectSpec":
        """Load a project from *directory*.

        Raises ProjectSpecError with a clear message for any missing or
        malformed file so the CLI can surface it without a traceback.
        """
        path = Path(directory).expanduser().resolve()

        if not path.exists():
            raise ProjectSpecError(
                f"Directory not found: {path}\n"
                f"Run `evalfix init {directory}` to create it."
            )
        if not path.is_dir():
            raise ProjectSpecError(f"{path} is not a directory.")

        prompt  = cls._read_prompt(path)
        tests   = cls._read_evals(path)
        config  = cls._read_config(path)
        tools   = cls._read_tools(path)

        return cls(path=path, prompt=prompt, tests=tests,
                   config=config, tools=tools)

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def write_prompt(self, content: str) -> None:
        """Overwrite prompt.txt with *content*."""
        prompt_file = self.path / "prompt.txt"
        prompt_file.write_text(content, encoding="utf-8")
        self.prompt = content

    # ------------------------------------------------------------------
    # Convenience properties
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def model(self) -> str:
        return self.config.get("model", "claude-sonnet-4-6")

    @property
    def temperature(self) -> float:
        return float(self.config.get("temperature", 1.0))

    @property
    def max_tokens(self) -> int:
        return int(self.config.get("max_tokens", 1024))

    # ------------------------------------------------------------------
    # Private readers
    # ------------------------------------------------------------------

    @staticmethod
    def _read_prompt(path: Path) -> str:
        f = path / "prompt.txt"
        if not f.exists():
            raise ProjectSpecError(
                f"Missing prompt.txt in {path}.\n"
                f"Create it with your system prompt, or run `evalfix init {path}`."
            )
        content = f.read_text(encoding="utf-8").strip()
        if not content:
            raise ProjectSpecError(f"prompt.txt in {path} is empty.")
        return content

    @staticmethod
    def _read_evals(path: Path) -> list[TestSpec]:
        f = path / "evals.yaml"
        if not f.exists():
            raise ProjectSpecError(
                f"Missing evals.yaml in {path}.\n"
                f"Run `evalfix init {path}` to generate one."
            )
        try:
            data = yaml.safe_load(f.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise ProjectSpecError(f"Could not parse evals.yaml: {exc}") from exc

        if not isinstance(data, dict) or "tests" not in data:
            raise ProjectSpecError(
                "evals.yaml must have a top-level 'tests' key.\n"
                "Example:\n  tests:\n    - id: my_test\n      input: ...\n      expected: ..."
            )

        raw_tests = data["tests"]
        if not isinstance(raw_tests, list) or len(raw_tests) == 0:
            raise ProjectSpecError("evals.yaml 'tests' list is empty.")

        tests: list[TestSpec] = []
        for i, item in enumerate(raw_tests):
            if not isinstance(item, dict):
                raise ProjectSpecError(
                    f"evals.yaml test #{i + 1} is not a mapping."
                )
            for required in ("id", "input", "expected"):
                if required not in item:
                    raise ProjectSpecError(
                        f"evals.yaml test #{i + 1} is missing required field '{required}'."
                    )
            tests.append(TestSpec.from_dict(item))

        # Catch duplicate IDs early
        seen: set[str] = set()
        for t in tests:
            if t.id in seen:
                raise ProjectSpecError(
                    f"Duplicate test id '{t.id}' in evals.yaml."
                )
            seen.add(t.id)

        return tests

    @staticmethod
    def _read_config(path: Path) -> dict:
        f = path / "config.yaml"
        if not f.exists():
            return {}
        try:
            data = yaml.safe_load(f.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise ProjectSpecError(f"Could not parse config.yaml: {exc}") from exc
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _read_tools(path: Path) -> list[dict] | None:
        f = path / "tools.json"
        if not f.exists():
            return None
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ProjectSpecError(f"Could not parse tools.json: {exc}") from exc
        if not isinstance(data, list):
            raise ProjectSpecError("tools.json must be a JSON array.")
        return data or None


# ---------------------------------------------------------------------------
# Error type
# ---------------------------------------------------------------------------

class ProjectSpecError(Exception):
    """Raised when a project folder is missing or malformed."""
