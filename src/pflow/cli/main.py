"""pflow CLI entry point."""

from __future__ import annotations

import signal
import sys
from contextlib import suppress
from importlib.metadata import version as pkg_version
from typing import Any, ClassVar

import click

from pflow.cli.error_output import output_error
from pflow.core.exceptions import PflowError
from pflow.guide import render_entry_content


class PflowCLI(click.Group):
    """Click group with default-command routing for workflow execution."""

    ignore_unknown_options = True

    # Commands removed in the CLI restructure (Task 151). Agents with old
    # instructions will try these — give them a clear migration path.
    _removed_commands: ClassVar[dict[str, str]] = {
        "workflow": "Workflow commands are now top-level: pflow list, pflow find, pflow describe, pflow history, pflow save",
        "registry": "Registry commands replaced: pflow probe (run nodes), pflow mcp list (list nodes), pflow mcp find (discover nodes)",
        "instructions": "Replaced by: pflow guide",
        "trace": "Replaced by: pflow report",
    }

    def resolve_command(
        self,
        ctx: click.Context,
        args: list[str],
    ) -> tuple[str | None, click.Command | None, list[str]]:
        if not args:
            return super().resolve_command(ctx, args)

        cmd_name = args[0]
        cmd = self.get_command(ctx, cmd_name)
        if cmd is not None:
            return cmd_name, cmd, args[1:]

        if cmd_name in self._removed_commands:
            click.echo(f"Error: '{cmd_name}' command was removed.\n{self._removed_commands[cmd_name]}", err=True)
            ctx.exit(1)

        return "run", self.get_command(ctx, "run"), args

    def invoke(self, ctx: click.Context) -> Any:
        # Group-level error boundary: route uncaught PflowError subclasses
        # through the unified diagnostic pipeline so subcommands (describe,
        # history, save, etc.) render structured errors instead of raw
        # Python tracebacks. The `run` command has its own boundary with
        # full --output-format / metrics parity; it never lets PflowError
        # escape, so this override is inert for that path.
        try:
            return super().invoke(ctx)
        except PflowError as e:
            obj = ctx.obj or {}
            output_error(
                ctx,
                exception=e,
                output_format=obj.get("output_format", "text"),
                verbose=obj.get("verbose", False),
            )
            ctx.exit(1)

    def format_usage(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        formatter.write_usage(ctx.command_path, "[OPTIONS] COMMAND [ARGS]...")

    def format_help(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        self.format_usage(ctx, formatter)
        formatter.write_paragraph()
        # Render entry content directly — bypasses Click's paragraph wrapper
        # so the aligned Quick Start table stays intact.
        formatter.write(f"  {render_entry_content().strip()}\n")
        formatter.write("\n")
        # format_options on Group also calls format_commands internally
        self.format_options(ctx, formatter)


def _setup_signals() -> None:
    """Configure signal handlers for all commands."""

    def _handle_sigint(signum: int, frame: object) -> None:
        click.echo("\nInterrupted by user", err=True)
        sys.exit(130)

    signal.signal(signal.SIGINT, _handle_sigint)
    with suppress(AttributeError):
        signal.signal(signal.SIGPIPE, signal.SIG_IGN)


def _get_version() -> str:
    """Return the installed package version with a local fallback."""
    try:
        return pkg_version("pflow-cli")
    except Exception:
        return "0.11.0"


@click.group(cls=PflowCLI, invoke_without_command=True)
@click.version_option(version=_get_version(), prog_name="pflow", message="pflow version %(version)s")
@click.option("--verbose", "-v", is_flag=True, help="Show detailed execution output")
@click.pass_context
def cli(ctx: click.Context, verbose: bool) -> None:
    """pflow CLI group."""
    from pflow.cli.logging_config import configure_logging

    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose
    configure_logging(verbose)
    _setup_signals()
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())
        ctx.exit(0)


from pflow.cli.commands.describe import describe_cmd  # noqa: E402
from pflow.cli.commands.find import find_cmd  # noqa: E402
from pflow.cli.commands.guide import guide_cmd  # noqa: E402
from pflow.cli.commands.history import history_cmd  # noqa: E402
from pflow.cli.commands.list import list_cmd  # noqa: E402
from pflow.cli.commands.mcp import mcp  # noqa: E402
from pflow.cli.commands.probe import probe_cmd  # noqa: E402
from pflow.cli.commands.read_fields import read_fields  # noqa: E402
from pflow.cli.commands.report import report_cmd  # noqa: E402
from pflow.cli.commands.run import run  # noqa: E402
from pflow.cli.commands.save import save_cmd  # noqa: E402
from pflow.cli.commands.settings import settings  # noqa: E402
from pflow.cli.commands.skills import skill  # noqa: E402
from pflow.cli.commands.visualize import visualize  # noqa: E402

cli.add_command(run)
cli.add_command(list_cmd)
cli.add_command(find_cmd)
cli.add_command(describe_cmd)
cli.add_command(history_cmd)
cli.add_command(save_cmd)
cli.add_command(guide_cmd)
cli.add_command(probe_cmd)
cli.add_command(mcp)
cli.add_command(settings)
cli.add_command(read_fields)
cli.add_command(skill)
cli.add_command(report_cmd)
cli.add_command(visualize)


def cli_main() -> None:
    """Run the CLI in standalone mode."""
    cli(standalone_mode=True)


main = cli
