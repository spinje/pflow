# Braindump: Task 129 + 130 Feature Planning Session

These two tasks were planned together in one long conversation. Task 130 depends on Task 129 but also fixes an existing bug (sub-workflow save). This braindump covers both because the context is deeply intertwined.

## Where I Am

Both task specs are written (`.taskmaster/tasks/task_129/task-129.md` and `task_130/task-130.md`). No implementation has started. We were about to begin detailed implementation planning for Task 129 when context ran out.

## User's Mental Model

The user thinks in terms of **observed problems, not theorized ones**. They repeatedly steered the conversation away from speculative features toward what's actually broken. Key moments:

- When I proposed `{{include}}` for prompt reuse, the user asked "but isn't this solved by the template system?" — and they were right. `${var}` already handles shared content. This killed `{{include}}` as a feature.
- When I proposed `prompt_file:` as a new parameter name, the user asked "why not just use the original name like 'prompt' and write a file path instead?" — leading to auto-detection, which is simpler.
- When I said "tooling simplicity" justified `WORKFLOW.pflow.md` over `{name}.pflow.md`, the user pushed: "is the tooling simplicity really such a big deal? can you dig deeper" — and I had to admit it wasn't. One string concatenation vs one constant.
- The user consistently asked "what are the actual problems?" and "any drawbacks to X?" — always testing assumptions.

**The user's real priority**: solve observed friction from a real AI agent building a real system. Not hypothetical improvements. Every feature must trace back to a concrete pain point from the music-generation project.

**Their stated hierarchy**: (1) get prompts/code out of large workflow files, (2) make saved workflows work with dependencies, (3) don't over-engineer.

## Key Insights

### The feature request was partially wrong

The original feature request (`scratchpads/prompt-file-references/README.md`) came from an AI agent working on the music-generation project. It overstated the DRY problem:
- "The creative brief appears in 3 different prompts" — actually appears in 5, but as `${creative_brief}` template references, which is the CORRECT solution. The template system already handles this.
- "shared PROMPT INSTRUCTIONS are copy-pasted across prompts" — we read the actual 913-line workflow and found minimal literal copy-paste. The specialist reviewers have domain-specific content, not duplicated content.
- The real Core Concept block repetition (5 occurrences of 3 lines) is too trivial to justify `{{include}}`.

**What's actually wrong**: file size (913 lines), navigation, editing ergonomics (especially YAML-indented prompts in batch blocks), and diff noise. NOT duplication.

### The code block problem was invisible

The original request focused entirely on prompts. But reading `lyrics-generator.pflow.md` revealed `build-file-list` — a 105-line Python code node embedded in the workflow. Same editing problem, never mentioned. The feature was generalized from "prompt files" to "any code block parameter can reference a file."

### Auto-detection emerged from questioning assumptions

The progression was: `prompt_file:` (new param) → `file:` prefix → auto-detection. The user drove each simplification. Auto-detection works because for every code-block param except `command`, a file path is never valid literal content. And for `command`, a bare file path as the entire command value via YAML param is not a real-world pattern.

### The sub-workflow save bug already exists

The user caught this: "how are we currently handling saved workflows that use subworkflows? wouldn't that be the same problem?" — and they were right. Task 130 doesn't just support file references; it fixes an existing bug where `- workflow: ./sub.pflow.md` breaks after `pflow workflow save`.

### Compile-time vs runtime was a real design tension

I initially pushed runtime resolution because the batch wrapper processes items at runtime. The user pushed back on validation: "we need to make sure we can validate everything as early as possible." The subagent research revealed the critical ordering issue: validation runs BEFORE node creation in the compiler. So file resolution must be an IR transformation step between parsing and compilation — not in the compiler itself. This was a significant architectural insight that changed the approach.

## Assumptions & Uncertainties

ASSUMPTION: The detection heuristic (starts with `./` or `../`, or contains `/` AND ends with recognized extension) won't produce false positives on real workflow content. We didn't test this against the full example corpus in `examples/`.

ASSUMPTION: The IR transformation step can be inserted cleanly between parsing and compilation in all execution paths (CLI, MCP server, nested workflow executor). We verified CLI and identified the MCP gap, but didn't trace the nested workflow executor path in detail.

ASSUMPTION: Inline batch items in the IR are always Python dicts (parsed from YAML). The subagent confirmed this for the `yaml batch` code block path, but I'm not 100% sure about edge cases (what if batch config comes from a template-referenced source?).

UNCLEAR: How should the MCP server handle file references? We identified the gap (`_pflow_workflow_file` is never set in MCP execution), but didn't resolve it. For saved workflows, the MCP server knows the path (via `WorkflowManager.get_path()`), so it could set `_pflow_workflow_file`. For inline content, file references can't work.

UNCLEAR: The task spec says "migration" for existing single-file saved workflows to folders. We didn't decide between automatic migration on access vs. explicit migration command. The user didn't express a preference. Simplest is probably: load checks folder first, falls back to single file, auto-wraps in folder on next save.

NEEDS VERIFICATION: The `_source_files` provenance tracking — we decided to add it, but didn't design the exact mechanism. The current `_source_lines` is barely used (only PythonCodeNode reads it, validation errors have zero source location). Adding `_source_files` follows the same pattern, but the validation pipeline would need to actually consume it for error messages. This might be more work than it sounds.

NEEDS VERIFICATION: Does the existing `_check_param_code_block_conflicts()` actually catch our mutual exclusivity case? We reasoned that since auto-detection uses the same param name (`prompt`), the check works. But the check runs in the parser, and auto-detection happens post-parsing (in the IR transformation step). At parse time, `- prompt: ./prompts/foo.md` is just a string param — the parser doesn't know it's a file reference. The code block `prompt` would also be stored. Does the conflict check see both? YES — it checks if the same param name appears in both YAML params and code blocks, regardless of the value. So `- prompt: ./path` (YAML) + ` ```prompt ``` ` (code block) would trigger the conflict. Confirmed.

## Unexplored Territory

UNEXPLORED: **Error messages for the user when file content fails validation.** We said "provenance tracking" but didn't design the UX. When `${bad_var}` fails in an external file, what does the error look like? "Template variable ${bad_var} in node 'write-lyrics' param 'prompt' (from file ./prompts/write-lyrics.prompt.md) has no valid source"? The format matters for usability.

UNEXPLORED: **How does `pflow workflow save` discover file references?** Task 130's dependency discovery needs to find all file references in a workflow. But after Task 129, file references are resolved in the IR transformation step — the IR the save service sees might already have content substituted. The save service needs to discover dependencies BEFORE resolution (from the raw IR), not after. This is a subtle integration point.

CONSIDER: **The `pflow validate` command.** Does it run the IR transformation step? It should — validation should catch file-not-found errors. Verify that the validation CLI path includes the new step.

CONSIDER: **Nested workflows with their own file references.** If `lyrics-generator.pflow.md` references `song-creator.pflow.md` which itself has `- prompt: ./prompts/foo.md`, the nested workflow's file references resolve relative to `song-creator.pflow.md`'s location (via `_pflow_workflow_file` propagation). But when bundled for save, the relative structure must be preserved for both levels. The dependency discovery needs to be recursive.

CONSIDER: **The `pflow instructions usage` agent context.** This generates instructions for AI agents. Should it mention file references? Probably — agents are the primary authors.

MIGHT MATTER: **Performance of file reading at compile time.** For a workflow with 20 external files, that's 20 file reads before execution starts. Probably negligible, but worth noting.

MIGHT MATTER: **File encoding.** We assumed UTF-8. What if an external file has a different encoding? The current parser only handles UTF-8 (per CLAUDE.md: "UTF-8 only, no encoding detection"). So file references should follow the same rule.

MIGHT MATTER: **Circular file references.** Can a prompt file reference another prompt file? No — file references are resolved once, not recursively. A prompt file is just text content. But if batch YAML references another YAML file... we didn't discuss recursive file references. Keep it simple: one level only.

UNEXPLORED: **Testing strategy.** We didn't discuss how to test file references. Need test workflows with external files, which means test fixtures with directory structures (not just single markdown files). The existing test infrastructure (`tests/test_core/`, `tests/test_runtime/`) may need new fixture patterns.

UNEXPLORED: **Documentation.** The user-facing docs (`docs/`) and agent instructions (`cli/resources/`) will need updates. Not urgent (no users yet), but should be tracked.

## What I'd Tell Myself

1. **Start with Task 129.** It's self-contained and delivers immediate value. Task 130 fixes an existing bug (sub-workflow save) independently of file references, but the full integration needs 129 first.

2. **The IR transformation function is the core deliverable.** Everything else (detection heuristic, YAML vs text, batch items) flows from getting `resolve_file_references(ir_dict, base_dir)` right. Start there.

3. **Don't build `{{include}}`.** The user explicitly agreed it's not needed. The template system handles reuse. If a future user asks, point them at `${var}` with input defaults or a code node that reads files.

4. **The music-generation project is the test case.** `~/projects/music-generation/workflows/` has 4 workflow files with the exact problems we're solving. Use it for integration testing.

5. **The user values simplicity over completeness.** They repeatedly simplified the design (auto-detect over `_file`, same param name, no `{{include}}`). Don't add features that weren't discussed.

## Open Threads

- **We were about to start implementation planning for Task 129** when context ran out. The task spec has the approach, but the detailed breakdown into implementation steps hasn't been done.
- **The MCP server gap** was identified but not resolved. Need to decide: set `_pflow_workflow_file` in MCP execution for saved workflows, or defer?
- **Migration strategy for Task 130** (existing single-file saved workflows → folders) wasn't decided. Auto-migrate on access is simplest.
- **The `_source_files` provenance mechanism** was agreed on conceptually but not designed in detail.

## The Music-Generation Project — Critical Context

This project at `~/projects/music-generation/workflows/` is the real-world motivation. Key files:

- `lyrics-generator.pflow.md` (526 lines) — orchestrator, references 3 sub-workflows by relative path
- `fetch-source.pflow.md` (140 lines) — pure plumbing, zero prompts, benefits from single-file property
- `analyze-source.pflow.md` (166 lines) — 5 analysis specialists in YAML batch, moderate
- `song-creator.pflow.md` (913 lines) — the monster, 682 lines of prompts, the primary motivation

The full pipeline does ~58 LLM calls per run. The specialist batch pattern (N parallel LLM prompts → format code node) appears in both `analyze-source` and `song-creator`.

Bug found during analysis: in `analyze-source.pflow.md`, the first 4 specialist prompts say "You are one of four specialists" but there are 5 specialists. The musicality specialist correctly says "five."

## Relevant Files & References

### Pflow codebase (the files that matter for implementation)
- `src/pflow/core/markdown_parser.py:87-96` — `_CODE_BLOCK_TAG_TO_PARAM` mapping (which params are code blocks)
- `src/pflow/core/markdown_parser.py:689-702` — `_check_param_code_block_conflicts()` (mutual exclusivity)
- `src/pflow/core/markdown_parser.py:708-721` — `_route_code_blocks_to_node()` (YAML vs text distinction)
- `src/pflow/runtime/compilation/compiler.py:601` — `compile_ir_to_flow()` entry point
- `src/pflow/runtime/compilation/compiler.py:265-269` — source line threading into params
- `src/pflow/runtime/wrappers/batch_node.py` — batch wrapper, inline items as parsed dicts
- `src/pflow/runtime/workflow_executor.py:181-183` — `_is_file_reference()` (existing detection pattern)
- `src/pflow/runtime/workflow_executor.py:260-267` — `_resolve_safe_path()` (relative path resolution)
- `src/pflow/core/workflow/manager.py:191-235` — `WorkflowManager.save()`
- `src/pflow/core/workflow/save_service.py:252-309` — `save_workflow_with_options()`
- `src/pflow/core/workflow/skill_service.py` — skill symlinks

### Feature request and analysis
- `scratchpads/prompt-file-references/README.md` — original agent feature request (partially wrong, see "Key Insights")
- `~/projects/music-generation/workflows/` — real-world test case (4 files)

### Subagent research (captured in context, not in files)
- Batch lifecycle: batch config is parsed Python dict in IR, compiler passes through without inspection, batch wrapper processes at runtime
- Source line tracking: `_source_lines` maps param→line number, only PythonCodeNode uses it, validation has zero source location
- Workflow file path: not available in parser, available in compiler via `initial_params["_pflow_workflow_file"]`, MCP server never sets it
- Conflict check: existing check handles same-name conflicts for YAML params vs code blocks

## For the Next Agent

**Start by reading**:
1. This braindump (you're doing it)
2. `.taskmaster/tasks/task_129/task-129.md` — the detailed task spec
3. `.taskmaster/tasks/task_130/task-130.md` — the companion task spec
4. `scratchpads/prompt-file-references/README.md` — the original feature request (context, but note the debunked claims in "Key Insights" above)

**Don't bother with**:
- Building `{{include}}` — explicitly killed in discussion
- The `_file` suffix naming convention — replaced by auto-detection
- `WORKFLOW.pflow.md` canonical naming — rejected in favor of `{name}.pflow.md`

**The user cares most about**:
- Solving real problems from real usage, not theoretical ones
- Simplicity — every feature addition was questioned and simplified
- Early validation — errors at compile time, not mid-execution
- Not breaking existing workflows

**The conversation pattern**: The user asks probing questions ("is this really such a big deal?", "but isn't this solved by X?", "any drawbacks?"). They trust you to do research but verify your reasoning. Don't present weak arguments as strong ones — they'll catch it.

---

> **Note to next agent**: Read this document fully before taking any action. When ready, confirm you've read and understood by summarizing the key points, then state you're ready to proceed.
