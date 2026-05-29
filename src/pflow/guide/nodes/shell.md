# Shell Node

**Use for**: External tools and side effects — any program where the exit code or side effect is the point.

- CLI tools: git, curl, docker, ffmpeg, terraform, npm
- System commands: mkdir, chmod, which
- Binary/streaming data: use `shell` with `curl`
- Use macOS-compatible (BSD) commands, not GNU-specific extensions
- Use `$VAR` not `${VAR}` for shell variables (braces conflict with pflow template syntax)
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

### Testing Shell Pipelines

**Testing shell pipelines independently:**
When building shell commands with piped CLI tools (e.g., git log | head, curl | grep), test the complete pipeline outside pflow first:
```bash
# Test with actual data source before integrating:
curl -s "https://example.com/api" | head -20

# Once verified, integrate into workflow
```

**Pipeline exit codes**: Only the last command's exit code is captured. In `grep | sed`, if sed fails you see sed's stderr, but can't tell if grep found matches or not.

