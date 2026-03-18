from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent.parent / ".env")

from cli.output import console, print_error, print_success


# Default file contents written when they don't already exist
_DEFAULT_CONFIG = """\
model: claude-haiku-4-5-20251001
temperature: 1.0
max_tokens: 1024
"""

_DEFAULT_TOOLS = "[]\n"


def run(directory: str, model: str) -> None:
    path = Path(directory).expanduser().resolve()

    # ── 1. Create or validate directory ──────────────────────────────────────
    if path.exists() and not path.is_dir():
        print_error(f"{path} exists and is not a directory.")
        sys.exit(1)

    path.mkdir(parents=True, exist_ok=True)

    # ── 2. Get the system prompt ──────────────────────────────────────────────
    prompt_file = path / "prompt.txt"

    if prompt_file.exists():
        prompt_text = prompt_file.read_text(encoding="utf-8").strip()
        if not prompt_text:
            print_error("prompt.txt exists but is empty. Add your system prompt and re-run.")
            sys.exit(1)
        console.print(f"[dim]Using existing prompt.txt ({len(prompt_text)} chars)[/dim]")
    else:
        console.print(
            "\n[bold]Paste your system prompt below.[/bold]  "
            "Press [bold]Enter[/bold] twice when done.\n"
        )
        lines: list[str] = []
        try:
            while True:
                line = input()
                if line == "" and lines and lines[-1] == "":
                    break
                lines.append(line)
        except EOFError:
            pass

        prompt_text = "\n".join(lines).strip()
        if not prompt_text:
            print_error("No prompt entered. Exiting.")
            sys.exit(1)

        prompt_file.write_text(prompt_text, encoding="utf-8")
        print_success("prompt.txt written.")

    # ── 3. Collect optional example interactions ──────────────────────────────
    evals_file = path / "evals.yaml"

    if evals_file.exists():
        console.print(f"[dim]evals.yaml already exists — skipping generation.[/dim]")
        _write_support_files(path)
        console.print(f"\n[bold green]✓ {path.name}[/bold green] is ready.\n")
        console.print(f"  [dim]Run:[/dim]  evalfix run {directory}\n")
        return

    console.print(
        "\n[bold]Add up to 3 example user messages[/bold] to help generate better evals.  "
        "Press [bold]Enter[/bold] to skip.\n"
    )
    examples: list[str] = []
    for i in range(1, 4):
        try:
            val = input(f"  Example {i}: ").strip()
        except EOFError:
            break
        if val:
            examples.append(val)
        else:
            break

    # ── 4. Generate evals.yaml via Claude ────────────────────────────────────
    console.print()
    with console.status("[dim]Generating eval suite with Claude...[/dim]"):
        try:
            from cli.init_generator import generate
            yaml_str = generate(prompt=prompt_text, examples=examples, model=model)
        except Exception as e:
            print_error(f"Generation failed: {e}")
            sys.exit(1)

    # Validate the YAML parses and has tests before writing
    try:
        import yaml
        parsed = yaml.safe_load(yaml_str)
        n_tests = len(parsed.get("tests", []))
        if n_tests == 0:
            raise ValueError("No tests in generated YAML")
    except Exception as e:
        print_error(f"Claude returned invalid YAML: {e}\n\nRaw output:\n{yaml_str}")
        sys.exit(1)

    evals_file.write_text(yaml_str, encoding="utf-8")
    print_success(f"evals.yaml written — {n_tests} test cases generated.")

    # ── 5. Write support files ────────────────────────────────────────────────
    _write_support_files(path)

    # ── 6. Done ───────────────────────────────────────────────────────────────
    console.print(f"\n[bold green]✓ {path.name}[/bold green] is ready.\n")
    console.print(f"  [dim]Run:[/dim]  evalfix run {directory}\n")


def _write_support_files(path: Path) -> None:
    config_file = path / "config.yaml"
    if not config_file.exists():
        config_file.write_text(_DEFAULT_CONFIG, encoding="utf-8")
        print_success("config.yaml written.")

    tools_file = path / "tools.json"
    if not tools_file.exists():
        tools_file.write_text(_DEFAULT_TOOLS, encoding="utf-8")
        print_success("tools.json written.")
