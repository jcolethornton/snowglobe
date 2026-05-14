import typer
from snowglobe.cli.registry import command

@command("set")
def set_cmd(ctx, args):
    if len(args) < 2:
        typer.echo("Usage: set <field> <value>")
        return

    field = args[0]
    value = args[1]

    if field == "object_type":
        ctx.object_type = value
    elif field == "object_name":
        ctx.object_name = value
    elif field == "privilege":
        ctx.privilege = value
    else:
        print(f"Unknown field: {field}")
        return

    typer.echo(f"{field} set to {value}")

