import click
from rich.console import Console

console = Console()


@click.group()
@click.version_option(version="0.1.0", prog_name="evalfix")
def cli():
    """evalfix — shorten the time between red CI and green CI for LLM agents.

    \b
    Typical workflow:
      evalfix init    my-project/  Generate a starter eval suite from your prompt
      evalfix run     my-project/  Run evals against the current prompt
      evalfix fix     my-project/  Run evals, analyze failures, apply an AI patch
      evalfix report  my-project/  Show last run results in the terminal (or HTML)
      evalfix history my-project/  Show score trends across all runs
    """


@cli.command()
@click.argument("directory", default=".", metavar="PROJECT_DIR")
@click.option("--model", default="claude-sonnet-4-6", show_default=True,
              help="Model to use when generating the eval suite.")
def init(directory, model):
    """Generate a starter eval suite from a prompt.

    Creates PROJECT_DIR with prompt.txt, evals.yaml, config.yaml, and
    tools.json.  If the directory already exists and contains a prompt.txt
    that file is used as the starting prompt.
    """
    from cli.commands.init import run
    run(directory, model)


@cli.command()
@click.argument("directory", default=".", metavar="PROJECT_DIR")
@click.option("--model", default=None,
              help="Override the model set in config.yaml.")
@click.option("--json", "as_json", is_flag=True, default=False,
              help="Print results as JSON (useful for piping / CI).")
def run(directory, model, as_json):
    """Run evals on the current prompt.

    Exits 0 if every test passes, 1 if any fail — safe to use in CI.
    """
    from cli.commands.run import run as do_run
    do_run(directory, model_override=model, as_json=as_json)


@cli.command()
@click.argument("directory", default=".", metavar="PROJECT_DIR")
@click.option("--model", default=None,
              help="Override the model set in config.yaml.")
@click.option("--yes", "-y", is_flag=True, default=False,
              help="Auto-accept the generated patch without prompting.")
def fix(directory, model, yes):
    """Run evals, analyze failures, and apply an AI-generated patch.

    If all tests are already passing this is a no-op.  Otherwise evalfix
    reads the failing cases, sends the full context to the optimizer, shows
    you a diff, and (optionally) writes the improved prompt back to
    prompt.txt.
    """
    from cli.commands.fix import run as do_fix
    do_fix(directory, model_override=model, auto_accept=yes)


@cli.command()
@click.argument("directory", default=".", metavar="PROJECT_DIR")
@click.option("--html", is_flag=True, default=False,
              help="Also write an HTML report to PROJECT_DIR/report.html.")
def report(directory, html):
    """Show the last run results in the terminal.

    Pass --html to also generate a PROJECT_DIR/report.html file that can be
    opened in any browser.
    """
    from cli.commands.report import run as do_report
    do_report(directory, write_html=html)


@cli.command()
@click.argument("directory", default=".", metavar="PROJECT_DIR")
@click.option("--html", is_flag=True, default=False,
              help="Write a score chart to PROJECT_DIR/history.html.")
@click.option("--last", default=None, type=int, metavar="N",
              help="Show only the last N runs.")
def history(directory, html, last):
    """Show score trends across all runs.

    Displays a table of every eval run for this project ordered by time,
    with pass/fail counts, scores, and trend arrows.
    """
    from cli.commands.history import run as do_history
    do_history(directory, write_html=html, last_n=last)
