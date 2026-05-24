import typer
from pathlib import Path
from typing import Callable, Optional, Protocol

debug_app = typer.Typer(
    help="Diagnose configuration and connectivity issues",
    no_args_is_help=False,
)


class DiagnosticsReporter(Protocol):
    """
    Sink for diagnostics output. Each frontend (CLI, TUI, test) supplies one.

    Levels:
      header — top banner / separator
      step   — "[n/total] label"
      ok     — success line for the current check
      fail   — failure line + optional hint
      info   — supplementary detail or remediation tip
      done   — final summary line at the end of a successful run
    """
    def header(self, msg: str) -> None: ...
    def step(self, n: int, total: int, label: str) -> None: ...
    def ok(self, msg: str) -> None: ...
    def fail(self, msg: str, hint: str = "") -> None: ...
    def info(self, msg: str) -> None: ...
    def done(self, msg: str) -> None: ...


class TyperReporter:
    """Default reporter — renders coloured output via typer."""

    def header(self, msg: str) -> None:
        typer.echo(f"\n{msg}")
        typer.echo("=" * 40)

    def step(self, n: int, total: int, label: str) -> None:
        typer.echo(f"\n[{n}/{total}] {label}")

    def ok(self, msg: str) -> None:
        typer.secho(f"  ✓ {msg}", fg=typer.colors.GREEN)

    def fail(self, msg: str, hint: str = "") -> None:
        typer.secho(f"  ✗ {msg}", fg=typer.colors.RED)
        if hint:
            typer.secho(f"    → {hint}", fg=typer.colors.YELLOW)

    def info(self, msg: str) -> None:
        typer.secho(f"    {msg}", dim=True)

    def done(self, msg: str) -> None:
        typer.echo("\n" + "=" * 40)
        typer.secho(msg, fg=typer.colors.GREEN, bold=True)
        typer.echo("")


class CallableReporter:
    """
    Reporter that delegates every line to a single callback `(level, msg)`.

    Use from the TUI to route output into a RichLog or any other sink:

        reporter = CallableReporter(lambda level, msg: my_log.write(level, msg))
        run_diagnostics(reporter=reporter)
    """

    def __init__(self, write: Callable[[str, str], None]):
        self._write = write

    def header(self, msg: str) -> None:
        self._write("header", msg)

    def step(self, n: int, total: int, label: str) -> None:
        self._write("step", f"[{n}/{total}] {label}")

    def ok(self, msg: str) -> None:
        self._write("ok", msg)

    def fail(self, msg: str, hint: str = "") -> None:
        self._write("fail", msg)
        if hint:
            self._write("info", f"→ {hint}")

    def info(self, msg: str) -> None:
        self._write("info", msg)

    def done(self, msg: str) -> None:
        self._write("done", msg)


def run_diagnostics(
    profile_name: str = "default",
    verbose: bool = False,
    reporter: Optional[DiagnosticsReporter] = None,
) -> bool:
    """
    Run all diagnostic checks and report results via the supplied reporter.

    Returns True if every check passed, False otherwise. Does not raise on
    a failed check — callers decide how to react (CLI exits, TUI just shows
    the log).
    """
    r = reporter or TyperReporter()
    TOTAL = 8

    r.header("Snowglobe Connection Diagnostics")

    # --- Step 1: Config file exists ---
    r.step(1, TOTAL, "Config file")
    from snowglobe.config.loader import SnowglobeConfig
    config_path = SnowglobeConfig.CONFIG_PATH

    if not config_path.exists():
        r.fail(f"Config not found at {config_path}")
        r.info(f"Create {config_path} with your Snowflake profiles.")
        r.info("See: snowglobe/config.yml for an example.")
        return False
    r.ok(f"Found {config_path}")

    # --- Step 2: Valid YAML ---
    r.step(2, TOTAL, "YAML parsing")
    try:
        import yaml
        with open(config_path, "r") as f:
            raw = yaml.safe_load(f)
        if not isinstance(raw, dict):
            r.fail("Config file is not a YAML mapping")
            return False
        r.ok(f"Valid YAML with {len(raw)} profile(s): {', '.join(raw.keys())}")
    except yaml.YAMLError as e:
        r.fail(f"YAML parse error: {e}")
        return False

    # --- Step 3: Profile exists ---
    r.step(3, TOTAL, f"Profile '{profile_name}'")
    try:
        config = SnowglobeConfig()
        profile = config.get_profile(profile_name)
        r.ok(f"Profile '{profile_name}' loaded")
    except Exception as e:
        r.fail(f"Profile not found: {e}")
        try:
            r.info(f"Available profiles: {', '.join(config.list_profiles())}")
        except Exception:
            pass
        return False

    # --- Step 4: Required fields ---
    r.step(4, TOTAL, "Required fields")
    required = ["account", "user"]
    missing = [f for f in required if not profile.get(f)]
    has_auth = bool(profile.get("password") or profile.get("private_key_path"))

    if missing:
        r.fail(f"Missing required fields: {', '.join(missing)}")
        return False
    if not has_auth:
        r.fail("No auth method — need 'password' or 'private_key_path'")
        return False
    r.ok(f"account={profile['account']}, user={profile['user']}")

    # --- Step 5: Auth credentials resolve ---
    r.step(5, TOTAL, "Auth credentials")
    auth_method = "key_pair" if profile.get("private_key_path") else "password"

    if auth_method == "key_pair":
        key_path = Path(profile["private_key_path"]).expanduser()
        if not key_path.exists():
            r.fail(f"Key file not found: {key_path}")
            r.info("Check that private_key_path points to an existing .pem file")
            return False
        r.ok(f"Key pair auth — key file exists at {key_path}")

        try:
            from cryptography.hazmat.primitives import serialization
            pwd = profile.get("private_key_pwd")
            with key_path.open("rb") as f:
                serialization.load_pem_private_key(
                    f.read(),
                    password=pwd.encode() if pwd else None,
                )
            r.ok("Key file is a valid PEM private key")
        except Exception as e:
            r.fail(f"Key file parse error: {e}")
            r.info("Ensure the key is in PEM format and the passphrase (if any) is correct")
            return False
    else:
        password = profile.get("password", "")
        if password.startswith("$") or not password:
            r.fail(f"Password appears unresolved: '{password}'")
            r.info("Check that the environment variable is set")
            return False
        r.ok("Password auth — credentials present")

    # --- Step 6: Snowflake connectivity ---
    r.step(6, TOTAL, "Snowflake connection")
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
            r.ok("Connected to Snowflake successfully")

            # --- Step 7: Role ---
            r.step(7, TOTAL, "Role")
            result = sf.query("SELECT CURRENT_ROLE() AS role")
            current_role = result[0]["ROLE"] if result else None
            if current_role:
                r.ok(f"Active role: {current_role}")
            else:
                r.fail("Could not determine current role")

            # --- Step 8: Warehouse ---
            r.step(8, TOTAL, "Warehouse")
            result = sf.query("SELECT CURRENT_WAREHOUSE() AS wh")
            current_wh = result[0]["WH"] if result else None
            if current_wh:
                r.ok(f"Active warehouse: {current_wh}")
            else:
                r.fail("No warehouse active", hint="Set 'warehouse' in your profile or run USE WAREHOUSE")

    except Exception as e:
        r.fail(f"Connection failed: {e}")
        error_str = str(e).lower()
        if "incorrect username or password" in error_str:
            r.info("Check your username and password in the profile")
        elif "account" in error_str:
            r.info(f"Verify account identifier: {profile['account']}")
            r.info("Format should be: <orgname>-<accountname> or <locator>.<region>.<cloud>")
        elif "private key" in error_str:
            r.info("Key pair auth failed — check key file and passphrase")
        elif "timeout" in error_str or "could not connect" in error_str:
            r.info("Network issue — check firewall, VPN, or proxy settings")
        else:
            r.info("See Snowflake documentation for connection troubleshooting")
        return False

    r.done("All checks passed.")
    return True


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
    if not run_diagnostics(profile_name=name, verbose=verbose):
        raise typer.Exit(1)
