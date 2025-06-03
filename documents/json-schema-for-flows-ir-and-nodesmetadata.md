# JSON Schema Governance: Flows & Node Metadata

This document defines JSON schema governance for two key pflow artifacts:

1. **Flow IR**: JSON representation of executable flows (orchestration, mappings, execution)
2. **Node Metadata**: JSON interface definitions extracted from node docstrings (inputs, outputs, params)

Both schemas work together to enable metadata-driven flow planning and validation.

> **Architecture Context**: See [Node Metadata Strategy](./node-metadata.md) for extraction details and [Shared Store Pattern](./shared-store-node-proxy-architecture.md) for interface concepts.

---

## 1 · Document Envelope (Flow IR)

```json
{
  "$schema": "https://pflow.dev/schemas/flow-0.1.json",
  "ir_version": "0.1.0",
  "metadata": {
    "created": "2025-01-01T12:00:00Z",
    "description": "YouTube video summary pipeline",
    "planner_version": "1.0.0",
    "locked_nodes": {
      "core/yt-transcript": "1.0.0",
      "core/summarize-text": "2.1.0"
    }
  },
  "nodes": [...],
  "edges": [...],
  "mappings": {...}
}
```

**Field Requirements:**

- `$schema` dereferences a JSON-Schema; hard error if not recognised
- `ir_version` uses semantic versioning; unknown higher major → refuse to run
- `metadata.locked_nodes` mirrors [version lockfile](./node-discovery-namespacing-and-versioning.md) for deterministic execution
- `metadata.planner_version` tracks planner that generated IR for provenance

---

## 2 · Node Metadata Schema

Node metadata is extracted from Python docstrings and stored as JSON for fast planner access.

### 2.1 Node Metadata Structure

```json
{
  "node": {
    "id": "yt-transcript",
    "namespace": "core",
    "version": "1.0.0",
    "python_file": "nodes/core/yt-transcript/1.0.0/node.py",
    "class_name": "YTTranscript"
  },
  "interface": {
    "inputs": {
      "url": {
        "type": "str",
        "required": true,
        "description": "YouTube video URL"
      }
    },
    "outputs": {
      "transcript": {
        "type": "str", 
        "description": "Extracted transcript text"
      }
    },
    "params": {
      "language": {
        "type": "str",
        "default": "en",
        "optional": true,
        "description": "Transcript language code"
      }
    },
    "actions": ["default", "video_unavailable"]
  },
  "documentation": {
    "description": "Fetches YouTube transcript from video URL",
    "long_description": "Downloads and extracts transcript text..."
  },
  "extraction": {
    "source_hash": "sha256:abc123...",
    "extracted_at": "2025-01-01T12:00:00Z",
    "extractor_version": "1.0.0"
  }
}
```

### 2.2 Interface Declaration Rules

- **Natural Interfaces**: Inputs/outputs use `shared["key"]` patterns from docstrings
- **Params Structure**: Maps to `self.params.get("key", default)` usage in code  
- **Action Enumeration**: Lists all possible return values from node `post()` method
- **Type Information**: Basic types (str, int, float, bool, dict, list, any)

### 2.3 Extraction and Validation

- **Source**: Structured docstrings using Interface sections (see [Node Metadata](./node-metadata.md))
- **Validation**: Extracted metadata must match actual code behavior
- **Staleness**: Source file hash tracks when re-extraction needed
- **Registry**: Metadata stored alongside Python files in registry structure

---

## 3 · Node Object (Flow IR)

Flow IR references nodes by registry ID, with metadata resolved during validation.

```json
{
  "id": "fetch-transcript", 
  "registry_id": "core/yt-transcript",
  "version": "1.0.0",
  "params": {
    "language": "en",
    "timeout": 30
  },
  "execution": {
    "max_retries": 2,
    "use_cache": true,
    "wait": 1.0
  }
}
```

**Field Specifications:**

| Field | Rules | Notes |
|---|---|---|
| `id` | Unique token, `[A-Za-z0-9_-]{1,64}` | Flow-scoped identifier |
| `registry_id` | Namespace/name format | References node in registry for metadata resolution |
| `version` | Semantic version string | Resolved during [planner validation](./planner-responsibility-functionality-spec.md) |
| `params` | Arbitrary JSON for node behavior | **Never** contains shared store keys or execution directives |
| `execution.max_retries` | Integer ≥ 0, only for `@flow_safe` nodes | See [Runtime Behavior](./runtime-behavior-specification.md) |
| `execution.use_cache` | Boolean, only for `@flow_safe` nodes | Cache eligibility enforced at runtime |
| `execution.wait` | Float ≥ 0, retry delay in seconds | Used by [pocketflow framework](../pocketflow/__init__.py) |

**Interface Resolution:**

- Planner resolves inputs/outputs from node metadata during validation
- Registry metadata validates params and execution config eligibility
- Node interfaces declared through docstring metadata, not IR params

> **Natural Interface Pattern**: See [shared store specification](./shared-store-node-proxy-architecture.md) for natural interface concepts

---

## 4 · Edge Object

**Basic Transitions:**

```json
{"from": "fetch-transcript", "to": "create-summary"}
```

**Action-Based Transitions:**

```json
[
  {"from": "validator", "to": "processor"},
  {"from": "validator", "to": "error-handler", "action": "fail"},
  {"from": "processor", "to": "validator", "action": "continue"},
  {"from": "processor", "to": "finalizer"}
]
```

**Rules:**

- DAG must be acyclic; validator enforces
- Default transitions omit `"action"` field
- Named actions enable conditional flow control
- All declared actions must have defined transitions

> **Flow Structure**: See [planner specification](./planner-responsibility-functionality-spec.md) for action-based transition generation

---

## 5 · Proxy Mapping Schema

**Optional Flow-Level Mappings:**

```json
{
  "mappings": {
    "summarize-text": {
      "input_mappings": {"text": "raw_transcript"},
      "output_mappings": {"summary": "article_summary"}  
    },
    "store-result": {
      "input_mappings": {"content": "article_summary"}
    }
  }
}
```

**Mapping Purpose:**

- Enable complex flow routing while preserving natural node interfaces
- Generated by planner for marketplace compatibility scenarios
- Completely optional - nodes use direct shared store access when no mappings defined
- Transparent to node code via `NodeAwareSharedStore` proxy

> **Architecture Integration**: See [shared store pattern](./shared-store-node-proxy-architecture.md) for proxy implementation details

---

## 6 · Side-Effect Model

Node purity status determined by `@flow_safe` decorator (see [Runtime Behavior Specification](./runtime-behavior-specification.md)). IR validation enforces purity constraints:

- Only `@flow_safe` nodes may specify `max_retries > 0`
- Only `@flow_safe` nodes may specify `use_cache: true`
- Purity status read from node manifest; IR does not repeat it
- Validation occurs during [planner pipeline](./planner-responsibility-functionality-spec.md)

---

## 7 · Failure Semantics

**Retry Configuration:**

- Absence of `execution.max_retries` → `0` retries (fail fast)
- Flow aborts on first un-retried failure with status `FAILED`
- Retry configuration integrates with [pocketflow framework](../pocketflow/__init__.py) patterns

**Failure Logging:**

- Engine records `failure_trace` array in run log
- IR itself remains immutable during execution
- Complete failure context preserved for debugging

> **Runtime Integration**: See [runtime specification](./runtime-behavior-specification.md) for complete failure handling

---

## 8 · Caching Contract

IR enables caching through `execution.use_cache` field with validation rules:

- Only `@flow_safe` nodes may specify `use_cache: true`
- Cache eligibility determined at runtime by multiple factors
- IR validation occurs during planner pipeline
- Cache bypass (`--reset-cache`) is runtime flag, does not mutate IR

> **Implementation Details**: See [Runtime Behavior Specification](./runtime-behavior-specification.md) for cache key computation and storage

---

## 9 · Enhanced Validation Pipeline

### 9.1 Node Metadata Validation (Registry Phase)

1. **Extraction Validation**: Docstring → metadata consistency
2. **Code Analysis**: Static analysis of actual shared["key"] usage  
3. **Interface Verification**: Documented vs actual interface matching
4. **Staleness Check**: Source hash validation for re-extraction needs

### 9.2 Flow IR Validation (Composition Phase)

1. **JSON Structure**: Parse → strict no-comments
2. **Schema Validation**: `$schema` + `ir_version` compatibility check  
3. **Registry Resolution**: All referenced nodes exist in [registry](./node-discovery-namespacing-and-versioning.md)
4. **Graph Analysis**: Cycle detection including action-based transition paths
5. **Interface Compatibility**: Input/output key alignment between connected nodes
6. **Proxy Mapping**: Validation of mapping definitions when present
7. **Purity Constraints**: `@flow_safe` requirement for `max_retries` and `use_cache`
8. **Framework Compatibility**: [pocketflow](../pocketflow/__init__.py) execution pattern validation

### 9.3 Cross-Reference Validation

- **Params Validation**: Flow IR params match node metadata param definitions
- **Interface Alignment**: Connected nodes have compatible input/output keys
- **Mapping Necessity**: Detect when proxy mappings required vs optional
- **Action Coverage**: All node actions have defined transitions

Flow failing any step is rejected before execution with comprehensive diagnostics.

> **Planner Integration**: Validation occurs during [planner responsibility phases](./planner-responsibility-functionality-spec.md)

---

## 10 · Evolution Rules

**Version Compatibility:**

- **Minor IR additions**: New optional fields allowed; unknown optional fields ignored but preserved
- **Major IR bump**: Engine refuses to run; user must upgrade `pflow`  
- **Deprecation Process**: Features flagged two minor versions before removal

**Extension Compatibility:**

- Forward compatibility for new mapping types
- Action-based transition extensions
- Execution configuration additions

**Node Metadata Schema Versioning:**

- **metadata_schema_version**: Track metadata format evolution
- **Backward Compatibility**: Older metadata formats supported during transitions  
- **Migration Tools**: Automatic upgrade utilities for schema changes

---

## 11 · Extension Points

**Planned Extensions:**

- `execution.timeout` for node execution limits
- `constraints` object for resource caps (CPU, memory, disk)
- `annotations` free-form metadata for GUI/tooling integration
- Advanced mapping patterns for nested shared store keys
- Conditional execution based on shared store state

**Node Metadata Extensions:**

- Examples with shared store states and expected outputs
- Performance characteristics and resource usage
- Error handling patterns and recovery strategies
- Compatibility matrices between node versions

**Extension Principles:**

- Maintain backward compatibility
- Optional fields with sensible defaults
- Clear validation rules for new features

---

## 12 · Registry Integration Commands

### 12.1 Node Metadata Management

```bash
# Extract metadata from Python file  
pflow registry extract node.py --output metadata.json

# Validate code/metadata consistency
pflow registry validate node.py

# Install node with automatic metadata extraction
pflow registry install node.py --namespace core

# List nodes with interface information
pflow registry list --format table
```

### 12.2 Flow Validation with Metadata

```bash
# Validate flow IR against registry
pflow validate flow.ir.json

# Check interface compatibility 
pflow validate flow.ir.json --check-interfaces

# Generate missing proxy mappings
pflow validate flow.ir.json --suggest-mappings
```

### 12.3 Registry Structure

```
~/.pflow/registry/
├─ nodes/
│   ├─ core/yt-transcript/1.0.0/
│   │   ├─ node.py           # Source code
│   │   └─ metadata.json     # Extracted interface
│   └─ custom/my-node/1.0.0/
│       ├─ node.py
│       └─ metadata.json
├─ index.json               # Fast lookup index
└─ schemas/
    ├─ node-metadata.schema.json
    └─ flow-ir.schema.json
```

---

## 13 · Performance Architecture

### 13.1 Registry Loading Strategy

Fast planner context generation using pre-extracted metadata:

```python
def build_llm_context(available_nodes: List[str]) -> str:
    """Load pre-extracted metadata for instant LLM context."""
    metadata_files = [f"registry/nodes/{node}/metadata.json" 
                     for node in available_nodes]
    
    # Instant JSON loading vs Python parsing
    interfaces = [json.load(open(f)) for f in metadata_files]
    return format_for_llm(interfaces)
```

### 13.2 Validation Caching

- **Registry Index**: Fast node lookup without filesystem scanning
- **Interface Cache**: Pre-validated interface compatibility matrix
- **Staleness Detection**: Hash-based change detection for selective re-extraction

### 13.3 CLI Performance

- **Registry Commands**: Instant metadata access for rich CLI experience
- **Flow Validation**: Fast interface checking without Python imports
- **Search Operations**: JSON-based filtering and querying

---

## 14 · Complete Example Flow

```json
{
  "$schema": "https://pflow.dev/schemas/flow-0.1.json", 
  "ir_version": "0.1.0",
  "metadata": {
    "created": "2025-01-01T12:00:00Z",
    "description": "YouTube video summary with error handling",
    "planner_version": "1.0.0",
    "locked_nodes": {
      "core/yt-transcript": "1.0.0",
      "core/summarize-text": "2.1.0",
      "core/error-handler": "1.0.0"
    }
  },
  "nodes": [
    {
      "id": "fetch-transcript",
      "registry_id": "core/yt-transcript",
      "version": "1.0.0", 
      "params": {"language": "en"},
      "execution": {"max_retries": 2, "wait": 1.0}
    },
    {
      "id": "create-summary",
      "registry_id": "core/summarize-text",
      "version": "2.1.0",
      "params": {"temperature": 0.7, "max_tokens": 150},
      "execution": {"use_cache": true}
    },
    {
      "id": "handle-error",
      "registry_id": "core/error-handler",
      "version": "1.0.0",
      "params": {"fallback_message": "Video unavailable"}
    }
  ],
  "edges": [
    {"from": "fetch-transcript", "to": "create-summary"},
    {"from": "fetch-transcript", "to": "handle-error", "action": "video_unavailable"}
  ],
  "mappings": {
    "create-summary": {
      "input_mappings": {"text": "transcript"}
    }
  }
}
```

**Example Features:**

- Registry-based node references with metadata resolution
- Natural interface compatibility (`shared["transcript"]` → `shared["text"]` via mapping)
- Action-based error handling (`video_unavailable` action)
- Proper execution configuration for retry and caching
- Version locking for reproducibility

---

## 15 · Integration References

This dual schema system integrates with pflow's complete architecture:

- **Shared Store Pattern**: [Natural interfaces and proxy mappings](./shared-store-node-proxy-architecture.md)
- **Planner Validation**: [Dual-mode operation and IR generation](./planner-responsibility-functionality-spec.md)  
- **CLI Resolution**: [Parameter injection and override rules](./shared-store-cli-runtime-specification.md)
- **Node Registry**: [Versioning and discovery](./node-discovery-namespacing-and-versioning.md)
- **Runtime Behavior**: [Caching, retry, and side-effect management](./runtime-behavior-specification.md)
- **Framework Integration**: [pocketflow execution patterns](../pocketflow/__init__.py)
- **Node Metadata Strategy**: [Extraction and documentation](./node-metadata.md)

---

This governance document ensures both Flow IR and Node Metadata schemas align with pflow's established architecture while providing focused schema definitions for JSON validation, evolution, and metadata-driven planning capabilities.
