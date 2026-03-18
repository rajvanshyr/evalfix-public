from __future__ import annotations

import json
import sys
from pathlib import Path

# Ensure the project root (where config.py lives) is on sys.path when the
# CLI is invoked as an installed entry-point outside the source directory.
_ROOT = Path(__file__).parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv
load_dotenv(_ROOT / ".env")

from cli.output import console, print_error


def run(directory: str, model_override: str | None, as_json: bool) -> None:
    from cli.project import ProjectSpec, ProjectSpecError

    # 1. Load project spec from disk
    try:
        spec = ProjectSpec.load(directory)
    except ProjectSpecError as e:
        print_error(str(e))
        sys.exit(1)

    if model_override:
        spec.config["model"] = model_override

    # 2. Bootstrap Flask app context
    from app import create_app
    app = create_app()

    with app.app_context():
        from app.extensions import db
        db.create_all()
        from app.models.test_run import TestRun
        from app.models.test_result import TestResult
        from app.models.test_case import TestCase
        from app.services.evaluator import run_test_run
        from cli.sync import sync_project
        from cli.output import print_run_summary

        # 3. Sync folder → DB records
        sync_result = sync_project(spec)

        if not as_json and sync_result.sdk_failures_ingested:
            console.print(
                f"  [dim]Ingested {sync_result.sdk_failures_ingested} "
                f"production failure{'s' if sync_result.sdk_failures_ingested != 1 else ''} "
                f"from evalfix-sdk.[/dim]"
            )

        if not as_json and sync_result.version_created:
            console.print(
                f"  [dim]New prompt version minted "
                f"(v{_version_number(sync_result.version_id)}).[/dim]"
            )

        # 4. Create TestRun
        test_run = TestRun(
            prompt_version_id=sync_result.version_id,
            triggered_by="cli",
        )
        db.session.add(test_run)
        db.session.commit()

        # 5. Run evals — print header then stream each result live
        if not as_json:
            from cli.output import print_run_header, print_test_result_live
            print_run_header(spec, sync_result)
            callback = print_test_result_live
        else:
            callback = None

        try:
            run_test_run(test_run.id, on_result=callback)
        except Exception as e:
            print_error(f"Evaluator failed: {e}")
            sys.exit(1)

        # 6. Load results from DB
        db.session.refresh(test_run)
        results = (
            TestResult.query
            .filter_by(test_run_id=test_run.id)
            .all()
        )
        test_cases = {
            tc.id: tc
            for tc in TestCase.query.filter_by(prompt_id=sync_result.prompt_id).all()
        }
        result_rows = [
            (r, test_cases[r.test_case_id])
            for r in results
            if r.test_case_id in test_cases
        ]

        # 7. Display
        print_run_summary(spec, sync_result, test_run, result_rows, as_json=as_json)

        # 8. Persist state for `evalfix report`
        _write_state(directory, test_run, sync_result)

        # 9. CI-friendly exit code
        if test_run.fail_count > 0:
            sys.exit(1)


def _version_number(version_id: str) -> str:
    try:
        from app.models.prompt_version import PromptVersion
        from app.extensions import db
        v = db.session.get(PromptVersion, version_id)
        return str(v.version_number) if v else "?"
    except Exception:
        return "?"


def _write_state(directory: str, test_run, sync_result) -> None:
    state_dir = Path(directory) / ".evalfix"
    state_dir.mkdir(exist_ok=True)

    state = {
        "test_run_id": test_run.id,
        "version_id":  sync_result.version_id,
        "project_id":  sync_result.project_id,
        "prompt_id":   sync_result.prompt_id,
        "pass_count":  test_run.pass_count,
        "fail_count":  test_run.fail_count,
        "total_count": test_run.total_count,
        "avg_score":   test_run.avg_score,
        "completed_at": (
            test_run.completed_at.isoformat()
            if test_run.completed_at else None
        ),
    }
    (state_dir / "last_run.json").write_text(json.dumps(state, indent=2))
