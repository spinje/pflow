# Implementation Plan for Subtask 1.1

## Objective
Add the [project.scripts] section to pyproject.toml with the entry point `pflow = "pflow.cli:main"` to register the pflow command for system-wide availability after package installation.

## Implementation Steps

1. [ ] Read current pyproject.toml to understand exact structure
   - File: `/Users/andfal/projects/pflow/pyproject.toml`
   - Change: None (just reading)
   - Test: Verify I can parse the file structure

2. [ ] Add [project.scripts] section after dependencies
   - File: `/Users/andfal/projects/pflow/pyproject.toml`
   - Change: Insert new section between line 25 (end of dependencies) and line 27 (start of [project.urls])
   - Test: Verify TOML remains valid with `python -m toml pyproject.toml`

3. [ ] Test package installation
   - File: None (command execution)
   - Change: Run `pip install -e .` in project root
   - Test: Command completes without errors

4. [ ] Verify entry point registration
   - File: None (command execution)
   - Change: Run `pip show -f pflow` to see installed files
   - Test: Confirm pflow script appears in output

5. [ ] Test pflow command (expect failure)
   - File: None (command execution)
   - Change: Run `pflow` command
   - Test: Should fail with ImportError mentioning pflow.cli module

## Pattern Applications
- Using standard Python packaging patterns (PEP 517/518)
- Following TOML section ordering conventions
- No anti-patterns to avoid (first task)

## Risk Mitigations
- **Risk**: Breaking existing TOML structure
  - **Mitigation**: Careful placement between sections, preserve formatting
- **Risk**: Wrong entry point syntax
  - **Mitigation**: Use exact format from specification `pflow = "pflow.cli:main"`
- **Risk**: Package installation fails
  - **Mitigation**: Test in isolated environment first
