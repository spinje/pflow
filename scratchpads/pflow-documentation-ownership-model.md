# pflow Documentation Ownership Model

## Overview

This document establishes clear ownership for key concepts across the pflow documentation structure. Each concept has a designated canonical source document that serves as the authoritative reference, with other documents referencing but not duplicating the core definition.

## Ownership Principles

1. **Single Source of Truth**: Each concept has ONE canonical document
2. **Clear References**: Other documents link to canonical sources
3. **No Duplication**: Avoid repeating detailed definitions across documents
4. **Logical Grouping**: Concepts live where they make most sense contextually
5. **Progressive Disclosure**: Documents build on each other in logical order

## Key Concept Ownership

### 1. Shared Store Pattern

**Canonical Source**: `docs/shared-store.md`
- **Why**: This is the dedicated pattern document, provides complete architectural context
- **Scope**: Pattern definition, node autonomy, proxy architecture, template variables
- **References From**:
  - `prd.md` - Links for detailed pattern explanation
  - `architecture.md` - Links for implementation details
  - `schemas.md` - Links for mapping schema context

### 2. Template Variables

**Canonical Source**: `docs/shared-store.md` (Section: Template Variable Resolution)
- **Why**: Template variables are fundamentally about data flow through shared store
- **Scope**: $variable syntax, resolution process, dependency flow
- **References From**:
  - `architecture.md` - Brief mention with link to shared-store.md
  - `cli-runtime.md` - Links for template resolution details

### 3. MVP Boundaries

**Canonical Source**: `docs/mvp-scope.md`
- **Why**: Dedicated MVP scope document with clear inclusion/exclusion lists
- **Scope**: What's in v0.1, what's deferred to v2.0/v3.0, success criteria
- **References From**:
  - `prd.md` - High-level MVP mention, links to mvp-scope.md
  - `architecture.md` - MVP focus statement, links for details
  - `components.md` - Component-specific MVP boundaries

### 4. Pocketflow Integration

**Canonical Source**: `pocketflow/__init__.py` (Code) + `pocketflow/CLAUDE.md` (Documentation)
- **Why**: The actual framework code is the truth, CLAUDE.md provides navigation
- **Scope**: Node lifecycle, Flow operators, framework capabilities
- **References From**:
  - All pflow docs reference pocketflow patterns but don't redefine them
  - `architecture.md` - Links to pocketflow for foundation details
  - `shared-store.md` - Links for framework integration

### 5. Node Interfaces

**Canonical Source**: `docs/schemas.md` (Section: Node Metadata Schema)
- **Why**: Centralized schema governance for all interface definitions
- **Scope**: Input/output declarations, params structure, metadata format
- **References From**:
  - `shared-store.md` - Links for interface declaration requirements
  - `planner.md` - References metadata-driven selection
  - Individual node package docs - Use schema format

### 6. JSON IR Schemas

**Canonical Source**: `docs/schemas.md`
- **Why**: Complete schema governance document with validation rules
- **Scope**: Flow IR structure, node definitions, edge formats, validation pipeline
- **References From**:
  - `prd.md` - High-level IR mention, links to schemas.md
  - `architecture.md` - IR structure overview, links for details
  - `planner.md` - IR generation process references schema

### 7. Planning Architecture

**Canonical Source**: `docs/planner.md`
- **Why**: Comprehensive planner specification with dual-mode details
- **Scope**: NL path, CLI path, validation, metadata-driven selection
- **References From**:
  - `prd.md` - Planning overview, links to planner.md
  - `architecture.md` - High-level planning mention
  - `mvp-scope.md` - Planning as MVP feature

### 8. Registry System

**Canonical Source**: `docs/registry.md`
- **Why**: Complete registry architecture and versioning strategy
- **Scope**: Node discovery, versioning, namespacing, MCP integration
- **References From**:
  - `schemas.md` - Registry structure for metadata storage
  - `planner.md` - Registry queries during planning
  - `architecture.md` - Component overview

### 9. Runtime Behavior

**Canonical Source**: `docs/runtime.md`
- **Why**: Authoritative runtime specification with performance details
- **Scope**: Execution flow, caching, retries, failure handling
- **References From**:
  - `prd.md` - Performance targets reference runtime.md
  - `schemas.md` - Execution config validation rules
  - `architecture.md` - Execution layer overview

### 10. CLI Syntax

**Canonical Source**: `docs/cli-runtime.md`
- **Why**: Complete CLI specification with resolution algorithms
- **Scope**: Command structure, flag resolution, parameter categories
- **References From**:
  - `architecture.md` - CLI layer overview, links for details
  - `prd.md` - CLI examples reference complete spec
  - `shell-pipes.md` - Integration with CLI runtime

## Document Hierarchy and Dependencies

### Foundation Documents (Read First)
1. `pocketflow/__init__.py` - Core framework
2. `pocketflow/CLAUDE.md` - Framework navigation
3. `docs/shared-store.md` - Core pattern

### Architecture Documents (Read Second)
1. `docs/prd.md` - Complete vision and requirements
2. `docs/architecture.md` - MVP-focused implementation
3. `docs/mvp-scope.md` - Clear boundaries

### Specification Documents (Read Third)
1. `docs/schemas.md` - Data structures
2. `docs/planner.md` - Planning pipeline
3. `docs/runtime.md` - Execution behavior
4. `docs/registry.md` - Node management
5. `docs/cli-runtime.md` - CLI interface

### Implementation Documents (Read As Needed)
1. `docs/core-node-packages/*.md` - Node specifications
2. `docs/implementation-details/*.md` - Technical details
3. `docs/components.md` - Component breakdown

## Maintenance Guidelines

### When Adding New Concepts

1. **Determine Natural Home**: Where does this concept logically belong?
2. **Check Existing Ownership**: Is there already a canonical source?
3. **Create Single Source**: Define concept in ONE document
4. **Add References**: Update other documents to link to canonical source
5. **Update This Model**: Add new concept to ownership model

### When Updating Existing Concepts

1. **Find Canonical Source**: Use this ownership model
2. **Update Primary Document**: Make changes in canonical location
3. **Check References**: Ensure links still make sense
4. **Avoid Duplication**: Don't add detailed definitions elsewhere

### Cross-References Best Practices

1. **Use Explicit Links**: `See [Shared Store Pattern](./shared-store.md)`
2. **Reference Specific Sections**: Link to section headers when appropriate
3. **Provide Context**: Briefly explain why reader should follow link
4. **Maintain Link Integrity**: Regular link validation (test_links.py)

## Document Purpose Summary

- **prd.md**: Master vision, complete architecture, strategic positioning
- **architecture.md**: MVP implementation focus, component details
- **mvp-scope.md**: Clear in/out boundaries, success criteria
- **shared-store.md**: Core pattern, proxy design, template variables
- **schemas.md**: JSON structures, validation rules, metadata formats
- **planner.md**: Dual-mode planning, validation pipeline
- **runtime.md**: Execution engine, performance, caching
- **registry.md**: Node discovery, versioning strategy
- **cli-runtime.md**: CLI interface, parameter resolution
- **components.md**: Feature-by-feature breakdown

## Benefits of This Model

1. **Reduced Confusion**: Developers know where to find authoritative information
2. **Easier Maintenance**: Updates happen in one place
3. **Better Navigation**: Clear document relationships and dependencies
4. **Consistent Understanding**: Single source prevents conflicting definitions
5. **Efficient Learning**: Progressive disclosure through document hierarchy

## Regular Review

This ownership model should be reviewed and updated:
- When adding new major concepts
- During significant architectural changes
- As part of documentation maintenance cycles
- When confusion arises about concept ownership
