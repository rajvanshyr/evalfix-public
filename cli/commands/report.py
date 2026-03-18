from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from cli.output import console, print_error


def run(directory: str, write_html: bool) -> None:
    state_file = Path(directory) / ".evalfix" / "last_run.json"

    if not state_file.exists():
        print_error(
            f"No run found for {directory}.\n"
            f"Run `evalfix run {directory}` first."
        )
        sys.exit(1)

    state = json.loads(state_file.read_text())

    from app import create_app
    app = create_app()

    with app.app_context():
        from app.extensions import db
        db.create_all()
        from app.models.test_run import TestRun
        from app.models.test_result import TestResult
        from app.models.test_case import TestCase
        from app.models.prompt_version import PromptVersion
        from cli.project import ProjectSpec, ProjectSpecError
        from cli.sync import SyncResult
        from cli.output import print_run_summary

        test_run = db.session.get(TestRun, state["test_run_id"])
        if not test_run:
            print_error("Run record not found in database.")
            sys.exit(1)

        results = TestResult.query.filter_by(test_run_id=test_run.id).all()
        test_cases = {
            tc.id: tc
            for tc in TestCase.query.filter_by(prompt_id=state["prompt_id"]).all()
        }
        result_rows = [
            (r, test_cases[r.test_case_id])
            for r in results
            if r.test_case_id in test_cases
        ]

        # Reconstruct just enough of spec/sync_result for print_run_summary
        try:
            spec = ProjectSpec.load(directory)
        except ProjectSpecError:
            # Directory may have moved — build a minimal stand-in
            spec = _MinimalSpec(Path(directory).name, state)

        sync_result = SyncResult(
            project_id=state["project_id"],
            prompt_id=state["prompt_id"],
            version_id=state["version_id"],
        )

        print_run_summary(spec, sync_result, test_run, result_rows)

        if write_html:
            html = _render_html(spec, test_run, result_rows)
            out = Path(directory) / "report.html"
            out.write_text(html, encoding="utf-8")
            console.print(f"[dim]Report written to[/dim] [bold]{out}[/bold]\n")


# ---------------------------------------------------------------------------
# Minimal spec stand-in when the directory has moved
# ---------------------------------------------------------------------------

class _MinimalSpec:
    def __init__(self, name: str, state: dict):
        self.name  = name
        self.model = "unknown"
        self.config = {}


# ---------------------------------------------------------------------------
# HTML report
# ---------------------------------------------------------------------------

def _render_html(spec, test_run, result_rows: list) -> str:
    from datetime import timezone

    completed = (
        test_run.completed_at.strftime("%Y-%m-%d %H:%M UTC")
        if test_run.completed_at else "—"
    )
    score = f"{test_run.avg_score:.2f}" if test_run.avg_score is not None else "—"
    status_color = "#22c55e" if test_run.fail_count == 0 else "#ef4444"
    status_label = "PASSED" if test_run.fail_count == 0 else "FAILED"

    rows_html = ""
    for result, tc in result_rows:
        passed       = result.passed
        bg           = "#f0fdf4" if passed else "#fef2f2"
        badge_color  = "#16a34a" if passed else "#dc2626"
        badge_label  = "pass" if passed else "FAIL"
        score_val    = f"{result.score:.2f}" if result.score is not None else "—"
        latency      = f"{result.latency_ms}ms" if result.latency_ms else "—"
        actual       = _he(result.actual_output or "")
        input_val    = _he((tc.input_variables or {}).get("input", ""))
        expected_val = _he(tc.expected_output or tc.description or "")
        reasoning    = (
            f'<div class="reasoning">{_he(result.judge_reasoning)}</div>'
            if result.judge_reasoning else ""
        )
        error = (
            f'<div class="error">error: {_he(result.error)}</div>'
            if result.error else ""
        )

        rows_html += f"""
        <tr style="background:{bg}">
          <td><code>{_he(tc.name or "")}</code></td>
          <td>{input_val}</td>
          <td>{expected_val}</td>
          <td><span class="badge" style="background:{badge_color}">{badge_label}</span></td>
          <td>{score_val}</td>
          <td>{latency}</td>
        </tr>
        {"" if not (reasoning or error) else f'<tr style="background:{bg}"><td></td><td colspan="5">{reasoning}{error}</td></tr>'}
        """

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>evalfix report — {_he(spec.name)}</title>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: Inter, system-ui, sans-serif; background: #09090f; color: #f1f5f9;
            -webkit-font-smoothing: antialiased; padding: 40px 24px; }}
    .wrap {{ max-width: 960px; margin: 0 auto; }}
    .header {{ background: #111118; border: 1px solid #1e1e2e; border-radius: 12px;
               padding: 20px 24px; margin-bottom: 24px; }}
    .header-top {{ display: flex; align-items: center; justify-content: space-between;
                   margin-bottom: 8px; }}
    .project {{ font-size: 20px; font-weight: 700; color: #f1f5f9; }}
    .meta {{ font-size: 13px; color: #64748b; }}
    .status {{ font-size: 13px; font-weight: 700; color: {status_color}; }}
    .stats {{ display: flex; gap: 24px; margin-top: 12px; }}
    .stat {{ font-size: 13px; color: #94a3b8; }}
    .stat span {{ font-weight: 600; color: #f1f5f9; }}
    table {{ width: 100%; border-collapse: collapse; background: #111118;
             border: 1px solid #1e1e2e; border-radius: 12px; overflow: hidden; }}
    th {{ background: #0d0d16; padding: 10px 14px; text-align: left;
          font-size: 11px; font-weight: 600; color: #64748b;
          text-transform: uppercase; letter-spacing: .05em; }}
    td {{ padding: 10px 14px; font-size: 13px; color: #cbd5e1;
          border-top: 1px solid #1e1e2e; vertical-align: top; }}
    code {{ font-family: 'JetBrains Mono', monospace; font-size: 12px; color: #a78bfa; }}
    .badge {{ display: inline-block; padding: 2px 8px; border-radius: 999px;
              font-size: 11px; font-weight: 700; color: #fff; }}
    .reasoning {{ font-size: 12px; color: #94a3b8; font-style: italic; margin-top: 4px; }}
    .error {{ font-size: 12px; color: #f87171; margin-top: 4px; }}
    .footer {{ margin-top: 24px; text-align: center; font-size: 12px; color: #334155; }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="header">
      <div class="header-top">
        <div class="project">{_he(spec.name)}</div>
        <div class="status">{status_label}</div>
      </div>
      <div class="meta">{completed}</div>
      <div class="stats">
        <div class="stat">Tests <span>{test_run.total_count}</span></div>
        <div class="stat">Passed <span style="color:#22c55e">{test_run.pass_count}</span></div>
        <div class="stat">Failed <span style="color:#ef4444">{test_run.fail_count}</span></div>
        <div class="stat">Avg score <span>{score}</span></div>
      </div>
    </div>

    <table>
      <thead>
        <tr>
          <th>Test</th><th>Input</th><th>Expected</th>
          <th>Result</th><th>Score</th><th>Latency</th>
        </tr>
      </thead>
      <tbody>
        {rows_html}
      </tbody>
    </table>

    <div class="footer">Generated by evalfix</div>
  </div>
</body>
</html>"""


def _he(text: str | None) -> str:
    """Minimal HTML escaping."""
    if not text:
        return ""
    return (text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))
