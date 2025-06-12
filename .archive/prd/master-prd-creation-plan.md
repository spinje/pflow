# Master PRD Creation Plan

## Executive Summary

After analyzing the three existing PRD versions and the comprehensive architectural documentation, I've identified significant gaps and contradictions that need resolution. The current PRDs contain valuable insights but are inconsistent with the detailed specifications. This plan outlines how to create a definitive master PRD that synthesizes all available information while maintaining architectural coherence.

## Key Findings from Analysis

### 1. Architectural Inconsistencies Found

**MCP Integration Contradiction:**
- **PRDs state**: Standalone `~/.pflow/mcp.json` registry
- **MCP spec states**: Unified registry integration, eliminates standalone MCP config
- **Resolution needed**: Follow unified registry approach from architectural specs

**Planner Architecture Mismatch:**
- **PRDs describe**: Simple 8-9 step pipeline with basic LLM calls
- **Planner spec defines**: Comprehensive dual-mode operation with detailed validation framework
- **Resolution needed**: Adopt complete planner specification with dual-mode architecture

**Cache Key Computation Variance:**
- **PRD-pflow.md**: `SHA-256(node-type + params + input hash)`
- **PRD-pflow-2.md**: `SHA-256(node-type + params + input hash + snapshot hash)`
- **Runtime spec defines**: `node_hash ⊕ effective_params ⊕ input_data_sha256`
- **Resolution needed**: Use runtime specification formula

**CLI Resolution Algorithm:**
- **PRDs**: Varying descriptions of parameter resolution
- **CLI spec defines**: Complete "Type flags; engine decides" algorithm
- **Resolution needed**: Adopt detailed CLI specification algorithm

**JSON IR Schema:**
- **PRDs mention**: Basic IR v0.1 with minimal schema
- **JSON governance doc**: Complete schema with versioning, validation rules
- **Resolution needed**: Reference complete JSON schema governance

### 2. Missing Critical Information in PRDs

**Shared Store + Proxy Pattern:**
- PRDs don't explain the NodeAwareSharedStore proxy pattern
- Missing natural interface vs proxy mapping distinction
- No mention of marketplace compatibility through mappings

**Node Metadata System:**
- PRDs don't describe metadata extraction from docstrings
- Missing planner's metadata-driven selection process
- No mention of registry structure and node discovery

**Action-Based Flow Control:**
- PRDs mention basic node connections
- Missing action-based transitions for error handling
- No conditional flow control patterns

**Version Resolution:**
- PRDs have minimal versioning discussion
- Missing semver resolution rules and lockfile integration
- No mention of namespace collision handling

### 3. Valuable PRD Insights to Preserve

**Strategic Positioning (from PRD-pflow-2.md):**
- Planner protocol transparency as key differentiator
- Two-step LLM design rationale
- Config override snapshot hash concept

**User Journey Examples (from all PRDs):**
- Concrete CLI examples with real commands
- Progressive complexity demonstration
- Automation workflow patterns

**MVP Acceptance Criteria (from PRD-pflow-2.md & 3):**
- Specific performance targets
- Planner success rate metrics
- End-to-end latency requirements

## Master PRD Structure Plan

### Section 1: Vision & Strategic Positioning
**Source**: Synthesis of all three PRDs + architectural context
**Key updates**:
- Emphasize shared store + proxy pattern as core differentiator
- Include planner-executor separation as architectural principle
- Add metadata-driven planning as strategic advantage
- Reference complete pocketflow framework integration

### Section 2: Architectural Overview
**Source**: Planner specification + shared store specs
**New content**:
- Dual-mode operation diagram (NL path vs CLI path)
- Shared store + proxy pattern explanation
- Node registry and metadata system overview
- JSON IR governance integration

### Section 3: Core Concepts
**Source**: All architectural specifications
**Comprehensive coverage**:
- Node classification (@flow_safe vs impure)
- Shared store natural interfaces
- Proxy mapping for complex flows
- Action-based transitions
- Version resolution and namespacing

### Section 4: Planning Pipeline
**Source**: Planner responsibility specification
**Detailed architecture**:
- Natural language path (10-stage process)
- CLI pipe path (7-stage validation)
- LLM selection with metadata context
- Retrieval-first strategy
- Validation framework integration

### Section 5: CLI Surface & Parameter Resolution
**Source**: CLI runtime specification
**Complete algorithm**:
- "Type flags; engine decides" principle
- Data injection vs params override rules
- Execution config categorization
- Reserved key handling (stdin)

### Section 6: JSON IR & Schema Governance
**Source**: JSON schema governance document
**Complete specification**:
- Document envelope structure
- Node metadata schema
- Edge objects and action-based transitions
- Proxy mapping schema
- Validation pipeline

### Section 7: Runtime Behavior
**Source**: Runtime behavior specification
**Comprehensive coverage**:
- Opt-in purity model (@flow_safe)
- Cache eligibility requirements
- Retry configuration and integration
- Failure semantics and error recovery

### Section 8: MCP Integration
**Source**: MCP integration specification
**Unified approach**:
- Registry integration (not standalone config)
- Wrapper node generation
- Natural interface mapping
- Action-based error handling for MCP tools

### Section 9: Node Discovery & Versioning
**Source**: Node discovery specification
**Complete system**:
- Semantic versioning resolution
- Namespace collision handling
- Registry structure and search order
- Lockfile generation and usage

### Section 10: Validation & Quality
**Source**: All specifications + PRD insights
**Comprehensive framework**:
- Validation pipeline stages
- Error recovery mechanisms
- Testing requirements
- CI/CD integration

### Section 11: User Experience
**Source**: PRD user journeys + architectural integration
**End-to-end workflows**:
- Natural language exploration
- CLI pipe iteration
- Flow reuse and composition
- Production deployment

### Section 12: Performance & Metrics
**Source**: PRD acceptance criteria + architectural performance notes
**Concrete targets**:
- Planner latency and success rates
- Cache hit ratios
- End-to-end flow performance
- Validation accuracy

### Section 13: Security & Trust Model
**Source**: Runtime behavior + MCP security specs
**Complete framework**:
- Flow origin trust levels
- Cache safety rules
- MCP authentication
- Node registry security

### Section 14: Implementation Roadmap
**Source**: All PRD roadmaps + architectural extensibility
**Prioritized features**:
- MVP capabilities
- Post-MVP enhancements
- Future architectural evolution

## Resolution Strategy for Contradictions

### 1. Authoritative Source Priority
When contradictions exist, follow this hierarchy:
1. **Architectural specifications** (most detailed, technically accurate)
2. **PRD-pflow-2.md** (most comprehensive PRD)
3. **PRD-pflow-3.md** (structured approach)
4. **PRD-pflow.md** (base concepts)

### 2. Specific Contradiction Resolutions

**MCP Registry:**
- **Decision**: Adopt unified registry from MCP specification
- **Rationale**: Eliminates planner architecture conflicts

**Planner Architecture:**
- **Decision**: Use complete dual-mode specification
- **Rationale**: Provides complete technical accuracy

**Cache Key Formula:**
- **Decision**: Use runtime specification formula
- **Rationale**: Technically precise and implementation-ready

**CLI Resolution:**
- **Decision**: Adopt complete "Type flags; engine decides" algorithm
- **Rationale**: Provides clear implementation guidance

### 3. Information Synthesis Approach

**Preserve valuable PRD insights while ensuring architectural consistency:**
- Keep strategic positioning and user journey examples
- Integrate technical details from architectural specs
- Maintain MVP acceptance criteria with architectural context
- Add missing critical concepts (proxy pattern, metadata system)

## Quality Assurance Plan

### 1. Technical Accuracy Validation
- Cross-reference every technical detail with architectural specifications
- Ensure JSON IR examples match schema governance
- Validate CLI examples against resolution algorithm
- Verify cache and retry behavior matches runtime specification

### 2. Completeness Check
- Ensure all architectural patterns are explained
- Cover complete user journey from NL to execution
- Include all CLI commands and flags
- Address all integration points (MCP, registry, planner)

### 3. Consistency Verification
- No contradictions between sections
- Consistent terminology throughout
- Aligned examples and code snippets
- Coherent architectural narrative

### 4. Clarity and Usability
- Clear section organization and flow
- Concrete examples for abstract concepts
- Implementation-ready specifications
- User-focused explanations alongside technical details

## Implementation Timeline

### Phase 1: Core Architecture (Days 1-2)
- Vision, strategic positioning, and architectural overview
- Core concepts synthesis
- Technical contradiction resolution

### Phase 2: Technical Specifications (Days 3-4)
- Planning pipeline integration
- CLI surface and parameter resolution
- JSON IR and schema governance
- Runtime behavior synthesis

### Phase 3: Integration & User Experience (Days 5-6)
- MCP integration unified approach
- Node discovery and versioning
- User experience workflows
- Validation and quality frameworks

### Phase 4: Quality Assurance (Day 7)
- Technical accuracy validation
- Completeness verification
- Consistency checking
- Final review and polish

## Success Criteria

The master PRD will be considered successful when:

1. **Technical Accuracy**: No contradictions with architectural specifications
2. **Completeness**: All major pflow concepts and patterns covered
3. **Implementation Ready**: Sufficient detail for development work
4. **User Clarity**: Clear value proposition and usage patterns
5. **Architectural Coherence**: Consistent technical narrative throughout

## Updated Plan Based on Requirements

### Target Audience & Approach Confirmed
- **Primary audience**: Product managers and architects
- **Technical detail level**: Conceptual clarity with lightweight code examples and Mermaid diagrams
- **Document type**: PRD-focused but includes necessary technical specifications
- **Goal**: Make every important concept crystal clear without extreme implementation detail

### New Framework Insights Incorporated

From analyzing the actual pocketflow framework (`__init__.py` and `communication.md`):

**Confirmed Architectural Patterns:**
- 100-line lightweight framework with `prep()`, `exec()`, `post()` pattern
- Action-based transitions via `node - "action" >> next_node` syntax
- Shared store as primary communication mechanism (heap-like shared memory)
- Params for batch operations and node configuration (stack-like per-node config)
- Built-in retry mechanism with `max_retries` and `wait` parameters
- `Flow` orchestration with automatic successor management

**Key Clarifications:**
- Shared store is the primary data flow mechanism (not just an option)
- Params are mainly for identifiers and batch operations, not primary data flow
- The `>>` operator and action-based transitions are core framework features
- Framework already supports the retry and failure semantics described in specs
- pflow's innovation is the PATTERN (shared store + natural interfaces + proxy mapping) not the framework
- The 100-line framework is stable; complexity is in the planning, validation, and orchestration layers

### Updated Section Plans

#### Section 2: Architectural Overview (Enhanced)
**New Mermaid diagrams to include:**
- Dual-mode operation flow (NL path vs CLI pipe path)
- Shared store + proxy pattern visualization
- Node lifecycle (`prep` → `exec` → `post`)
- Action-based transition examples

#### Section 3: Core Concepts (Refined for PM/Architect audience)
**Focus on conceptual clarity:**
- Framework foundations: 100-line pocketflow as the execution engine
- Shared store pattern: heap-like memory vs stack-like params
- Natural interfaces: how nodes communicate through intuitive keys
- Proxy pattern: marketplace compatibility without node complexity
- `@flow_safe` decorator: purity model for caching and retries

#### Section 4: Planning Pipeline (Simplified technical detail)
**Conceptual flow with minimal code:**
- High-level Mermaid diagram of dual-mode operation
- LLM selection process overview
- Validation checkpoints without implementation details
- User experience flow from intent to execution

#### Section 5: CLI Surface (User-focused)
**Emphasize user experience:**
- "Type flags; engine decides" principle explanation
- Example commands with expected behavior
- Parameter resolution examples (data injection vs config override)
- Error handling and user feedback

### Content Balance Strategy

**70% Product Requirements / 30% Technical Specification:**
- Strategic positioning and user value propositions (PRD focus)
- User journeys and experience design (PRD focus)
- High-level architecture and concepts (PRD with technical context)
- Implementation patterns and detailed specs (Technical, but conceptually focused)

**Code Examples Approach:**
- Use lightweight, conceptual code snippets (5-10 lines max)
- Focus on interfaces and patterns, not implementation details
- Include Mermaid diagrams for complex workflows
- Reference detailed specs for implementation teams

**Technical Depth Guidelines:**
- Explain WHAT and WHY (PM/architect needs)
- Minimal HOW unless critical for understanding
- Use diagrams and examples to clarify abstract concepts
- Provide clear references to detailed implementation specs

This plan provides a roadmap for creating a PM/architect-focused master PRD that makes every important pflow concept crystal clear while maintaining the right balance of product vision and technical specification.
