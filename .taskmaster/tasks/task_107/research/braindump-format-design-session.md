# Braindump: Task 107 Format Design Session

## Where I Am

The format specification is complete and all assumptions have been verified against the codebase. Three documents exist in `.taskmaster/tasks/task_107/research/`:
- `design-decisions.md` — 25 numbered decisions, verified architecture findings, parsing algorithm
- `format-spec-decisions.md` — stress-tested format details, complete examples, parsing rules
- This file — tacit knowledge, gotchas, and implementation context that the formal docs don't capture

**Read `design-decisions.md` and `format-spec-decisions.md` FIRST.** This braindump fills in what they don't cover.

**No implementation was done.** The next step is implementation planning.

---

## Decisions Made (complete, all open questions resolved)

- **File extension**: `.pflow.md`
- **Linting scope**: `ast.parse()` for Python code blocks at parse time, `yaml.safe_load()` for YAML config blocks (already part of parsing). Nothing for shell/prompt. Full linting is Task 118.
- **Unknown param warnings**: In scope — compare params against `interface["params"]` keys during compilation. Uses existing registry metadata infrastructure.
- **Required param validation**: Out of scope — [Issue #76](https://github.com/spinje/pflow/issues/76). Needs `required: bool` field added to interface metadata.
- **Description concatenation**: Join prose paragraphs with `\n\n`, strip leading/trailing whitespace.
- **Node prose**: Saved to `purpose` field in IR (effectively dead code at runtime, but forces documentation).
- **Parser library**: Custom line-by-line state machine. No markdown library dependency (Decision 25).

---

## User's Mental Model

### How they think (use their words)

The user's most important reframe: **"If the .md document was JUST documentation, how would you expect it to look?"** This single question shaped the entire format. Every time we got lost in parser mechanics or config-file thinking, coming back to "what would a documentation author write?" gave us the answer.

Other key phrases:
- **"Documentation IS code"** — the workflow file IS the documentation. They're the same thing.
- **"LLMs are the users"** — LLMs generate what they've been trained on (markdown documentation). Optimizing for LLMs = optimizing for natural documentation.
- **"Faster horse problem"** — people won't know they want markdown until they see it. Don't ask, show.
- **"JSON was HELL for AI agents"** — the escaping, the single-line prompts. Strong word, intentional.

### Their decision-making style

The user doesn't accept the first "good enough" answer. They push back, sometimes multiple times, until the design feels RIGHT. They caught me converging too quickly on several occasions:
- When I proposed frontmatter for inputs → "im not sure if name and inputs/outputs should be in frontmatter"
- When I proposed YAML code blocks for inputs → "does the prose usually come before or after the - list?"
- When I proposed `string = ""` syntax → "is that natural syntax for you?"
- When I was ready to settle → "lets take a step back and think about this clearly... this is fundamental"

**They trust their instinct but want it validated.** Several times they said "or maybe im thinking wrong here" — they're genuinely open to being wrong but usually aren't.

### Their priorities (in order)

1. **Consistency** — one pattern for everything beats multiple optimal-for-each-case patterns
2. **Naturalness** — it should look like documentation LLMs have seen billions of times
3. **LLM generation quality** — minimize errors when generating workflows
4. **Self-documenting** — the format forces good documentation by default
5. **Elegance** — they have taste and care about the design feeling "right"

---

## Key Insights (the non-obvious stuff)

### The conversation's pivotal moments

1. **Complex outputs forced the universal pattern.** We had different syntax for inputs (YAML blocks), nodes (headings), and outputs (list items). Then I showed that outputs can have multi-line source templates (assembling a markdown doc from multiple node outputs). This meant outputs need code blocks → outputs need headings → outputs follow the same pattern as nodes → why not make inputs the same? This single realization unified the entire format.

2. **YAML `#` comments were a happy accident.** We decided to parse `- ` lines as YAML (not simple line splitting) because agents would try YAML nesting. The bonus: `- model: gpt-4  # chosen for accuracy` works for free because YAML supports `#` comments. The user loved this — it gives agents two documentation mechanisms (inline comments AND prose paragraphs).

3. **Saved workflow frontmatter is NOT the same as authoring frontmatter.** I kept arguing against frontmatter for the authoring format (inputs/outputs don't belong there). The user then clarified: frontmatter is for SYSTEM METADATA on saved workflows, added programmatically by pflow. Agents never write it. These are two completely different use cases that happen to use the same YAML-between-dashes syntax. Don't confuse them.

4. **The `- ` prefix solves parsing ambiguity.** Without it (`type: http` as bare text), you can't distinguish params from prose. With it (`- type: http`), every param is visually and syntactically distinct. This is why bare YAML was rejected — not because of indentation concerns, but because of prose/param ambiguity.

### Lessons learned (if starting this conversation over)

1. **Don't propose YAML frontmatter first.** Start with "what would natural documentation look like?" and let the structure emerge. The user's reframe saved us from building a config-file-in-markdown instead of a documentation-that-executes.

2. **The consistency insight is the most important one.** Every time we had a "special syntax for X" idea, it created problems when X needed to do something Y could do. Universal patterns win.

3. **Test against real workflows early.** We didn't convert and test a real workflow until late in the discussion. Doing this earlier would have revealed the complex-output-needs-code-blocks insight sooner.

4. **The user thinks in terms of what LLMs should generate.** Not in terms of parser convenience. Whenever I optimized for parser simplicity at the cost of naturalness, they pushed back.

---

## Verified Facts (from codebase investigation)

These were assumptions in earlier sessions. All now confirmed against actual code.

### normalize_ir() — confirmed at ir_schema.py:559-592

Adds exactly 3 things:
1. `ir_version: "0.1.0"` if missing
2. `edges: []` if missing (and no `flow` field)
3. Renames `parameters` → `params` in nodes

Called from CLI, MCP server, and workflow save service. The markdown parser should produce a dict WITHOUT `ir_version` (let normalize_ir handle it) but WITH `edges` (generated from document order).

### Top-level node fields — confirmed at ir_schema.py:197-212

Only 5 fields, with `additionalProperties: False`:

| Field | Required | Parser maps from |
|-------|----------|-----------------|
| `id` | Yes | `###` heading text |
| `type` | Yes | `- type:` param (extracted, not passed to `params`) |
| `purpose` | No | Prose description (joined with `\n\n`) |
| `params` | No | All other `- key: value` params + code block content |
| `batch` | No | `yaml batch` code block (top-level, NOT under `params`) |

**Critical for the parser**: `type` goes to top-level, NOT into `params`. `batch` goes to top-level, NOT into `params`. Everything else goes into `params`. The `source` field on outputs also goes to the output dict directly, not under params.

### purpose field — dead code at runtime

Optional in IR schema. NOT used by: compiler, runtime, CLI display (`pflow workflow describe`), MCP server, error messages, or validation. Only the legacy planner references it. Safe to populate from node prose. Won't break anything, might be useful for future display.

### YAML template variables — no clash

PyYAML `safe_load()` treats `${target_url}` as plain string content. No special interpretation.

### YAML type coercion — matches JSON exactly

`int`, `bool`, `float`, `str`, `list` types match what `json.loads()` produces. **Gotcha**: unquoted `yes`/`no`/`on`/`off` become Python booleans. Document this for agents: `- value: "yes"` if you want a string.

### Unknown params — silently accepted

`params` has `additionalProperties: True`. Nodes use `.get()` and ignore unknown keys. Documentation bullets accidentally parsed as `- key: value` pass silently through all validation. This is why the unknown param warning (comparing against registry interface metadata) is in scope for Task 107.

### Template validation — happens before execution

The `TemplateValidator` runs during `compile_ir_to_flow()` and catches:
- `${nonexistent_node.output}` — error before execution
- `${fetch.nonexistent_field}` — error before execution
- Malformed `${unclosed` — error before execution
- Type mismatches — error before execution

**This means**: template references in prompt and shell blocks ARE validated pre-execution. No new work needed for template validation in the markdown parser — the existing validation handles it after the dict is produced.

### Required params — runtime only

Each node checks its own required params in `prep()` (e.g., `if not url: raise ValueError`). There is NO pre-execution check. The compiler does NOT validate params against interface metadata. Issue #76 tracks adding this.

### Code node input/variable validation — exists at runtime

The code node's `prep()` validates:
- `_check_input_annotations()` — every `inputs` key must have a matching type annotation in the code
- `_check_input_types()` — `isinstance()` check that resolved values match declared types

This happens at runtime, not compile time. The markdown parser doesn't need to duplicate this.

### Why code node uses separate `inputs` dict (not inline templates)

Template resolution inside code strings would produce JSON-serialized strings, not Python objects. `${fetch.result}` (a list) would become `[{"id": 1}]` as a string literal pasted into the code, breaking `ast.parse()`. The `inputs` dict uses `resolve_nested()` which preserves native Python types, then injects them into the `exec()` namespace.

### Registry interface metadata — params enumerable

`interface["params"]` gives a list of `{"key": "url", "type": "str", "description": "..."}` dicts for each node type. The template validator already loads this during compilation. The unknown param warning can use this same data.

No `required: bool` field exists — required/optional is only in description text like `"(optional)"`. This is why required param validation is deferred to Issue #76.

### Input schema has `stdin` field — not in format examples

The IR input schema has 5 fields: `description`, `required`, `type`, `default`, `stdin` (boolean, for piped stdin data). The `stdin` field wasn't shown in any format example. The parser must handle `- stdin: true` on inputs. It maps directly to the input dict (same level as `description`, `type`, etc.).

### Output schema has `type` field — not in format examples

The IR output schema has 3 fields: `description`, `type` (enum: string/number/boolean/object/array), `source`. Outputs can have `- type: string` just like inputs. Not shown in examples but follows the universal pattern naturally.

### Workflow `description` lives OUTSIDE the IR

The top-level IR schema has NO `description` field (`additionalProperties: False`). The `description` is stored in the WorkflowManager's metadata wrapper (`{"description": "...", "ir": {...}, ...}`). In the markdown format, the workflow description comes from H1 prose (between `#` title and first `##`). This means:
- The parser extracts it separately from the IR dict
- When saving, agents no longer specify description separately — it's in the markdown content
- The parser return type must expose `description` alongside `ir`

### Unused top-level IR fields — safe to ignore

The full IR schema has 9 top-level fields. The parser only needs to produce: `nodes`, `edges`, `inputs`, `outputs`. The rest use defaults:
- `ir_version` — added by `normalize_ir()`
- `start_node` — always first node (default behavior)
- `mappings` — proxy mappings, default `{}`
- `enable_namespacing` — default `true`
- `template_resolution_mode` — default `"strict"`

### Parser return type

The parser must return more than just the IR dict. Different callers need different fields:

```python
@dataclass
class MarkdownParseResult:
    ir: dict[str, Any]                    # The workflow IR dict
    title: str | None                     # H1 heading text
    description: str | None               # H1 prose (between # and first ##)
    metadata: dict[str, Any] | None       # Frontmatter (None for authored files)
```

Most callers use `.ir`. WorkflowManager uses all fields (metadata for timestamps/stats, description for display, title for search).

---

## The `-` Bullet Footgun (most important risk)

The format uses `- key: value` for params and `*` for documentation bullet lists. LLMs default to `-` for markdown bullets. If an LLM writes:

```markdown
- Note: this uses Jina Reader for better quality
- type: http
```

The `Note` line becomes a param. Since unknown params are silently accepted, no error occurs.

**Mitigations**:
1. Clear agent instructions about `*` for bullets
2. Unknown param warning at compile time (in scope for Task 107) — would flag "unknown param `Note` on http node"
3. The param would have no effect on execution (workflow still works correctly)

**Risk level**: Low severity (workflow works), medium probability (LLMs use `-` by default). The unknown param warning is the key mitigation.

---

## Integration Points (7 JSON parse points)

Every place a workflow file is loaded from disk. Each needs updating to call the markdown parser:

| # | File | Line | Function | Context |
|---|------|------|----------|---------|
| 1 | `src/pflow/cli/main.py` | 172 | `_try_load_workflow_from_file()` | CLI loads workflow from path |
| 2 | `src/pflow/runtime/compiler.py` | 157 | `_parse_ir_input()` | Compiler accepts string input |
| 3 | `src/pflow/core/workflow_manager.py` | 205 | `load()` | Loads saved workflows |
| 4 | `src/pflow/mcp_server/utils/resolver.py` | 61 | `resolve_workflow()` | MCP resolves file paths |
| 5 | `src/pflow/runtime/workflow_executor.py` | 246 | `_load_workflow_from_path()` | Nested workflow loading |
| 6 | `src/pflow/core/workflow_save_service.py` | 176 | `_load_from_file_path()` | Workflow save operations (CLI/MCP) |
| 7 | `src/pflow/planning/context_builder.py` | 255 | `_try_load_workflow()` | Discovery workflow scanning |

Everything downstream operates on dicts. No changes needed to compiler, validator, or executor.

## Error Messages Mentioning JSON (~10-12 places to update)

The originally documented 6 plus additional findings from codebase verification:

| File | Line | Message | Action |
|------|------|---------|--------|
| `cli/main.py` | 133 | "Invalid JSON syntax in {path}" | Replace with markdown parse errors |
| `cli/main.py` | 155 | "Fix the JSON syntax error" | Replace |
| `ir_schema.py` | 481 | "Invalid JSON: {e}" | Replace with YAML/structure errors |
| `ir_schema.py` | 370-387 | `_get_output_suggestion()` shows JSON examples | Update to markdown syntax (Decision 23) |
| `workflow_manager.py` | 214 | "Invalid JSON in workflow" | Update for .pflow.md format |
| `workflow_executor.py` | 248 | "Invalid JSON in workflow file" | Update for nested workflows |
| `workflow_executor.py` | 254 | "Workflow must be a JSON object" | Update |
| `workflow_validator.py` | 497 | "Replace JSON string with object syntax" | Remove (JSON anti-pattern not relevant) |
| `workflow_save_service.py` | 183 | "Invalid JSON in {path}: {e}" | Update for markdown format |
| `mcp_server/utils/resolver.py` | 64 | "Invalid JSON in file: {e}" | Update for markdown format |

Additional MCP config messages (`mcp/manager.py`, `cli/mcp.py`) mention JSON but are about MCP server configs, not workflows — no change needed.

---

## Implementation Gotchas

### Line numbers and IR validation errors — source map NOT needed

The parser produces an IR dict, then existing validators run on it. Concern: validators produce errors with abstract IR paths like `nodes[0].type` — no markdown line numbers. Do we need a source map to translate these?

**Verified answer: No.** The validation layers fall into two categories:

1. **Structural validation** (jsonschema in `validate_ir()`): Produces `nodes[0].type` style paths. Catches missing `type`, missing `id`, wrong types, unknown fields. But the **parser can and should catch all of these first** — it knows when a node has no `- type:` param, it controls which fields go where, and it always produces `id` from headings. If the parser validates structural completeness, jsonschema becomes a safety net that never triggers.

2. **Semantic validation** (template validator, data flow, node types, output sources): Already uses **node IDs by name**. E.g., `"Node 'fetch-messages' template ${fetch-messages.msg} references non-existent output 'msg'"`. No abstract paths — user can find `### fetch-messages` in the markdown easily.

**Conclusion**: The parser IS the line number mechanism. It front-loads structural validation with markdown line numbers. Semantic errors already reference node names. A source map would translate errors that never reach the user — unnecessary complexity with maintenance cost (parallel data structure that must stay in sync with the IR dict).

**If we're wrong**: Adding a source map later is straightforward — the parser already tracks line numbers for every element. But the jsonschema safety net hasn't triggered in practice because the parser ensures structural correctness.

### The `- ` line collection is the parser's core complexity

The parser must:
1. Track whether it's inside a code fence (don't collect `- ` lines from inside code blocks)
2. Collect `- ` lines AND their indented continuations (for nested YAML like `- headers:` with indented sub-keys)
3. Collect from non-contiguous positions (prose can appear between `- ` lines)
4. Join collected lines and parse as YAML sequence
5. Merge the resulting list of single-key dicts into one dict

The indentation continuation rule: any `- ` line PLUS subsequent lines that are indented more than the `-`, until the next `- ` line or non-indented non-blank line.

### `type` must be extracted from params

When the parser collects `- type: http`, this goes to the TOP-LEVEL `type` field of the node dict, not into `params`. The parser must extract `type` from the merged params dict and place it at the node level. Same for `batch` from code blocks.

### Code block info string parsing

The info string `shell command` means: first word = language hint (for editors), last word = param name (for the parser). If one word (e.g., `prompt`), it's both. The parser ignores the language word and only uses the last word for mapping.

Special mappings:
- `yaml batch` → top-level `batch` field (not `params.batch`)
- `source` / `markdown source` / `json source` → output-level `source` field (not `params.source`)
- Everything else → `params.{last_word}`

### ast.parse() for Python code blocks

Python code blocks don't contain `${...}` template variables (those are in the `inputs` param). So `ast.parse()` works directly on the code content with no placeholder tricks. Run it at parse time and report errors with markdown line numbers.

### WorkflowManager needs format migration

Currently stores saved workflows as `~/.pflow/workflows/{name}.json` with a JSON metadata wrapper. Needs to change to `~/.pflow/workflows/{name}.pflow.md` with YAML frontmatter for metadata. See Decision 17 in design-decisions.md.

### The `_is_path_like()` check in CLI

The CLI has a function that determines if the first argument is a file path (vs. a saved workflow name). It currently checks for `.json` extension. Needs to also check for `.pflow.md`.

### Empty sections are valid

`## Inputs` with no `###` headings underneath = no inputs. Same for `## Outputs`. The parser should accept this silently. `## Steps` with no `###` headings should error (a workflow needs at least one node).

### Parser strictness

The current spec leans strict: required descriptions, no bare code blocks, duplicate param errors. But there are cases where leniency helps — like ignoring unknown `##` sections (already decided: silently ignore, with warnings for near-misses like `## Input` without the 's'). If you face a strictness choice during implementation, the default should be strict with helpful error messages.

### Edge cases to watch

**`images` param on LLM nodes.** In the full example, `- images: ${item}` is an inline param. But what if `images` needs to be a complex structure (array of URLs with metadata)? It would need a `yaml images` code block. Probably rare, but the code block pattern should work for it.

**YAML `- ` lines collected from non-contiguous positions.** If you collect `- type: llm` and `- model: gpt-4` from lines scattered across the entity (with prose between them), and join them with newlines, YAML parses this correctly as a sequence. Each `- ` starts a new sequence item. But verify with actual YAML parser behavior when items have indented continuations collected from non-adjacent lines.

---

## Unexplored Territory (not blocking, but good to know)

**How does `pflow workflow describe` change?** Currently reads JSON and displays info. With markdown, it could render the markdown directly or extract descriptions from the parsed IR.

**Agent instructions need rewriting.** `pflow instructions create --part 1/2/3` teaches JSON format. Needs complete rewrite for markdown. Not part of Task 107 but needed before launch.

**MCP server workflow creation.** The `run_workflow` MCP tool accepts dicts (no change needed). But if any MCP tools accept file paths or create workflow files, they need the markdown parser/writer.

**Converting existing examples.** The `examples/` directory has JSON workflows that need conversion to `.pflow.md`. Good test cases for the parser. The `webpage-to-markdown` workflow is already converted in `format-spec-decisions.md` as a reference.

---

## Relevant Files & References

### Must-read before implementation
- `.taskmaster/tasks/task_107/research/design-decisions.md` — THE comprehensive spec (25 decisions, verified findings)
- `.taskmaster/tasks/task_107/research/format-spec-decisions.md` — format details, complete examples, parsing rules
- `src/pflow/core/ir_schema.py` — IR schema definition (this is what the parser produces)
- `src/pflow/cli/main.py:162-193` — `_try_load_workflow_from_file()` (primary CLI integration point)
- `src/pflow/runtime/compiler.py:155-160` — `_parse_ir_input()` (dict/string handling)
- `src/pflow/runtime/compiler.py:1058-1075` — template validation call site (where unknown param warning hooks in)
- `src/pflow/runtime/template_validator.py:931-936` — where registry interface metadata is loaded (reuse for param warnings)
- `src/pflow/registry/metadata_extractor.py` — how interface metadata is extracted from node docstrings

### Starting context (only if you need background on WHY decisions were made)
- `.taskmaster/tasks/task_107/starting-context/braindump-implementation-context.md`
- `.taskmaster/tasks/task_107/starting-context/braindump-comprehensive-format-exploration.md`

### Architecture
- `architecture/architecture.md` — overall pflow architecture
- `src/pflow/pocketflow/__init__.py` — the underlying framework (~200 lines)
- `architecture/reference/enhanced-interface-format.md` — node interface documentation format

### Example workflows to convert as test cases
- `examples/real-workflows/generate-changelog/workflow.json` — complex (15 nodes, batch, multiple outputs)
- `examples/real-workflows/webpage-to-markdown/workflow.json` — medium complexity (already converted in format-spec-decisions.md)

---

## For the Next Agent

**Read first**: `design-decisions.md` and `format-spec-decisions.md`. They have everything — 25 decisions, verified findings, complete examples, parsing rules.

**Don't read**: The 4 braindump files in `starting-context/`. They're pre-design exploration, superseded by the research docs.

**The format is settled.** Don't redesign it. If you find an edge case the spec doesn't cover, add a parsing rule — don't change the format. The user spent hours iterating on this design and is happy with it.

**Start with a real workflow, not tests.** Write a complete markdown workflow file manually, then try to parse it. The first parse attempt will reveal edge cases that abstract test cases miss. The `webpage-to-markdown` workflow in `format-spec-decisions.md` is a good starting point.

**Build line number tracking from the start.** Every element the parser extracts should carry its source line number. Needed for parser-level error messages. Painful to retrofit. (Note: a source map for IR validation is NOT needed — see "Line numbers and IR validation errors" in Implementation Gotchas.)

**Test the `batch` and `type` routing early.** Verify `yaml batch` ends up at `node["batch"]` not `node["params"]["batch"]`, and `- type: http` ends up at `node["type"]` not `node["params"]["type"]`. These are the easiest bugs to introduce.

**The 7 JSON parse points are your integration checklist.** Each needs updating. Test each independently. (Originally documented as 5 — two additional found in `workflow_save_service.py` and `context_builder.py`.)

**Unknown param warning is in scope.** During compilation (where template validation already loads registry metadata), add a check comparing actual params against `interface["params"]` keys. Flag unknowns with "did you mean?" suggestions. This catches typos AND the `-` bullet footgun.

**Parser must validate structural completeness.** The parser should catch all issues that jsonschema would catch (missing `type`, unknown fields, etc.) with markdown line numbers. This means jsonschema validation becomes a safety net, and abstract `nodes[0]` style paths never reach users.
