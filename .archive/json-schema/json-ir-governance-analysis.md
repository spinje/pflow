# JSON IR Governance Analysis: Contradictions and Inconsistencies

## Executive Summary

The JSON IR Governance document contains **fundamental contradictions** with the established pflow architecture and specifications. The most critical issues involve misrepresenting the core shared store pattern and using inconsistent field naming throughout the IR schema.

---

## Critical Contradictions

### 1. Fundamental Shared Store Architecture Violation

**Source of Truth** (shared-store-node-proxy-architecture.md):
- Nodes use **natural interfaces**: `shared["text"]`, `shared["url"]`
- "Node writers shouldn't need to understand flow orchestration concepts"
- Keys are accessed directly: `return shared["text"]` in `prep()`, `shared["summary"] = result` in `post()`

**JSON IR Governance Contradiction**:
- Section 4 states: "Nodes **must** declare every key they read/write via `params` (`input_key`, `output_key`, custom)"
- Example shows: `"params": {"input_key": null, "output_key": "weather.stockholm"}`
- This completely contradicts the natural interface principle

**Impact**: This represents a fundamental architectural mismatch. The governance document describes a parameterized key system that goes against the core design principle of standalone nodes with intuitive interfaces.

### 2. IR Schema Field Inconsistencies

**Source of Truth** (planner-responsibility-functionality-spec.md):
```json
{
  "id": "yt-transcript",
  "version": "1.0.0",
  "params": {"temperature": 0.7},
  "execution": {"max_retries": 2, "wait": 1.0}
}
```

**JSON IR Governance Inconsistencies**:
```json
{
  "id": "a1",
  "type": "mcp/weather.get@0.3.2",
  "exec": {
    "retries": 2,
    "use_cache": true
  }
}
```

**Specific Contradictions**:
- **Node identification**: Uses `"type": "namespace/name@version"` instead of separate `"version"` field
- **Execution config**: Uses `"exec"` instead of `"execution"`
- **Retry parameter**: Uses `"retries"` instead of `"max_retries"`

### 3. Node Interface Documentation Mismatch

**Source of Truth** (shared-store-cli-runtime-specification.md):
```python
class YTTranscript(Node):
    """Interface:
    - Reads: shared["url"] - YouTube video URL
    - Writes: shared["transcript"] - extracted transcript text
    - Params: language (default "en") - transcript language
    """
    def prep(self, shared):
        return shared["url"]  # Natural interface
```

**JSON IR Governance Example**:
```json
{
  "params": {
    "city": "Stockholm",
    "input_key": null,
    "output_key": "weather.stockholm"
  }
}
```

**Problem**: The governance document shows shared store keys being managed through params, but source documents show params are for node behavior configuration (like `"language": "en"`, `"temperature": 0.7`).

---

## Mapping System Misrepresentation

**Source of Truth** (shared-store-node-proxy-architecture.md):
- Mappings are **optional** and handled by proxy when needed for complex flows
- Mappings defined at **flow level** in IR: `"mappings": {"node-id": {"input_mappings": {...}}}`
- Nodes always use natural interfaces; proxy translates when mappings exist

**JSON IR Governance Miss**:
- No mention of the proxy pattern or `mappings` section in IR
- Incorrectly suggests key management happens through node params
- Missing the critical distinction between natural interfaces and optional mapping layer

---

## Runtime Integration Inconsistencies

### CLI Parameter Resolution

**Source of Truth** (shared-store-cli-runtime-specification.md):
- "Single user rule — Type flags; engine decides"
- Flags matching shared store keys → data injection
- Flags matching param names → param overrides
- `params` are flat structure: `self.params.get("temperature", 0.7)`

**JSON IR Governance**:
- Does not address CLI integration
- Parameterized key system conflicts with direct CLI → shared store injection

### Framework Integration

**Source of Truth** (multiple documents):
- Built on **pocketflow framework** (100 lines)
- Uses `prep()`/`exec()`/`post()` pattern
- Nodes inherit from `pocketflow.Node`
- Params accessed via `self.params.get()`

**JSON IR Governance**:
- No mention of pocketflow integration
- No reference to established execution patterns
- Disconnected from actual runtime implementation

---

## Versioning and Registry Contradictions

**Source of Truth** (node-discovery-namespacing-and-versioning.md):
- Node identifier: `<namespace>/<name>@<semver>`
- Separate version lockfiles and execution lockfiles
- Registry integration with planner metadata extraction

**JSON IR Governance**:
- Uses `"type"` field combining namespace/name/version
- `"locked_nodes"` concept aligns but field structure differs
- No integration with established registry and lockfile systems

---

## Missing Critical Components

The JSON IR Governance document **completely omits** several core architectural elements:

1. **Proxy Pattern**: No mention of `NodeAwareSharedStore` or mapping system
2. **Action-Based Transitions**: Missing conditional flow control (`node - "error" >> handler`)
3. **Planner Integration**: No connection to dual-mode operation (NL + CLI paths)
4. **Trust Model**: Missing flow origin trust levels and security considerations
5. **Framework Integration**: No pocketflow compatibility or execution pattern alignment

---

## Recommendations

### Immediate Actions Required

1. **Rewrite Section 4** to align with natural interface pattern
2. **Standardize field naming** to match established IR schema from planner spec
3. **Add mappings section** to describe proxy pattern integration
4. **Include action-based transitions** for conditional flow control
5. **Align with pocketflow framework** execution patterns

### Architectural Alignment

The JSON IR Governance document should:
- **Support natural interfaces** as the primary node pattern
- **Document proxy mappings** as optional compatibility layer
- **Integrate with planner** dual-mode operation and validation
- **Align with CLI runtime** parameter resolution rules
- **Reference framework patterns** from pocketflow integration

### Schema Consistency

All IR examples should use consistent field names:
- `"execution"` not `"exec"`
- `"max_retries"` not `"retries"`
- Separate `"version"` field or consistent `"type"` format
- Natural interface documentation in node metadata

---

## Severity Assessment

**Critical**: The shared store architecture contradiction represents a fundamental misunderstanding of pflow's core design principles. This must be corrected before any IR implementation.

**High**: Field naming inconsistencies will cause runtime failures and compiler errors.

**Medium**: Missing proxy pattern documentation leaves implementation gaps.

**Low**: Framework integration references for completeness.

---

## Conclusion

The JSON IR Governance document requires **substantial revision** to align with pflow's established architecture. The current version contradicts core design principles and would lead to incompatible implementations. Priority should be given to correcting the shared store pattern representation and standardizing IR field schemas.
