# Task 151: CLI Surface Restructure — Implementation Plan

## Context

pflow's CLI surface grew organically and doesn't serve AI agents well. Commands are nested under groups (`pflow workflow discover`, `pflow registry list`) that force agents to remember which namespace each verb lives under. Inconsistent verbs (`list` vs `search` vs `discover`) overlap in meaning. The `registry run` name implies production use when it's actually exploratory testing. A monolithic `pflow instructions` dumps 2,225 lines of instructions.

This task flattens the CLI into a consistent, agent-friendly surface. Workflows are the primary artifact, so workflow operations become top-level commands. The `registry` group is eliminated entirely. `instructions` is replaced by a `guide` stub (content filled by Task 77). All naming decisions were settled by subagent polls (N=5 each) and are final.

**pflow has zero users.** Clean cutover — no aliases, no deprecation warnings, no backwards compatibility.

**Scope is CLI only.** The MCP server (`src/pflow/mcp_server/`) keeps its existing tool names. A follow-up task (Task 152) brings MCP into parity. However, we DO update import statements in `mcp_server/` when shared service functions are renamed, since those are internal wiring, not public API.

## Final CLI Surface

```
# Top-level (agent-facing, frequent)
pflow my-workflow param=value      # run workflow (catch-all default, unchanged)
pflow list [keyword...]            # list saved workflows (keyword filter)
pflow find "description"           # LLM-powered workflow search
pflow describe <workflow>          # show workflow interface
pflow history <workflow>           # execution history
pflow save <file> --name <name>    # save to library
pflow guide [topics...]            # learn how to build workflows (stub — Task 77)
pflow probe <node> param=value     # test a single node
pflow read-fields <exec> <paths>   # existing, unchanged

# MCP namespace
pflow mcp list [keyword...]        # list MCP tools (grouped-by-server summary)
pflow mcp find "description"       # LLM-powered MCP tool search
pflow mcp describe <tool>          # MCP tool details
pflow mcp servers                  # list configured servers (was: mcp list)
pflow mcp add|remove|sync          # server lifecycle (unchanged)
pflow mcp serve                    # run pflow as MCP server (unchanged)

# Config/maintenance
pflow settings ...                 # config (unchanged, except output-mode flattened)
pflow skill save|list|remove       # AI tool skills (unchanged)
pflow trace report                 # trace inspection (unchanged)
pflow visualize                    # mermaid diagram (unchanged)
```

**Commands deleted (no replacement, no alias):** `pflow registry *`, `pflow workflow *`, `pflow instructions *`, `pflow mcp tools`, `pflow mcp info`.

## Key Architecture Decisions

### 1. Click-native routing replaces hand-rolled wrapper

**Current:** `main_wrapper.py` scans `sys.argv`, matches subcommand names in a dict, mutates `sys.argv` in-place, calls the handler, restores `sys.argv`. Help text is manually maintained in a docstring (already stale — missing 4 of 9 commands).

**New:** Subclass `click.Group` as `PflowCLI` using the `click-default-group` pattern (vendored, ~20 lines). Set `ignore_unknown_options=True` on the group so that options belonging to the `run` command (like `--output-format`) pass through the group parser without error. Override `resolve_command()` to route unknown first args to a hidden `run` command. Click auto-generates the `Commands:` section in `--help`. Standard `CliRunner` testing.

**Why `ignore_unknown_options=True` on the group is required:** Click's group parser runs BEFORE subcommand routing. Without `ignore_unknown_options`, `pflow --output-format json my-workflow` fails because the group doesn't recognize `--output-format` (it's a `run` option). With `ignore_unknown_options=True`, unrecognized options pass through to the default subcommand. This is the standard solution used by `click-default-group` (565K weekly PyPI downloads) — we vendor the pattern instead of adding a dependency.

**Typo safety:** The `is_likely_workflow_name` heuristic already handles the "typo routes to default" concern — single bare words without hyphens or params are rejected with a helpful error.

```python
class PflowCLI(click.Group):
    # Let unrecognized options (--output-format, etc.) pass through to the
    # default 'run' command instead of erroring at the group level.
    ignore_unknown_options = True

    def resolve_command(self, ctx: click.Context, args: list[str]) -> tuple:
        cmd_name = args[0]
        cmd = self.get_command(ctx, cmd_name)
        if cmd is not None:
            return cmd_name, cmd, args[1:]
        # Not a known command — treat as workflow execution
        return "run", self.get_command(ctx, "run"), args

    def format_usage(self, ctx, formatter):
        formatter.write_usage(ctx.command_path, "[OPTIONS] COMMAND [ARGS]...")
```

**Edge cases:**
- `pflow` (no args) → Click shows group help (resolve_command not called when no remaining args)
- `pflow --help` → Click's help option triggers before resolve_command
- `pflow --version` → `@click.version_option()` on the group handles it
- `pflow --verbose mcp list` → group consumes `--verbose` (known option), resolves `mcp`
- `pflow --output-format json my-workflow` → group skips `--output-format` (unknown), all tokens reach `run`, which parses `--output-format json` normally
- `pflow run my-workflow` → `run` is a registered (hidden) command, Click routes naturally. No need for `_preprocess_run_prefix`.
- `pflow my-workflow --help` → falls to `run`, which has `add_help_option=False` and `ignore_unknown_options=True` so `--help` passes through to `_show_workflow_help()`
- `pflow my-workflow.pflow.md --output-format json` → falls to `run` with `allow_interspersed_args=True`, `--output-format` consumed as a `run` option

### 2. main.py becomes small entry point; workflow execution moves to commands/run.py

**Current:** `main.py` is 1058 lines mixing entry point with workflow execution logic.

**New:** `main.py` is ~60 lines: `PflowCLI` class, group definition, command registration, `cli_main()`. All workflow execution logic (30+ functions) moves to `commands/run.py`.

`main.py` re-exports `main = cli` for backward compat with 5 integration test files that do `from pflow.cli.main import main`.

### 3. One file per command in `commands/`

Each flattened command gets its own file: `list.py`, `find.py`, `describe.py`, `history.py`, `save.py`, `guide.py`, `probe.py`, `run.py`.

### 4. Guide content in `src/pflow/guide/` package

Guide content is a first-class concept, not a CLI implementation detail. The `pflow.guide` package owns content AND content logic. Both CLI (`pflow guide`) and MCP (Task 152) import from it. Task 151 creates the package with a placeholder `entry.md` and `render_entry_content()`. Task 77 fills in real content and adds `compose_guide()`.

### 5. Group options vs command options

- **Group-level:** `--verbose`, `--version` (via Click built-in)
- **`run` command only:** `--output-key`, `--output-format`, `--print`, `--no-trace`, `--report`, `--report-dir`, `--validate-only`, `--cache/--no-cache`, `--only`
- The group callback sets `ctx.obj["verbose"]`. The `run` command reads it from there.
- `_setup_signals()` moves to the group callback (applies to all commands).
- `_inject_settings_env_vars()` stays in `run` command (only needed for workflow execution).
- `_auto_discover_mcp_servers()` stays in `run` command.

### 6. `pflow run` is a registered hidden command

With Click-native routing, `pflow run my-workflow` naturally routes to the `run` command. Click strips `run` from args, so the command receives `["my-workflow"]`. No need for `_preprocess_run_prefix`. However, `pflow run` with no args should error helpfully — the `run` command handles empty args.

---

## Implementation Phases

Each phase produces a state where `make test` and `make check` pass. Implement phases sequentially.

---

## Phase 1: Foundation — Click-native Routing + run.py Extraction

**Objective:** Replace `main_wrapper.py` with Click-native routing. Move workflow execution logic from `main.py` to `commands/run.py`. All existing commands still work via the new routing.

### Create: `src/pflow/cli/commands/run.py`

Move ALL workflow execution logic from `main.py` into this file. This is the hidden default command that handles `pflow <workflow> [params...]`.

**What moves from `main.py`:**
- ALL functions EXCEPT `_setup_signals` (moves to group callback in main.py) and the `cli` group definition
- Specifically: `handle_sigint` (stays in main.py alongside `_setup_signals`), `_get_output_controller`, `_echo_trace`, `_read_stdin_data`, `_cleanup_temp_files`, `_handle_workflow_success`, `_save_trace_and_report`, `_echo_target_node_path`, `execute_json_workflow`, `_emit_failure_tag`, `_display_execution_result`, `_display_validation_result`, `_initialize_context`, `_preprocess_run_prefix` (keep for backward compat with `pflow run` — see note), `_validate_workflow_flags`, `_find_stdin_input`, `_extract_stdin_text`, `_route_stdin_to_params`, `_validate_and_prepare_workflow_params`, `_show_workflow_help`, `_setup_workflow_execution`, `_handle_named_workflow`, `_inject_settings_env_vars`, `_try_execute_named_workflow`, `_handle_invalid_workflow_input`
- The entire `workflow_command` function becomes the `run` command, with these changes:

**Click decorator for `run`:**
```python
@click.command(
    name="run",
    hidden=True,
    add_help_option=False,
    context_settings={"ignore_unknown_options": True, "allow_interspersed_args": True},
)
@click.pass_context
@click.option("--output-key", "-o", "output_key", help="Shared store key to output to stdout (default: auto-detect)")
@click.option("--output-format", type=click.Choice(["text", "json"], case_sensitive=False), default="text", help="Output format: text (default) or json")
@click.option("-p", "--print", "print_flag", is_flag=True, help="Minimal output: suppress header, summary, and warnings on stderr")
@click.option("--no-trace", is_flag=True, help="Disable workflow execution trace saving")
@click.option("--report", "report_flag", is_flag=True, default=False, help="Generate execution report")
@click.option("--report-dir", "report_dir", default=None, help="Custom output directory for report (implies --report)")
@click.option("--validate-only", is_flag=True, help="Validate workflow without executing")
@click.option("--cache/--no-cache", default=True, help="Enable/disable memoization cache")
@click.option("--only", "only_node", default=None, help="Run workflow through this node then stop")
@click.argument("workflow", nargs=-1, type=click.UNPROCESSED)
def run(ctx, output_key, output_format, print_flag, no_trace, report_flag, report_dir, validate_only, cache, only_node, workflow):
```

**Key changes from current `workflow_command`:**
- `--version` removed (now on the group via `@click.version_option`)
- `--verbose` removed (now on the group; read from `ctx.obj.get("verbose", False)`)
- `add_help_option=False` — prevents Click from consuming `--help` so it passes through to `_show_workflow_help` for individual workflows
- `hidden=True` — doesn't appear in `Commands:` section of `--help`
- The version-check block at the top of the function body is removed
- `_setup_signals()` call removed (done in group callback)
- Read `verbose` from `ctx.obj.get("verbose", False)` instead of function parameter

**Note on `_preprocess_run_prefix`:** Keep this function in `run.py` but it should now ONLY handle the error case (`pflow run` with no args via the hidden command). When `pflow run my-workflow` comes through Click routing, Click strips `run` from args, so the `run` command receives `["my-workflow"]` — no prefix to strip. But if someone directly invokes the `run` command somehow with `["run", "my-workflow"]`, the prefix stripping catches it. Actually, this shouldn't happen with Click routing. The function can be simplified or removed. **Decision: keep it for safety but it should rarely trigger.**

**Imports:** Copy all imports from `main.py` that the moved functions use. Remove imports that only the group/entry-point code needs.

**Public API:** Export `execute_json_workflow` and `run` for test mock.patch targets.

### Rewrite: `src/pflow/cli/main.py`

Replace the entire 1058-line file with ~60 lines:

```python
"""pflow CLI entry point.

Defines the PflowCLI group (Click-native routing with default-command pattern)
and registers all commands. Workflow execution logic lives in commands/run.py.
"""
from __future__ import annotations

import signal
import sys

import click

from pflow.guide import render_entry_content


class PflowCLI(click.Group):
    """Click group with default-command routing for workflow execution.

    Uses ignore_unknown_options=True so that run-specific options
    (--output-format, --no-trace, etc.) pass through the group parser
    to the hidden 'run' command. This is the standard click-default-group
    pattern, vendored inline.
    """

    ignore_unknown_options = True

    def resolve_command(self, ctx: click.Context, args: list[str]) -> tuple:
        cmd_name = args[0]
        cmd = self.get_command(ctx, cmd_name)
        if cmd is not None:
            return cmd_name, cmd, args[1:]
        # Not a known subcommand — treat as workflow execution
        return "run", self.get_command(ctx, "run"), args

    def format_usage(self, ctx, formatter):
        formatter.write_usage(ctx.command_path, "[OPTIONS] COMMAND [ARGS]...")


def _setup_signals() -> None:
    """Configure signal handlers for all commands."""
    def _handle_sigint(signum, frame):  # noqa: ARG001
        click.echo("\nInterrupted by user", err=True)
        sys.exit(130)

    signal.signal(signal.SIGINT, _handle_sigint)
    try:
        signal.signal(signal.SIGPIPE, signal.SIG_IGN)
    except AttributeError:
        pass  # Windows


def _get_version() -> str:
    try:
        from importlib.metadata import version as pkg_version
        return pkg_version("pflow-cli")
    except Exception:
        return "0.11.0"


@click.group(cls=PflowCLI, help=render_entry_content())
@click.version_option(version=_get_version(), prog_name="pflow", message="pflow version %(version)s")
@click.option("--verbose", "-v", is_flag=True, help="Show detailed execution output")
@click.pass_context
def cli(ctx: click.Context, verbose: bool) -> None:
    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose
    # MUST call configure_logging — sets up root logger, silences noisy
    # third-party libraries (httpx, httpcore, mcp SDK, composio, etc.)
    from pflow.cli.logging_config import configure_logging
    configure_logging(verbose)
    _setup_signals()


# Register all commands
from pflow.cli.commands.run import run  # noqa: E402
# ... (all other commands registered here — see Phase 2/3 for the full list)
# For Phase 1, register all EXISTING commands:
from pflow.cli.commands.mcp import mcp  # noqa: E402
from pflow.cli.commands.registry import registry  # noqa: E402
from pflow.cli.commands.workflow import workflow  # noqa: E402
from pflow.cli.commands.settings import settings  # noqa: E402
from pflow.cli.commands.instructions import instructions  # noqa: E402
from pflow.cli.commands.read_fields import read_fields  # noqa: E402
from pflow.cli.commands.skills import skill  # noqa: E402
from pflow.cli.commands.trace import trace  # noqa: E402
from pflow.cli.commands.visualize import visualize  # noqa: E402

cli.add_command(run)
cli.add_command(mcp)
cli.add_command(registry)
cli.add_command(workflow)
cli.add_command(settings)
cli.add_command(instructions)
cli.add_command(read_fields)
cli.add_command(skill)
cli.add_command(trace)
cli.add_command(visualize)


def cli_main() -> None:
    cli(standalone_mode=True)


# Backward compat for tests: `from pflow.cli.main import main`
main = cli
```

**IMPORTANT:** The `help=render_entry_content()` call requires `src/pflow/guide/` to exist. Create the guide package FIRST (see below).

### Create: `src/pflow/guide/__init__.py`

```python
"""pflow guide content package.

Provides render_entry_content() for pflow --help and pflow guide (no args).
Content files are populated by Task 77. This module provides placeholders
until then.
"""
from pathlib import Path


def render_entry_content() -> str:
    """Read entry.md content, or return placeholder if not yet populated."""
    entry_path = Path(__file__).parent / "entry.md"
    try:
        if entry_path.exists():
            content = entry_path.read_text(encoding="utf-8")
            if content.strip():
                return content
    except (OSError, UnicodeDecodeError):
        pass  # Fall through to placeholder
    return _placeholder_entry_content()


def _placeholder_entry_content() -> str:
    return """\
pflow runs workflows — sequences of nodes (http, shell, llm, code, file, mcp) \
that chain together through a shared data store.

Quick start:
  pflow <workflow-file>       Run a workflow file
  pflow <saved-name>          Run a saved workflow
  pflow list                  List saved workflows
  pflow find "description"    Search workflows by intent (LLM-powered)
  pflow guide                 Learn how to build workflows
  pflow mcp list              List available MCP tools

Use 'pflow <command> --help' for details on any command.\
"""
```

### Create: `src/pflow/guide/entry.md`

Empty file. Task 77 populates it. `render_entry_content()` will use the placeholder until then.

### Modify: `src/pflow/cli/__init__.py`

Change `cli_main` import from `main_wrapper` to `main`:

```python
# Old:
from pflow.cli.main_wrapper import cli_main
# New:
from pflow.cli.main import cli_main
```

### Delete: `src/pflow/cli/main_wrapper.py`

Entire file. Its routing logic is replaced by `PflowCLI.resolve_command`.

### Test changes for Phase 1

**Mock.patch targets that change:**

All patches targeting `pflow.cli.main.WorkflowManager` → `pflow.cli.commands.run.WorkflowManager`
All patches targeting `pflow.cli.main.execute_json_workflow` → `pflow.cli.commands.run.execute_json_workflow`
All patches targeting `pflow.cli.main.workflow_command` → `pflow.cli.commands.run.run`

Files to update:
- `tests/test_cli/test_workflow_resolution.py`: patches change from `pflow.cli.main.*` to `pflow.cli.commands.run.*`
- `tests/test_cli/test_nested_workflow_cli.py`: patches change
- `tests/test_cli/test_registry_cli.py`: line 632, `pflow.cli.main.workflow_command` → `pflow.cli.commands.run.run`

**Tests importing from `main_wrapper.py` (will crash on deletion — MUST update):**

- `tests/test_cli/test_validate_only.py:23` — `from pflow.cli.main_wrapper import cli_main` → change to `from pflow.cli.main import cli_main`
- `tests/test_cli/test_validation_before_execution.py:24` — same fix
- `tests/test_cli/test_nested_workflow_cli.py:89` — same fix
- `tests/test_cli/test_workflow_save.py:147` — subprocess `python -m pflow.cli.main_wrapper` → change to `python -m pflow.cli`
- `tests/test_cli/test_dual_mode_stdin.py:331,349,409` — subprocess calls, same fix as above

**Tests importing `from pflow.cli.main import main` (20 files — semantics change):**

`main` is now the Click group, not `workflow_command`. Most CliRunner invocations work transparently because the group routes to `run`. But these files WILL break due to assertion changes:

- `tests/test_cli/test_cli.py` — asserts `"Reusable CLI workflows..."` in help output → update to match `render_entry_content()` placeholder text. Asserts `"pflow version "` format → preserved by `message=` parameter. Asserts empty-args behavior → now shows group help (exit code 0), not "No workflow" error.
- `tests/test_cli/test_main.py` — same help text and empty-args assertions need updating.

The remaining 18 files should work transparently but MUST be verified:
`test_parse_error_handling.py`, `test_shell_stderr_warnings.py`, `test_shell_stderr_display.py`, `test_workflow_output_handling.py`, `test_workflow_resolution.py`, `test_unified_error_output.py`, `test_agent_ux_fixes.py`, `test_workflow_save.py`, `test_dual_mode_stdin.py`, `test_enhanced_error_output.py`, `test_workflow_output_source_simple.py`, `test_rerun_display.py`, `test_progress_streaming_subprocess.py`, `test_e2e_workflow.py`, `test_metrics_integration.py`, `test_sigpipe_regression.py`, `test_workflow_outputs_namespaced.py`, `test_shell_smart_handling.py`.

Run `make test` after Phase 1 and fix any assertion failures in these files.

### Checkpoint

```bash
make test && make check
pflow --help          # Should show placeholder entry content + auto-generated Commands
pflow --version       # Should show version
pflow --verbose list  # Should work (verbose is group option, list is a command)
```

---

## Phase 2: Flatten Workflow Commands

**Objective:** Split `workflow.py` into per-command files. Delete `workflow.py`. Register new commands in the group.

### Create: `src/pflow/cli/commands/list.py`

Port the `list_workflows` function from `workflow.py:19-69`.

```python
@click.command(name="list")
@click.argument("keywords", nargs=-1)
@click.option("--json", "output_json", is_flag=True, help="Output as JSON")
def list_cmd(keywords: tuple[str, ...], output_json: bool) -> None:
    """List saved workflows, optionally filtered by keywords."""
```

**Changes from current `workflow list`:**
- Argument changes from `filter_pattern` (single string) to `keywords` (nargs=-1 tuple)
- The function name is `list_cmd` (not `list` — avoid shadowing the built-in)
- Add smart-case: if a keyword contains any uppercase letter, match case-sensitively for that keyword; otherwise case-insensitive
- Add match highlighting: when outputting text, use `click.style(matched_substring, bold=True)` for matched parts in name and description

**Smart-case implementation:**
```python
def _matches_keyword(keyword: str, text: str) -> bool:
    if keyword == keyword.lower():
        return keyword in text.lower()
    return keyword in text

# In filter logic:
if keywords:
    workflows = [
        w for w in workflows
        if all(
            _matches_keyword(kw, w.get("name", "")) or _matches_keyword(kw, w.get("description", ""))
            for kw in keywords
        )
    ]
```

**Match highlighting:** Pass `highlight_keywords` to the formatter or apply highlighting after formatting. Simplest approach: apply highlighting to the workflow name and description in the output. Use `click.style(substring, bold=True)`. Click auto-strips ANSI codes for non-TTY output.

**Imports needed:**
- `json`, `sys`, `click`
- `from pflow.core.workflow.manager import WorkflowManager`
- Lazy: `from pflow.execution.formatters.workflow_list_formatter import format_workflow_list`

**Current logic to preserve:** The empty-state message ("No saved workflows"), the JSON mode (strip `ir` field), the no-results-with-keywords guidance.

### Create: `src/pflow/cli/commands/find.py`

Port the `discover_workflows` function from `workflow.py:150-190`.

```python
@click.command(name="find")
@click.argument("query")
def find_cmd(query: str) -> None:
    """Search saved workflows by intent using LLM.

    Unlike 'list' (keyword matching), 'find' uses an LLM to understand
    what you're looking for and match it to saved workflows.

    Examples:
      pflow find "something that fetches github PRs"
      pflow find "workflow for sending slack notifications"
    """
```

**Imports needed:**
- `sys`, `click`
- `from pflow.core.workflow.manager import WorkflowManager`
- Lazy: `from pflow.core.workflow.discovery import discover_workflow`
- Lazy: `from pflow.execution.formatters.discovery_formatter import format_discovery_result, format_no_matches_with_suggestions`
- Lazy: `from pflow.cli.discovery_errors import handle_discovery_error`

**Move from `workflow.py`:** The `_validate_discovery_query` helper (inline it in this file).

**Logic:** Identical to current `workflow discover`. Validate query (non-empty, max 500 chars), call `discover_workflow(query, workflow_manager=manager)`, format and display result.

### Create: `src/pflow/cli/commands/describe.py`

Port the `describe_workflow` function from `workflow.py:85-102`.

```python
@click.command(name="describe")
@click.argument("name")
def describe_cmd(name: str) -> None:
    """Show workflow interface — inputs, outputs, and example usage.

    Examples:
      pflow describe my-workflow
      pflow describe fetch-github-prs
    """
```

**Imports needed:**
- `sys`, `click`
- `from pflow.core.workflow.manager import WorkflowManager`
- Lazy: `from pflow.execution.formatters.workflow_describe_formatter import format_workflow_interface`

**Include inline:** The `_handle_workflow_not_found` helper (7 lines). Duplicate it here — it's too small for a shared module. Also used by `history.py` (duplicate there too).

```python
def _handle_workflow_not_found(name: str, wm: WorkflowManager) -> None:
    all_workflows = wm.list_all()
    similar = [w["name"] for w in all_workflows if name.lower() in w["name"].lower()][:3]
    click.echo(f"Error: Workflow '{name}' not found.", err=True)
    if similar:
        click.echo(f"  Did you mean: {', '.join(similar)}", err=True)
    sys.exit(1)
```

### Create: `src/pflow/cli/commands/history.py`

Port the `workflow_history` function from `workflow.py:105-129`.

```python
@click.command(name="history")
@click.argument("workflow_name")
def history_cmd(workflow_name: str) -> None:
    """Show execution history for a saved workflow.

    Examples:
      pflow history my-workflow
    """
```

**Imports needed:**
- `sys`, `click`
- `from pflow.core.workflow.manager import WorkflowManager`
- Lazy: `from pflow.execution.formatters.history_formatter import format_workflow_history`

**Include inline:** Duplicate `_handle_workflow_not_found` (same as describe.py).

### Create: `src/pflow/cli/commands/save.py`

Port the `save_workflow` function from `workflow.py:249-330`.

```python
@click.command(name="save")
@click.argument("file_path", type=click.Path(exists=True, readable=True))
@click.option("--name", required=True, help="Workflow name (lowercase-with-hyphens, max 50 chars)")
@click.option("--delete-draft", is_flag=True, help="Delete source file after save")
@click.option("--force", is_flag=True, help="Overwrite existing workflow")
def save_cmd(file_path: str, name: str, delete_draft: bool, force: bool) -> None:
    """Save a workflow file to the library.

    Examples:
      pflow save workflow.pflow.md --name my-workflow
      pflow save draft.pflow.md --name api-fetcher --delete-draft
      pflow save workflow.pflow.md --name my-workflow --force
    """
```

**Fix:** Change `--name` help text from "max 30 chars" to "max 50 chars" (matching actual validation).

**Move from `workflow.py`:** The `_delete_draft_if_requested` helper (inline it).

**Imports needed:**
- `sys`, `click`, `from pathlib import Path`
- `from pflow.core.exceptions import MarkdownParseError, WorkflowValidationError`
- Lazy: `from pflow.core.workflow.save_service import save_workflow_with_options, validate_workflow_name, delete_draft_safely`
- Lazy: `from pflow.execution.formatters.validation_formatter import format_validation_failure`
- Lazy: `from pflow.execution.formatters.workflow_save_formatter import format_save_success`

### Delete: `src/pflow/cli/commands/workflow.py`

Entire file removed after all subcommands are ported.

### Update: `src/pflow/cli/main.py` — command registration

Replace the `workflow` group registration:

```python
# Remove:
from pflow.cli.commands.workflow import workflow  # noqa: E402
cli.add_command(workflow)

# Add:
from pflow.cli.commands.list import list_cmd  # noqa: E402
from pflow.cli.commands.find import find_cmd  # noqa: E402
from pflow.cli.commands.describe import describe_cmd  # noqa: E402
from pflow.cli.commands.history import history_cmd  # noqa: E402
from pflow.cli.commands.save import save_cmd  # noqa: E402

cli.add_command(list_cmd)
cli.add_command(find_cmd)
cli.add_command(describe_cmd)
cli.add_command(history_cmd)
cli.add_command(save_cmd)
```

### Test changes for Phase 2

**Split `tests/test_cli/test_workflow_commands.py`** into:
- `tests/test_cli/test_list.py` — list-related tests
- `tests/test_cli/test_describe.py` — describe-related tests
- `tests/test_cli/test_history.py` — history-related tests

**Update all mock.patch targets:**
- `pflow.cli.commands.workflow.WorkflowManager` → `pflow.cli.commands.list.WorkflowManager` (in list tests), `pflow.cli.commands.describe.WorkflowManager` (in describe tests), etc.

**Split `tests/test_cli/test_discovery_commands.py`:**
- Workflow discover tests → `tests/test_cli/test_find.py`
- Registry discover tests → keep temporarily, move to `test_mcp_commands.py` in Phase 4
- Update patches: `pflow.core.workflow.discovery.discover_workflow` patches stay the same (they patch the source, not the CLI import site)

**Delete `tests/test_cli/test_workflow_commands.py`** after split is complete.

**Update `tests/test_cli/test_workflow_save_cli.py`:**
- Line 12 imports `from pflow.cli.commands.workflow import workflow as workflow_cmd` → change to import `save_cmd` from `pflow.cli.commands.save`
- 15+ CliRunner invocations need to invoke `save_cmd` instead of `workflow_cmd` with `["save", ...]` args

**Update `tests/test_cli/test_workflow_save_security.py`:**
- Lines 169, 181, 190 import `_validate_discovery_query` from `commands/workflow` → update to import from `commands/find` (where it's inlined)

**New test for `list` keyword filtering:**
- Smart-case: verify that `pflow list "HTTP"` is case-sensitive but `pflow list "http"` is case-insensitive
- AND logic: verify `pflow list "github" "pr"` requires both keywords to match
- Name + description search: verify keywords match against both fields
- Empty result: verify helpful guidance message

### Checkpoint

```bash
make test && make check
pflow list                  # Lists saved workflows
pflow list github           # Filters by keyword
pflow find "fetch api"      # LLM search (may fail without API key — that's OK)
pflow describe <name>       # Shows interface
pflow history <name>        # Shows history
pflow save <file> --name x  # Saves
pflow workflow list         # Should still work (workflow group still registered in Phase 1)
```

Wait — in Phase 2, we delete `workflow.py` and remove the `workflow` group. So `pflow workflow list` should fail after Phase 2. This is expected (clean cutover).

---

## Phase 3: New Commands + Deletions

**Objective:** Create `guide` and `probe` commands. Delete `registry`, `instructions` commands. Move `normalize_node_id` to registry package.

### Create: `src/pflow/cli/commands/guide.py`

```python
"""pflow guide command — learn how to build workflows."""
import click

from pflow.guide import render_entry_content


@click.command(name="guide")
@click.argument("topics", nargs=-1)
def guide_cmd(topics: tuple[str, ...]) -> None:
    """Learn how to build workflows with pflow.

    Without arguments, shows the same overview as 'pflow --help'.
    With topics, shows tailored content for those topics (Task 77).

    Examples:
      pflow guide              Show overview
      pflow guide http llm     Learn about HTTP and LLM nodes
      pflow guide batch        Learn about batch processing
    """
    if not topics:
        click.echo(render_entry_content())
        return

    # Task 77 will implement compose_guide(topics).
    # Until then, show a helpful placeholder.
    topic_list = ", ".join(topics)
    click.echo(f"Guide content for topics [{topic_list}] is not yet implemented.")
    click.echo("This will be available after Task 77 ships.")
    click.echo()
    click.echo("Meanwhile, for full instructions run:")
    click.echo("  cat src/pflow/cli/resources/cli-agent-instructions.md")
```

### Create: `src/pflow/cli/commands/probe.py`

Port from `registry_run.py`. The `probe` command is a Click command that wraps `execute_single_node()`.

```python
"""pflow probe — test a single node interactively."""
import click


@click.command(name="probe")
@click.argument("node_type")
@click.argument("params", nargs=-1)
@click.option("--output-format", type=click.Choice(["json"]), default=None, help="Output format")
@click.pass_context
def probe_cmd(ctx: click.Context, node_type: str, params: tuple[str, ...], output_format: str | None) -> None:
    """Test a single node without building a full workflow.

    Returns metadata and template paths — not raw data. This prevents
    context overload and lets you use read-fields for specific values.

    Examples:
      pflow probe shell command="echo hello"
      pflow probe http url="https://api.example.com/data"
      pflow probe llm prompt="Summarize this" model="gpt-4"
      pflow probe mcp-github-create-issue owner="org" repo="my-repo" title="Bug"
    """
    from pflow.cli.commands._probe_impl import execute_single_node

    # Read verbose from group-level --verbose (not a probe-specific flag)
    verbose = ctx.obj.get("verbose", False)
    execute_single_node(
        node_type=node_type,
        params=params,
        output_format=output_format or "text",
        show_structure=(output_format != "json"),
        verbose=verbose,
    )
```

### Rename: `src/pflow/cli/commands/registry_run.py` → `src/pflow/cli/commands/_probe_impl.py`

Rename the file. Update the lazy import inside it:

```python
# Old (line 145):
from pflow.cli.commands.registry import normalize_node_id
# New:
from pflow.registry.node_id import normalize_node_id
```

No other changes to the file's logic. The leading underscore signals it's an internal implementation module, not a Click command.

### Move: `normalize_node_id()` to `src/pflow/registry/node_id.py`

Create a new file `src/pflow/registry/node_id.py` containing the `normalize_node_id` function (currently at `registry.py:467-517`). Pure function, no CLI dependencies.

Update `src/pflow/registry/__init__.py` to export it:
```python
from pflow.registry.node_id import normalize_node_id
```

### Delete: `src/pflow/cli/commands/registry.py`

Entire file. All subcommands are either:
- Moved to `probe.py` (`run`)
- Absorbed by `mcp list/find/describe` (Phase 4)
- Removed (`scan`)

### Delete: `src/pflow/cli/commands/instructions.py`

Entire file. Replaced by `guide.py`.

### Update: `src/pflow/cli/main.py` — command registration

```python
# Remove:
from pflow.cli.commands.registry import registry
from pflow.cli.commands.instructions import instructions
cli.add_command(registry)
cli.add_command(instructions)

# Add:
from pflow.cli.commands.guide import guide_cmd
from pflow.cli.commands.probe import probe_cmd
cli.add_command(guide_cmd)
cli.add_command(probe_cmd)
```

### Test changes for Phase 3

**Create `tests/test_cli/test_guide.py`:**
- `pflow guide` returns non-empty placeholder (or entry.md content)
- `pflow guide http` returns placeholder with topic acknowledgment
- `pflow guide http llm` accepts multiple topics

**Rename `tests/test_cli/test_registry_run.py` → `tests/test_cli/test_probe.py`:**
- Update ALL 39 mock.patch targets: `pflow.cli.commands.registry_run.*` → `pflow.cli.commands._probe_impl.*`
- Update the Click command invocation: invoke `probe_cmd` instead of `registry` group's `run`
- Update CliRunner to invoke `probe_cmd` directly (no longer via `registry` group)

**Update `tests/test_cli/test_registry_normalization.py`:**
- Change import: `from pflow.cli.commands.registry import normalize_node_id` → `from pflow.registry.node_id import normalize_node_id`
- Remove any tests for the `registry describe` command (if the test file contains `TestRegistryDescribeCommand`, remove that test class or move to `test_mcp_commands.py`)

**Delete or gut `tests/test_cli/test_registry_cli.py`:**
- Tests for `registry list`, `registry describe`, `registry scan` are no longer needed
- Tests for `registry discover` move to `test_mcp_commands.py` in Phase 4 (adapted for `mcp find`)
- The routing test at line 632 (patching `workflow_command`) already updated in Phase 1

**Delete `tests/test_cli/test_registry_describe.py`:**
- Tests for `registry describe` are no longer needed

**Delete `tests/test_cli/test_instructions.py`:**
- Replaced by `test_guide.py`

### Checkpoint

```bash
make test && make check
pflow guide                    # Shows placeholder
pflow guide http               # Shows topic placeholder
pflow probe shell command="echo hi"  # Runs shell node, shows metadata
pflow registry list            # Should fail (command not found)
pflow instructions usage       # Should fail (command not found)
```

---

## Phase 4: MCP Namespace Restructure

**Objective:** Rename `mcp list` → `mcp servers`. Create new `mcp list` (tools), `mcp find`, `mcp describe`. Remove `mcp tools` and `mcp info`.

### Modify: `src/pflow/cli/commands/mcp.py`

This is a significant rewrite of the file. Here are the changes:

**1. Rename `list_servers` to `servers`:**

```python
# Old:
@mcp.command(name="list")
def list_servers(output_json):
# New:
@mcp.command(name="servers")
def servers(output_json):
    """List configured MCP servers."""
```

Logic unchanged — it still calls `MCPServerManager().get_all_servers()`.

**2. Create new `mcp list` (tools, grouped-by-server):**

```python
@mcp.command(name="list")
@click.argument("keywords", nargs=-1)
@click.option("--json", "output_json", is_flag=True, help="Output as JSON")
def list_tools(keywords: tuple[str, ...], output_json: bool) -> None:
    """List MCP tools, optionally filtered by keywords.

    Without keywords, shows a grouped-by-server summary.
    With keywords, shows matching tools with full details.

    Keywords use AND logic and search both name and description.
    Smart-case: lowercase keywords match case-insensitively.

    Examples:
      pflow mcp list                   Show all tools grouped by server
      pflow mcp list slack             Filter to tools matching 'slack'
      pflow mcp list slack send        Tools matching both 'slack' AND 'send'
    """
```

**Implementation for no-keyword mode (grouped summary):**

Use `MCPRegistrar.registry.load()` directly (not `list_registered_tools()`) to get full metadata in one call. Group by `entry["interface"]["mcp_metadata"]["server"]` (robust — don't use name splitting). Show:

```
MCP Tools (247 total across 6 servers)

slack (38 tools)
  send-message, list-channels, get-user, post-reaction, upload-file...

github (52 tools)
  create-issue, list-repos, get-pull, create-pr, merge-pr...
```

For each server: show count + first 5 tool names (use `mcp_metadata["tool"]` for the clean name, not the full `mcp-server-tool` node name). Truncate with `...` if more than 5.

Cross-reference with `MCPServerManager.list_servers()` to show servers with zero tools (configured but not synced) with a sync suggestion.

**Implementation for keyword mode (filtered detail):**

Filter all MCP nodes using the same smart-case AND logic as `pflow list`. Show matching tools with full name + description, grouped by server. Highlight matched substrings.

```
Matching MCP tools (3 results):

slack:
  mcp-slack-send-message — Send a message to a channel
  mcp-slack-post-reaction — Add a reaction to a message

github:
  mcp-github-create-issue — Create a new issue in a repository
```

**3. Create new `mcp find` (LLM search):**

```python
@mcp.command(name="find")
@click.argument("query")
def find_tools(query: str) -> None:
    """Search MCP tools by intent using LLM.

    Unlike 'mcp list' (keyword matching), 'mcp find' uses an LLM
    to understand what you're looking for across all MCP servers.

    Examples:
      pflow mcp find "send a slack message"
      pflow mcp find "create github issues"
    """
```

**Implementation:**
1. Validate query (non-empty, max 500 chars) — same pattern as `find.py`
2. Load registry, filter to `mcp-` prefixed nodes
3. Call `discover_components(query, registry_metadata=mcp_only_metadata)` — this requires adding an optional `registry_metadata` parameter to `discover_components()` (see Phase 5, but add the parameter HERE to unblock this command)
4. Display result using `discovery_formatter.format_discovery_result()` or a simpler format showing matched tools
5. Error handling via `handle_discovery_error()` from `cli/discovery_errors.py`

**Note on `discover_components` parameter:** Add the `registry_metadata` parameter to `discover_components()` in this phase (even though the rename happens in Phase 5). This is necessary because `mcp find` needs to scope to MCP-only nodes.

**4. Rename `info` to `describe`:**

```python
# Old:
@mcp.command(name="info")
def info(tool):
# New:
@mcp.command(name="describe")
def describe_tool(tool):
    """Show detailed information about an MCP tool.

    Examples:
      pflow mcp describe mcp-github-create-issue
      pflow mcp describe mcp-slack-send-message
    """
```

Logic unchanged — same `MCPRegistrar.get_tool_info()` call, same output format.

**5. Remove `tools` command:**

Delete the `tools` function and its `@mcp.command(name="tools")` decorator. Also delete the helper functions that ONLY `tools` uses: `_get_tools_info_as_json`, `_display_server_tools`, `_display_all_tools_grouped`, `_group_tools_by_server` (unless the new `list_tools` reuses any of them).

Actually, `_group_tools_by_server` is useful for the new `list_tools` but uses naive name-splitting. Write a better version that uses `mcp_metadata.server` from registry entries.

**Helpers to keep:** `_format_server_output`, `_format_http_server`, `_format_stdio_server` (used by `servers`), `_validate_timeout_flags`, `_apply_http_timeouts`, `_is_json_string`, `_is_server_config`, `_add_from_json_string` (used by `add`), `_validate_sync_arguments`, `_sync_all_servers`, `_sync_single_server`, `_display_registered_tools` (used by `sync`), `_format_tool_header`, `_format_parameters`, `_format_outputs`, `_suggest_similar_tools` (used by `describe`).

**Helpers to delete:** `_get_tools_info_as_json`, `_display_server_tools`, `_display_all_tools_grouped`, `_group_tools_by_server` (replaced by better implementation in `list_tools`).

### Modify: `src/pflow/registry/discovery.py`

Add optional `registry_metadata` parameter to `discover_components()`:

```python
def discover_components(
    task: str,
    model_name: Optional[str] = None,
    registry_metadata: Optional[dict[str, Any]] = None,  # NEW
) -> ComponentSelection:
    if registry_metadata is None:
        registry = Registry()
        registry_metadata = registry.load()
    # ... rest of function uses registry_metadata instead of loading its own
```

This is backward-compatible. Existing callers (MCP server's `discovery_service.py`) don't pass it and get the old behavior.

### Test changes for Phase 4

**Create `tests/test_cli/test_mcp_commands.py`:**
- Test `mcp servers` lists configured servers (port from existing mcp list tests)
- Test `mcp list` no-args: grouped-by-server summary format
- Test `mcp list` with keywords: filtered detail view
- Test `mcp list` with multiple keywords: AND logic
- Test `mcp find`: LLM search (mock the LLM call)
- Test `mcp describe`: tool detail view (port from existing mcp info tests)
- Test `mcp tools` is gone (invocation should fail)
- Test `mcp info` is gone

### Checkpoint

```bash
make test && make check
pflow mcp servers              # Lists configured servers (was: mcp list)
pflow mcp list                 # Grouped tool summary
pflow mcp list slack           # Filtered tool list
pflow mcp find "send a message" # LLM search (may fail without API key)
pflow mcp describe <tool>      # Tool details
pflow mcp tools                # Should fail (removed)
pflow mcp info <tool>          # Should fail (removed)
```

---

## Phase 5: Shared Service Renames + Cleanup

**Objective:** Rename shared functions, consolidate reserved names, flatten settings output-mode, rename discovery_errors, clean up dead code.

### 5a. Rename `discover_workflow()` → `find_workflow()`

**File:** `src/pflow/core/workflow/discovery.py`

Rename the function. Update all import sites:

| File | Old import | New import |
|------|-----------|------------|
| `src/pflow/cli/commands/find.py` | `from pflow.core.workflow.discovery import discover_workflow` | `from pflow.core.workflow.discovery import find_workflow` |
| `src/pflow/mcp_server/services/discovery_service.py:32` | `from pflow.core.workflow.discovery import discover_workflow` | `from pflow.core.workflow.discovery import find_workflow` |
| `tests/test_cli/test_discovery_commands.py` (or wherever it moved) | `pflow.core.workflow.discovery.discover_workflow` | `pflow.core.workflow.discovery.find_workflow` |

### 5b. Rename `discover_components()` → `find_components()`

**File:** `src/pflow/registry/discovery.py`

Rename the function (already has the new `registry_metadata` parameter from Phase 4).

Update all import sites:

| File | Old import | New import |
|------|-----------|------------|
| `src/pflow/cli/commands/mcp.py` (in `find_tools`) | `from pflow.registry.discovery import discover_components` | `from pflow.registry.discovery import find_components` |
| `src/pflow/mcp_server/services/discovery_service.py:68` | `from pflow.registry.discovery import discover_components` | `from pflow.registry.discovery import find_components` |
| Any test files patching this function | Update patch target |

### 5c. Consolidate reserved workflow names

**Goal:** Single source of truth for reserved names. Expand to include ALL CLI command names + `run`.

**File: `src/pflow/core/workflow/save_service.py`**

Replace `RESERVED_WORKFLOW_NAMES` (lines 20-30):

```python
RESERVED_WORKFLOW_NAMES: frozenset[str] = frozenset({
    # Generic reserved
    "null", "undefined", "none", "test",
    # Top-level CLI commands
    "list", "find", "describe", "history", "save", "guide", "probe",
    "run", "read-fields",
    # CLI command groups
    "mcp", "skill", "settings", "trace", "visualize",
    # Legacy (prevent confusion)
    "registry", "workflow", "instructions",
})
```

Change from `set` to `frozenset` for immutability.

**File: `src/pflow/core/workflow/manager.py`**

Replace the private `_validate_workflow_name` method (lines 114-148) to delegate to `save_service.validate_workflow_name`:

```python
def _validate_workflow_name(self, name: str) -> None:
    from pflow.core.workflow.save_service import validate_workflow_name
    is_valid, error = validate_workflow_name(name)
    if not is_valid:
        raise WorkflowValidationError(error)
```

This eliminates the duplicated reserved names set and regex.

### 5d. Rename `discovery_errors.py` → `find_errors.py`

**Rename:** `src/pflow/cli/discovery_errors.py` → `src/pflow/cli/find_errors.py`

**Update import sites (2 lazy imports):**
- `src/pflow/cli/commands/find.py`: `from pflow.cli.find_errors import handle_discovery_error`
- `src/pflow/cli/commands/mcp.py` (in `find_tools`): `from pflow.cli.find_errors import handle_discovery_error`

The function name `handle_discovery_error` stays the same (it's descriptive of what it does, not tied to the old CLI verb).

### 5e. Flatten `settings registry output-mode` → `settings output-mode`

**File: `src/pflow/cli/commands/settings.py`**

Remove the `registry` subgroup (lines 543-549):
```python
# DELETE:
@settings.group(name="registry")
def registry_settings() -> None:
    """Manage registry settings."""
    pass
```

Change the `output-mode` command's parent from `registry_settings` to `settings`:
```python
# Old:
@registry_settings.command(name="output-mode")
# New:
@settings.command(name="output-mode")
```

Update the help text and examples within the function (line 581 references `pflow settings registry output-mode`).

### 5f. Clean up dead code

1. **`src/pflow/cli/commands/registry.py`** — already deleted in Phase 3
2. **`_output_json_describe()` in registry.py** — already deleted (dead code, never called)
3. **Verify formatters are NOT dead:** All formatters in `execution/formatters/` have MCP server consumers. Do NOT delete any of them. The commands being moved (not deleted) will re-import them from new file locations.

### Test changes for Phase 5

- `tests/test_core/test_workflow_discovery.py` — imports `discover_workflow` at line 6 → rename to `find_workflow`. Update 7+ direct calls throughout the file.
- `tests/test_registry/test_component_discovery.py` — imports `discover_components` at line 3 → rename to `find_components`. Update 7+ direct calls.
- Update any mock.patch targets referencing `discover_workflow` → `find_workflow`
- Update any mock.patch targets referencing `discover_components` → `find_components`
- Update `tests/test_cli/test_settings_cli.py` — if it tests `settings registry output-mode`, update to test `settings output-mode`
- Create `tests/test_cli/test_reserved_names.py` — test that all CLI command names are rejected by `validate_workflow_name()`: `list`, `find`, `describe`, `history`, `save`, `guide`, `probe`, `run`, `mcp`, `skill`, `settings`, `trace`, `visualize`, `read-fields`, `instructions`, `registry`, `workflow`

### Checkpoint

```bash
make test && make check
pflow save test.pflow.md --name list      # Should fail: reserved name
pflow save test.pflow.md --name find      # Should fail: reserved name
pflow settings output-mode                # Should show current mode
pflow settings output-mode structure      # Should set mode
pflow settings registry output-mode       # Should fail (removed)
```

---

## Phase 5.5: Stale Command References in Production Code

**Objective:** Update ALL user-visible strings that reference deleted CLI commands. These are in error messages, help text, suggestion strings, and enrichment templates across production code. The plan review found 12+ files with stale references that the original plan marked as "NOT touched."

**Strategy:** Run a comprehensive grep across ALL `.py` files and update every hit:

```bash
grep -rn "'pflow registry\|\"pflow registry\|'pflow workflow \|\"pflow workflow \|'pflow instructions\|\"pflow instructions\|pflow mcp tools\|pflow mcp info" src/pflow/ --include="*.py"
```

**Known files with stale command references:**

| File | Lines | Old reference | New reference |
|------|-------|--------------|---------------|
| `src/pflow/core/exceptions.py` | 76 | `"pflow workflow list"` | `"pflow list"` |
| `src/pflow/core/workflow/skill_service.py` | 97 | `"pflow workflow history"` | `"pflow history"` |
| `src/pflow/core/workflow/skill_service.py` | 100-102 | `"pflow instructions create"` | `"pflow guide"` |
| `src/pflow/cli/commands/skills.py` | 129, 140, 223 | `"pflow workflow save"` | `"pflow save"` |
| `src/pflow/cli/commands/read_fields.py` | 51 | `"pflow registry run"` | `"pflow probe"` |
| `src/pflow/cli/commands/settings.py` | 348, 455, 557 | `"pflow registry discover"`, `"pflow workflow discover"`, `"pflow registry run"` | `"pflow mcp find"` / `"pflow find"` / `"pflow probe"` |
| `src/pflow/cli/rerun_display.py` | 90 | `"pflow workflow describe"` | `"pflow describe"` |
| `src/pflow/execution/formatters/registry_error_helpers.py` | 28, 29, 63, 66, 68 | `"pflow registry discover"`, `"pflow registry list"`, `"pflow registry describe"` | `"pflow mcp find"`, `"pflow mcp list"`, `"pflow mcp describe"` |
| `src/pflow/execution/formatters/workflow_save_formatter.py` | 90 | `"pflow workflow describe"` | `"pflow describe"` |
| `src/pflow/execution/formatters/workflow_list_formatter.py` | 75 | `"pflow workflow save"` | `"pflow save"` |
| `src/pflow/runtime/compilation/mcp_resolution.py` | 67, 96 | `"pflow registry list"` | `"pflow mcp list"` |
| `src/pflow/nodes/mcp/node.py` | 43, 127, 215 | `"pflow registry run"`, `"pflow registry list"` | `"pflow probe"`, `"pflow mcp list"` |
| `src/pflow/cli/find_errors.py` (renamed in Phase 5) | 37-38 | `"pflow workflow list"`, `"pflow workflow describe"` | `"pflow list"`, `"pflow describe"` |

**Also update `commands/run.py`** (the moved code from `main.py`):
- Lines 491, 852-873 contain `"pflow workflow list"` and other stale suggestions in `_handle_invalid_workflow_input`

**Also update `architecture/` docs:**
- `architecture/architecture.md` — 15+ references to old commands
- `architecture/features/simple-nodes.md` — 5+ references
- `architecture/CLAUDE.md` — 2 references

**After updating, verify with grep:**
```bash
grep -rn "pflow registry\|pflow workflow list\|pflow workflow describe\|pflow workflow discover\|pflow workflow history\|pflow workflow save\|pflow instructions\|pflow mcp tools\|pflow mcp info" src/pflow/ --include="*.py" | grep -v changelog | grep -v "# historical"
```
Should return zero hits.

### Checkpoint
```bash
make test && make check
# Verify grep returns zero stale references
```

---

## Phase 6: Documentation

**Objective:** Update all documentation to reflect the new CLI surface.

### 6a. Internal docs — search-and-replace in resource files

**File: `src/pflow/cli/resources/cli-agent-instructions.md`**

Search-and-replace (apply ALL, not just the first occurrence):

| Old | New |
|-----|-----|
| `pflow workflow discover` | `pflow find` |
| `pflow workflow list` | `pflow list` |
| `pflow workflow describe` | `pflow describe` |
| `pflow workflow history` | `pflow history` |
| `pflow workflow save` | `pflow save` |
| `pflow registry run` | `pflow probe` |
| `pflow registry list` | Context-dependent: if about MCP tools → `pflow mcp list`; if about node discovery → `pflow guide` |
| `pflow registry describe` | Context-dependent: if about MCP tools → `pflow mcp describe`; if about core nodes → `pflow guide <topic>` |
| `pflow registry discover` | Context-dependent: if about MCP → `pflow mcp find`; if about building → `pflow guide` |
| `pflow registry scan` | Remove the reference (feature deprecated) |
| `pflow instructions usage` | `pflow --help` |
| `pflow instructions create` | `pflow guide` |
| `pflow mcp tools` | `pflow mcp list` |
| `pflow mcp info` | `pflow mcp describe` |
| `pflow mcp list` (in server-listing context) | `pflow mcp servers` |

**Context-dependent replacements require reading the surrounding paragraph.** The agent should read each occurrence and decide based on whether it's talking about MCP tools or core node discovery.

**File: `src/pflow/cli/resources/cli-basic-usage.md`**

Same search-and-replace table as above.

### 6b. CLAUDE.md updates

**File: `src/pflow/cli/CLAUDE.md`**

Update to reflect new architecture:
- Document `PflowCLI` group class
- Document per-command file structure
- Update mock.patch target documentation
- Remove references to `main_wrapper.py`
- Document the `run` command as the hidden default

**File: `src/pflow/cli/commands/CLAUDE.md`**

Update per-command documentation:
- Remove `workflow.py`, `registry.py`, `registry_run.py`, `instructions.py`
- Add `list.py`, `find.py`, `describe.py`, `history.py`, `save.py`, `guide.py`, `probe.py`, `run.py`
- Document `_probe_impl.py` as internal implementation

**File: `README.md`**

Update the CLI commands section with new command names.

### 6c. User-facing docs (`docs/` folder)

**Files to DELETE:**
- `docs/reference/cli/workflow.mdx`
- `docs/reference/cli/registry.mdx`

**Files to CREATE (7 new pages):**
- `docs/reference/cli/list.mdx` — `pflow list` reference
- `docs/reference/cli/find.mdx` — `pflow find` reference
- `docs/reference/cli/describe.mdx` — `pflow describe` reference
- `docs/reference/cli/history.mdx` — `pflow history` reference
- `docs/reference/cli/save.mdx` — `pflow save` reference
- `docs/reference/cli/guide.mdx` — `pflow guide` reference
- `docs/reference/cli/probe.mdx` — `pflow probe` reference

Each new page should follow the format of existing CLI reference pages (look at `docs/reference/cli/skill.mdx` as a template). Include: description, usage syntax, options, examples.

**File: `docs/docs.json`**

Update the "CLI commands" group in navigation:

```json
{
  "group": "CLI commands",
  "pages": [
    "reference/cli/index",
    "reference/cli/list",
    "reference/cli/find",
    "reference/cli/describe",
    "reference/cli/history",
    "reference/cli/save",
    "reference/cli/guide",
    "reference/cli/probe",
    "reference/cli/skill",
    "reference/cli/mcp",
    "reference/cli/settings"
  ]
}
```

Remove `reference/cli/workflow` and `reference/cli/registry` from the navigation.

**Files to UPDATE (search-and-replace old CLI commands):**

Apply the same search-and-replace table from 6a to ALL docs files listed below. Also fix 7 broken cross-reference links (links to deleted `workflow.mdx` and `registry.mdx`).

| File | Approx references | Notes |
|------|-------------------|-------|
| `docs/reference/cli/index.mdx` | 9 | Major rewrite — command cards, links |
| `docs/reference/cli/mcp.mdx` | 14 | `list` → `servers`, add `list`/`find`/`describe`, remove `tools`/`info` |
| `docs/reference/cli/skill.mdx` | 2 | Minor — fix workflow/registry references |
| `docs/reference/cli/settings.mdx` | 5 | Fix `registry run` reference, update `settings registry` to `settings output-mode` |
| `docs/quickstart.mdx` | 7 | Critical user path — verify walkthrough works |
| `docs/guides/using-pflow.mdx` | 4 | Fix workflow/registry references |
| `docs/guides/publishing-skills.mdx` | 4 | Fix workflow references |
| `docs/guides/adding-mcp-servers.mdx` | 6 | Fix mcp tools/info/list references |
| `docs/guides/debugging.mdx` | 1 | Fix mcp list reference |
| `docs/integrations/overview.mdx` | 1 | Fix instructions reference |
| `docs/integrations/claude-code.mdx` | 1 | Fix instructions reference |
| `docs/integrations/cursor.mdx` | 2 | Fix instructions/workflow references |
| `docs/integrations/windsurf.mdx` | 2 | Fix instructions/workflow references |
| `docs/integrations/claude-desktop.mdx` | 1 | Fix workflow reference |
| `docs/integrations/vscode.mdx` | 1 | Fix workflow reference |
| `docs/reference/nodes/mcp.mdx` | 1 | Fix registry reference |
| `docs/reference/nodes/index.mdx` | 6 | Fix registry references |
| `docs/reference/configuration.mdx` | 3 | Fix registry references |
| `docs/index.mdx` | 1 | Fix workflow reference |
| `docs/roadmap.mdx` | 1 | Fix workflow reference |
| `docs/CLAUDE.md` | 1 | Fix internal guidance reference |

**Files to NOT touch:**
- `docs/changelog.mdx` — historical entries keep old command names. ADD a new changelog entry for this restructure.

### 6d. Validation

After all doc updates, run:
```bash
grep -r "pflow registry" docs/ --include="*.mdx" | grep -v changelog.mdx   # Should return nothing
grep -r "pflow workflow discover" docs/ --include="*.mdx" | grep -v changelog.mdx  # Nothing
grep -r "pflow workflow list" docs/ --include="*.mdx" | grep -v changelog.mdx  # Nothing
grep -r "pflow workflow describe" docs/ --include="*.mdx" | grep -v changelog.mdx  # Nothing
grep -r "pflow workflow history" docs/ --include="*.mdx" | grep -v changelog.mdx  # Nothing
grep -r "pflow workflow save" docs/ --include="*.mdx" | grep -v changelog.mdx  # Nothing
grep -r "pflow instructions" docs/ --include="*.mdx" | grep -v changelog.mdx  # Nothing
grep -r "pflow mcp tools" docs/ --include="*.mdx" | grep -v changelog.mdx  # Nothing
grep -r "pflow mcp info" docs/ --include="*.mdx" | grep -v changelog.mdx  # Nothing
```

### Checkpoint

```bash
make test && make check
# All grep validations above pass
```

---

## Phase 7: Final Verification

### Automated

```bash
make test
make check
```

### Manual verification

```bash
# Help text
pflow --help                  # Entry content + auto-generated Commands
pflow guide                   # Same entry content as --help header
pflow mcp --help              # MCP namespace clean
pflow probe --help            # Explains metadata-not-data contract
pflow find --help             # Differentiates from list
pflow list --help             # Explains keyword matching
pflow mcp list --help         # Explains grouped summary vs keyword filter

# Workflow execution
pflow <some-workflow>.pflow.md          # Catch-all still works
pflow <saved-name> param=value          # Named workflow execution
pflow run <saved-name>                  # Run prefix works
pflow --verbose <saved-name>            # Verbose as group option

# New commands
pflow list                              # Lists saved workflows
pflow list github                       # Keyword filter
pflow describe <workflow>               # Shows interface
pflow history <workflow>                # Shows history
pflow probe shell command="echo hello"  # Tests shell node
pflow mcp servers                       # Lists configured servers
pflow mcp list                          # Grouped tool summary

# Reserved names
pflow save test.pflow.md --name find    # Should reject: reserved name
pflow save test.pflow.md --name list    # Should reject: reserved name

# Deleted commands (should all fail)
pflow workflow list                     # Not found
pflow registry list                     # Not found
pflow instructions usage                # Not found
pflow mcp tools                         # Not found
pflow mcp info <tool>                   # Not found

# Settings
pflow settings output-mode              # Works (was: settings registry output-mode)

# Unchanged commands
pflow skill list                        # Still works
pflow trace report                      # Still works
pflow visualize <workflow>              # Still works
pflow read-fields <exec-id> <path>      # Still works

# Error paths (MUST test — silent failures hide here)
pflow nonexistent-workflow           # Should show helpful error with suggestions
pflow my-workflow.pflow.md --help    # Should show workflow interface, NOT run command help
pflow --output-format json nonexistent.pflow.md  # JSON error output should work
pflow --output-format json list      # --output-format should pass through to run, not confuse list routing

# MCP server unaffected
# Connect via MCP client — old tool names (workflow_discover, registry_run, etc.) still work
```

---

## File Change Summary

### Files to CREATE
| File | Phase |
|------|-------|
| `src/pflow/guide/__init__.py` | 1 |
| `src/pflow/guide/entry.md` | 1 |
| `src/pflow/cli/commands/run.py` | 1 |
| `src/pflow/cli/commands/list.py` | 2 |
| `src/pflow/cli/commands/find.py` | 2 |
| `src/pflow/cli/commands/describe.py` | 2 |
| `src/pflow/cli/commands/history.py` | 2 |
| `src/pflow/cli/commands/save.py` | 2 |
| `src/pflow/cli/commands/guide.py` | 3 |
| `src/pflow/cli/commands/probe.py` | 3 |
| `src/pflow/registry/node_id.py` | 3 |
| `tests/test_cli/test_list.py` | 2 |
| `tests/test_cli/test_find.py` | 2 |
| `tests/test_cli/test_describe.py` | 2 |
| `tests/test_cli/test_history.py` | 2 |
| `tests/test_cli/test_guide.py` | 3 |
| `tests/test_cli/test_mcp_commands.py` | 4 |
| `tests/test_cli/test_reserved_names.py` | 5 |
| `docs/reference/cli/list.mdx` | 6 |
| `docs/reference/cli/find.mdx` | 6 |
| `docs/reference/cli/describe.mdx` | 6 |
| `docs/reference/cli/history.mdx` | 6 |
| `docs/reference/cli/save.mdx` | 6 |
| `docs/reference/cli/guide.mdx` | 6 |
| `docs/reference/cli/probe.mdx` | 6 |

### Files to DELETE
| File | Phase |
|------|-------|
| `src/pflow/cli/main_wrapper.py` | 1 |
| `src/pflow/cli/commands/workflow.py` | 2 |
| `src/pflow/cli/commands/registry.py` | 3 |
| `src/pflow/cli/commands/instructions.py` | 3 |
| `tests/test_cli/test_workflow_commands.py` | 2 |
| `tests/test_cli/test_instructions.py` | 3 |
| `tests/test_cli/test_registry_cli.py` | 3 |
| `tests/test_cli/test_registry_describe.py` | 3 |
| `tests/test_cli/test_discovery_commands.py` | 2/4 |
| `docs/reference/cli/workflow.mdx` | 6 |
| `docs/reference/cli/registry.mdx` | 6 |

### Files to RENAME
| Old | New | Phase |
|-----|-----|-------|
| `src/pflow/cli/commands/registry_run.py` | `src/pflow/cli/commands/_probe_impl.py` | 3 |
| `src/pflow/cli/discovery_errors.py` | `src/pflow/cli/find_errors.py` | 5 |
| `tests/test_cli/test_registry_run.py` | `tests/test_cli/test_probe.py` | 3 |

### Files to MODIFY (significant)
| File | Phase | What changes |
|------|-------|-------------|
| `src/pflow/cli/main.py` | 1 | Complete rewrite → small entry point |
| `src/pflow/cli/__init__.py` | 1 | Import source change |
| `src/pflow/cli/commands/mcp.py` | 4 | Major restructure |
| `src/pflow/cli/commands/settings.py` | 5 | Remove registry subgroup |
| `src/pflow/core/workflow/discovery.py` | 5 | Rename function |
| `src/pflow/core/workflow/save_service.py` | 5 | Expand reserved names, frozenset |
| `src/pflow/core/workflow/manager.py` | 5 | Delegate validation |
| `src/pflow/registry/discovery.py` | 4+5 | Add parameter, rename function |
| `src/pflow/registry/__init__.py` | 3 | Export normalize_node_id |
| `src/pflow/cli/commands/_probe_impl.py` | 3 | Update normalize_node_id import |
| `src/pflow/mcp_server/services/discovery_service.py` | 5 | Update 2 import names |

### Files ALSO modified (Phase 5.5 — stale command references)
| File | Phase | What changes |
|------|-------|-------------|
| `src/pflow/core/exceptions.py` | 5.5 | Stale `"pflow workflow list"` suggestion |
| `src/pflow/core/workflow/skill_service.py` | 5.5 | Stale `"pflow workflow history"`, `"pflow instructions create"` in enrichment templates |
| `src/pflow/cli/commands/skills.py` | 5.5 | Stale `"pflow workflow save"` references |
| `src/pflow/cli/commands/read_fields.py` | 5.5 | Stale `"pflow registry run"` reference |
| `src/pflow/cli/commands/settings.py` | 5 + 5.5 | Registry subgroup removal + stale command references |
| `src/pflow/cli/rerun_display.py` | 5.5 | Stale `"pflow workflow describe"` reference |
| `src/pflow/execution/formatters/registry_error_helpers.py` | 5.5 | Stale `"pflow registry *"` references (5 lines) |
| `src/pflow/execution/formatters/workflow_save_formatter.py` | 5.5 | Stale `"pflow workflow describe"` reference |
| `src/pflow/execution/formatters/workflow_list_formatter.py` | 5.5 | Stale `"pflow workflow save"` reference |
| `src/pflow/runtime/compilation/mcp_resolution.py` | 5.5 | Stale `"pflow registry list"` references |
| `src/pflow/nodes/mcp/node.py` | 5.5 | Stale `"pflow registry run"`, `"pflow registry list"` references |
| `src/pflow/core/settings.py` | 5.5 | Update `RegistrySettings.output_mode` description from "registry run" to "probe" |

### Files NOT touched
| File | Why |
|------|-----|
| `src/pflow/mcp_server/server.py` | Task 152 |
| `src/pflow/mcp_server/tools/*.py` | Task 152 |
| `src/pflow/mcp_server/resources/instructions/*.md` | Task 152 |
| `src/pflow/cli/commands/trace.py` | Unchanged |
| `src/pflow/cli/commands/visualize.py` | Unchanged |
| `tests/test_mcp_server/**` | MCP tests unchanged |

---

## Critical Gotchas

1. **Phase 1 ordering: create `src/pflow/guide/` BEFORE rewriting `main.py`.** `render_entry_content()` is called at import time via `help=render_entry_content()` on the group decorator. If the guide package doesn't exist, the import crashes. In Phase 1, the implementation order MUST be: (a) create guide package, (b) create `commands/run.py`, (c) rewrite `main.py`, (d) update `__init__.py`, (e) delete `main_wrapper.py`.

2. **`ignore_unknown_options=True` on BOTH the group AND the `run` command.** The group needs it so run-specific options (`--output-format`) pass through. The `run` command needs it so unknown flags in workflow args (`pflow my-workflow --help`) pass through to `_show_workflow_help()`.

3. **`add_help_option=False` on the `run` command** is essential. Without it, Click consumes `--help` from workflow args, breaking `pflow my-workflow --help` which should show workflow interface, not run command help.

4. **`context_settings={"ignore_unknown_options": True, "allow_interspersed_args": True}` on the `run` command** preserves current behavior where options like `--output-format` work after the workflow path AND unknown flags pass through.

5. **`configure_logging(verbose)` MUST be called in the group callback.** Not just `setLevel(DEBUG)`. The `configure_logging` function from `logging_config.py` silences 7 noisy third-party libraries (httpx, httpcore, mcp SDK, composio, etc.). Without it, verbose mode floods output with third-party logs.

6. **`--version` format: use `message="pflow version %(version)s"`** on `@click.version_option`. Click's default format adds a comma (`"pflow, version X.Y.Z"`). Tests assert on the current format without comma.

7. **Mock.patch targets must match import site, not definition site.** When `run.py` imports `WorkflowManager`, tests must patch `pflow.cli.commands.run.WorkflowManager`, not `pflow.core.workflow.manager.WorkflowManager`.

8. **The `main = cli` alias in `main.py`** means 20 test files invoking `from pflow.cli.main import main` now get the Click group instead of the workflow command. Most work transparently, but `test_cli.py` and `test_main.py` WILL break on help text and empty-args assertions. Verify all 20 files.

9. **5 test files import from `main_wrapper.py`** and will crash when it's deleted. Update them in Phase 1 BEFORE deleting the file.

10. **`settings registry output-mode` → `settings output-mode`** changes the CLI path but NOT the Pydantic data model (`PflowSettings.registry.output_mode`). The config structure is separate from the CLI structure. Update the `RegistrySettings.output_mode` description field in `core/settings.py` from "registry run" to "probe".

11. **Reserved names include `run`** — prevents someone from saving a workflow named `run` which would collide with the hidden command.

12. **No `WorkflowSaveError` class exists.** Use `WorkflowValidationError` for reserved name errors (same as current behavior).

13. **MCP tool name splitting bug:** The naive `split("-", 2)` approach breaks for multi-hyphen server names. Use `mcp_metadata.server` from registry entries instead. This is the correct approach for the new `mcp list` implementation.

14. **`probe` must NOT have its own `--verbose` flag.** Read verbose from `ctx.obj.get("verbose", False)` (set by the group callback). A duplicate `--verbose` on probe would shadow the group-level one.

15. **`_handle_workflow_not_found` format:** Preserve the EXACT current format (emoji prefix, bulleted list) from `workflow.py` when inlining into `describe.py` and `history.py`. Tests may assert on the format.

16. **`_validate_discovery_query` should be shared.** Both `find.py` and `mcp.py`'s `find_tools` need it. Put it in `find_errors.py` (the renamed `discovery_errors.py`) rather than duplicating it.

17. **Task 152 spec conflict:** Task 152's spec assumes `discover_workflow` and `discover_components` keep their names. After Phase 5 renames them, update Task 152's spec to match. This is a documentation update, not a code change.
