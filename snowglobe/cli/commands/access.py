from snowglobe.cli.registry import command
from snowglobe.core.access_service import AccessService
from snowglobe.output import cli


@command("access")
def access_command(ctx, *args):
    access_service = AccessService(ctx.app_context)

    try:
        result = access_service.inspect_access(
            username=ctx.username,
            role=ctx.role,
            object_type=ctx.object_type,
            object_name=ctx.object_name,
            privilege=ctx.privilege,
            ignore_excluded_roles=False,
            refresh_state=False,
        )

        print(cli.format_access_text(result))

    except Exception as e:
        print(f"Error: {e}")
