import typer
from pathlib import Path
from typing import Optional

debug_app = typer.Typer(
    help="Diagnose configuration and connectivity issues",
    no_args_is_help=False,
)


def _pass(msg: str):
    typer.secho(f"  ✓ {msg}", fg=typer.colors.GREEN)


def _fail(msg: str, hint: str = ""):
    typer.secho(f"  ✗ {msg}", fg=typer.colors.RED)
    if hint:
        typer.secho(f"    → {hint}", fg=typer.colors.YELLOW)


def _info(msg: str):
    typer.secho(f"    {msg}", dim=True)


def run_diagnostics(profile_name: str = "default", verbose: bool = False):
    """Run all diagnostic checks and report results."""

    typer.echo("\nSnowglobe Connection Diagnostics")
    typer.echo("=" * 40)

    # --- Step 1: Config file exists ---
    typer.echo("\n[1/8] Config file")
    from snowglobe.config.loader import SnowglobeConfig
    config_path = SnowglobeConfig.CONFIG_PATH

    if not config_path.exists():
        _fail(f"Config not found at {config_path}")
        _info(f"Create {config_path} with your Snowflake profiles.")
        _info("See: snowglobe/config.yml for an example.")
        raise typer.Exit(1)
    _pass(f"Found {config_path}")

    # --- Step 2: Valid YAML ---
    typer.echo("\n[2/8] YAML parsing")
    try:
        import yaml
        with open(config_path, "r") as f:
            raw = yaml.safe_load(f)
        if not isinstance(raw, dict):
            _fail("Config file is not a YAML mapping")
            raise typer.Exit(1)
        _pass(f"Valid YAML with {len(raw)} profile(s): {', '.join(raw.keys())}")
    except yaml.YAMLError as e:
        _fail(f"YAML parse error: {e}")
        raise typer.Exit(1)

    # --- Step 3: Profile exists ---
    typer.echo(f"\n[3/8] Profile '{profile_name}'")
    try:
        config = SnowglobeConfig()
        profile = config.get_profile(profile_name)
        _pass(f"Profile '{profile_name}' loaded")
    except Exception as e:
        _fail(f"Profile not found: {e}")
        _info(f"Available profiles: {', '.join(config.list_profiles())}")
        raise typer.Exit(1)

    # --- Step 4: Required fields ---
    typer.echo("\n[4/8] Required fields")
    required = ["account", "user"]
    missing = [f for f in required if not profile.get(f)]
    has_auth = bool(profile.get("password") or profile.get("private_key_path"))

    if missing:
        _fail(f"Missing required fields: {', '.join(missing)}")
        raise typer.Exit(1)
    if not has_auth:
        _fail("No auth method — need 'password' or 'private_key_path'")
        raise typer.Exit(1)
    _pass(f"account={profile['account']}, user={profile['user']}")

    # --- Step 5: Auth credentials resolve ---
    typer.echo("\n[5/8] Auth credentials")
    auth_method = "key_pair" if profile.get("private_key_path") else "password"

    if auth_method == "key_pair":
        key_path = Path(profile["private_key_path"]).expanduser()
        if not key_path.exists():
            _fail(f"Key file not found: {key_path}")
            _info("Check that private_key_path points to an existing .pem file")
            raise typer.Exit(1)
        _pass(f"Key pair auth — key file exists at {key_path}")

        # Try to parse the key
        try:
            from cryptography.hazmat.primitives import serialization
            pwd = profile.get("private_key_pwd")
            with key_path.open("rb") as f:
                serialization.load_pem_private_key(
                    f.read(),
                    password=pwd.encode() if pwd else None,
                )
            _pass("Key file is a valid PEM private key")
        except Exception as e:
            _fail(f"Key file parse error: {e}")
            _info("Ensure the key is in PEM format and the passphrase (if any) is correct")
            raise typer.Exit(1)
    else:
        password = profile.get("password", "")
        if password.startswith("$") or not password:
            _fail(f"Password appears unresolved: '{password}'")
            _info("Check that the environment variable is set")
            raise typer.Exit(1)
        _pass(f"Password auth — credentials present")

    # --- Step 6: Snowflake connectivity ---
    typer.echo("\n[6/8] Snowflake connection")
    try:
        from snowglobe.snowflake.connection import SnowflakeReadOnly
        sf = SnowflakeReadOnly(
            account=profile["account"],
            user=profile["user"],
            role=profile.get("role"),
            warehouse=profile.get("warehouse"),
            password=profile.get("password"),
            private_key_path=profile.get("private_key_path"),
            private_key_pwd=profile.get("private_key_pwd"),
        )
        with sf:
            _pass("Connected to Snowflake successfully")

            # --- Step 7: Role ---
            typer.echo("\n[7/8] Role")
            result = sf.query("SELECT CURRENT_ROLE() AS role")
            current_role = result[0]["ROLE"] if result else None
            if current_role:
                _pass(f"Active role: {current_role}")
            else:
                _fail("Could not determine current role")

            # --- Step 8: Warehouse ---
            typer.echo("\n[8/8] Warehouse")
            result = sf.query("SELECT CURRENT_WAREHOUSE() AS wh")
            current_wh = result[0]["WH"] if result else None
            if current_wh:
                _pass(f"Active warehouse: {current_wh}")
            else:
                _fail("No warehouse active", hint="Set 'warehouse' in your profile or run USE WAREHOUSE")

    except Exception as e:
        _fail(f"Connection failed: {e}")
        error_str = str(e).lower()
        if "incorrect username or password" in error_str:
            _info("Check your username and password in the profile")
        elif "account" in error_str:
            _info(f"Verify account identifier: {profile['account']}")
            _info("Format should be: <orgname>-<accountname> or <locator>.<region>.<cloud>")
        elif "private key" in error_str:
            _info("Key pair auth failed — check key file and passphrase")
        elif "timeout" in error_str or "could not connect" in error_str:
            _info("Network issue — check firewall, VPN, or proxy settings")
        else:
            _info("See Snowflake documentation for connection troubleshooting")
        raise typer.Exit(1)

    typer.echo("\n" + "=" * 40)
    typer.secho("All checks passed.", fg=typer.colors.GREEN, bold=True)
    typer.echo("")


@debug_app.callback(invoke_without_command=True)
def debug(
    ctx: typer.Context,
    profile_name: Optional[str] = typer.Option(None, "--profile", help="Profile to test (overrides global --profile)"),
):
    """
    Run connection diagnostics.

    Checks config file, credentials, and Snowflake connectivity
    step by step, reporting exactly where things fail.
    """
    context = ctx.obj
    name = profile_name or (context.profile_name if context else "default")
    verbose = context.verbose if context else False
    run_diagnostics(profile_name=name, verbose=verbose)
