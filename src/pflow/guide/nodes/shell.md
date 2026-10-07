# Shell Node

**Use for**: External tools and side effects — any program where the exit code or side effect is the point.

- CLI tools: git, curl, docker, ffmpeg, terraform, npm
- System commands: mkdir, chmod, which
- Binary/streaming data: use `shell` with `curl`
- Use macOS-compatible (BSD) commands, not GNU-specific extensions
- Use `$VAR` not `${VAR}` for shell variables (braces conflict with pflow template syntax). When you need braces (`${VAR:-default}`, `${#VAR}`), escape them: `$${VAR:-default}` reaches the shell as `${VAR:-default}`
- **Warning sign**: Long chains of `sed`, `awk`, `jq`, `tr`, `grep` piped together → use `code` node instead (more readable, portable, debuggable)
- **Don't use shell for data pass-through**: `jq '.'` before an LLM is unnecessary — pass `${node.response}` directly. Templates handle JSON natively.
- **Caching**: shell nodes don't cache by default (their output depends on external state) — safe to use inside iteration loops. Add `cache: true` only for a pure, expensive command whose output is fully determined by its declared inputs.

### Node Creation Pattern

```markdown
### list-recent-files

List recently modified files. Note: `$var` = shell variable, `${var}` = pflow template.

- type: shell

```shell command
find . -maxdepth ${depth} -type f -newer /tmp/marker 2>/dev/null | head -20
```
```

### Templates in Shell Commands

**In shell commands** — pflow variables resolve before the shell runs. Use a code block for multi-line or complex commands:

````markdown
### run-pipeline

Creates the output directory, then pulls items from the API into it.

- type: shell

```shell command
mkdir -p ${output_dir}/images && curl -s ${api_url}/items?limit=${limit}
```
````

### Environment variables (`env:`)

Bind values in `- env:` and read them in the command as shell variables. A bound value is data: quotes, `$`, backticks and newlines in it are never interpreted by the shell.

````markdown
### fetch-item

Fetches one page of items from the API.

- type: shell
- env:
    ENDPOINT: ${endpoint}
    LIMIT: ${limit}

```shell command
curl -s "https://api.example.com/$ENDPOINT?limit=$LIMIT"
```
````

- **Names**: UPPER_SNAKE, chosen for the content (`ISSUE_BODY`, not `X`) — letters, digits and underscores, not starting with a digit. Always double-quote the reference: `"$ISSUE_BODY"`. Names the shell itself relies on (`PATH`, `HOME`, `IFS`, …) get a validation warning. On Windows, Git Bash imports Windows path variables such as `PATH` and `TEMP` upper-cased, with their values converted to POSIX paths — use another name for data.
- **Every value binds as text** — exactly the text `${x}` produces inside a string: a number `3`, a boolean `True`/`False`, null empty, an object or array as JSON (`{"a": 1}`). A string bound directly (`DATA: ${fetch.stdout}`) arrives unchanged, JSON-looking or not; a value that first passes through an `inputs:` map (the step's own, a loop carry, a sub-workflow's inputs) is JSON-parsed there and re-serialized (`{"a":1}` → `{"a": 1}`), and a `key=value` given on the command line is typed first (`007` → `7`) — bind directly in `env:` when the bytes matter. Literal YAML values follow the same rule: `DEBUG: true` binds `True`, `VERSION: 1.10` binds `1.1`, `MODE: 0755` binds `493` — quote a value whose exact text matters (`VERSION: "1.10"`).
- **Large values go through `stdin:`**: the environment has an operating-system size limit (about 1 MB for everything together on macOS; at most 128 KB for one value on Linux). A value over it, or one containing a NUL byte, fails before the command starts.
- **Masking follows the name**: approval previews and the web UI hide a value whose name contains a credential word (`TOKEN`, `SECRET`, `PASSWORD`, `AUTH`, `CREDENTIAL`, `API_KEY`). Name secrets that way, and keep those words out of ordinary data — `TOKEN_LIMIT: "5"` shows as `<REDACTED>`, so an approver cannot see it.

### Testing Shell Pipelines

**Testing shell pipelines independently:**
When building shell commands with piped CLI tools (e.g., git log | head, curl | grep), test the complete pipeline outside pflow first:
```bash
# Test with actual data source before integrating:
curl -s "https://example.com/api" | head -20

# Once verified, integrate into workflow
```

**Pipeline exit codes**: Only the last command's exit code is captured. In `grep | sed`, if sed fails you see sed's stderr, but can't tell if grep found matches or not.

