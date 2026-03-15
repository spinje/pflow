# Real-World Usage Notes: Shell Variable Conflict

**Context**: Built a multi-source lyrics generation workflow (`music-generation` project) using pflow. The workflow chains source fetching (YouTube via yt-dlp, webpages via Jina Reader), LLM analysis, genre selection, lyric writing, and review. Multiple shell nodes, conditional branching, batch processing.

## Concrete Problems Encountered

### 1. Shell default value syntax blocked

Needed to auto-increment a folder number (0001, 0002, ...). Natural shell:
```bash
NEXT=$(printf "%04d" $(( ${LATEST:-0} + 1 )))
```
pflow interprets `${LATEST:-0}` as a template variable and fails. Had to work around with:
```bash
if [ -z "$LATEST" ]; then LATEST=0; fi
NEXT=$(printf "%04d" $(( LATEST + 1 )))
```
Ended up moving this to a code (Python) node entirely to avoid the issue.

### 2. Constant mental overhead

Every shell command required thinking: "is this `${}` pflow or shell?" Examples from the workflow:
```bash
# This is pflow — resolves before shell runs:
curl -sL "https://r.jina.ai/${source_url}"

# This is shell — but looks identical:
TITLE=$(yt-dlp --get-title "$SOURCE" 2>/dev/null)
```
The visual similarity between pflow's `${source_url}` and shell's `${LATEST:-0}` creates cognitive load on every line.

### 3. Drove architectural decisions

The `${VAR}` conflict influenced how I structured the workflow. I avoided shell nodes for anything with complex bash logic and pushed computation into Python code nodes instead — not because Python was better for the task, but because it didn't have the template conflict. This is the tail wagging the dog.

### 4. Batch shell nodes compound the issue

In batch shell nodes, you get `${item}` (pflow) mixed with shell variables in the same command:
```bash
SOURCE="${item}"
if echo "$SOURCE" | grep -qE '(youtube\.com|youtu\.be)'; then
  TMP=$(mktemp -d)
  yt-dlp --write-sub --write-auto-sub --sub-lang en --skip-download --sub-format vtt -o "$TMP/yt" "$SOURCE" 2>/dev/null
  ...
fi
```
`${item}` is pflow. `$TMP`, `$SOURCE` are shell. `$()` is command substitution. Three different `$` semantics in one block.

## Why `inputs` Is Better Than `${{...}}`

Considered two solutions during the build:

### Option A: `${{...}}` delimiters
- Solves the collision — shell never uses `${{...}}`
- But it's still magic interpolation inside shell code
- The shell block *looks* like shell but has hidden pflow behavior
- Ugly: `${{compute-output-dir.result}}` everywhere

### Option B: `inputs` param (like code nodes)
- Shell block is pure shell — no pflow syntax at all
- Explicit about what data flows into the node
- Consistent with how code nodes already work
- Aliases long paths: `${compute-output-dir.result}` becomes just `$output_dir`
- Standard tools (shellcheck, IDE highlighting) work on the shell block

**Clear winner: Option B.** It solves the collision AND makes shell nodes more readable and toolable.

### What it would look like in practice

Current (from lyrics-generator workflow):
```markdown
### fetch-webpage
- type: shell
- next: read-content

```shell command
curl -sL "https://r.jina.ai/${source}"
```
```

With `inputs`:
```markdown
### fetch-webpage
- type: shell
- inputs:
    source: ${source}
- next: read-content

```shell command
curl -sL "https://r.jina.ai/$source"
```
```

Current complex example:
```markdown
### read-raw-source
- type: shell

```shell command
cat "${compute-output-dir.result}/01-source-raw.md"
```
```

With `inputs`:
```markdown
### read-raw-source
- type: shell
- inputs:
    output_dir: ${compute-output-dir.result}

```shell command
cat "$output_dir/01-source-raw.md"
```
```

## Open Question from Task 118: Automatic vs Explicit Injection

> "Should shell nodes get a formal `inputs` param like code nodes, or inject all template-referenced values automatically?"

**Strong recommendation: explicit `inputs` param.**

Reasons from real usage:
1. You can see what a shell node depends on without reading the command
2. You control the bash variable names (aliasing long paths to short names)
3. No ambiguity about which `${...}` are pflow vs shell — there are no pflow `${...}` in the shell block
4. Automatic injection still requires parsing the shell block to find template references, which is fragile

## Answer to Open Question: `$HOME`, `$PATH` Alongside Injected Variables

> "How to handle shell commands that genuinely need bash variable expansion (`$HOME`, `$PATH`) alongside pflow-injected variables?"

This is a non-issue with the `inputs` approach. Since pflow never touches the shell block, `$HOME` and `$PATH` are just normal bash variables. They coexist naturally with pflow-injected variables:

```markdown
### example
- type: shell
- inputs:
    api_url: ${config.api_url}

```shell command
curl -sL "$api_url" > "$HOME/.cache/data.json"
```
```

No conflict. `$api_url` is injected by pflow. `$HOME` is a standard env var. Both are just bash variables from the shell's perspective.

## Additional Observation: Conditional Branching Convergence

While not directly related to Task 118, the workflow exposed another pain point. When using conditional branching, converging branches requires a workaround because downstream nodes can't reference outputs from non-executed branches. The pattern used:

1. Each branch writes to a shared temp file
2. A convergence node reads the file back with `cat`

This works but feels like a hack. A first-class convergence mechanism (e.g., `${fetch-youtube.stdout ?? fetch-webpage.stdout}` fallback operator) would eliminate this pattern. Might warrant its own task.

## Workflow Details

- **Project**: `/Users/andfal/projects/music-generation`
- **Workflow**: `lyrics-generator.pflow.md` (multi-source lyrics generation)
- **Sub-workflow**: `fetch-source.pflow.md` (source fetching with 4-way branching)
- **Nodes used**: shell, code, llm, write-file, workflow
- **Features exercised**: conditional branching, batch processing (parallel), nested workflows (attempted — hit validator issue with batch + workflow nodes)
