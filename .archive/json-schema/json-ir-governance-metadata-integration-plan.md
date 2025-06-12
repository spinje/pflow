# JSON IR Governance + Node Metadata Integration Plan

## Overview

This plan outlines how to enhance the JSON IR Governance document to properly integrate the node metadata strategy while maintaining clear separation of concerns between **flow-level IR** and **node-level metadata**.

---

## Core Integration Principles

### **1. Dual-Schema Approach**
- **Flow IR**: Orchestration, mappings, execution config (current focus)
- **Node Metadata**: Interface definitions, documentation, examples (new addition)
- **Clear Boundaries**: Flow IR references nodes by ID, metadata provides interface details

### **2. Registry-Driven Architecture**
- **Node Registration**: Python files → extracted JSON metadata → registry index
- **Flow Compilation**: IR generation uses registry metadata for validation
- **Performance**: Pre-extracted metadata enables fast planner operations

### **3. Validation Integration**
- **Node-Level**: Code/metadata consistency, interface validity
- **Flow-Level**: Node compatibility, mapping correctness, execution safety
- **Cross-Reference**: Flow IR validates against registered node metadata

---

## Document Structure Updates

### **Section 1: Document Scope Expansion**

**Current Focus**: JSON IR schema for flows
**Enhanced Focus**: JSON governance for flows AND node metadata

**New Introduction**:
```markdown
# JSON Schema Governance: Flows & Node Metadata

This document defines JSON schema governance for two key pflow artifacts:

1. **Flow IR**: JSON representation of executable flows (orchestration, mappings, execution)
2. **Node Metadata**: JSON interface definitions extracted from node docstrings (inputs, outputs, params)

Both schemas work together to enable metadata-driven flow planning and validation.

> **Architecture Context**: See [Node Metadata Strategy](./node-metadata-extraction.md) for extraction details and [Shared Store Pattern](./shared-store-node-proxy-architecture.md) for interface concepts.
```

### **Section 2: Registry Integration**

**New Section to Add**:
```markdown
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

- **Source**: Structured docstrings using Interface sections (see [Node Metadata](./node-metadata-extraction.md))
- **Validation**: Extracted metadata must match actual code behavior
- **Staleness**: Source file hash tracks when re-extraction needed
- **Registry**: Metadata stored alongside Python files in registry structure
```

### **Section 3: Flow IR Updates**

**Enhanced Node References**:
```markdown
## 3 · Node Object (Enhanced)

Flow IR references nodes by registry ID, with metadata resolved during validation.

```json
{
  "id": "fetch-transcript",
  "registry_id": "core/yt-transcript",
  "version": "1.0.0",
  "params": {
    "language": "en"
  },
  "execution": {
    "max_retries": 2,
    "use_cache": true
  }
}
```

**Field Updates**:
- **registry_id**: References node in registry (namespace/name format)
- **Interface Resolution**: Planner resolves inputs/outputs from node metadata
- **Validation**: Registry metadata validates params and execution config eligibility
```

### **Section 4: Validation Pipeline Enhancement**

**Current**: Basic IR validation
**Enhanced**: Two-phase validation using registry metadata

```markdown
## 8 · Enhanced Validation Pipeline

### 8.1 Node Metadata Validation (Registry Phase)

1. **Extraction Validation**: Docstring → metadata consistency
2. **Code Analysis**: Static analysis of actual shared["key"] usage
3. **Interface Verification**: Documented vs actual interface matching
4. **Staleness Check**: Source hash validation for re-extraction needs

### 8.2 Flow IR Validation (Composition Phase)

1. **Registry Resolution**: All referenced nodes exist in registry
2. **Interface Compatibility**: Input/output key alignment between nodes
3. **Mapping Validation**: Proxy mappings resolve interface mismatches correctly
4. **Execution Safety**: `@flow_safe` requirements for retry/cache config
5. **Action Coverage**: All node actions have defined transitions

### 8.3 Cross-Reference Validation

- **Params Validation**: Flow IR params match node metadata param definitions
- **Interface Alignment**: Connected nodes have compatible input/output keys
- **Mapping Necessity**: Detect when proxy mappings required vs optional
```

### **Section 5: Registry Commands Integration**

**New Section**:
```markdown
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
```

---

## Performance Considerations

### **Planner Optimization Strategy**

**Problem**: Planner needs fast access to all node interfaces for LLM context
**Solution**: Pre-extracted JSON metadata enables instant loading

```markdown
## 13 · Performance Architecture

### 13.1 Registry Loading Strategy

```python
# Fast planner context generation
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
```

---

## Migration Strategy

### **Phase 1: Node Metadata Foundation**

1. **Add Node Metadata Section** to JSON IR Governance
2. **Define Extraction Pipeline** with docstring → JSON workflow
3. **Enhance Registry Commands** to support metadata extraction
4. **Update Validation Rules** to include metadata consistency

### **Phase 2: Flow IR Integration**

1. **Update Node Object Schema** to reference registry metadata
2. **Enhance Validation Pipeline** with two-phase approach
3. **Add Interface Compatibility** validation using metadata
4. **Integrate Mapping Generation** based on interface mismatches

### **Phase 3: Performance Optimization**

1. **Implement Registry Index** for fast metadata loading
2. **Add Planner Integration** using pre-extracted metadata
3. **Optimize CLI Commands** with rich metadata display
4. **Add Validation Caching** for frequently used flows

---

## Schema Evolution Strategy

### **Versioning Approach**

```markdown
## 14 · Schema Evolution & Compatibility

### 14.1 Node Metadata Schema Versioning

- **metadata_schema_version**: Track metadata format evolution
- **Backward Compatibility**: Older metadata formats supported during transitions
- **Migration Tools**: Automatic upgrade utilities for schema changes

### 14.2 Flow IR Schema Coordination

- **IR Schema**: Maintains compatibility with node metadata references
- **Joint Evolution**: Major changes coordinate between flow IR and node metadata
- **Validation Alignment**: Schema changes maintain validation consistency

### 14.3 Registry Compatibility

- **Multi-Version Support**: Registry supports multiple metadata schema versions
- **Gradual Migration**: Nodes can be migrated incrementally to new schemas
- **Tooling Support**: CLI commands handle schema version differences gracefully
```

---

## Quality Assurance Checklist

### **Node Metadata Integration**
- [ ] Clear separation between flow IR and node metadata schemas
- [ ] Registry structure supports both Python files and extracted JSON
- [ ] Validation pipeline includes metadata consistency checking
- [ ] Performance optimization through pre-extracted metadata

### **Flow IR Enhancement**
- [ ] Node references use registry IDs for metadata resolution
- [ ] Interface validation uses extracted metadata for compatibility
- [ ] Proxy mapping generation integrated with interface definitions
- [ ] Execution safety validation uses node metadata constraints

### **Registry Integration**
- [ ] CLI commands support rich metadata display and management
- [ ] Registry index enables fast node discovery and filtering
- [ ] Installation workflow includes automatic metadata extraction
- [ ] Validation tools detect code/metadata inconsistencies

### **Planner Compatibility**
- [ ] Fast metadata loading for LLM context generation
- [ ] Interface-aware flow validation and mapping generation
- [ ] Registry-driven node selection and compatibility checking
- [ ] Performance optimizations for large node registries

---

## Success Criteria

The enhanced JSON IR Governance document will successfully integrate node metadata when:

1. **Clear Boundaries**: Flow IR and node metadata have distinct, well-defined scopes
2. **Registry Integration**: Complete workflow from Python files to extracted metadata
3. **Performance**: Planner operations use fast JSON metadata instead of Python parsing
4. **Validation**: Two-phase validation ensures both code consistency and flow compatibility
5. **CLI Excellence**: Rich metadata-driven commands for developers and users

This integration maintains the focused scope of JSON IR governance while adding essential node metadata capabilities that enable metadata-driven flow planning and validation.
