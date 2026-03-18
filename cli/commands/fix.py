from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv
load_dotenv(_ROOT / ".env")

from cli.output import console, print_error, print_success


def run(directory: str, model_override: str | None, auto_accept: bool) -> None:
    from cli.project import ProjectSpec, ProjectSpecError

    try:
        spec = ProjectSpec.load(directory)
    except ProjectSpecError as e:
        print_error(str(e))
        sys.exit(1)

    if model_override:
        spec.config["model"] = model_override

    from app import create_app
    app = create_app()

    with app.app_context():
        from app.extensions import db
        db.create_all()
        from app.models.test_run import TestRun
        from app.models.test_result import TestResult
        from app.models.test_case import TestCase
        from app.models.prompt_version import PromptVersion
        from app.models.prompt import Prompt
        from app.services.evaluator import run_test_run
        from app.services.multi_agent_optimizer import run as multi_agent_run
        from cli.sync import sync_project
        from cli.output import (
            print_run_summary, print_diff, print_fix_summary,
            print_root_cause, print_multi_agent_failure,
            print_optimizer_header, print_optimizer_step,
        )

        # ── 1. Sync + initial eval run ────────────────────────────────────────
        sync_result = sync_project(spec)

        if sync_result.sdk_failures_ingested:
            console.print(
                f"  [dim]Ingested {sync_result.sdk_failures_ingested} "
                f"production failure{'s' if sync_result.sdk_failures_ingested != 1 else ''} "
                f"from evalfix-sdk.[/dim]"
            )

        from cli.output import print_run_header, print_test_result_live
        print_run_header(spec, sync_result)

        test_run = TestRun(
            prompt_version_id=sync_result.version_id,
            triggered_by="cli",
        )
        db.session.add(test_run)
        db.session.commit()

        try:
            run_test_run(test_run.id, on_result=print_test_result_live)
        except Exception as e:
            print_error(f"Evaluator failed: {e}")
            sys.exit(1)

        db.session.refresh(test_run)

        all_test_cases = TestCase.query.filter_by(prompt_id=sync_result.prompt_id).all()
        tc_by_id = {tc.id: tc for tc in all_test_cases}

        results = TestResult.query.filter_by(test_run_id=test_run.id).all()
        result_rows = [
            (r, tc_by_id[r.test_case_id])
            for r in results if r.test_case_id in tc_by_id
        ]

        print_run_summary(spec, sync_result, test_run, result_rows)

        # ── 2. Nothing to fix? ────────────────────────────────────────────────
        if test_run.fail_count == 0:
            print_success("All tests passing — nothing to fix.")
            return

        failed_rows = [(r, tc) for r, tc in result_rows if not r.passed]
        old_prompt  = _extract_system_prompt(
            db.session.get(PromptVersion, sync_result.version_id)
        )

        # ── 3. Multi-agent optimization loop ─────────────────────────────────
        print_optimizer_header(test_run.fail_count)

        try:
            ma_result = multi_agent_run(
                prompt=old_prompt,
                failed_rows=failed_rows,
                all_test_cases=all_test_cases,
                prompt_id=sync_result.prompt_id,
                base_version_id=sync_result.version_id,
                model=spec.model,
                on_progress=print_optimizer_step,
            )
        except Exception as e:
            print_error(f"Multi-agent optimizer failed: {e}")
            sys.exit(1)

        # ── 4. Show iteration summaries ───────────────────────────────────────
        for it in ma_result.history:
            console.print()
            if it.screened_out:
                console.print(
                    f"  [yellow]⚠ regression screener blocked iteration {it.iteration} — retrying[/yellow]"
                )
            else:
                score = f"{it.avg_score:.2f}" if it.avg_score is not None else "—"
                status = "[green]✓[/green]" if it.fail_count == 0 else "[red]✗[/red]"
                console.print(
                    f"  {status}  [dim]iteration {it.iteration}:[/dim]  "
                    f"[green]{it.pass_count} passed[/green]  "
                    f"[red]{it.fail_count} failed[/red]  "
                    f"[dim]score {score}[/dim]"
                )

        # ── 5. Failed to fix ──────────────────────────────────────────────────
        if not ma_result.success:
            print_multi_agent_failure(ma_result)
            sys.exit(1)

        # Reuse print_diff with a mock opt_run that has just the reasoning field
        class _MockOptRun:
            reasoning = ma_result.history[-1].candidate_fix.reasoning

        print_diff(_MockOptRun(), old_prompt, ma_result.final_prompt)

        if auto_accept:
            accept = True
        else:
            try:
                answer = input("Accept this change? [y/N] ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                answer = "n"
            accept = answer in ("y", "yes")

        if not accept:
            console.print("[dim]Change discarded. prompt.txt unchanged.[/dim]\n")
            return

        # ── 7. Write accepted prompt and show before/after summary ────────────
        spec.write_prompt(ma_result.final_prompt)
        print_success("prompt.txt updated.")

        # Promote the last draft version to active
        _promote_last_draft(sync_result.prompt_id, sync_result.version_id, db)

        sync_result2 = sync_project(spec)
        from cli.commands.run import _write_state
        _write_state(directory, _last_test_run(sync_result2.version_id), sync_result2)

        # Final before/after score
        last_it = ma_result.history[-1]
        print_fix_summary(
            before_score=test_run.avg_score,
            after_score=last_it.avg_score,
            before_fails=test_run.fail_count,
            after_fails=last_it.fail_count,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_system_prompt(version) -> str:
    if version and version.content_type == "chat":
        try:
            for msg in json.loads(version.content):
                if msg.get("role") == "system":
                    return msg["content"]
        except (json.JSONDecodeError, KeyError):
            pass
    return version.content if version else ""


def _promote_last_draft(prompt_id: str, old_version_id: str, db) -> None:
    """Promote the most recently created draft version to active."""
    from app.models.prompt_version import PromptVersion
    from app.models.prompt import Prompt

    draft = (
        PromptVersion.query
        .filter_by(prompt_id=prompt_id, status="draft")
        .order_by(PromptVersion.created_at.desc())
        .first()
    )
    if not draft:
        return

    draft.status = "active"
    old = db.session.get(PromptVersion, old_version_id)
    if old:
        old.status = "archived"

    prompt = db.session.get(Prompt, prompt_id)
    if prompt:
        prompt.current_version_id = draft.id

    db.session.commit()


def _last_test_run(version_id: str):
    """Return the most recent TestRun for a version (for state persistence)."""
    from app.models.test_run import TestRun
    return (
        TestRun.query
        .filter_by(prompt_version_id=version_id)
        .order_by(TestRun.created_at.desc())
        .first()
    )
