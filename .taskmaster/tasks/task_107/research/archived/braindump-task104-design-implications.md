# Braindump: Task 104 Design Session Implications for Task 107

## Where I Am

During the Task 104 (Python code node) design session, **Task 107 (Markdown Workflow Format) kept coming up as the forcing function for critical decisions**. We didn't design Task 107 explicitly, but we made several key architectural choices BECAUSE of Task 107.

This braindump captures what we learned about Task 107's requirements and constraints through the lens of designing the code node that will live inside markdown workflows.

**Critical insight**: Task 107 is NEXT, not future. The user said this explicitly, which completely changed our approach to type hints in Task 104.

## User's Mental Model

### Markdown Workflows are the Agent-First Format

The user sees JSON IR as necessary but **not ergonomic for humans or AI agents**. Markdown is the target format because:
- Natural for documentation
- Familiar to developers
- **Python code blocks work with standard tooling** (mypy, LSP, IDE autocomplete)

**This is why type hints became required in Task 104** - not for validation alone, but to enable Python tooling to work seamlessly in markdown.

### The Vision: Workflows as Literate Programs

From the research materials we read (`.taskmaster/tasks/task_104/research/new-nodes.md`), there's a concept of workflows being **both executable and readable**. Markdown enables this.

The user didn't explicitly say "literate programming" but the pattern is clear:
1. Markdown for human-readable structure
2. YAML frontmatter for node configuration
3. Code blocks for actual logic (with syntax highlighting, type checking, etc.)

### Type Stubs are the Integration Point

We discussed generating `.pyi` stub files so that Python tooling understands the workflow context. Example:

```python
# .pflow/workflow_types.pyi (auto-generated)
class fetch:
    result: dict  # From HTTP node metadata

class transform:
    result: list[dict]  # From code node type annotations
```

This enables IDEs to provide autocomplete on `fetch.result` inside code blocks.

**The user didn't ask for this** - I suggested it based on the type hints requirement. They didn't reject it, which suggests alignment with their thinking.

## Key Insights from Task 104 Design

### 1. Type Hints Enable Cross-Node Validation

With type hints in code blocks, markdown workflows can be validated BEFORE execution:

```markdown
## fetch
type: http
url: https://api.example.com

## transform
type: code
```python
data: list[dict] = fetch.result  # mypy can check: fetch.result is dict, expects list!
```
```

This validation would happen at **compile time** (when converting markdown → JSON IR), not just runtime.

### 2. The Frontmatter Format is Implied

Based on our discussion of `inputs` and `requires`, the markdown format likely looks like:

```markdown
## node-id
type: code
inputs:
  records: ${fetch.result}
  limit: 10
requires: [pandas]
timeout: 60

```python
import pandas as pd

records: list[dict]
limit: int

df = pd.DataFrame(records)
result: dict = df.describe().to_dict()
```
```

**ASSUMPTION**: Frontmatter uses YAML syntax (not JSON) for readability.
**ASSUMPTION**: Code blocks use triple-backtick with language identifier.
**ASSUMPTION**: Template variables (`${...}`) work in frontmatter values.

### 3. The Code Block IS the `code` Parameter

The Python code block content becomes the `code` parameter in JSON IR. Everything else is frontmatter.

This means:
- No need to escape the code
- Syntax highlighting works
- IDEs can validate the code in-place
- Type checkers see valid Python

### 4. Multiple Code Blocks per Node?

**UNEXPLORED**: Can a node have multiple code blocks? Helper functions + main execution?

```markdown
## transform
type: code

```python
# Helper function
def clean_record(r: dict) -> dict:
    return {k: v for k, v in r.items() if v is not None}
```

```python
# Main execution
records: list[dict]
result: list = [clean_record(r) for r in records]
```
```

Or are they concatenated? Or only the last one used?

**NEEDS DECISION**: How are multiple code blocks handled?

## Assumptions & Uncertainties

### ASSUMPTION: YAML Frontmatter Format

We assumed frontmatter uses YAML (like Jekyll, Hugo, etc.):

```markdown
## node-id
type: code
inputs:
  key: value
requires:
  - pandas
  - numpy
```

**NOT** JSON:
```markdown
## node-id
{
  "type": "code",
  "inputs": {"key": "value"}
}
```

**NEEDS VERIFICATION**: Is this the intended format?

### ASSUMPTION: Node ID from Heading

```markdown
## my-transform-node
type: code
```

The `## heading` becomes the node ID (`my-transform-node`).

**NEEDS VERIFICATION**: Is this correct, or is there a separate `id:` field in frontmatter?

### UNCLEAR: How are Edges Defined?

In JSON IR, edges are explicit:
```json
{"from": "fetch", "to": "transform"}
```

In markdown, are they:
- **Implicit** (sequential order)?
- **Explicit** in frontmatter (`depends: [fetch, parse]`)?
- **Inferred** from template variables (`${fetch.result}` implies edge)?

**NEEDS DESIGN DECISION**: Edge definition strategy.

### UNCLEAR: Workflow-Level Metadata

Where do workflow inputs/outputs get declared?

```markdown
---
inputs:
  api_token: str
outputs:
  summary: dict
---

## fetch
type: http
headers:
  Authorization: Bearer ${api_token}
```

**ASSUMPTION**: Top-level YAML frontmatter (before any `##` headings) for workflow metadata.

### UNCLEAR: Conditional Nodes / Branching

Task 38 (conditional branching) isn't implemented yet. How would it look in markdown?

```markdown
## validate
type: code
```python
data: dict
result: bool = data.get('valid', False)
```

## process
type: code
condition: ${validate.result} == true
```

**UNEXPLORED**: Conditional syntax in markdown format.

## Unexplored Territory

### UNEXPLORED: Comment Syntax in Workflows

Can users add comments in markdown workflows?

```markdown
<!-- This node validates the input -->
## validate
type: code
```

Or:
```markdown
## validate
# This validates the input
type: code
```

**MIGHT MATTER**: If comments are preserved, they could be useful for AI agents understanding workflow intent.

### CONSIDER: Code Block Language Identifiers

We assumed:
```markdown
```python
code here
```
```

But what about:
```markdown
```py
code here
```
```

**MIGHT MATTER**: Parser should accept both `python` and `py` as valid identifiers.

### CONSIDER: Indentation in Code Blocks

Python is indentation-sensitive. Markdown code blocks preserve indentation:

```markdown
```python
    # Accidentally indented
    result = data[:10]
```
```

Does the parser strip leading indentation? Or does Python's `IndentationError` bubble up?

**PROBABLY**: Strip common leading whitespace (like Python's `textwrap.dedent()`).

### UNEXPLORED: Inline vs Block Syntax

For simple nodes, inline syntax might be cleaner:

```markdown
## fetch { type: http, url: "https://api.example.com" }
```

vs:

```markdown
## fetch
type: http
url: https://api.example.com
```

**MIGHT MATTER**: Inline for simple nodes, block for complex. Or enforce consistency?

### CONSIDER: Type Stub Generation Timing

When are `.pyi` stubs generated?
- On workflow load (every run)?
- On workflow save (one-time)?
- On explicit validation command (`pflow validate workflow.md`)?

**ASSUMPTION**: Generated during validation/compile step, not at runtime.

### UNEXPLORED: Multi-File Workflows

Can markdown workflows span multiple files?

```markdown
<!-- main.md -->
Import: ./nodes/data-processing.md
Import: ./nodes/api-calls.md

## orchestrate
type: code
```

**MIGHT MATTER**: For large workflows, file splitting could improve maintainability.

### CONSIDER: Workflow Versioning in Markdown

Should markdown workflows include version metadata?

```markdown
---
version: 1.2.0
pflow_version: ">=0.8.0"
---
```

**MIGHT MATTER**: For reproducibility and compatibility checks.

## What I'd Tell Myself

### Start With the Code Node Markdown Format

The Python code node in markdown is the **most complex case**. If you design for that, simpler nodes (HTTP, shell) will be trivial.

Design markdown format in this order:
1. Code node with type hints and inputs
2. HTTP/shell nodes (simpler)
3. Workflow-level metadata
4. Edge definition strategy
5. Conditional branches (Task 38 integration)

### The Type System is the Value Proposition

Markdown workflows aren't just "JSON but prettier". The value is:
- **Python tooling integration** (mypy, LSP, IDE)
- **Syntax highlighting** in editors
- **Human readability** for documentation

If the type system doesn't work, markdown format loses most of its value.

### Don't Reinvent Frontmatter

Use YAML for frontmatter. It's a solved problem:
- Jekyll uses it
- Hugo uses it
- GitHub Actions uses it

Developers already know this pattern. Don't invent new syntax.

### Parser Should Be Lenient

Markdown is for humans. The parser should:
- Strip leading/trailing whitespace
- Accept both `python` and `py` language identifiers
- Tolerate missing frontmatter (use defaults)
- Give helpful error messages for malformed YAML

## Open Threads

### Thread 1: JSON IR as Compilation Target

Markdown workflows should **compile to JSON IR**, not be executed directly. This means:
1. Markdown parser → JSON IR
2. Existing validation/execution pipeline (unchanged)

**Benefits**:
- No code duplication
- Markdown is just a better authoring format
- JSON IR remains the "assembly language"

### Thread 2: Round-Trip Conversion

Can JSON IR → Markdown conversion work?

Use case: User generates workflow with planner (JSON IR) → converts to markdown for editing → converts back to JSON for execution.

**PROBABLY**: One-way only (Markdown → JSON). JSON → Markdown loses formatting/comments.

### Thread 3: Template Variables in Frontmatter

We assumed `${...}` works in frontmatter:

```yaml
url: ${base_url}/api/users
```

But frontmatter is YAML, which has its own variable syntax. How do we distinguish?

**PROBABLY**: Treat `${...}` as literal strings in YAML, resolve during JSON IR compilation.

### Thread 4: mypy Integration for Validation

We discussed running mypy on workflows. The flow would be:

```bash
pflow validate workflow.md --strict

# Behind the scenes:
1. Generate .pyi stubs from node metadata
2. Extract code blocks
3. Generate virtual Python file with workflow context
4. Run: mypy virtual_file.py
5. Parse mypy errors, make user-friendly
```

**ASSUMPTION**: This is optional (via `--strict` flag), not required for basic validation.

## Relevant Files & References

### Research Materials from Task 104 Session:
- `.taskmaster/tasks/task_104/research/new-nodes.md` - Discusses template syntax alternatives and the vision for declarative nodes (mentions JMESPath, Jinja2 as examples of NOT adding filters to templates)
- `.taskmaster/tasks/task_104/research/output-format.md` - Discusses how outputs vs actions are distinguished (relevant for markdown node definitions)
- `.taskmaster/tasks/task_104/research/template-variables.md` - Template resolution behavior

### Task 104 Spec:
- `.taskmaster/tasks/task_104/starting-context/task-104-spec.md` - Complete Python code node specification with type hints

### Architecture Docs:
- `architecture/reference/enhanced-interface-format.md` - Node interface documentation format (relevant for metadata extraction from markdown)

### Existing Markdown-Adjacent Patterns:
- GitHub Actions workflows (YAML frontmatter + job definitions)
- Jupyter notebooks (code + markdown cells, but JSON format)
- RMarkdown (markdown + R code blocks)

## For the Next Agent

### Start By:

1. **Define the simplest possible markdown workflow** - One HTTP node, no variables. Nail the parser for that.
2. **Add the Python code node** - This is the complex case (frontmatter + code block + type hints).
3. **Design edge definition** - Implicit vs explicit, how does it compile to JSON IR?
4. **Implement validation** - Basic syntax validation, then type checking.

### Don't Bother With:

- Round-trip JSON → Markdown conversion (one-way only)
- Complex conditional syntax until Task 38 is done
- Multi-file workflows (nice-to-have, not MVP)
- Custom frontmatter syntax (use YAML, it's standard)

### The User Cares Most About:

1. **Python tooling integration** - mypy, LSP, IDE autocomplete MUST work
2. **Readability** - Markdown should be more pleasant to read/write than JSON
3. **Agent-friendly** - AI agents should be able to generate/modify markdown workflows
4. **No information loss** - Markdown → JSON IR should preserve all semantics

### Critical Design Constraints:

**From Task 104 design session:**
- Type hints are REQUIRED in code blocks (for tooling)
- `inputs` dict is separate from code parameter (explicit in frontmatter)
- `requires` field for dependencies (documentation, possible future validation)
- Timeout and other config in frontmatter

**Example markdown code node:**
```markdown
## transform
type: code
inputs:
  records: ${fetch.result}
  limit: 10
requires: [pandas]
timeout: 60

```python
import pandas as pd

records: list[dict]
limit: int

df = pd.DataFrame(records)
result: dict = df.describe().to_dict()
```
```

**Compiles to JSON IR:**
```json
{
  "id": "transform",
  "type": "code",
  "params": {
    "inputs": {
      "records": "${fetch.result}",
      "limit": 10
    },
    "code": "import pandas as pd\n\nrecords: list[dict]\nlimit: int\n\ndf = pd.DataFrame(records)\nresult: dict = df.describe().to_dict()",
    "requires": ["pandas"],
    "timeout": 60
  }
}
```

### Questions to Answer Before Implementation:

1. **Edge definition strategy** - How are dependencies declared?
2. **Node ID extraction** - From `##` heading or frontmatter `id:` field?
3. **Workflow-level metadata** - Top-level frontmatter format?
4. **Multiple code blocks** - Concatenated or error?
5. **Type stub generation** - When and where?
6. **mypy integration** - MVP feature or future enhancement?

### Validation Strategy:

**Layer 1**: Markdown syntax validation
- Valid YAML frontmatter
- Code blocks properly closed
- Node IDs unique

**Layer 2**: JSON IR validation
- Compile markdown → JSON IR
- Run existing JSON IR validators
- All type/template validation

**Layer 3**: Python tooling (optional)
- Generate `.pyi` stubs
- Run mypy on code blocks
- Report type errors

---

## Connection to Task 104

**The type hint requirement in Task 104 EXISTS BECAUSE of Task 107.**

We made the Python code node require type hints specifically to enable markdown workflows to work with Python tooling. Without Task 107, type hints could have been optional.

This is **strategic co-design** - Task 104 was designed with its markdown form in mind, even though Task 107 isn't implemented yet.

---

**Note to next agent**: This braindump captures the **implicit requirements** for Task 107 that emerged during Task 104's design. We didn't design Task 107 explicitly, but we made several architectural choices that constrain and enable it. Read this alongside Task 104's spec to understand the full picture. When ready, confirm you've understood the type system integration requirements and the markdown format implications before proceeding.

---

## Post-Implementation Review (after Task 104 completed)

*Added after implementing Task 104 and verifying all assumptions against the actual code.*

### What's Accurate

The core thesis of this document holds up well after implementation:

- **Type hints required because of Task 107** — confirmed. The `prep()` phase rejects code without annotations for both inputs and `result`.
- **Code block = `code` parameter** — confirmed. The `code` string is passed to `ast.parse()` then `exec()`. The markdown triple-backtick content maps 1:1.
- **`inputs` dict separate from code** — confirmed. `inputs` is a top-level param alongside `code`, `timeout`, `requires`. Template resolution happens on the `inputs` dict values, not inside the code string.
- **Markdown → JSON IR → existing pipeline** — confirmed. The integration test proves the code node works through `compile_ir_to_flow` with template resolution and namespacing. No special handling needed.
- **The example JSON IR compilation (lines 469-505)** — verified correct against the actual `PythonCodeNode` API.

### Inaccuracies to Correct

**Lines 62-63 — Cross-node type checking example is misleading:**

The example shows:
```python
data: list[dict] = fetch.result  # mypy can check
```

This is NOT how the code node works. In actual usage:
- The code block contains `data: list[dict]` as a bare annotation (or `data: list[dict] = ...` with a local expression)
- `fetch.result` is a template `${fetch.result}` in the `inputs` dict, resolved to a native Python object BEFORE `exec()` runs
- The code block never references `fetch.result` as a Python identifier — it sees `data` as an already-injected local variable

Cross-node type checking would need to happen at the *frontmatter* level (matching `inputs: {data: ${fetch.result}}` against fetch's output type), not inside the code block. The code block's type annotations validate the *shape* of what was injected, not the *source*.

**Lines 33-43 — Type stub format is speculative:**

The `.pyi` stub example (`class fetch: result: dict`) is presented with more confidence than warranted. This is one idea among several. The actual mechanism for IDE integration hasn't been designed. Treat this as brainstorm material, not a decision.

**Line 92 — YAML frontmatter treated as decided:**

Stated as "ASSUMPTION" at line 92 but treated as settled at lines 355-360 ("Use YAML for frontmatter. It's a solved problem"). This is still an open design question — YAML is reasonable but not decided.

**Line 165 — Node ID from heading needs normalization:**

pflow node IDs are kebab-case strings (e.g., `read-file`, `my-transform`). Markdown headings can contain spaces, special characters, etc. A normalization step (`## My Transform Node` → `my-transform-node`) is implied but never acknowledged. This is a small detail but will matter during implementation.

### Scope Creep Warning

This document explores significant territory beyond Task 107's MVP: multi-file workflows, conditional branches, versioning, inline syntax, round-trip conversion, mypy integration. These are interesting ideas but could mislead the next agent into thinking Task 107 is larger than it needs to be.

**Task 107 MVP should be**: parse a markdown file → produce a JSON IR dict → feed it to the existing `compile_ir_to_flow` pipeline. That's it. Everything else (type stubs, mypy, multi-file, conditionals) is future work.

### Implementation Details That Matter for Task 107

From building Task 104, here are concrete facts the next agent should know:

1. **Template resolution handles nested dicts.** The `TemplateAwareNodeWrapper` resolves `${...}` inside nested structures like `inputs: {"data": "${source.data}"}`. This means the markdown parser just needs to produce the same JSON IR structure — the runtime handles the rest.

2. **The `inputs` dict preserves types.** Simple templates (`${var}`) preserve the original Python type (list, dict, int). The code node receives native objects, not JSON strings. The markdown parser doesn't need to do any type coercion.

3. **Node type `"code"` is registered via `name = "code"` class attribute.** The scanner auto-discovers `PythonCodeNode` from `src/pflow/nodes/python/python_code.py`. No IR schema changes were needed — the type field accepts any string.

4. **Outer type validation only.** `list[dict]` checks `isinstance(value, list)`, ignoring element types. Deep generic validation is not implemented. This limits how much compile-time type checking Task 107 can realistically offer.

5. **`requires` is documentation-only.** The field is stored but not validated or enforced. If a required package isn't installed, Python's `ImportError` bubbles up at runtime with a helpful error message. Task 107 could optionally add pre-flight checking here.

6. **ThreadPoolExecutor timeout has a known limitation.** The worker thread can't be killed — it becomes a zombie after timeout. This is documented and accepted for MVP. It means markdown workflows with timeout-prone code nodes may leak threads. Container sandboxing (Task 87) is the real fix.
