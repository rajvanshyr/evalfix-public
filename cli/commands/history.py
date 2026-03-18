from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv
load_dotenv(_ROOT / ".env", override=True)

from cli.output import console, print_error


def run(directory: str, write_html: bool, last_n: int | None) -> None:
    state_file = Path(directory) / ".evalfix" / "last_run.json"

    if not state_file.exists():
        print_error(
            f"No runs found for {directory}.\n"
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
        from app.models.prompt_version import PromptVersion

        # Load all runs for this project's prompt, oldest first
        runs = (
            TestRun.query
            .join(PromptVersion, TestRun.prompt_version_id == PromptVersion.id)
            .filter(PromptVersion.prompt_id == state["prompt_id"])
            .filter(TestRun.status == "completed")
            .order_by(TestRun.created_at.asc())
            .all()
        )

        if not runs:
            print_error("No completed runs found in the database.")
            sys.exit(1)

        if last_n:
            runs = runs[-last_n:]

        # Attach version numbers
        version_cache: dict[str, int] = {}
        def get_version_num(vid: str) -> int:
            if vid not in version_cache:
                v = db.session.get(PromptVersion, vid)
                version_cache[vid] = v.version_number if v else 0
            return version_cache[vid]

        _print_history_table(runs, get_version_num, state["project_id"])

        if write_html:
            html = _render_html(runs, get_version_num, directory)
            out = Path(directory) / "history.html"
            out.write_text(html, encoding="utf-8")
            console.print(f"[dim]History written to[/dim] [bold]{out}[/bold]\n")
            console.print(f"[dim]Open with:[/dim]  open {out}\n")


# ---------------------------------------------------------------------------
# Terminal table
# ---------------------------------------------------------------------------

def _print_history_table(runs, get_version_num, project_id: str) -> None:
    from rich.table import Table
    from rich import box

    # Compute trend arrows
    scores = [r.avg_score for r in runs]

    best_score = max((s for s in scores if s is not None), default=None)
    best_idx   = next(
        (i for i, s in enumerate(scores) if s == best_score), None
    )

    console.print()

    table = Table(
        box=box.SIMPLE_HEAD,
        show_edge=False,
        pad_edge=False,
        header_style="dim",
        title=f"[bold]{Path('.').name}[/bold]  ·  {len(runs)} runs",
        title_justify="left",
    )

    table.add_column("#",        justify="right",  style="dim",   min_width=3)
    table.add_column("Date",     style="dim",                     min_width=14)
    table.add_column("Version",  justify="center",                min_width=7)
    table.add_column("Passed",   justify="center",                min_width=8)
    table.add_column("Failed",   justify="center",                min_width=8)
    table.add_column("Score",    justify="right",                 min_width=7)
    table.add_column("Trend",    justify="center",                min_width=5)
    table.add_column("Trigger",  style="dim",                     min_width=8)

    for i, run in enumerate(runs):
        v_num    = get_version_num(run.prompt_version_id)
        date_str = run.created_at.strftime("%b %d %H:%M") if run.created_at else "—"
        score    = run.avg_score

        # Colour score
        if score is None:
            score_str = "[dim]—[/dim]"
        elif score >= 0.9:
            score_str = f"[bold green]{score:.2f}[/bold green]"
        elif score >= 0.6:
            score_str = f"[yellow]{score:.2f}[/yellow]"
        else:
            score_str = f"[red]{score:.2f}[/red]"

        # Trend arrow vs. previous run
        if i == 0 or scores[i - 1] is None or score is None:
            trend = "[dim]—[/dim]"
        elif score > scores[i - 1]:
            delta = score - scores[i - 1]
            trend = f"[green]↑ +{delta:.2f}[/green]"
        elif score < scores[i - 1]:
            delta = scores[i - 1] - score
            trend = f"[red]↓ -{delta:.2f}[/red]"
        else:
            trend = "[dim]=[/dim]"

        # Star the best run
        is_best  = (i == best_idx)
        run_num  = f"[bold yellow]★ {i+1}[/bold yellow]" if is_best else str(i + 1)
        passed   = f"[green]{run.pass_count}[/green]"
        failed   = f"[red]{run.fail_count}[/red]" if run.fail_count > 0 else "[dim]0[/dim]"
        trigger  = run.triggered_by or "cli"

        table.add_row(run_num, date_str, f"v{v_num}", passed, failed,
                      score_str, trend, trigger)

    console.print(table)

    # Summary line
    if best_score is not None:
        first_score = next((s for s in scores if s is not None), None)
        if first_score is not None and best_score > first_score:
            delta = best_score - first_score
            console.print(
                f"  [dim]Best score[/dim] [bold green]{best_score:.2f}[/bold green]"
                f"  [dim]·  improved[/dim] [green]+{delta:.2f}[/green]"
                f" [dim]since first run[/dim]\n"
            )
    console.print()


# ---------------------------------------------------------------------------
# HTML report with inline SVG score chart
# ---------------------------------------------------------------------------

def _render_html(runs, get_version_num, directory: str) -> str:
    from pathlib import Path

    name = Path(directory).resolve().name

    # Build data points for the chart
    points = []
    for i, run in enumerate(runs):
        points.append({
            "i": i,
            "score": run.avg_score or 0,
            "pass": run.pass_count,
            "fail": run.fail_count,
            "total": run.total_count,
            "version": get_version_num(run.prompt_version_id),
            "date": run.created_at.strftime("%b %d %H:%M") if run.created_at else "",
            "trigger": run.triggered_by or "cli",
        })

    n       = len(points)
    W, H    = 800, 200
    PAD_L   = 40
    PAD_R   = 20
    PAD_T   = 20
    PAD_B   = 30
    chart_w = W - PAD_L - PAD_R
    chart_h = H - PAD_T - PAD_B

    def cx(i):
        return PAD_L + (i / max(n - 1, 1)) * chart_w

    def cy(score):
        return PAD_T + (1 - score) * chart_h

    # SVG polyline
    if n >= 2:
        line_pts = " ".join(f"{cx(p['i']):.1f},{cy(p['score']):.1f}" for p in points)
        polyline = f'<polyline points="{line_pts}" fill="none" stroke="#7c3aed" stroke-width="2.5" stroke-linejoin="round"/>'
    else:
        polyline = ""

    # Dots
    dots = ""
    for p in points:
        color = "#22c55e" if p["score"] >= 0.9 else "#fbbf24" if p["score"] >= 0.6 else "#ef4444"
        dots += (
            f'<circle cx="{cx(p["i"]):.1f}" cy="{cy(p["score"]):.1f}" r="5" '
            f'fill="{color}" stroke="#09090f" stroke-width="2">'
            f'<title>Run {p["i"]+1} · v{p["version"]} · {p["date"]}\n'
            f'Score: {p["score"]:.2f} · {p["pass"]}/{p["total"]} passed</title>'
            f'</circle>'
        )

    # Y-axis gridlines
    grid = ""
    for val in [0.0, 0.25, 0.5, 0.75, 1.0]:
        y = cy(val)
        grid += (
            f'<line x1="{PAD_L}" y1="{y:.1f}" x2="{W-PAD_R}" y2="{y:.1f}" '
            f'stroke="#1e1e2e" stroke-width="1"/>'
            f'<text x="{PAD_L-6}" y="{y+4:.1f}" text-anchor="end" '
            f'font-size="10" fill="#64748b">{val:.2f}</text>'
        )

    # Table rows
    rows_html = ""
    prev_score = None
    for i, p in enumerate(points):
        bg = "#0d0d16" if i % 2 == 0 else "#111118"
        s  = p["score"]
        score_color = "#22c55e" if s >= 0.9 else "#fbbf24" if s >= 0.6 else "#ef4444"

        if prev_score is None:
            trend = "—"
            trend_color = "#64748b"
        elif s > prev_score:
            trend = f"↑ +{s-prev_score:.2f}"
            trend_color = "#22c55e"
        elif s < prev_score:
            trend = f"↓ -{prev_score-s:.2f}"
            trend_color = "#ef4444"
        else:
            trend = "="
            trend_color = "#64748b"

        rows_html += f"""
        <tr style="background:{bg}">
          <td style="color:#64748b">{i+1}</td>
          <td>{p['date']}</td>
          <td style="color:#a78bfa">v{p['version']}</td>
          <td style="color:#22c55e">{p['pass']}</td>
          <td style="color:{'#ef4444' if p['fail'] > 0 else '#64748b'}">{p['fail']}</td>
          <td style="color:{score_color};font-weight:600">{s:.2f}</td>
          <td style="color:{trend_color}">{trend}</td>
          <td style="color:#64748b">{p['trigger']}</td>
        </tr>"""
        prev_score = s

    svg = f"""<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg"
     style="width:100%;height:{H}px;display:block">
  <rect width="{W}" height="{H}" fill="#0d0d16" rx="8"/>
  {grid}
  {polyline}
  {dots}
</svg>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1.0">
  <title>evalfix history — {_he(name)}</title>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400&display=swap" rel="stylesheet">
  <style>
    *{{box-sizing:border-box;margin:0;padding:0}}
    body{{font-family:Inter,system-ui,sans-serif;background:#09090f;color:#f1f5f9;
          -webkit-font-smoothing:antialiased;padding:40px 24px}}
    .wrap{{max-width:900px;margin:0 auto}}
    h1{{font-size:22px;font-weight:700;margin-bottom:4px}}
    .sub{{font-size:13px;color:#64748b;margin-bottom:28px}}
    .chart{{background:#0d0d16;border:1px solid #1e1e2e;border-radius:12px;
            overflow:hidden;margin-bottom:24px;padding:16px}}
    table{{width:100%;border-collapse:collapse;background:#111118;
           border:1px solid #1e1e2e;border-radius:12px;overflow:hidden}}
    th{{background:#0d0d16;padding:10px 14px;text-align:left;font-size:11px;
        font-weight:600;color:#64748b;text-transform:uppercase;letter-spacing:.05em}}
    td{{padding:10px 14px;font-size:13px;color:#cbd5e1;border-top:1px solid #1e1e2e}}
    .footer{{margin-top:24px;text-align:center;font-size:12px;color:#334155}}
  </style>
</head>
<body>
<div class="wrap">
  <h1>{_he(name)}</h1>
  <p class="sub">{len(runs)} runs · hover dots for details</p>
  <div class="chart">{svg}</div>
  <table>
    <thead>
      <tr>
        <th>#</th><th>Date</th><th>Version</th>
        <th>Passed</th><th>Failed</th><th>Score</th><th>Trend</th><th>Trigger</th>
      </tr>
    </thead>
    <tbody>{rows_html}</tbody>
  </table>
  <div class="footer">Generated by evalfix</div>
</div>
</body>
</html>"""


def _he(t: str | None) -> str:
    if not t:
        return ""
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
