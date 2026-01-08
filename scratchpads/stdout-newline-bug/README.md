# Bug Report: Shell stdout trailing newlines corrupt filenames

## Summary

When shell command output is used in `file_path` parameters via template variables like `${node.stdout}`, trailing newlines from shell output are **not stripped**, resulting in filenames containing literal newline characters (e.g., `myfile.md\n`).

This creates files that:
- Appear to exist in `find` and `ls` output
- Cannot be accessed via normal shell commands or file APIs
- Cause workflows to report "success" while producing unusable output

**Severity: High** - Silent data corruption with no error indication.

---

## The Problem

### Expected Behavior (per documentation)

From `pflow instructions create --part 2`:

> **What gets parsed:**
> - All JSON types: objects `{}`, arrays `[]`, numbers, booleans, strings, null
> - **Shell output with trailing `\n` is automatically stripped**
> - Plain text and invalid JSON gracefully stay as strings

### Actual Behavior

Trailing newlines are **only** stripped during JSON parsing for path traversal. Raw `stdout` access preserves the newline:

| Template Pattern | Newline Stripped? | Behavior |
|------------------|-------------------|----------|
| `${node.stdout}` | ❌ **No** | Raw output including `\n` |
| `${node.stdout.field}` | ✅ Yes | JSON parsed, newline stripped before parsing |
| `"prefix${node.stdout}suffix"` | ❌ **No** | Newline embedded in string |
| `{"key": "${node.stdout}"}` | ⚠️ Escaped | Becomes `\n` in JSON, jq converts back |

---

## Reproduction

### Minimal Test Case

**File: `test-newline-filename.json`**

```json
{
  "inputs": {},
  "nodes": [
    {
      "id": "generate-filename",
      "type": "shell",
      "params": {
        "command": "echo 'test-file'"
      }
    },
    {
      "id": "save-file",
      "type": "write-file",
      "params": {
        "file_path": "./${generate-filename.stdout}.txt",
        "content": "hello world"
      }
    }
  ],
  "edges": [
    {"from": "generate-filename", "to": "save-file"}
  ]
}
```

**Run:**
```bash
pflow test-newline-filename.json
```

**Result:**
```
✓ Workflow completed in 0.444s
✓ save-file (0ms)
```

**Actual file created:**
```python
>>> import os
>>> [repr(f) for f in os.listdir('.') if 'test-file' in f]
["'test-file\\n.txt'"]  # Literal newline in filename!
```

**Symptoms:**
```bash
$ cat test-file.txt
cat: test-file.txt: No such file or directory

$ ls -la | grep test
-rw-r--r--  1 user  staff  11 Jan  8 12:48 test-file
.txt                                        # <-- newline visible here
```

---

## Root Cause Analysis

### Why This Happens

1. **Shell commands always output trailing newlines** - This is standard Unix behavior. `echo 'foo'` outputs `foo\n`.

2. **pflow's template resolution passes stdout as-is** - When resolving `${node.stdout}`, pflow returns the raw string including the trailing `\n`.

3. **Newline stripping only happens during JSON parsing** - The documentation's claim about "automatic stripping" only applies when pflow parses stdout as JSON (for path traversal like `${node.stdout.field}`).

4. **`write-file` accepts the corrupted path** - The node doesn't validate or sanitize the `file_path` parameter.

### Hex Dump Evidence

```json
{
  "id": "check-value",
  "type": "shell",
  "params": {
    "command": "printf '%s' '${generate-name.stdout}' | xxd"
  }
}
```

**Output:**
```
00000000: 6d79 6669 6c65 0a                        myfile.
                    ^^-- 0x0a = newline character
```

### JSON Context Escaping (Different Bug?)

When stdout is used in an inline object:

```json
{"stdin": {"name": "${generate-name.stdout}"}}
```

The newline is **escaped** to `\n` (two characters: `0x5c 0x6e`):

```
00000000: 7b22 6e61 6d65 223a 2022 6d79 6669 6c65  {"name": "myfile
00000010: 5c6e 227d                                \n"}
```

When jq processes this, it converts `\n` back to a real newline, so the problem persists.

---

## Impact Assessment

### Why This Is Severe

1. **Silent Failure** - Workflow reports success, no errors or warnings
2. **Invisible Corruption** - Newlines look like line breaks in terminal output
3. **File Inaccessibility** - Created files can't be opened by normal tools
4. **Debugging Difficulty** - Requires `repr()` or hex dump to detect
5. **Common Pattern** - Dynamic filenames from shell output is a standard use case

### Real-World Example

Building a `webpage-to-markdown` workflow:

```json
{
  "id": "get-date",
  "type": "shell",
  "params": {"command": "date +%Y-%m-%d"}
},
{
  "id": "save-file",
  "type": "write-file",
  "params": {
    "file_path": "./${get-date.stdout}-article.md",
    "content": "${markdown}"
  }
}
```

**Expected:** `./2026-01-08-article.md`
**Actual:** `./2026-01-08\n-article.md` (corrupted, inaccessible)

---

## Proposed Solutions

### Option 1: Auto-strip for `file_path` parameters (Recommended)

The `write-file` node should strip leading/trailing whitespace from `file_path`:

```python
file_path = params["file_path"].strip()
```

**Pros:** Targeted fix, no breaking changes, handles the most dangerous case
**Cons:** Doesn't fix other contexts

### Option 2: Strip trailing newlines from all shell stdout

When capturing shell output, strip trailing newlines:

```python
stdout = process.stdout.rstrip('\n')
```

**Pros:** Fixes all cases, matches user expectation
**Cons:** Could break edge cases relying on preserved newlines (unlikely)

### Option 3: Add explicit trim syntax

Add template modifier syntax:

```
${node.stdout}        # raw
${node.stdout|trim}   # stripped
${node.stdout|strip}  # stripped
```

**Pros:** Explicit, no magic, user control
**Cons:** Requires users to remember, doesn't fix existing workflows

### Option 4: Update documentation only

Clarify that stripping only happens during JSON parsing, and users must handle raw stdout manually.

**Pros:** No code changes
**Cons:** Poor UX, users will keep hitting this issue

---

## Current Workarounds

### Workaround 1: Use `tr -d '\n'`

```json
{"command": "date +%Y-%m-%d | tr -d '\\n'"}
```

**Problem:** Easy to forget, verbose, must apply to every shell command.

### Workaround 2: Use `jq -j` instead of `jq -r`

```json
{"command": "echo '{\"x\":1}' | jq -j '.x'"}
```

**Problem:** Only works for jq, doesn't help with other commands.

### Workaround 3: Output JSON and use path traversal

```json
// Instead of:
{"command": "echo 'myfile'"}
{"file_path": "./${node.stdout}.txt"}

// Use:
{"command": "echo '{\"name\": \"myfile\"}'"}
{"file_path": "./${node.stdout.name}.txt"}
```

**Problem:** Verbose, unnatural, requires restructuring workflows.

---

## Test Files

See the following files in this directory for reproduction:

- `test-raw-stdout.json` - Shows newline in raw stdout
- `test-json-path.json` - Shows newline stripped via JSON path
- `test-filename-corruption.json` - Demonstrates corrupted filename
- `test-inline-object.json` - Shows escaping behavior in objects

---

## Appendix: Discovery Timeline

This bug was discovered while building a `webpage-to-markdown` workflow:

1. Workflow completed "successfully"
2. Output file couldn't be accessed via `cat`, `Read` tool, or file APIs
3. `find` showed the file existed
4. `ls -la` showed weird line break in output
5. Python `repr()` revealed `'filename.md\n'`
6. Required 15+ minutes of debugging to identify

The fix required adding `tr -d '\n'` to three separate shell commands and changing `jq -r` to `jq -rj` - none of which is intuitive or documented.
