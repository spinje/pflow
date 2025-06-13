# ClaudeCode Core Node Spec (Legacy - See Updated Architecture)

> **Note**: This specification represents an earlier, coarse-grained approach. The current MVP uses an **action-based platform node architecture** where Claude Code functionality is integrated into the `claude` platform node with an `implement` action. See `claude-platform-node-spec.md` for the updated approach that reduces cognitive load and aligns with MCP patterns.

Below is a focused evaluation plus a **mini-spec** for a *single, minimal* `ClaudeCode` core node that just “fires-and-forgets” a prompt+context to the headless **claude-code** CLI.  It assumes the MVP already has the pure-cached `Prompt` node described earlier.

---

## 1  Does a “claude-code” node belong in core?

| Criterion                 | Fit for core?                                                | Rationale                                                                                                              |
| ------------------------- | ------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------- |
| **User value**            | **High**                                                     | Gives pflow an out-of-the-box “AI refactor / write tests / explain this file” action that no other single node covers. |
| **Complexity surface**    | Manageable *if narrowed to one-shot runs*                    | We avoid multistep chat loops, tool selection, etc.—headless mode already bundles an agent loop.                       |
| **Architectural match**   | Acceptable as *impure* node                                  | Writes to the working tree ⇒ violates purity, so no caching/retry; that’s OK—pflow allows impure nodes.                |
| **Security blast radius** | Contained with explicit path param & no default `git commit` | Same level of risk as a shell-exec node.                                                                               |
| **Maintenance load**      | Low                                                          | Headless CLI is stable; we treat it as a black-box subprocess.                                                         |

**Conclusion**  → **Yes**, include *one* `ClaudeCode` node in core, but keep the scope to *“single prompt over a local repo/path”*; nothing interactive, no streaming code actions.

---

## 2  Purity & Caching stance

* The node **must be flagged impure** (no `@flow_safe`), because:

  * It mutates the filesystem (or git index).
  * Its output depends on Anthropic’s stochastic policy (even with T=0 the model may change daily).

* Therefore:
  `max_retries`, `use_cache` **forbidden** by validation.

---

## 3  Node interface (natural keys & params)

| Channel              | Key                           | Type                                  | Notes                                                    |
| -------------------- | ----------------------------- | ------------------------------------- | -------------------------------------------------------- |
| **Input (shared)**   | `repo_path`                   | `str`                                 | Absolute or relative path that becomes working dir.      |
|                      | `prompt`                      | `str`                                 | The user’s request (e.g. “add pytest tests for foo.py”). |
| **Output (shared)**  | `cc_summary`                  | `str`                                 | Whatever headless mode prints in JSON `summary` field.   |
| **Params**           | `model` (`str`)               | default `"claude-3-opus"`             |                                                          |
|                      | `allowed_tools` (`list[str]`) | e.g. `["search_replace","run_tests"]` |                                                          |
|                      | `dry_run` (`bool`)            | `True` → only diff summary, no writes |                                                          |
|                      | `timeout` (`int`)             | seconds; default `300`                |                                                          |
| **Execution limits** | none (impure)                 |                                       |                                                          |

Minimal docstring excerpt (what the planner sees):

```
Reads:  shared["repo_path"], shared["prompt"]
Writes: shared["cc_summary"]
Params: model, allowed_tools, dry_run, timeout
Actions: "default", "error"
Purity: impure
```

---

## 4  Execution outline

```python
class ClaudeCode(Node):
    """Run Claude-Code headless agent once.

    Reads  : repo_path, prompt
    Writes : cc_summary
    Params : model="claude-3-opus", allowed_tools=[], dry_run=True, timeout=300
    """

    def prep(self, shared):
        return {
            "cwd": pathlib.Path(shared["repo_path"]).expanduser().resolve(),
            "prompt": shared["prompt"]
        }

    def exec(self, prep):
        cmd = [
            "claude",
            "-p", prep["prompt"],
            "--headless",
            "--model", self.params.get("model", "claude-3-opus"),
            "--output-format", "json"
        ]
        if self.params.get("allowed_tools"):
            cmd += ["--allowed-tools", ",".join(self.params["allowed_tools"])]
        if self.params.get("dry_run", True):
            cmd.append("--dry-run")

        try:
            out = subprocess.run(
                cmd,
                cwd=prep["cwd"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=self.params.get("timeout", 300),
                check=True,
            ).stdout
            return json.loads(out)
        except subprocess.CalledProcessError as e:
            return "error", e.stderr  # -> post() returns action "error"

    def post(self, shared, prep, exec_res):
        if isinstance(exec_res, tuple) and exec_res[0] == "error":
            shared["cc_summary"] = exec_res[1][:1_000]
            return "error"
        shared["cc_summary"] = exec_res.get("summary", "")
        return "default"
```

---

## 5  Planner & CLI behaviour

* **Autocomplete:** only five params—manageable.
* **Validation:**

  * fails if `repo_path` missing, path not a git repo, or headless CLI absent.
  * rejects `--use-cache` or `--max-retries` flags.
* **Typical CLI**

```bash
pflow claude-code \
      --repo-path ./myproj \
      --prompt "rename all foo functions to bar" \
      --allowed-tools search_replace,run_tests \
      --dry-run=false
```

The flow writer can chain diff review nodes or git-commit nodes afterwards.

---

## 6  Follow-up roadmap (post-MVP)

1. **`Embed` node** (pure, cacheable) → reuse `llm` embeddings or Anthropic’s `/embeddings`.
2. **`ToolCall` node** (pure) → general function-calling with any backend.
3. **`ClaudeCode` streaming/interactive** variant that supports multi-turn plans, gated behind an `impure-interactive` trust flag.

---

## 7  Risk checklist

| Risk                         | Mitigation                                                                           |
| ---------------------------- | ------------------------------------------------------------------------------------ |
| Accidental destructive edits | `dry_run=True` default, plus explicit param check.                                   |
| API change in claude-code    | Version pin (`>=0.3.0,<0.4.0`) embedded in node metadata; planner warns on mismatch. |
| Large stdout hangs           | `timeout` param; size cap in post().                                                 |
| Security (running tools)     | User must list `allowed_tools`.                                                      |
