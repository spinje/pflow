# Shell Node

**Use for**: External tools and side effects — any program where the exit code or side effect is the point.

- CLI tools: git, curl, docker, ffmpeg, terraform, npm
- System commands: mkdir, chmod, which
- Binary/streaming data: use `shell` with `curl`
- Use macOS-compatible (BSD) commands, not GNU-specific extensions
- **The command is plain sh** — pflow never fills in `${…}` there. `$HOME`, `${HOME}`, `${NAME:-default}` and `${#NAME}` are the shell's own, with nothing to escape. Values reach the command through `env:` (below).
- **Warning sign**: Long chains of `sed`, `awk`, `jq`, `tr`, `grep` piped together → use `code` node instead (more readable, portable, debuggable)
- **Don't use shell for data pass-through**: `jq '.'` before an LLM is unnecessary — pass `${node.response}` directly. Templates handle JSON natively.
- **Caching**: shell nodes don't cache by default (their output depends on external state) — safe to use inside iteration loops. Add `cache: true` only for a pure, expensive command whose output is fully determined by its declared inputs.

### Node Creation Pattern

Bind each value in `- env:` under an UPPER_SNAKE name chosen for its content, and read it in the command as `"$NAME"` — always double-quoted. Use a `shell command` code block for multi-line or complex commands:

````markdown
### list-recent-files

List files modified since the marker, at most `DEPTH` directories deep.

- type: shell
- env:
    DEPTH: ${depth}

```shell command
find . -maxdepth "$DEPTH" -type f -newer /tmp/marker 2>/dev/null | head -20
```
````

### Passing values: `env:`

Templates resolve in `env:` like in any param; each entry becomes an environment variable of the command. A bound value is data: quotes, `$`, backticks and newlines in it are never interpreted by the shell.

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

A `${…}` in the command that names a pflow value this step could read — a workflow input, a step output such as `${fetch.stdout}`, the batch `${item}`, an `inputs:` key — fails validation with the `env:` line to add. So does `$${`.

- **Names**: UPPER_SNAKE, chosen for the content (`ISSUE_BODY`, not `X`) — letters, digits and underscores, not starting with a digit. Write `${ISSUE_BODY}` only where a letter, digit or `_` follows the name. Names the shell itself relies on (`PATH`, `HOME`, `IFS`, …) get a validation warning. On Windows, Git Bash imports Windows path variables such as `PATH` and `TEMP` upper-cased, with their values converted to POSIX paths — use another name for data.
- **Every value binds as text** — exactly the text `${x}` produces inside a string: a number `3`, a boolean `True`/`False`, null empty, an object or array as JSON (`{"a": 1}`). A string bound directly (`DATA: ${fetch.stdout}`) arrives unchanged, JSON-looking or not; a value that first passes through an `inputs:` map (the step's own, a loop carry, a sub-workflow's inputs) is JSON-parsed there and re-serialized (`{"a":1}` → `{"a": 1}`), and a `key=value` given on the command line is typed first (`007` → `7`) — bind directly in `env:` when the bytes matter. Literal YAML values follow the same rule: `DEBUG: true` binds `True`, `VERSION: 1.10` binds `1.1`, `MODE: 0755` binds `493` — quote a value whose exact text matters (`VERSION: "1.10"`).
- **Large values go through `stdin:`**: the operating system limits the environment — on macOS about 1 MB for the arguments and the whole environment together; on Linux at most 128 KiB for one value (on Windows a 200 KB value binds). A value over the limit, or one containing a NUL byte, fails before the command starts. `- stdin: ${fetch.response}` pipes a value of any size or shape to the command (`jq`, `wc`, `cat`); objects and arrays arrive as JSON.
- **Masking follows the name**: approval previews, the web UI, error output and `pflow report` hide a value whose name contains one of the words `TOKEN`, `SECRET`, `PASSWORD`, `AUTH`, `CREDENTIAL` or `API_KEY`. Name secrets that way (`GITHUB_TOKEN`), and keep those words out of ordinary data — `TOKEN_LIMIT: "5"` shows as `<REDACTED>`, so the person approving the step cannot see it.

**`inputs:` on a shell step** is the namespace `env:`, `stdin` and `cwd` read from, and where a loop `carry:` lands — the command never sees it. Bind each key you need in `env:` (`env: {STATE: ${state}}`, then `"$STATE"`); an `inputs:` key no other param reads gets a warning.

**The dangerous-command check** reads the command text only. It cannot see what a variable will hold — guard destructive commands yourself (`[ -n "$DIR" ] || exit 1`).

### Testing Shell Pipelines

**Testing shell pipelines independently:**
When building shell commands with piped CLI tools (e.g., git log | head, curl | grep), test the complete pipeline outside pflow first:
```bash
# Test with actual data source before integrating:
curl -s "https://example.com/api" | head -20

# Once verified, integrate into workflow
```

**Pipeline exit codes**: Only the last command's exit code is captured. In `grep | sed`, if sed fails you see sed's stderr, but can't tell if grep found matches or not.
