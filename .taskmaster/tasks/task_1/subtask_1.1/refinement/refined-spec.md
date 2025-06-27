# Refined Specification for Subtask 1.1

## Clear Objective
Add the [project.scripts] section to pyproject.toml with the entry point `pflow = "pflow.cli:main"` to register the pflow command for system-wide availability after package installation.

## Context from Knowledge Base
- Building on: Standard Python packaging practices using pyproject.toml
- Avoiding: Incorrect entry point syntax or module path errors
- Following: Modern Python packaging standards (PEP 517/518)

## Technical Specification

### Inputs
- Existing pyproject.toml file at project root
- Entry point specification: `pflow = "pflow.cli:main"`

### Outputs
- Modified pyproject.toml with [project.scripts] section added
- Entry point registered in package metadata

### Implementation Constraints
- Must use: Exact syntax `[project.scripts]` as a TOML section
- Must avoid: Creating the CLI module (that's subtask 1.2's responsibility)
- Must maintain: Existing pyproject.toml structure and formatting

## Success Criteria
- [ ] [project.scripts] section added to pyproject.toml
- [ ] Entry point defined as `pflow = "pflow.cli:main"`
- [ ] File remains valid TOML (can be parsed without errors)
- [ ] `pip install -e .` completes successfully
- [ ] `pflow` command appears in installed scripts (via `pip show -f pflow`)
- [ ] No other changes made to pyproject.toml

## Test Strategy
- Unit tests: Parse modified pyproject.toml to verify structure
- Integration tests: Run `pip install -e .` in test environment
- Manual verification: Check that pflow command is registered (ImportError when run is expected)

## Dependencies
- Requires: pyproject.toml exists (✓ confirmed)
- Impacts: Subtask 1.2 will create the module this entry point references

## Decisions Made
- Only configure entry point, don't create module structure (clear task separation)
- Assume package structure for CLI module (src/pflow/cli/__init__.py) based on project scalability needs
- Place [project.scripts] section after [project] section for logical organization

## Implementation Details

The exact change to make in pyproject.toml:

1. Locate the end of the [project] section (after line 19 with dependencies)
2. Add the following before [project.urls] section:

```toml
[project.scripts]
pflow = "pflow.cli:main"
```

This follows the standard console_scripts entry point format where:
- `pflow` is the command name users will type
- `pflow.cli` is the Python module path (relative to src/)
- `main` is the callable function in that module

The build system (hatchling) will automatically create the appropriate wrapper scripts during installation that will:
1. Set up the Python environment
2. Import pflow.cli
3. Call the main() function
4. Handle command-line arguments appropriately
