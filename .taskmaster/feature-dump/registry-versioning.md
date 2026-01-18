# Node Namespacing & Versioning (Planned)

> **Status**: Future Feature (v2.0+)
> **Current Reality**: pflow uses simple node names only (`llm`, `shell`, `github-get-issue`).
> See [Architecture](../architecture.md#node-naming) for current node naming conventions.

This document describes the planned namespace and versioning system for pflow nodes.

---

## 1 - Identifier Syntax

```
<namespace>/<name>@<semver>
```

Examples:
`core/yt-transcript@1.0.0` `core/github-get-issue@1.0.0` `core/llm@1.0.0` `mcp/weather-get@0.3.2`

### 1.1 Namespace

- Lower-case, dot-separated: `[a-z0-9]+(\.[a-z0-9]+)*`
- Reserved roots: `core`, `mcp`
- Collision isolation: identical names in different namespaces may co-exist
- Example: `vesperance.data/extractor`

### 1.2 Version

- Semantic versioning `MAJOR.MINOR.PATCH`
- **MAJOR** bump - breaking interface change
- **MINOR** bump - additive, backward-compatible
- **PATCH** - bug-fix only
- CLI shorthand `@1` - latest `1.x.x`
- Pre-release versions (`1.0.0-beta`) not supported initially

---

## 2 - Version Resolution

Resolution occurs in **two phases** aligned with pflow's dual-mode operation.

### 2.1 Natural Language Path

1. **Planner Discovery**: Extract metadata from all installed node versions
2. **LLM Selection**: Thinking model chooses nodes AND appropriate versions
3. **IR Generation**: Planner embeds resolved versions in JSON IR
4. **Runtime**: Executes with pinned versions

### 2.2 CLI Path

1. **CLI Parsing**: Extract node references with optional version hints (`yt-transcript@1.0.0`)
2. **Resolution**: Resolve ambiguous versions using lockfile + compatibility policies
3. **Validation**: Ensure selected versions compatible with flow requirements
4. **IR Generation**: Generate IR with resolved versions

### 2.3 Resolution Policies

**Version Resolution Order**:

1. **Explicit version** (`@1.2.0`) - use exactly
2. **Major hint** (`@1`) - use highest `1.x.x`
3. **Version lockfile** - use pinned version
4. **Single version installed** - use it
5. **Multiple versions** - abort with disambiguation prompt

**No latest-by-default** - reproducibility requires explicit version management.

---

## 3 - File-system Layout

```
~/.pflow/nodes/               # User-installed nodes
site-packages/pflow/nodes/    # Package nodes
/usr/local/share/pflow/nodes/ # System registry
./nodes/                      # Flow-local overrides
```

**Search order**: flow-local - user - system - built-in

---

## 4 - Installation

```bash
pflow registry install my-node.py
```

Copies to `~/.pflow/nodes/<namespace>/<name>/<version>/` and triggers metadata extraction.

### 4.1 Metadata Generation

During installation, metadata is extracted:

```json
{
  "id": "yt-transcript",
  "namespace": "core",
  "version": "1.2.4",
  "description": "Fetches YouTube transcript from video URL",
  "inputs": ["url"],
  "outputs": ["transcript"],
  "params": {"language": "en"}
}
```

### 4.2 Validation

Installation validates:

- Node inherits from `pocketflow.Node`
- Natural interface documentation present
- Version number follows semver
- No conflicts with existing versions

---

## 5 - Lockfiles

### 5.1 Version Resolution Lockfile (`flow.versions.lock`)

**Purpose**: Pin node versions for deterministic execution

```json
{
  "yt-transcript": "1.0.0",
  "llm": "1.0.0",
  "write-file": "1.5.2"
}
```

### 5.2 Execution Lockfile (`flow.exec.lock`)

**Purpose**: Complete validated IR with signatures for reproducible execution

```json
{
  "ir_hash": "sha256:abc123...",
  "node_versions": {"yt-transcript": "1.0.0", "llm": "1.0.0"},
  "signature": "valid",
  "ir": { /* complete JSON IR */ }
}
```

---

## 6 - CLI Grammar with Versions

```
<flow> ::= <node> [--param value] {>> <node> [--param value]}*
<node> ::= [<namespace>/]<name>[@<semver>]
```

**Examples**:

```bash
# Explicit versioning
pflow yt-transcript@1.0.0 --url=X => llm@1.0.0 --prompt="Summarize"

# Major version hint
pflow yt-transcript@1 --url=X => llm --prompt="Summarize"
```

---

## 7 - Conflict Rules

- Installing an already-present `<namespace>/<name>/<version>` without `--force` aborts
- Different majors may coexist for compatibility
- Planner warns if flow references conflicting major versions

---

## 8 - Rationale

**Reproducibility**: Version pinning prevents silent breakage and ensures deterministic flow execution.

**Namespace Isolation**: Prevents naming conflicts while supporting distributed node development.

**Compatibility Management**: Explicit version management allows controlled evolution of node interfaces.

**CI/CD Support**: Lockfile-based approach ensures reliable automated testing and deployment.

---

## See Also

- [Architecture](../architecture.md#node-naming) - Current simple name-based node naming
- [Simple Nodes](../features/simple-nodes.md) - Node naming conventions
