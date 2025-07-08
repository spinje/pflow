# Knowledge Synthesis for Subtask 1.1

## Relevant Patterns from Previous Tasks
- No previous tasks completed yet (this is the first subtask)

## Known Pitfalls to Avoid
- **Incorrect Entry Point Syntax**: Must use the format `package.module:function` - the colon separator is critical
- **Missing Module**: The module path specified in entry point must exist when the package is installed
- **Wrong Package Path**: Entry point must reflect the actual package structure (src-layout in this case)

## Established Conventions
- **Package Structure**: Project uses src-layout (`src/pflow/`)
- **CLI Framework**: Click is chosen over Typer for flexibility
- **Build System**: Uses hatchling as the build backend
- **Entry Point Format**: Standard Python console_scripts format

## Codebase Evolution Context
- **Current State**: Basic package configuration exists but no CLI entry point
- **Target State**: Enable `pflow` command after installation via `pip install -e .`
- **Impact**: This is foundational - all future CLI development depends on this entry point

## Python Packaging Standards
- **PEP 517/518**: Modern packaging using pyproject.toml
- **Console Scripts**: Standard mechanism for creating command-line tools
- **Entry Point Discovery**: Python's pkg_resources/importlib.metadata finds and loads entry points

## Technical Considerations
- The entry point `pflow.cli:main` expects:
  - A module at `src/pflow/cli.py` or `src/pflow/cli/__init__.py`
  - A callable (function) named `main` in that module
- The build system (hatchling) will create the appropriate wrapper scripts during installation
- Development installation (`pip install -e .`) creates editable entry points
