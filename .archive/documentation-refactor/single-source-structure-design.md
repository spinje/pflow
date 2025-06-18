# Single Source of Truth Structure Design

## Design Principles

1. **One concept, one location** - Each technical concept has exactly one authoritative source
2. **Clear ownership** - Every document has a clear purpose and boundary
3. **Minimal cross-references** - Other docs link to canonical sources, not duplicate
4. **Discoverable structure** - Logical organization makes finding information intuitive

## Proposed Document Structure

### Core Reference Documents (New)

#### 1. `node-reference.md` (NEW)
**Purpose**: Canonical source for all node-related concepts
**Content**:
- Node lifecycle (prep/exec/post) - moved from multiple docs
- Node implementation patterns - consolidated from examples
- Node isolation principles - from shared-store.md
- Best practices and anti-patterns
- Common node templates

**Consolidates from**:
- shared-store.md (node examples)
- simple-nodes.md (patterns)
- architecture.md (node lifecycle)
- pflow-pocketflow-integration-guide.md (node basics)

#### 2. `cli-reference.md` (NEW)
**Purpose**: Complete CLI syntax and usage reference
**Content**:
- Command structure and syntax
- The `>>` operator (pipe composition)
- Shell pipe integration (`|` operator)
- Flag-to-shared-store mappings
- Command examples and patterns

**Consolidates from**:
- cli-runtime.md (syntax portions)
- architecture.md (CLI examples)
- shell-pipes.md (integration details)
- Various scattered examples

#### 3. `execution-reference.md` (NEW)
**Purpose**: Runtime behavior and execution model
**Content**:
- Execution flow and phases
- Error handling and recovery
- Retry mechanisms
- Validation pipeline
- Performance considerations

**Consolidates from**:
- runtime.md (behavior portions)
- architecture.md (execution engine)
- components.md (runtime details)

### Existing Documents - Redefined Purposes

#### `schemas.md`
**Purpose**: JSON schemas and data structures ONLY
**Changes**:
- Remove execution behavior discussions
- Remove node implementation examples
- Focus purely on schema definitions
- Add JSON Schema formal definitions

#### `runtime.md`
**Purpose**: Caching and safety mechanisms
**Changes**:
- Remove general execution flow (→ execution-reference.md)
- Focus on caching strategy and implementation
- Keep safety decorators and contracts
- Remove duplicated pocketflow explanations

#### `shared-store.md`
**Purpose**: Shared store pattern and proxy system
**Changes**:
- Remove node implementation examples (→ node-reference.md)
- Keep proxy pattern details
- Keep template variable system
- Focus on communication patterns

#### `architecture.md`
**Purpose**: High-level system design and component relationships
**Changes**:
- Remove detailed implementations
- Remove duplicated examples
- Add links to reference docs
- Focus on architectural decisions

#### `prd.md`
**Purpose**: Product vision and requirements
**Changes**:
- Remove technical implementation details
- Link to reference docs for specifics
- Focus on user stories and goals

#### `planner.md`
**Purpose**: Planning system specification
**Changes**:
- Remove duplicated schema definitions
- Remove caching details
- Focus on planner-specific behavior

### Organization Hierarchy

```
docs/
├── reference/                    # Technical references (NEW FOLDER)
│   ├── node-reference.md        # Node patterns and lifecycle
│   ├── cli-reference.md         # CLI syntax and usage
│   ├── execution-reference.md   # Runtime and execution model
│   └── api-reference.md         # Future: API specifications
├── core-concepts/               # Rename from current flat structure
│   ├── schemas.md              # JSON schemas only
│   ├── shared-store.md         # Communication patterns
│   ├── runtime.md              # Caching and safety
│   └── registry.md             # Discovery system
├── architecture/                # High-level design
│   ├── architecture.md         # System design
│   ├── components.md           # Component inventory
│   └── pflow-pocketflow-integration-guide.md
├── features/                    # Feature specifications
│   ├── planner.md
│   ├── cli-runtime.md          # CLI-runtime integration
│   ├── shell-pipes.md
│   └── mcp-integration.md
├── node-packages/              # Node documentation
│   ├── llm-nodes.md
│   ├── github-nodes.md
│   ├── claude-nodes.md
│   └── ci-nodes.md
└── index.md                    # Navigation hub
```

## Content Migration Map

### To `node-reference.md`:
- Node lifecycle explanation from runtime.md, architecture.md, pflow-pocketflow-integration-guide.md
- LLMNode example (consolidated from 3 versions)
- Node implementation patterns from simple-nodes.md
- "Check shared first, then params" pattern
- Node isolation principles from shared-store.md

### To `cli-reference.md`:
- CLI syntax from architecture.md, cli-runtime.md
- `>>` operator explanations (from 7+ files)
- Command structure and examples
- Shell pipe integration from shell-pipes.md
- Template variable usage in CLI

### To `execution-reference.md`:
- Execution flow from runtime.md, architecture.md
- Error handling strategies (consolidated)
- Retry mechanisms
- Validation pipeline from schemas.md, runtime.md
- Action-based transitions (future)

### To remain in `schemas.md`:
- All JSON schema definitions
- No examples or implementation details
- Pure structural specifications

### To remain in `runtime.md`:
- Caching strategy and implementation
- Cache key computation
- Safety decorators
- Performance optimizations

## Benefits

1. **Reduced duplication**: ~40% less content
2. **Clear ownership**: Each concept has one home
3. **Easier maintenance**: Single update location
4. **Better discoverability**: Logical organization
5. **Consistent depth**: Reference docs are comprehensive

## Implementation Priority

1. Create reference documents first
2. Migrate content systematically
3. Update cross-references
4. Remove duplications
5. Reorganize folder structure
