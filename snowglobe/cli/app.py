import typer
from typing import Optional
from snowglobe import __version__
from snowglobe.cli.context import SnowglobeContext
from snowglobe.cli.access import access_app
from snowglobe.cli.optimizer import opt_app
from snowglobe.cli.cost import cost_app
from snowglobe.cli.diff import diff_app
from snowglobe.cli.report import report_app
from snowglobe.cli.debug import debug_app


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"snowglobe-cli {__version__}")
        raise typer.Exit()

app = typer.Typer(
    help="Snowglobe — Explainable cost and access visibility for Snowflake",
    no_args_is_help=False,
    context_settings={"ignore_unknown_options": True}
)

app.add_typer(access_app, name="access")
app.add_typer(cost_app, name="cost")
app.add_typer(diff_app, name="diff")
app.add_typer(opt_app, name="optimize")
app.add_typer(report_app, name="report")
app.add_typer(debug_app, name="debug")


@app.command()
def refresh(
    ctx: typer.Context,
    full: bool = typer.Option(False, "--full", help="Force full refresh (ignore incremental)")
):
    """Refresh cached state from Snowflake. Incremental by default."""
    from snowglobe.core.access_service import AccessService

    context = ctx.obj
    service = AccessService(context)
    service.setup_state()

    service.refresh_state(full=full)

    typer.secho(f"  Users:        {len(service.user_graph.assigned_roles)}", fg=typer.colors.GREEN)
    typer.secho(f"  Roles:        {len(service.role_graph.parents)}", fg=typer.colors.GREEN)
    total_objects = sum(len(v) for v in service.object_index.values())
    typer.secho(f"  Object index: {total_objects} FQNs", fg=typer.colors.GREEN)
    typer.secho("Done.", fg=typer.colors.GREEN, bold=True)


def _launch_tui(context, *, vim_flag: bool = False, fallback_to_shell: bool = False) -> None:
    """
    Start the Textual TUI.

    If `fallback_to_shell=True` and Textual isn't installed, drop into the
    REPL shell instead with a one-line notice. Used by the default
    `snowglobe` (no-args) path so users without the TUI extra still get
    something useful. The explicit `snowglobe tui` subcommand passes
    `fallback_to_shell=False` and exits with an error if Textual is missing.
    """
    try:
        from snowglobe.tui.app import SnowglobeApp, VimSnowglobeApp
    except ImportError as e:
        if "textual" in str(e).lower():
            if fallback_to_shell:
                typer.secho(
                    "TUI not available (install with: pip install 'snowglobe-cli[tui]'). "
                    "Falling back to the REPL shell.",
                    fg=typer.colors.YELLOW,
                )
                from snowglobe.cli.shell import start_shell
                start_shell(context)
                return
            typer.secho(
                "TUI requires the 'textual' package. Install with:\n"
                "  pip install 'snowglobe-cli[tui]'   (or)   pip install textual",
                fg=typer.colors.YELLOW,
            )
            raise typer.Exit(1)
        raise

    # CLI flag wins; otherwise inherit from the active profile's `vim: true`.
    profile_vim = bool((context.profile or {}).get("vim", False)) if context.profile else False
    context.vim_mode = vim_flag or profile_vim

    app_cls = VimSnowglobeApp if context.vim_mode else SnowglobeApp
    app_cls(context=context).run()


@app.command()
def tui(
    ctx: typer.Context,
    vim: bool = typer.Option(
        False, "--vim",
        help="Enable vim-style navigation (j/k/h/l/g/G/Ctrl-d/Ctrl-u + Esc blurs inputs).",
    ),
):
    """Launch the rich Textual-based TUI (same as running `snowglobe` with no command)."""
    _launch_tui(ctx.obj, vim_flag=vim, fallback_to_shell=False)


@app.command()
def shell(ctx: typer.Context):
    """Launch the interactive REPL shell (the prompt_toolkit fuzzy-completion REPL)."""
    from snowglobe.cli.shell import start_shell
    start_shell(ctx.obj)


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    profile_name: str = typer.Option(
        "default",
        "--profile",
        help="Snowflake connection profile to use",
    ),
    role: str | None = typer.Option(
        None,
        "--role",
        help="Override Snowflake role",
    ),
    output: str = typer.Option(
        "table",
        "--output",
        help="Output format: table | json",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Enable verbose output"
    ),
    version: Optional[bool] = typer.Option(
        None,
        "--version",
        "-V",
        callback=_version_callback,
        is_eager=True,
        help="Show version and exit.",
    ),
):
    """
    Inspect and understand Snowflake cost, access, and ownership.

    Snowglobe is read-only by design.

    Run without a command to launch the TUI.
    Use `snowglobe shell` for the REPL shell, or any subcommand for headless use.
    """
    context = SnowglobeContext(
        profile_name=profile_name,
        role=role,
        output=output,
        verbose=verbose
    )
    context.load_profile()
    ctx.obj = context

    # No subcommand → launch the TUI (falling back to the REPL shell
    # if the optional Textual dependency isn't installed).
    if ctx.invoked_subcommand is None:
        _launch_tui(context, vim_flag=False, fallback_to_shell=True)
