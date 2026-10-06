# Task 182: Lint Code Blocks in Workflows — ruff for Python, shellcheck for Shell

## Description

Workflow code blocks get only a syntax check today (`ast.parse()` for Python,
`src/pflow/core/markdown_parser.py:1149`; nothing for shell). Run real linters over them — ruff on Python
bodies, shellcheck on shell bodies — and report findings with markdown line numbers, so an agent
learns about an undefined name or a quoting bug at validation instead of mid-run.

## Status
not started

## Priority

low

## Roadmap

then

## Problem

- Python bodies: undefined names, unused imports and common bugs pass validation and fail at run
  time, or never fail and produce wrong results.
- Shell bodies: quoting mistakes and unset variables are invisible until the command runs. A
  bare misspelled variable (`$ENDPONT` beside a declared `ENDPOINT`) is silent at validation
  and at run time. Whether shellcheck catches it is UNVERIFIED: SC2154 may not flag
  upper-case names (it assumes they come from the environment), and Task 118's guide convention is
  UPPER_SNAKE — check before promising it.
- No one has asked for this by issue; the evidence is the class of run-time failures a linter
  would have caught. Confirm the need against recent traces or dogfood findings before planning.

## Design intent (confirm at start — not a locked design)

- Lint findings are emitted as `Diagnostic`s through `WorkflowValidator`, so the CLI's JSON
  output, the MCP `workflow_validate` tool and any editor integration (Task 167) get them without
  a second report format. Whether that is a `--lint` flag on validation or always-on warnings is
  an open question.
- Python bodies declare inputs as bare annotations (`records: list[dict]`) that pflow binds; ruff
  must see them as defined, and line numbers must map back to the markdown source.
- shellcheck is an external binary. Its absence degrades to one clear "shell linting skipped"
  message — and because it is optional, its findings can never be validation *errors* (validation
  results must not differ between machines).

## Open questions (resolve at start)

- ruff as a runtime dependency (~26 MB, about 9% of the install) or optional with graceful
  absence?
- Flag or default? Which rule sets — a small, high-signal selection, or the tools' defaults?
- Performance budget for validation with linting on.

Solution / Requirements / Verification — finalized when the task is started (just-in-time).

## Dependencies

- Shell linting needs Task 118 (a shell body that contains pflow Templates is not valid sh).
  Python linting needs nothing — no Python body in the repo contains a Template — and could ship
  first.

## References

- Split out of Task 118 on 2026-10-06 (user ruling); 118's `starting-context/` and `research/`
  hold the original linting notes.
