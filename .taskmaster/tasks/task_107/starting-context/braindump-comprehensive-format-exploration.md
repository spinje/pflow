# Comprehensive Braindump: Workflow Format Exploration

**Task 107: Implement Markdown Workflow Format**

This document captures an extensive exploration of workflow authoring formats for pflow. The conversation evolved from "improve the changelog workflow" to "should we fundamentally rethink how workflows are authored?"

---

## Executive Summary

We explored four format options for pflow workflows:
1. **JSON (current)** - Universal but painful for prompts/code
2. **YAML** - Better multi-line, but still limited
3. **Markdown** - Literate programming with lintable code blocks
4. **Python DSL** - Native Python with template references

**Key insight:** LLMs are the primary workflow authors, not humans. The format should optimize for LLM generation quality, not human editing.

**No final decision was made.** This document presents all options with tradeoffs for the implementing agent to decide.

---

## How We Got Here

The conversation started with improving the `generate-changelog` workflow:
1. Added `get-docs-diff` node for richer context
2. Added `get-recent-updates` node for style reference
3. Added breaking changes accordion to Mintlify output
4. Updated prompts for better accuracy

During implementation, the **friction of JSON became apparent**:
```json
"prompt": "Analyze this:\n\n${item.subject}\n\nRules:\n- Be concise\n- No guessing"
```

This led to questioning: is JSON the right format?

---

## The Core Problem

### JSON Pain Points

**1. Prompt editing is terrible:**
```json
"prompt": "Analyze this change for a user-facing changelog entry.\n\n## Context\nCommit subject: ${item.subject}\nPR Title: ${item.pr_title}\n\n## Rules\n- ONLY use information explicitly provided\n- If unclear whether user-facing, default to SKIP\n\n## Output Format\nIf INCLUDE: Write entry ending with [#N](link)\nIf SKIP: Output \"SKIP: \" followed by the original commit subject"
```

All on one line. Escaped newlines. Escaped quotes. Unreadable.

**2. Shell commands with jq are cryptic:**
```json
"command": "jq -r 'to_entries | map(\"### Image \" + (.key + 1 | tostring) + \"\\n\" + .value.response) | join(\"\\n\")'"
```

Can't lint. Can't test. Errors only at runtime. Even LLMs struggle.

**3. Documentation is separate:**
- `workflow.json` + `README.md` = two files that drift apart
- The `purpose` field is one line, no formatting

**4. Token inefficiency:**
- Escaped `\n` instead of actual newlines
- Quotes around every key
- ~20-40% more tokens than necessary

---

## The Key Reframe

**"LLMs are the users, not humans."**

This changes everything:
- "Users need to learn new format" → LLMs already know markdown/Python
- "Novel = scary" → LLMs don't feel fear
- "Maintain ecosystem compatibility" → What ecosystem? We're pre-release

The current JSON format is already unusable by humans (editing a prompt on one escaped line). We're not losing human-friendliness by changing formats - we're potentially gaining it as a side benefit.

---

## Option 1: Markdown Format

### Structure

````markdown
---
name: generate-changelog
inputs:
  since_tag: { type: string, default: "" }
outputs:
  version: ${compute.stdout}
edges: [get-tag, analyze, refine, format]
---

# Generate Changelog

This workflow creates professional changelogs from git history.

---

## get-tag
type: git-get-latest-tag
purpose: Get baseline tag

## analyze
type: llm
model: gpt-4

```batch
items: ${commits.stdout}
parallel: true
max_concurrent: 10
```

```prompt
Analyze this change for a changelog entry.

## Context
${item.subject}

## Rules
- Be concise
- If unclear, output SKIP
```

## transform
type: shell

```shell
# This is lintable with shellcheck!
jq -r '.items | map(.name)'
```

## process-data
type: python

```python
# This is lintable with ruff/mypy!
import json
data = json.loads(input)
filtered = [x for x in data if x["active"]]
print(json.dumps(filtered))
```
````

### Advantages

| Advantage | Why It Matters |
|-----------|----------------|
| **Lintable code blocks** | shellcheck for `shell`, ruff/mypy for `python` |
| **Natural prompts** | Just text, no escaping |
| **Documentation inline** | Literate programming - workflow IS the docs |
| **Token efficient** | ~20-40% fewer tokens |
| **LLM-native** | Markdown is what LLMs write constantly |
| **Renders on GitHub** | Beautiful documentation for free |
| **Familiar syntax** | Headers, code blocks - nothing new |

### Disadvantages

| Disadvantage | Impact |
|--------------|--------|
| **Custom parser needed** | Few hundred lines, but still custom |
| **Three syntaxes mixed** | YAML frontmatter + Markdown + code blocks |
| **Edge cases** | Prompts containing markdown syntax |
| **Novel format** | No existing tooling ecosystem |

### Documentation Flexibility

The markdown format replaces the one-line `purpose` field with full prose:

```markdown
## fetch
type: http
url: https://r.jina.ai/${target_url}

Uses [Jina Reader](https://r.jina.ai) for conversion.

> **Why Jina?** We tested Trafilatura, Readability, and direct fetching.
> Jina had the best quality for SPAs and paywalled content.

**Expected output:** Clean markdown with images as `![alt](url)` references.
```

Documentation can be:
- Inline with each node
- At the end of the file
- Mixed (brief inline, detailed at end)

---

## Option 2: Python DSL

### Structure

```python
from pflow import workflow, llm, shell, http, git_tag, T

@workflow(
    inputs={"since_tag": str},
    outputs=["version", "entries"]
)
def generate_changelog():
    """
    Generate professional changelogs from git history.

    Uses two-pass LLM approach for accurate classification
    and proper formatting.
    """

    # Get baseline tag
    tag = git_tag()

    # Fetch commits with PR metadata
    commits = shell(f"""
        git log {T.tag.stdout}..HEAD --oneline
    """)

    # Analyze each commit (batch processing)
    analysis = llm(
        prompt="""
            Analyze this change for a changelog entry.

            ## Context
            ${item.subject}

            ## Rules
            - Be concise
            - If unclear, output SKIP
        """,
        batch=T.commits.stdout,
        parallel=True
    )

    # Transform with Python (lintable!)
    filtered = python("""
        entries = [a for a in analysis if not a.startswith("SKIP")]

        if any("BREAKING" in e for e in entries):
            return {"bump": "major", "entries": entries}
        return {"bump": "minor", "entries": entries}
    """)

    return Flow(tag >> commits >> analysis >> filtered)
```

### The Template Variable Question

At definition time, `tag.stdout` doesn't exist. Options:

1. **Keep template strings:** `"${tag.stdout}"` - same as current
2. **T object (lazy reference):** `T.tag.stdout` → produces `${tag.stdout}`
3. **Lambda:** `lambda shared: shared["tag"]["stdout"]` - verbose

Either way, you need some form of deferred reference.

### Advantages

| Advantage | Why It Matters |
|-----------|----------------|
| **One language** | Not YAML + Markdown + code blocks mixed |
| **No custom parser** | It's just Python |
| **Full IDE support** | Autocomplete, refactoring, debugging |
| **Native linting** | ruff, mypy work automatically |
| **LLM fluency** | LLMs are very good at Python |
| **Full expressiveness** | Loops, conditionals, functions |
| **Transparent** | What you see is what runs |

### Disadvantages

| Disadvantage | Impact |
|--------------|--------|
| **Static validation harder** | Need to import/run to validate |
| **UI builders harder** | Can't easily generate/edit Python |
| **Less "literate"** | Docstrings aren't as rich as markdown prose |
| **Feels like "code"** | Marketplace sharing feels riskier |
| **Graph visualization** | Need to build graph before rendering |

---

## Option 3: Hybrid (Python authoring → IR storage)

```
LLM/Human writes → Python DSL
                        ↓
                   [compile to IR]
                        ↓
                   JSON/Markdown IR ← UI builder generates
                        ↓
                   [validate statically]
                        ↓
                   [execute]
```

Like TypeScript → JavaScript:
- Python is the "source language" for authoring
- IR is the "compiled form" for storage/sharing/validation

### Advantages

- Best authoring experience (Python)
- Static validation on IR
- UI builders work with IR
- Marketplace stores IR (safer feeling)

### Disadvantages

- Two representations to maintain
- Compilation step
- More complexity

---

## Comparison Matrix

| Aspect | JSON (current) | Markdown | Python DSL |
|--------|----------------|----------|------------|
| **LLM authoring** | Medium (escaping) | High | High |
| **Prompt editing** | Painful | Natural | Natural |
| **Code linting** | None | shellcheck, ruff | Full |
| **Documentation** | Separate | Inline | Docstrings |
| **Token efficiency** | Low | High | High |
| **Static validation** | Full | Full | Limited |
| **UI builders** | Easy | Medium | Hard |
| **Parser needed** | Standard | Custom | None |
| **Shareability** | Data file | Data file | Code file |
| **Security** | Hidden shell | Hidden shell | Explicit code |

---

## Tokens to Explain Format to LLM

This is a key metric - how many tokens to teach an LLM the format?

| Format | Tokens | Why |
|--------|--------|-----|
| **Python DSL** | ~100-200 | Only need to explain `${...}` templates |
| **Markdown** | ~300-500 | Explain conventions (## = node, etc.) |
| **JSON** | ~500-1000 | Schema, escaping rules, structure |

**Python requires least explanation** because LLMs already know Python deeply.

---

## Complex Features: How Would They Look?

### Conditionals (Task 38)

PocketFlow uses action strings from `post()`:

**Markdown:**
```markdown
## validate
type: python

```python
def post(shared, prep_res, exec_res):
    if exec_res["status"] == 200:
        return "success"
    return "error"
```

# In frontmatter:
edges:
  - validate → process (on: success)
  - validate → handle-error (on: error)
```

**Python DSL:**
```python
validate = python("""
    if result["status"] == 200:
        return "success"
    return "error"
""")

validate - "success" >> process
validate - "error" >> handle_error
```

### Nested Workflows (Task 59)

**Markdown:**
```markdown
## run-payment
type: flow
workflow: ./payment-flow.md
```

**Python DSL:**
```python
from payment_flow import payment_workflow

run_payment = payment_workflow()
main_flow = validate >> run_payment >> complete
```

### Parallel Execution (Task 39)

Currently pflow is linear. Batch processing handles data parallelism. True graph parallelism (Task 39) would need:

**Markdown:**
```yaml
edges:
  - fetch → [process-a, process-b]  # fan-out
  - [process-a, process-b] → combine  # fan-in
```

**Python DSL:**
```python
# Using PocketFlow's AsyncParallelBatchFlow
parallel_group = parallel(process_a, process_b)
flow = fetch >> parallel_group >> combine
```

---

## Security Analysis

**Key insight: Security is roughly equivalent across formats.**

Current JSON with shell node:
```json
{"type": "shell", "params": {"command": "rm -rf /"}}
```

Python DSL:
```python
shell("rm -rf /")
```

Both execute arbitrary commands. The difference:
- JSON **hides** the danger (looks like data)
- Python **exposes** the danger (obviously code)

Python is arguably **more transparent** - code review catches dangerous commands more easily.

The real security boundary is **trusting the workflow source**, regardless of format.

---

## Functionality Analysis

### What's Lost with Python DSL

1. **Static validation without execution** - Can't verify template references, node existence, graph validity without at least importing the Python

2. **UI workflow builders** - Drag-and-drop builders generate data, not code

3. **Safe inspection** - Can't analyze a Python workflow without running Python

4. **Programmatic generation** - Generating code is harder than generating data

### What's Gained with Python DSL

1. **Full expressiveness** - Real loops, conditionals, functions
2. **Native tooling** - IDEs, linters, debuggers just work
3. **Transparency** - What you see is what runs
4. **LLM fluency** - LLMs write Python better than DSLs

---

## The Task 104 Factor

**Task 104: Python Script Node** changes the equation significantly.

Currently, data transformations use shell+jq:
```json
"command": "jq -r 'to_entries | map(.name)'"
```

With Python node:
```python
entries = [item["name"] for item in data]
```

This is:
- Readable
- Lintable (ruff catches typos)
- Testable
- Familiar to everyone

**The markdown format's value increases dramatically with Python nodes** because you get:
- Lintable Python in ` ```python ` blocks
- Lintable shell in ` ```shell ` blocks
- Natural prompts in ` ```prompt ` blocks

Without Task 104, you're still stuck with jq one-liners (just in a prettier format).

---

## Agent Instructions Impact

The current agent instructions (`pflow instructions create --part 1/2/3`) teach JSON format extensively. Any new format would require:

1. Rewriting the instructions
2. Teaching the new conventions
3. Updating all examples

This is significant work, but also an opportunity to make instructions simpler (less to explain with markdown/Python).

---

## Migration Considerations

- **No backwards compatibility needed** - MVP with zero users
- **Existing examples** - Would need conversion (generate-changelog, webpage-to-markdown, etc.)
- **Could support multiple formats** - Parser auto-detects by extension

---

## Open Questions for Implementer

1. **Which format?** Markdown, Python DSL, or hybrid?

2. **If markdown:**
   - File extension? `.md`, `.pflow.md`, `.pflow`?
   - How to handle prompts containing markdown?
   - Preserve docs in IR or discard?

3. **If Python DSL:**
   - How to handle template references? `T.node.output` or `"${node.output}"`?
   - How to enable static validation?
   - How to support UI builders in future?

4. **If hybrid:**
   - Which is source of truth?
   - Bidirectional conversion needed?
   - When does compilation happen?

5. **Task 104 dependency:**
   - Should this wait for Python node?
   - The value proposition is much stronger with lintable Python transforms

---

## Recommendations (Not Decisions)

### If prioritizing LLM authoring quality:
**Python DSL** - LLMs write Python fluently, no custom parser, full tooling

### If prioritizing documentation/shareability:
**Markdown** - Literate programming, renders on GitHub, feels like "data"

### If prioritizing flexibility:
**Hybrid** - Python for authoring, IR for storage, UI builders for visual editing

### Minimum viable improvement:
**Markdown** - Gets 80% of benefits with reasonable complexity

---

## Files Changed During This Conversation

### Workflow improvements (implemented):
- `examples/real-workflows/generate-changelog/workflow.json` - Added docs diff, style reference, breaking changes
- `examples/real-workflows/generate-changelog/README.md` - Updated documentation

### Test outputs (need review before commit):
- `CHANGELOG.md` - Generated v1.0.0 section
- `docs/changelog.mdx` - Generated Update block with breaking changes accordion

### Cleanup needed:
- Delete stray `. taskmaster` directory (space in name, created by typo)

---

## Key Quotes from User

> "LLMs are the users... the JSON format is almost unusable by humans (editing a prompt is VERY HARD on 1 line) but LLMs are the ones writing 95%-100% of most workflows"

> "is the step from JSON with arbitrary jq and shell commands to readable markdown with embedded lintable and real code huge? it feels like going from a broken toy to something actually elegant and production ready"

> "what would be the ultimate format for LLMs to write and understand? what would require least amounts of tokens to explain to an LLM?"

---

## For the Next Agent

**Before deciding on a format:**
1. Read the task file: `.taskmaster/tasks/task_107/task-107.md`
2. Consider Task 104 (Python node) - it amplifies markdown/Python benefits
3. Try converting `generate-changelog` to your chosen format
4. Measure token counts for format explanation

**The user's priorities:**
1. LLM authoring quality (can LLMs generate correct workflows?)
2. Linting (catch errors before runtime)
3. Readability (both for LLMs reading existing workflows and humans reviewing)
4. Documentation inline (workflows should be self-explaining)

**What the user explicitly did NOT decide:**
- Which format to use
- Whether to do hybrid approach
- File extension
- Implementation timeline

**Start by:** Having a conversation with the user about which direction they want to go, given these tradeoffs. Don't assume the markdown format is the answer - it might be Python DSL or hybrid.

---

## Additional Insights (Continued Exploration)

### Shell/jq Linting Reality Check

**What shellcheck catches:**
- Bash syntax errors
- Quoting issues (`$var` vs `"$var"`)
- Common mistakes

**What shellcheck does NOT catch:**
- jq syntax errors (`jq '.items | map(.nam)'` ← typo undetected)
- jq logic errors
- Template variables look like bash variables to shellcheck

**jq can be validated separately:**
```bash
jq --null-input '.items | map(.name)'  # syntax check
```

**Key insight:** If Task 104 (Python node) replaces most jq usage, Python linting (ruff) catches way more. Shell linting becomes less important.

**Built into pflow validate:** Yes, can extract blocks and lint:
- Shell blocks → shellcheck
- Python blocks → ruff
- jq expressions → `jq --null-input`

### Edge Syntax - Complete Freedom

In YAML frontmatter, we design the parser. Any syntax we want:

```yaml
# Option A: Simple array (linear)
edges: [get-tag, resolve, commits, analyze]

# Option B: PocketFlow-style operators
edges:
  - get-tag >> resolve >> commits
  - route - "ok" >> success
  - route - "fail" >> error

# Option C: Explicit objects (flexible)
edges:
  - from: route
    on:
      ok: success
      fail: error

# Option D: Brackets for parallel
edges:
  - fetch → [process-a, process-b] → combine
```

**The question is what's clearest for LLMs**, not what syntax exists.

### Task 46 Clarification

**Goal:** Export to standalone Python needing only:
- PocketFlow core (~200 lines)
- Node implementations used

**NOT needing:** pflow runtime (25k lines)

**Two export targets:**

| Target | Dependencies | Code Complexity |
|--------|--------------|-----------------|
| pflow Python | pflow (25k loc) | Simple: `llm(prompt="...")` |
| Standalone PocketFlow | PocketFlow (200 loc) | Complex: Full Node classes |

**Standalone PocketFlow requires:**
```python
class AnalyzeNode(Node):
    def prep(self, shared):
        return shared["commits"]
    def exec(self, prep_res):
        return call_llm(f"Analyze: {prep_res}")
    def post(self, shared, prep_res, exec_res):
        shared["analysis"] = exec_res
```

**pflow Python is just:**
```python
analyze = llm(prompt="Analyze: ${commits}")
```

**Insight:** Generating pflow Python from markdown is much easier than generating standalone PocketFlow. Task 46 (zero-dependency) is harder but has deployment benefits.

### Testing Markdown Workflows

**Would it feel unnatural to write pytest tests for markdown?**

**Answer: No.** Here's why:

```python
# End-to-end test
def test_changelog_workflow():
    with mock_llm(responses=["Added feature X", "SKIP: internal"]):
        result = pflow.run("generate-changelog.md", inputs={"since_tag": "v1.0.0"})
    assert "Added feature X" in result["entries"]

# Individual node test
def test_analyze_node():
    result = pflow.run_node("workflow.md", node_id="analyze", inputs={...})
    assert result.startswith("Added")

# Extract and test code block directly
def test_transform_logic():
    code = pflow.extract_block("workflow.md", "transform", "python")
    result = run_python(code, inputs={"data": [1, 2, 3]})
    assert result == expected
```

**Self-documenting markdown provides test instructions:**
```markdown
## analyze
Classifies commits as user-facing or internal.

**Expected inputs:** `{subject: "commit message"}`
**Expected outputs:** "Added feature X" or "SKIP: internal"
```

**The docs tell you what to test.** Testing story is similar for both formats.

### The Python-in-Python Absurdity

The earlier braindump had this example:
```python
filtered = python("""
    entries = [a for a in analysis if not a.startswith("SKIP")]
    return {"bump": "major", "entries": entries}
""")
```

**This is nonsensical.** If we're in Python, why write Python as a string? Same escaping problem we're trying to avoid.

In a Python DSL, complex logic would need:
- Lambda (limited - no statements)
- Named function (verbose)
- String code (absurd)

**Markdown actually handles this better:**
````markdown
## filter
type: python

```python
entries = [a for a in inputs["analysis"] if not a.startswith("SKIP")]
outputs["entries"] = entries
```
````

Real Python in a code block, lintable, not a string-in-Python.

### Template Variables Are The Same Everywhere

All formats use `${node.output}`:
- JSON: `"prompt": "Analyze: ${commits.stdout}"`
- YAML: `prompt: Analyze: ${commits.stdout}`
- Markdown: `Analyze: ${commits.stdout}` (in code block)
- Python: `llm(prompt="Analyze: ${commits.stdout}")`

**It's just a string.** pflow runtime resolves it. No "deferred execution" magic.

The formats differ in SYNTAX, not SEMANTICS.

### Pre-Built Nodes for Complex Features

pflow uses pre-built nodes. You don't write custom Node classes.

**Conditionals:** Pre-built `condition` node:
```yaml
## route
type: condition
when: ${api.status} == 200
on_true: success
on_false: error
```

**Parallel:** Edge declarations, not node logic:
```yaml
edges:
  - fetch → [process-a, process-b] → combine
```

No custom nodes needed. Agent configures pre-built nodes and declares graph structure.

### User's Key Answers

1. **Iteration frequency:** Happens a lot - hardening, adding functionality
2. **Who modifies:** Different LLMs (not the creator)
3. **Visual builder:** Less important if markdown is human-readable
4. **Marketplace:** Can wait, pflow cloud for org sharing
5. **Complexity distribution:** Mix of simple and complex

**Implication:** Format must support modification by different LLMs. Self-documenting nature of markdown helps here.

### Error Messages Infrastructure

Whatever we build for JSON error messages works for markdown:
- Source location tracking
- Line number mapping
- Helpful error messages

**No extra cost for markdown.** Same infrastructure.

### Debugging Idea: `--stop-at` Flag

During workflow development, would be useful to:
```bash
pflow workflow.md --stop-at refine-entries
```
Stop at a node, inspect intermediate outputs, iterate. Not implemented but would help development regardless of format choice.

### pflow Is Fundamentally Declarative

This is crucial context for the format decision:

- **Template variables** (`${node.output}`) describe RELATIONSHIPS, not execution
- **Graph structure** is defined separately from execution
- **Pre-built nodes** are configured, not coded
- This is WHY you can't just "write Python" - the paradigm is declarative

The question isn't "Python vs Markdown" - it's "what's the best syntax for declarative workflow configuration?"

### Static Validation Without Execution

**Markdown/JSON:** Can parse, validate structure, check references without executing anything
- CI can validate without dependencies
- Security scanning without code execution
- IDE support without running Python

**Python DSL:** Must import/execute to see the workflow graph
- Requires Python runtime for validation
- Code executes during "parsing"

This matters for security scanning and CI pipelines.

### The Planner Is Deprecated

User clarification: Agents don't use a "planner" for one-shot generation. Instead:
- `pflow registry discover` - find nodes
- `pflow registry run` - test nodes
- `pflow workflow save` - persist workflows
- Iterate in chat with user

Workflows are built incrementally through conversation, not generated all at once. Format must support this iterative, exploratory process.

### Version Control / Diffs

**JSON diffs poorly:**
```diff
- "prompt": "Analyze:\n\n${item.subject}\n\nRules:\n- Be concise"
+ "prompt": "Analyze:\n\n${item.subject}\n\nRules:\n- Be concise\n- Be specific"
```
One line changed = entire string shows as changed.

**Markdown diffs beautifully:**
```diff
  - Be concise
+ - Be specific
```

For collaboration and code review, markdown is significantly better.

### The TypeScript → JavaScript Analogy

- **Markdown** = TypeScript (authoring format, source of truth)
- **IR** = JavaScript (execution format, compiled output)

You don't "maintain two formats" - markdown compiles to IR. Like TypeScript, the source format is richer than the compiled form.

---

## Updated Comparison Matrix

| Factor | JSON | Markdown | Python DSL |
|--------|------|----------|------------|
| LLM authoring | Medium | High | High |
| Multi-LLM modification | Poor (no docs) | Excellent (self-documenting) | Medium (docstrings) |
| Prompt editing | Painful | Natural | Natural |
| Code linting | None | shellcheck + ruff | Full |
| Documentation | Separate | Inline (first-class) | Docstrings |
| Testing | Via pflow | Via pflow + extract blocks | Native Python |
| Custom parser | No | Yes | No |
| Edge syntax | Flexible | Flexible | PocketFlow native |
| Complex logic | jq strings | Python code blocks | Python (but string?) |

---

## The Remaining Decision Point

**Markdown advantages:**
- Self-documenting (critical for multi-LLM iteration)
- Code blocks are lintable AND readable
- Python code in code blocks works naturally
- Documentation is first-class

**Python DSL advantages:**
- No custom parser
- Native Python tooling
- LLMs know Python deeply

**The key question:**
Is markdown's self-documenting nature worth the custom parser?

Or: Will LLMs write good docstrings in Python, making documentation equivalent?

**Instinct:** Markdown invites prose naturally. Python docstrings feel like an afterthought. For multi-LLM iteration where context matters, markdown's inline documentation is a meaningful advantage.

---

**Note to next agent**: Read this document fully before taking any action. This represents several hours of deep exploration. When ready, confirm you've read and understood by summarizing the key tradeoffs, then ask the user which direction they want to pursue.
