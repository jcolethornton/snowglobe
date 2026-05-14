import typer
from snowglobe.cli.registry import command

@command("use")
def use_cmd(ctx, args):
    if len(args) < 2:
        typer.echo("Usage: use role <name> OR use user <name>")
        return

    kind = args[0]
    name = args[1]

    if kind == "role":
        ctx.inspect_type = "role"
        ctx.role = name
        ctx.username = None
        print(f"Using role: {name}")

    elif kind == "user":
        ctx.inspect_type = "user"
        ctx.username = name
        ctx.role = None
        typer.echo(f"Using user: {name}")
