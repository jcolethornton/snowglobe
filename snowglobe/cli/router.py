from snowglobe.cli import commands
from snowglobe.cli.registry import COMMANDS

def dispatch(text, ctx):
    parts = text.split()
    if not parts:
        return

    cmd = parts[0]
    args = parts[1:]

    if cmd not in COMMANDS:
        print(f"Unknown command: {cmd}")
        return

    COMMANDS[cmd](ctx, args)
