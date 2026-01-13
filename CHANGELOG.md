# Changelog

## v0.5.0 (2026-01-13)

- Removed parameter fallback pattern from all nodes to prevent silent namespace collisions [#28](https://github.com/spinje/pflow/pull/28)
- Changed `claude-code` node to use Claude Agent SDK, renaming parameters to `prompt` and `cwd`, enabling all tools by default, and adding `session` and `timeout` support [#10](https://github.com/spinje/pflow/pull/10)
- Changed shell node to strip trailing newlines from `stdout` by default [#51](https://github.com/spinje/pflow/pull/51)
- Changed CLI agent instructions to increase the `max_concurrent` limit for batch processing
- Added batch processing capability with support for both sequential and parallel execution modes [#11](https://github.com/spinje/pflow/pull/11)
- Added real-time progress display for batch node execution, showing completion status as items finish [#20](https://github.com/spinje/pflow/pull/20)
- Added automatic JSON string parsing during nested template access (e.g., `${node.stdout.field}`) [#37](https://github.com/spinje/pflow/pull/37)
- Added automatic parsing of JSON strings in inline object templates [#39](https://github.com/spinje/pflow/pull/39)
- Added automatic coercion of dictionary and list inputs to JSON strings for string-typed parameters [#41](https://github.com/spinje/pflow/pull/41)
- Added type preservation for simple templates in nested structures to prevent double-serialization [#32](https://github.com/spinje/pflow/pull/32)
- Added the original input item to batch results as an `item` field for self-contained downstream processing [#54](https://github.com/spinje/pflow/pull/54)
- Added support for auto-serializing arrays and dictionaries to JSON when used in string template contexts [#19](https://github.com/spinje/pflow/pull/19)
- Added stderr check to shell node smart handling to ensure pipeline errors are caught [#58](https://github.com/spinje/pflow/pull/58)
- Added release context file and CLI summary to the `generate-changelog` workflow
- Fixed critical SIGPIPE issue causing silent process termination when subprocesses ignored large stdin data [#26](https://github.com/spinje/pflow/pull/26)
- Fixed workflow name mismatch bug by deriving the workflow name directly from its filename [#46](https://github.com/spinje/pflow/pull/46)
- Fixed optional workflow inputs without defaults to resolve to `None` instead of failing resolution [#49](https://github.com/spinje/pflow/pull/49)
- Fixed LLM usage tracking for batch node inner executions to ensure costs are correctly captured [#22](https://github.com/spinje/pflow/pull/22)
- Fixed issue where upstream shell stderr was not surfaced when downstream nodes failed [#52](https://github.com/spinje/pflow/pull/52)
- Fixed shell command validation to allow union types containing `str` or `any` [#61](https://github.com/spinje/pflow/pull/61)
- Fixed structured output mode skipping smart filtering and added Gemini thinking optimizations [#43](https://github.com/spinje/pflow/pull/43)
- Fixed static validation to correctly recognize batch output structures and dotted references like `${item.field}`
- Fixed `--output-format json` support for the `registry run` command
- Fixed validation failures by normalizing type strings to lowercase across the registry and nodes
- Fixed the planner to handle missing file paths gracefully
- Improved shell error visibility by surfacing `stderr` even when the exit code is 0 [#56](https://github.com/spinje/pflow/pull/56)
- Improved shell node validation by moving dictionary and list checks to compile time [#30](https://github.com/spinje/pflow/pull/30)
- Improved `git-log` node to support tag and branch refs for `since` and `until` parameters
