# JSON Schema Governance: Flows & Node Metadata

This document defines JSON schema governance for two key pflow artifacts:

1. **Flow IR**: JSON representation of executable flows (orchestration, mappings, execution)
2. **Node Metadata**: JSON interface definitions extracted from node docstrings (inputs, outputs, params)

Both schemas work together to enable metadata-driven flow planning and validation.

> **Architecture Context**: See [Node Metadata Strategy](../implementation-details/metadata-extraction.md) for extraction details and [Shared Store Pattern](./shared-store.md) for interface concepts.

---

## Document Envelope Flow IR

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
      "core/llm": "1.0.0"
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
- `metadata.locked_nodes` mirrors [version lockfile](./registry.md) for deterministic execution
- `metadata.planner_version` tracks planner that generated IR for provenance

> **Example**: See [examples/core/minimal.json](../../examples/core/minimal.json) for the simplest valid Flow IR - a single node with no edges or metadata.

---

## Node Metadata Schema

Node metadata is extracted from Python docstrings and stored as JSON for fast planner access.

### 2.1 Node Metadata Structure

```json
{
  "node": {
    "id": "yt-transcript",
    "module": "pflow.nodes.yt_transcript",
    "class_name": "YTTranscriptNode",
    "name": "yt-transcript"  // from class.name or kebab-case conversion
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

**LLM Node Example (General-purpose text processing):**

```json
{
  "node": {
    "id": "llm",
    "namespace": "core",
    "version": "1.0.0",
    "python_file": "nodes/core/llm/1.0.0/node.py",
    "class_name": "LLMNode"
  },
  "interface": {
    "inputs": {
      "prompt": {
        "type": "str",
        "description": "Prompt text to send to LLM"
      }
    },
    "outputs": {
      "response": {
        "type": "str",
        "description": "Generated response from LLM"
      }
    },
    "params": {
      "model": {
        "type": "str",
        "default": "gpt-4",
        "optional": true,
        "description": "LLM model to use"
      },
      "temperature": {
        "type": "float",
        "default": 0.7,
        "optional": true,
        "description": "Sampling temperature"
      }
    }
  },
  "documentation": {
    "description": "General-purpose LLM text processing",
    "long_description": "Processes any text prompt using configurable LLM models. Smart exception to simple node philosophy - prevents proliferation of specific prompt nodes."
  },
  "extraction": {
    "source_hash": "sha256:def456...",
    "extracted_at": "2025-01-01T12:00:00Z",
    "extractor_version": "1.0.0"
  }
}
```

### 2.2 Interface Declaration Rules

- **Natural Interfaces**: Inputs/outputs use `shared["key"]` patterns from docstrings
- **Params Structure**: Maps to `self.params.get("key", default)` usage in code
- **Type Information**: Basic types (str, int, float, bool, dict, list, any)

### 2.2.1 Type Information

Node metadata includes type information for validation:

- `inputs.*.type`: Expected input types (str, int, float, bool, dict, list, any)
- `outputs.*.type`: Produced output types
- `required` field: Distinguishes mandatory vs optional inputs

**Example:**
```json
{
  "interface": {
    "inputs": {
      "text": {"type": "str", "required": true},
      "format": {"type": "str", "required": false}
    },
    "outputs": {
      "summary": {"type": "str"}
    }
  }
}
```

### 2.3 Shared Key Declaration Requirements

All nodes must explicitly declare their shared store interface in metadata:

- **Input keys**: All shared store keys read during `prep()`
- **Output keys**: All shared store keys written during `post()`
- **Optional keys**: Keys that may or may not be present

**Example Declaration:**
```json
{
  "interface": {
    "inputs": {
      "url": {"required": true, "type": "str"},
      "timeout": {"required": false, "type": "int", "default": 30}
    },
    "outputs": {
      "transcript": {"type": "str"},
      "metadata": {"type": "dict"}
    }
  }
}
```

### 2.4 Extraction and Validation

- **Source**: Structured docstrings using Interface sections (see [Node Metadata](../implementation-details/metadata-extraction.md))
- **Validation**: Extracted metadata must match actual code behavior
- **Staleness**: Source file hash tracks when re-extraction needed
- **Registry**: Metadata stored alongside Python files in registry structure

---

## Node Object Flow IR

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
| `version` | Semantic version string | Resolved during [planner validation](../features/planner.md) |
| `params` | Arbitrary JSON for node behavior | **Never** contains shared store keys or execution directives |
| `execution.max_retries` | Integer ≥ 0, only for `@flow_safe` nodes | See [Runtime Behavior](./runtime.md) |
| `execution.use_cache` | Boolean, only for `@flow_safe` nodes | Cache eligibility enforced at runtime |
| `execution.wait` | Float ≥ 0, retry delay in seconds | Used by pocketflow framework (`pocketflow/__init__.py`) |

**Interface Resolution:**

- Planner resolves inputs/outputs from node metadata during validation
- Nodes may inherit from either BaseNode or Node from pocketflow
- Registry metadata validates params and execution config eligibility
- Node interfaces declared through docstring metadata, not IR params

> **Natural Interface Pattern**: See [shared store specification](./shared-store.md) for natural interface concepts

---

## Edge Object

**Simple Sequential Transitions:**

```json
[
  {"from": "fetch-transcript", "to": "process-text"},
  {"from": "process-text", "to": "write-output"}
]
```

**Action-Based Flow Control:**

```json
[
  {"from": "fetch-transcript", "to": "process-text"},
  {"from": "fetch-transcript", "to": "error-handler", "action": "error"},
  {"from": "process-text", "to": "write-output"},
  {"from": "error-handler", "to": "retry-fetch", "action": "retry"}
]
```

**Rules:**

- Simple sequential flow (node-to-node) for default paths
- Action-based transitions for error handling and conditional flow control
- Clear data flow from input to output
- Interface compatibility between connected nodes

> **Flow Structure**: See [planner specification](../features/planner.md) for simple node sequencing

**Examples from the Repository:**
- Sequential flow: [examples/core/simple-pipeline.json](../../examples/core/simple-pipeline.json) - Basic 3-node pipeline
- Error handling: [examples/core/error-handling.json](../../examples/core/error-handling.json) - Action-based routing with error recovery

---

## Proxy Mapping Schema

**Optional Flow-Level Mappings:**

```json
{
  "mappings": {
    "llm": {
      "input_mappings": {"prompt": "formatted_prompt"},
      "output_mappings": {"response": "article_summary"}
    },
    "write-file": {
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

> **Architecture Integration**: See [shared store pattern](./shared-store.md) for proxy implementation details

> **Example**: See [examples/core/proxy-mappings.json](../../examples/core/proxy-mappings.json) for a complete example of using mappings to adapt incompatible node interfaces.

---

## Side-Effect Model

Node purity status determined by `@flow_safe` decorator (see [Runtime Behavior Specification](./runtime.md)). IR validation enforces purity constraints:

- Only `@flow_safe` nodes may specify `max_retries > 0`
- Only `@flow_safe` nodes may specify `use_cache: true`
- Purity status read from node manifest; IR does not repeat it
- Validation occurs during [planner pipeline](../features/planner.md)

---

> **Execution Behavior**: See [Execution Reference](../reference/execution-reference.md) for failure semantics, retry configuration, and caching contracts

---

## Schema Validation Requirements

### 9.1 Node Metadata Schema Validation

- **Structure**: Must conform to node metadata JSON schema
- **Required fields**: node.id, interface.inputs, interface.outputs
- **Type validation**: All types must be valid (str, int, float, bool, dict, list, any)
- **Version format**: Semantic versioning (X.Y.Z)

### 9.2 Flow IR Schema Validation

- **Structure**: Must conform to flow IR JSON schema
- **Version compatibility**: ir_version must be supported
- **Node references**: All nodes must exist in registry
- **Edge validity**: Source and target nodes must exist
- **Mapping validity**: Mapped keys must match node interfaces

> **Validation Details**: See [Execution Reference](../reference/execution-reference.md#validation-pipeline) for complete validation pipeline

---

## Evolution Rules

**Version Compatibility:**

- **Minor IR additions**: New optional fields allowed; unknown optional fields ignored but preserved
- **Major IR bump**: Engine refuses to run; user must upgrade `pflow`
- **Deprecation Process**: Features flagged two minor versions before removal

**Extension Compatibility:**

- Forward compatibility for new mapping types
- Simple node composition extensions
- Execution configuration additions

**Node Metadata Schema Versioning:**

- **metadata_schema_version**: Track metadata format evolution
- **Backward Compatibility**: Older metadata formats supported during transitions
- **Migration Tools**: Automatic upgrade utilities for schema changes

---

## Extension Points

**Planned Extensions:**

- `execution.timeout` for node execution limits
- `constraints` object for resource caps (CPU, memory, disk)
- `annotations` free-form metadata for GUI/tooling integration
- Advanced mapping patterns for nested shared store keys

**Node Metadata Extensions:**

- Examples with shared store states and expected outputs
- Performance characteristics and resource usage
- Error handling patterns and recovery strategies
- Compatibility matrices between node versions

**Extension Principles:**

- Maintain backward compatibility
- Optional fields with sensible defaults
- Clear validation rules for new features

> **Implementation Details**: See [CLI Reference](../reference/cli-reference.md) for registry commands and [Registry](./registry.md) for implementation details

---

## Complete Example Flow

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
      "core/llm": "1.0.0"
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
      "registry_id": "core/llm",
      "version": "1.0.0",
      "params": {"model": "gpt-4", "temperature": 0.7},
      "execution": {"use_cache": true}
    }
  ],
  "edges": [
    {"from": "fetch-transcript", "to": "create-summary"}
  ],
  "mappings": {
    "create-summary": {
      "input_mappings": {"prompt": "formatted_prompt"}
    }
  }
}
```

**Example Features:**

- Registry-based node references with metadata resolution
- Natural interface compatibility (`shared["transcript"]` → `shared["prompt"]` via mapping)
- Simple sequential data flow
- Proper execution configuration for retry and caching
- Version locking for reproducibility

---

## Example Repository

The pflow project includes a comprehensive set of examples demonstrating various IR patterns. See [examples/README.md](../../examples/README.md) for a complete guide to all examples and how to use them.

### Core Examples (`examples/core/`)
Basic patterns every user should understand:
- **[minimal.json](../../examples/core/minimal.json)** - Simplest valid IR with a single node
- **[simple-pipeline.json](../../examples/core/simple-pipeline.json)** - Basic 3-node sequential pipeline
- **[template-variables.json](../../examples/core/template-variables.json)** - Using `$variable` syntax for dynamic values
- **[error-handling.json](../../examples/core/error-handling.json)** - Action-based routing for error recovery
- **[proxy-mappings.json](../../examples/core/proxy-mappings.json)** - Interface adaptation with mappings

### Advanced Examples (`examples/advanced/`)
Complex real-world workflows:
- **[github-workflow.json](../../examples/advanced/github-workflow.json)** - Automated GitHub issue resolution
- **[content-pipeline.json](../../examples/advanced/content-pipeline.json)** - Multi-stage content generation

### Invalid Examples (`examples/invalid/`)
Common mistakes and their error messages:
- **[missing-version.json](../../examples/invalid/missing-version.json)** - Missing required `ir_version`
- **[bad-edge-ref.json](../../examples/invalid/bad-edge-ref.json)** - Edge references non-existent node
- **[duplicate-ids.json](../../examples/invalid/duplicate-ids.json)** - Multiple nodes with same ID
- **[wrong-types.json](../../examples/invalid/wrong-types.json)** - Incorrect field types

Each example includes a corresponding `.md` file explaining its purpose and patterns. Start with the core examples to understand fundamental concepts before exploring advanced patterns.

---

This document defines the JSON schemas for Flow IR and Node Metadata, providing the foundation for validation, evolution, and metadata-driven planning capabilities.

## See Also

- **Architecture**: [Shared Store + Proxy Pattern](./shared-store.md) - Natural interface patterns and proxy mapping design
- **Components**: [Planner Specification](../features/planner.md) - How schemas integrate with dual-mode planning
- **Components**: [Registry System](./registry.md) - Node discovery and metadata management
- **Implementation**: [Metadata Extraction](../implementation-details/metadata-extraction.md) - How node metadata is extracted from docstrings
- **Related Features**: [Runtime Behavior](./runtime.md) - How execution configuration in schemas affects runtime
