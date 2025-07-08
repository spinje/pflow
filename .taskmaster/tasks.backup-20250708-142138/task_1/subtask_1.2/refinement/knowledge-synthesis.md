# Knowledge Synthesis for Subtask 1.2

## Relevant Patterns from Previous Tasks
- **Module Structure Pattern**: Entry point expects `pflow.cli:main` - must create exact path `src/pflow/cli/__init__.py` with `main()` function - From subtask 1.1
- **Package Manager Pattern**: Use `uv` for all package operations, not standard pip - From subtask 1.1
- **TOML Formatting Pattern**: Maintain blank line spacing between sections when modifying pyproject.toml - From subtask 1.1

## Known Pitfalls to Avoid
- **Import Path Mismatch**: Entry point uses absolute imports (`from pflow.cli import main`), not relative - From subtask 1.1
- **Missing uv**: Don't use `pip` commands directly, always use `uv pip` - From subtask 1.1

## Established Conventions
- **Entry Point Convention**: `pflow = "pflow.cli:main"` already configured in pyproject.toml - Must match exactly
- **Directory Structure**: Use src-layout with `src/pflow/` as package root - From project context
- **Click Framework**: CLI must use click, not Typer or argparse - From project context

## Codebase Evolution Context
- **Entry Point Configured**: Subtask 1.1 added [project.scripts] section to pyproject.toml
- **Wrapper Script Created**: `.venv/bin/pflow` exists but fails with ModuleNotFoundError
- **Expected Import Path**: Error message confirms it's looking for `pflow.cli` module with `main` function
- **Package Installed**: pflow package is already installed in editable mode, ready for module creation
