# Node Discovery, Namespacing & Versioning

> **Version**: MVP
> **MVP Status**: ✅ Included
> For complete MVP boundaries, see [MVP Scope](../features/mvp-scope.md)

---

## 1 · Identifier Syntax

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

### 1.2 Name

- Lower-case, hyphens allowed: `[a-z0-9-]+`
- Should match the Python file stem
- Consistent with pflow's kebab-case convention
- **Simple node naming**: `platform-action` (e.g., `github-get-issue`, `slack-send-message`)
- **General nodes**: single purpose name (e.g., `llm`, `read-file`, `write-file`)

### 1.2.1 Simple Node Naming Conventions

**Platform Nodes** follow `platform-action` pattern:

| Platform | Examples | Purpose |
|----------|----------|---------|
| **GitHub** | `github-get-issue`, `github-create-pr`, `github-list-prs` | Individual GitHub operations |
| **Slack** | `slack-send-message`, `slack-get-channel`, `slack-upload-file` | Individual Slack operations |
| **YouTube** | `yt-transcript`, `yt-get-metadata`, `yt-download-audio` | Individual YouTube operations |

**General Nodes** use single-purpose names:

| Node | Purpose | Interface |
|------|---------|-----------|
| **`llm`** | General text processing | `prompt` → `response` |
| **`read-file`** | File input | `path` → `content` |
| **`write-file`** | File output | `content` + `path` → file |
| **`transform-json`** | JSON manipulation | `data` + `transform` → `result` |

**Naming Benefits**:
- **Predictable**: Users can guess node names (`github-get-issue`)
- **Discoverable**: `pflow registry search github` finds all GitHub nodes
- **Composable**: Clear single-purpose functions
- **Future CLI Grouping**: Naturally maps to `pflow github get-issue` syntax in v2.0

### 1.3 Version

- Semantic versioning `MAJOR.MINOR.PATCH`
- **MAJOR** bump ⇢ breaking interface change
- **MINOR** bump ⇢ additive, backward-compatible
- **PATCH** ⇢ bug-fix only
- CLI shorthand `@1` ⇢ latest `1.x.x`
- Pre-release versions (`1.0.0-beta`) not supported in MVP

---

## 2 · Version Resolution in Planner Pipeline

Resolution occurs in **two phases** aligned with pflow's dual-mode operation, integrated into the planner → compiler → runtime pipeline.

### 2.1 Natural Language Path

1. **Planner Discovery**: Extract metadata from all installed node versions during registry scan
2. **LLM Selection**: Thinking model chooses nodes AND appropriate versions from complete registry
3. **IR Generation**: Planner embeds resolved versions in JSON IR
4. **Runtime**: Executes with pinned versions from validated IR

### 2.2 CLI Pipe Path

1. **CLI Parsing**: Extract node references with optional version hints (`yt-transcript@1.0.0`)
2. **Planner Resolution**: Resolve ambiguous versions using version lockfile + compatibility policies
3. **Validation**: Ensure selected versions compatible with flow requirements and shared store interfaces
4. **IR Generation**: Generate IR with resolved versions for compiler handoff

### 2.3 Resolution Policies

**Version Resolution Order**:

1. **Explicit version** (`@1.2.0`) → use exactly
2. **Major hint** (`@1`) → use highest `1.x.x`
3. **Version lockfile** → use pinned version
4. **Single version installed** → use it
5. **Multiple versions** → abort with disambiguation prompt

**No latest-by-default** - reproducibility requires explicit version management.

---

## 3 · File-system Layout

### MVP Scope
```
src/pflow/nodes/              # Platform nodes (MVP focus)
├── llm.py
├── read_file.py
├── write_file.py
└── github_get_issue.py

~/.pflow/registry.json        # Persistent registry storage
```

### Future Extensions (v2.0+)
```
~/.pflow/nodes/               # User-installed nodes
site-packages/pflow/nodes/    # Package nodes
/usr/local/share/pflow/nodes/ # System registry
./nodes/                      # Flow-local overrides
```

**Search order (v2.0+)**: flow-local → user → system → built-in

**Registry Integration**: Planner scans these locations during metadata extraction to build unified registry for LLM selection and validation.

---

## 4 · Installation & Registry Integration

### 4.1 Manual Node Installation

```bash
pflow registry install my-node.py
```

Copies to `~/.pflow/nodes/<namespace>/<name>/<version>/` and triggers metadata extraction for planner integration.

### 4.2 Registry Integration

**Unified Registry**: All nodes (manual, MCP, system) appear in single registry system used by planner for:

- LLM metadata-driven selection
- Version compatibility validation
- Natural language → node mapping

> **See also**: [MCP Server Integration](../features/mcp-integration.md) for MCP wrapper node installation

### 4.3 Metadata Generation for Planner

During installation, planner-compatible metadata is extracted:

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

### 4.4 Version Validation

Installation validates:

- Node inherits from `pocketflow.BaseNode` (or `pocketflow.Node`)
- Natural interface documentation present
- Version number follows semver
- No conflicts with existing versions

---

## 5 · Lockfile Types and Integration

### 5.1 Version Resolution Lockfile (`flow.versions.lock`)

**Purpose**: Pin node versions for deterministic planning
**Generated by**: Planner during initial version resolution
**Content**: Simple version mapping

```json
{
  "yt-transcript": "1.0.0",
  "llm": "1.0.0",
  "write-file": "1.5.2"
}
```

**Used by**: Planner for consistent re-resolution across planning sessions

### 5.2 Execution Lockfile (`flow.exec.lock`)

**Purpose**: Complete validated IR with signatures for reproducible execution
**Generated by**: Planner after full validation pipeline
**Content**: Complete JSON IR + metadata

```json
{
  "ir_hash": "sha256:abc123...",
  "node_versions": {"yt-transcript": "1.0.0", "llm": "1.0.0"},
  "signature": "valid",
  "ir": { /* complete JSON IR */ }
}
```

**Used by**: Runtime for execution with integrity verification

### 5.3 Relationship

Version lockfile feeds into execution lockfile generation. Version changes trigger re-planning through planner's validation pipeline.

---

## 6 · CLI Grammar & Planner Integration

> **Integration Note**: Node versioning integrates with pflow's "Type flags; engine decides" CLI resolution. Version hints are validated by planner, not resolved independently.

```
<flow> ::= <node> [--param value] {>> <node> [--param value]}*
<node> ::= [<namespace>/]<name>[@<semver>]
```

**Examples with Version Integration**:

```bash
# Simple flow (planner resolves versions using lockfile)
pflow yt-transcript --url=X => llm --prompt="Summarize this transcript"

# Explicit versioning when needed
pflow yt-transcript@1.0.0 --url=X => llm@1.0.0 --prompt="Summarize"

# Mixed shorthand (planner validates compatibility)
pflow yt-transcript --url=X => llm@1 --prompt="Summarize"

# Natural language (planner selects appropriate versions)
pflow "summarize this youtube video"
```

**Resolution through Planner**: All CLI pipes are validated through planner's dual-mode operation, ensuring version compatibility and interface validation. Users can override version selection via `@version` syntax, but for major version changes the planner might need to validate compatibility and generate appropriate proxy mappings and make updates to the flow.

---

## 7 · Registry Commands

```bash
pflow registry list              # table of installed nodes with versions
pflow registry search llm        # fuzzy search across all registries
pflow registry describe llm@1.0.0        # detailed node information
pflow registry validate --all    # validate all installed nodes
pflow registry refresh           # re-scan filesystem, update metadata
```

**Planner Integration**: Registry commands directly support planner's metadata extraction and LLM selection requirements.

---

## 8 · Conflict Rules & Planner Validation

### 8.1 Installation Conflicts

- Installing an already-present `<namespace>/<name>/<version>` without `--force` aborts
- Different majors may coexist for compatibility
- Planner warns if flow references conflicting major versions

### 8.2 Planner Version Validation

**During LLM Selection**:

- Thinking model selects from all available versions in registry
- Interface compatibility checked between selected versions
- Automatic mapping generation when interfaces misalign

**During CLI Validation**:

- Version hints validated against installed versions
- Interface compatibility enforced between pipeline stages
- Missing versions trigger clear error messages with suggestions

### 8.3 Error Reporting

Version conflicts reported through planner's validation framework with actionable resolution steps.

---

## 9 · Architecture Integration Benefits

Versioning enables robust integration with pflow's core architectural principles:

**LLM Selection**: Thinking models can choose between different node versions based on:

- Feature requirements (newer versions with enhanced capabilities)
- Stability preferences (proven older versions for production)
- Interface compatibility (versions that work well together)

**Metadata-Driven Planning**: Version-aware metadata allows planner to:

- Select optimal simple node combinations for user requirements
- Generate appropriate proxy mappings for version compatibility
- Validate interface alignment across different node versions
- **LLM node preference**: Default to general LLM node for text processing tasks

**Flow Reproducibility**: Version lockfiles ensure:

- Deterministic flow execution across environments
- Reliable CI/CD pipeline behavior
- Audit trails for flow evolution over time

**Framework Integration**: Seamless operation with pocketflow's patterns:

- Natural interface preservation across versions
- Proxy mapping compatibility for marketplace flows
- Simple node composition patterns

---

## 10 · Metadata Extraction for Planner

### 10.1 Planner Discovery Process

1. **Filesystem Scan**: Discover all installed node versions from registry locations
2. **Metadata Extraction**: Generate planner-compatible metadata from each version's docstring and annotations
3. **Registry Construction**: Build in-memory registry for LLM selection and validation
4. **Version Filtering**: Present appropriate versions to thinking model based on context

### 10.2 Metadata Format Alignment

**Conversion Process**: Transform namespace/version info to planner metadata schema:

```python
# From versioned node file
class YTTranscriptNode(BaseNode):  # or Node
    """Fetches YouTube transcript.
    Interface:
    - Reads: shared["url"]: str  # YouTube video URL
    - Writes: shared["transcript"]: str  # Extracted transcript text
    """

# To planner metadata
{
  "id": "yt-transcript",
  "namespace": "core",
  "version": "1.0.0",
  "description": "Fetches YouTube transcript",
  "inputs": ["url"],
  "outputs": ["transcript"],
  "natural_interface": True
}
```

**Version Compatibility**: Metadata includes interface change indicators to support planner's compatibility validation.

---

## 11 · Pipeline Integration Examples

### 11.1 Natural Language Path

```
User: "summarize this youtube video"
  ↓
Planner Discovery: Scans all yt-transcript versions (1.0.0, 1.2.0, 2.0.0)
  ↓
LLM Selection: Chooses yt-transcript@1.2.0 + llm@1.0.0 (simple node preference)
  ↓
IR Generation: {"nodes": [{"id": "yt-transcript", "version": "1.2.0"}, {"id": "llm", "version": "1.0.0"}]}
  ↓
Runtime: Executes with pinned versions
```

### 11.2 CLI Pipe Path

```
User: pflow yt-transcript@1 --url=X => llm --prompt="Summarize this"
  ↓
CLI Parsing: Extract version hint "@1" for yt-transcript
  ↓
Planner Resolution: Resolve "@1" to "1.2.0" (highest 1.x.x), validate with llm default
  ↓
Validation: Check interface compatibility between yt-transcript@1.2.0 → llm@1.0.0
  ↓
IR Generation: Complete IR with resolved versions
  ↓
Runtime: Direct execution (no user verification needed for CLI path)
```

### 11.3 Version Lockfile Integration

```
Existing flow.versions.lock: {"yt-transcript": "1.0.0", "llm": "1.0.0"}
  ↓
User: pflow yt-transcript --url=X => llm --prompt="Summarize"
  ↓
Planner: Uses locked versions for consistency
  ↓
Validation: Ensures locked versions still compatible
  ↓
Execution: Runs with proven version combination
```

---

## 12 · Rationale

**Reproducibility**: Version pinning prevents silent breakage and ensures deterministic flow execution across environments and time.

**Planner Integration**: Versioned metadata enables intelligent LLM selection and validation, supporting both simple flows and complex orchestration scenarios.

**Namespace Isolation**: Prevents naming conflicts while supporting distributed node development and marketplace scenarios.

**Compatibility Management**: Explicit version management allows controlled evolution of node interfaces while maintaining backward compatibility.

**CI/CD Support**: Lockfile-based approach ensures reliable automated testing and deployment pipelines.

**Agent Compatibility**: Deterministic version resolution supports AI-generated flows that remain stable and auditable over time.

---

*End of document*

## See Also

- **Architecture**: [MVP Scope](../features/mvp-scope.md) - Clear boundaries for MVP registry features
- **Patterns**: [Simple Nodes](../features/simple-nodes.md) - Node design philosophy and naming conventions
- **Components**: [JSON Schemas](./schemas.md) - How registry metadata integrates with IR schemas
- **Components**: [Planner](../features/planner.md) - How planner uses registry for node discovery
- **Implementation**: [Metadata Extraction](../implementation-details/metadata-extraction.md) - Node metadata extraction process
- **Future Features**: [MCP Integration](../features/mcp-integration.md) - How MCP nodes integrate with registry (v2.0)
