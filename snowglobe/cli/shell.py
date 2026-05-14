import typer
from prompt_toolkit import PromptSession
from snowglobe.cli.shell_completer import SnowglobeCompleter
from snowglobe.cli.router import dispatch
from snowglobe.cli.context import ShellContext
from snowglobe.core.access_service import AccessService
from prompt_toolkit.completion import FuzzyCompleter

def start_shell(app_context):

    ctx = ShellContext(app_context)

    access_service = AccessService(app_context)
    ctx.user_graph, ctx.role_graph, ctx.grants = access_service.get_graphs()

    session = PromptSession(
        completer=FuzzyCompleter(SnowglobeCompleter(ctx))
    )

    typer.echo("Snow-Globe Interactive Shell")
    typer.echo("Type 'help' or 'exit'")
    
    while True:
        try:
            active = ctx.role or ctx.username or ""
            prompt_label = f"snowglobe[{active}]> " if active else "snowglobe> "
            text = session.prompt(prompt_label).strip()

            if text in {"exit", "quit"}:
                break

            dispatch(text, ctx)

        except KeyboardInterrupt:
            continue
        except EOFError:
            break


shell_app = typer.Typer(
    help="Snowflake visability",
    no_args_is_help=True,
)

@shell_app.command()
def shell(ctx: typer.Context):
    start_shell(ctx.obj)
