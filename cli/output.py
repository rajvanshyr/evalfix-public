"""
cli/output.py

All terminal formatting lives here.  Nothing else should print directly.
Aesthetic: matches the evalfix splash page — dark, minimal, red/green/violet.
"""

from __future__ import annotations

import difflib
import json

from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich import box

console = Console()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _truncate(text: str, max_len: int) -> str:
    text = text.replace("\n", " ").strip()
    return text if len(text) <= max_len else text[: max_len - 1] + "…"


def _score_bar(score: float, width: int = 26) -> str:
    filled = round(max(0.0, min(1.0, score)) * width)
    empty  = width - filled
    return "█" * filled + "░" * empty


def _score_color(score: float) -> str:
    if score >= 0.8:  return "green"
    if score >= 0.5:  return "yellow"
    return "red"


# ---------------------------------------------------------------------------
# Run header — printed before tests start
# ---------------------------------------------------------------------------

def print_run_header(spec, sync_result) -> None:
    from app.models.prompt_version import PromptVersion
    from app.extensions import db
    version = db.session.get(PromptVersion, sync_result.version_id)
    v_num   = version.version_number if version else "?"
    console.print()
    console.print(f"  [bold]{spec.name}[/bold]  [dim]·  v{v_num}  ·  {spec.model}[/dim]")
    console.print()


# ---------------------------------------------------------------------------
# Live per-test result — called by the evaluator callback
# ---------------------------------------------------------------------------

def print_test_result_live(tc, result) -> None:
    name  = _truncate(tc.name or tc.id or "", 24)
    score = result.score
    input_text = _truncate(
        tc.input_variables.get("input", "") if tc.input_variables else "", 40
    )

    if result.passed:
        icon      = "[green]✓[/green]"
        score_str = f"[green]{score:.2f}[/green]" if score is not None else "[green] — [/green]"
    else:
        icon      = "[red]✗[/red]"
        score_str = f"[red]{score:.2f}[/red]" if score is not None else "[red] — [/red]"

    console.print(
        f"  {icon}  [bold]{name:<24}[/bold]  {score_str}  [dim]{input_text}[/dim]"
    )


# ---------------------------------------------------------------------------
# Run summary — printed after all tests complete
# ---------------------------------------------------------------------------

def print_run_summary(spec, sync_result, test_run, result_rows, as_json: bool = False):
    if as_json:
        _print_json(test_run, result_rows)
        return

    _print_summary_block(spec, sync_result, test_run)
    _print_failure_boxes(result_rows)
    _print_footer(test_run)


def _print_summary_block(spec, sync_result, test_run):
    from app.models.prompt_version import PromptVersion
    from app.extensions import db
    version = db.session.get(PromptVersion, sync_result.version_id)
    v_num   = version.version_number if version else "?"

    score     = test_run.avg_score or 0.0
    score_str = f"{score:.2f}" if test_run.avg_score is not None else "—"
    color     = _score_color(score)
    bar       = _score_bar(score)

    elapsed = ""
    if test_run.started_at and test_run.completed_at:
        secs    = (test_run.completed_at - test_run.started_at).total_seconds()
        elapsed = f"  ·  {secs:.1f}s"

    all_pass = test_run.fail_count == 0
    badge    = "[bold green]● PASSING[/bold green]" if all_pass else "[bold red]✗ FAILING[/bold red]"

    console.print()
    console.print(Rule(style="dim"))
    console.print()
    console.print(
        f"  {badge}  [dim]{test_run.pass_count} passed · "
        f"{test_run.fail_count} failed{elapsed}[/dim]"
    )
    console.print()
    console.print(
        f"  [dim]score[/dim]  [{color}]{bar}[/{color}]  [{color}]{score_str}[/{color}]"
    )
    console.print()


def _print_failure_boxes(result_rows):
    failed = [(r, tc) for r, tc in result_rows if not r.passed]
    if not failed:
        return

    for result, tc in failed:
        name       = tc.name or tc.id or ""
        input_text = _truncate(
            tc.input_variables.get("input", "") if tc.input_variables else "", 60
        )
        actual     = _truncate(result.actual_output or "", 60)
        expected   = _truncate(tc.expected_output or tc.description or "", 60)

        lines = [f"[red]✗[/red]  [bold]{name}[/bold]"]
        if input_text:
            lines.append(f"   [dim]input[/dim]     {input_text}")
        if actual:
            lines.append(f"   [dim]got[/dim]       {actual}")
        if expected:
            lines.append(f"   [dim]expected[/dim]  {expected}")
        if result.judge_reasoning:
            lines.append(f"   [dim italic]{_truncate(result.judge_reasoning, 80)}[/dim italic]")
        if result.error:
            lines.append(f"   [red]error: {result.error}[/red]")

        console.print(
            Panel("\n".join(lines), box=box.ROUNDED, border_style="red", padding=(0, 1))
        )


def _print_footer(test_run):
    if test_run.fail_count > 0:
        console.print(
            "  [dim]Run [bold]evalfix fix[/bold] to generate an AI-powered fix.[/dim]\n"
        )
    else:
        console.print()


# ---------------------------------------------------------------------------
# JSON output
# ---------------------------------------------------------------------------

def _print_json(test_run, result_rows):
    output = {
        "status":      test_run.status,
        "pass_count":  test_run.pass_count,
        "fail_count":  test_run.fail_count,
        "total_count": test_run.total_count,
        "avg_score":   test_run.avg_score,
        "results": [
            {
                "test_id":         tc.name,
                "input":           tc.input_variables.get("input", "") if tc.input_variables else "",
                "expected":        tc.expected_output or "",
                "actual":          result.actual_output or "",
                "passed":          result.passed,
                "score":           result.score,
                "latency_ms":      result.latency_ms,
                "judge_reasoning": result.judge_reasoning,
                "error":           result.error,
            }
            for result, tc in result_rows
        ],
    }
    console.print_json(json.dumps(output))


# ---------------------------------------------------------------------------
# Fix / optimizer output
# ---------------------------------------------------------------------------

def print_optimizer_header(fail_count: int) -> None:
    console.print()
    console.print(Rule(style="dim"))
    console.print()
    console.print(
        f"  [bold yellow]◌ OPTIMIZING[/bold yellow]  "
        f"[dim]fixing {fail_count} failure{'s' if fail_count != 1 else ''}...[/dim]"
    )
    console.print()


def print_optimizer_step(message: str) -> None:
    console.print(f"  [dim]▸[/dim]  [dim]{message}[/dim]")


def print_iteration_header(i: int, total: int) -> None:
    if i > 1:
        console.print()
    console.print(f"  [dim]── iteration {i} of {total} ──[/dim]")
    console.print()


def print_root_cause(root_cause) -> None:
    lines = []
    if root_cause.failure_patterns:
        lines.append("[dim]failure patterns[/dim]")
        for p in root_cause.failure_patterns:
            lines.append(f"  [yellow]▸[/yellow] {p}")
    if root_cause.prompt_issues:
        if lines:
            lines.append("")
        lines.append("[dim]prompt issues[/dim]")
        for p in root_cause.prompt_issues:
            lines.append(f"  [red]▸[/red] {p}")
    c     = root_cause.confidence
    color = "green" if c >= 0.7 else "yellow"
    if lines:
        lines.append("")
    lines.append(f"[dim]confidence[/dim]  [{color}]{c:.0%}[/{color}]")

    console.print(
        Panel(
            "\n".join(lines),
            title="[bold]root cause[/bold]",
            box=box.ROUNDED,
            border_style="dim",
            padding=(0, 1),
        )
    )


def print_diff(opt_run, old_prompt: str, new_prompt: str) -> None:
    console.print()
    console.print(Rule(style="dim"))
    console.print()
    console.print("  [dim]prompt diff[/dim]")
    console.print()

    old_lines = old_prompt.splitlines()
    new_lines = new_prompt.splitlines()
    diff      = list(difflib.unified_diff(
        old_lines, new_lines, fromfile="current", tofile="improved", lineterm=""
    ))

    if not diff:
        console.print("  [dim](no textual changes)[/dim]")
    else:
        for line in diff:
            if line.startswith("+++") or line.startswith("---"):
                console.print(f"  [dim]{line}[/dim]")
            elif line.startswith("@@"):
                console.print(f"  [dim]{line}[/dim]")
            elif line.startswith("+"):
                console.print(f"  [green]{line}[/green]")
            elif line.startswith("-"):
                console.print(f"  [red]{line}[/red]")
            else:
                console.print(f"  [dim]{line}[/dim]")

    if opt_run.reasoning:
        console.print()
        console.print("  [dim]reasoning[/dim]")
        console.print()
        console.print(
            Panel(
                f"[dim]{opt_run.reasoning}[/dim]",
                box=box.ROUNDED,
                border_style="dim",
                padding=(0, 1),
            )
        )
    console.print()


def print_fix_summary(
    before_score: float | None,
    after_score:  float | None,
    before_fails: int,
    after_fails:  int,
) -> None:
    b      = f"{before_score:.2f}" if before_score is not None else "—"
    a      = f"{after_score:.2f}"  if after_score  is not None else "—"
    color  = _score_color(after_score or 0.0)
    arrow  = "[green]↑[/green]" if (after_score or 0) > (before_score or 0) else "[red]↓[/red]"

    before_bar = _score_bar(before_score or 0.0)
    after_bar  = _score_bar(after_score  or 0.0)

    console.print(
        Panel(
            f"  [dim]before[/dim]  [red]{before_bar}[/red]  [red]{b}[/red]  [dim]({before_fails} failed)[/dim]\n"
            f"  [dim]after [/dim]  [{color}]{after_bar}[/{color}]  [{color}]{a}[/{color}]  [dim]({after_fails} failed)[/dim]\n\n"
            f"  score  [red]{b}[/red]  {arrow}  [{color}]{a}[/{color}]",
            title="[bold green]✓ fixed[/bold green]",
            box=box.ROUNDED,
            border_style="green",
            padding=(0, 1),
        )
    )
    console.print()


def print_multi_agent_failure(result) -> None:
    console.print()
    console.print(
        Panel(
            f"[red]Could not auto-fix after {result.iterations} "
            f"iteration{'s' if result.iterations != 1 else ''}.[/red]\n\n"
            "The root cause analysis below may help you fix it manually.",
            box=box.ROUNDED,
            border_style="red",
            padding=(0, 1),
        )
    )
    for it in result.history:
        console.print(f"\n  [dim]iteration {it.iteration}[/dim]")
        console.print(f"  [dim]fix attempted:[/dim] {it.candidate_fix.changes_summary}")
        if it.screened_out:
            console.print("  [yellow]⚠ blocked by regression screener[/yellow]")
        else:
            score = f"{it.avg_score:.2f}" if it.avg_score is not None else "—"
            console.print(
                f"  [green]{it.pass_count} passed[/green]  "
                f"[red]{it.fail_count} failed[/red]  [dim]score {score}[/dim]"
            )
    if result.history:
        console.print()
        print_root_cause(result.history[-1].root_cause)

    if result.next_steps:
        _print_next_steps(result.next_steps)


_STEP_TYPE_STYLE = {
    "PROMPT_CHANGE":  ("violet",  "prompt"),
    "CODE_CHANGE":    ("cyan",    "code"),
    "TEST_CHANGE":    ("yellow",  "test"),
    "PROCESS_CHANGE": ("blue",    "process"),
    "MODEL_CHANGE":   ("magenta", "model"),
}


def _print_next_steps(advice) -> None:
    console.print()
    console.rule("[bold]what to do next[/bold]", style="dim")
    console.print()
    if advice.summary:
        console.print(f"  [dim]{advice.summary}[/dim]\n")

    for i, step in enumerate(advice.next_steps, 1):
        color, label = _STEP_TYPE_STYLE.get(step.type, ("white", step.type.lower()))
        console.print(
            f"  [bold]{i}.[/bold] [{color}][{label}][/{color}]  [bold]{step.title}[/bold]"
        )
        console.print(f"     [dim]{step.description}[/dim]\n")


# ---------------------------------------------------------------------------
# Simple helpers
# ---------------------------------------------------------------------------

def print_error(message: str):
    console.print(f"\n  [bold red]✗[/bold red]  {message}\n")


def print_info(message: str):
    console.print(f"  [dim]{message}[/dim]")


def print_success(message: str):
    console.print(f"\n  [bold green]✓[/bold green]  {message}\n")
