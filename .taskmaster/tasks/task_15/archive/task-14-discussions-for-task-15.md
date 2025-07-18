# Task 14 Discussions and Context for Task 15

## Overview

This document captures the key discussions and insights from Task 14 that inform the design and implementation of Task 15. While Task 14 focused on enriching node metadata for better planner context, significant architectural discussions emerged about evolving the context builder itself.

## What Task 14 Accomplished

Task 14 successfully implemented enriched metadata extraction that provides:

1. **Structured Node Information**
   - Clear input/output specifications with types
   - Nested structure, support for complex objects and arrays
   - Semantic descriptions for each field
   - Example usage patterns
   - Common workflow patterns where nodes are used together
   - Prerequisites and constraints

2. **Foundation for Better Planning**
   - Metadata that helps the planner understand node capabilities
   - Rich context about how nodes work together
   - Clear documentation of node behaviors and expectations

## What Was Discussed but Deferred to Task 15

### Two-Phase Context Building Architecture

During Task 14 implementation, we identified that the context builder could benefit from a two-phase approach:

**Phase 1: Discovery Context**
- Lightweight context focused on finding relevant nodes
- Includes node names, brief descriptions, and possibly tags (tags not implemented yet, and not needed for the MVP)
- Optimized for quick LLM processing to identify candidates
- Similar to a "search index" for nodes

**Phase 2: Implementation Context**
- Detailed context for selected nodes only
- Includes full metadata, examples, and usage patterns
- Focused context that doesn't overwhelm the LLM
- Provides everything needed for actual workflow generation

### Context Builder's Responsibility for Information Split

A critical architectural decision emerged from our discussions:

**The context builder is responsible for preparing and splitting the information.** Task 14 only provides enriched metadata - it's up to the context builder to decide how to present this information to the planner.

Specifically, the context builder will create exactly **two markdown files**:

1. **Node Selection File** (for discovery phase)
   - Contains ONLY node names and descriptions
   - Lightweight format for choosing which nodes to use
   - No technical details, just what each node does
   - Example:
     ```markdown
     ### github-get-issue
     Fetches issue details from GitHub

     ### read-file
     Reads content from a file
     ```

2. **Detailed Mapping File** (for implementation phase)
   - Contains full inputs/outputs/params with types
   - Includes structure information for complex outputs
   - Descriptions (if available) for each field
   - Nested structures (if available,)
   - Provides everything needed for the planner to map connections

This split serves a specific purpose:
- First file helps planner SELECT components without overwhelming detail
- Second file helps planner IMPLEMENT by showing how to connect components
- Task 14's enriched metadata makes both views possible from the same source

## Why These Changes Are Important

### Current Limitations
1. **Token Efficiency**: Current approach includes all metadata for all nodes, even when planning simple workflows
2. **Context Relevance**: LLM receives information about nodes it won't use, creating noise
3. **Scalability**: As more nodes are added, the context grows linearly, affecting performance
4. **Maintenance**: Single large context file becomes harder to update and verify

### Benefits of Two-Phase Approach
1. **Improved Planning Accuracy**: LLM can focus on relevant information at each phase
2. **Better Performance**: Reduced token usage and faster response times
3. **Scalability**: System remains efficient as node library grows
4. **Flexibility**: Different planning strategies can use different context combinations

## Key Insights from Discussions

### 1. Context is Not One-Size-Fits-All
Different planning phases need different types of information:
- Discovery needs breadth (all nodes, brief info)
- Implementation needs depth (selected nodes, full details)

### 2. Metadata Structure Enables Flexibility
The enriched metadata from Task 14 provides the foundation for generating different context views:
- Can extract just names and descriptions for discovery
- Can provide full details for implementation
- Can create specialized views (e.g., "all file operations")

### 3. Examples Are Crucial but Heavy
Workflow examples are valuable for the planner but add significant tokens:
- Should be included selectively based on discovered nodes
- Could be organized by pattern rather than by node
- Might benefit from a separate examples index

### 4. System Evolution Path
The two-phase approach sets up for future enhancements:
- Dynamic context generation based on user input
- Caching of common planning patterns
- Integration with vector search for large node libraries
- Potential for learned context selection

## How to Leverage Task 14's Work

### Available Foundation
1. **Rich Metadata Structure**: Use the Pydantic models for consistent metadata
2. **Extraction Infrastructure**: Build on the existing extraction patterns
3. **Test Coverage**: Extend the comprehensive tests for new functionality
4. **Documentation Patterns**: Follow the established documentation structure

### Recommended Approach for Task 15

1. **Start with Current Context Builder**
   - Understand how it generates the monolithic context
   - Identify how to split into the two required files

2. **Implement the Two-File Split**
   - Create `build_discovery_context()` → generates selection file
   - Create `build_planning_context()` → generates mapping file
   - Leverage Task 14's enriched metadata for both

3. **Key Implementation Points**
   - The context builder OWNS the split logic - it decides what goes where
   - Task 14 provides rich metadata; Task 15 creates smart views of it
   - Selection file must be minimal (names + descriptions only)
   - Mapping file includes all technical details for implementation

4. **Maintain Backward Compatibility**
   - Keep existing `build_context()` working
   - New two-file approach supplements, not replaces initially
   - Allow gradual migration of planner to use new format

## Critical Considerations

### Performance Metrics
- Measure token usage reduction in discovery phase
- Track planning accuracy with focused context
- Monitor overall planning time improvements

### Edge Cases
- Workflows that need many diverse nodes
- Discovery phase missing relevant nodes
- Balancing detail level in each phase

### Integration Points
- How planner communicates phase transitions
- Passing selected nodes between phases
- Handling context generation errors

## Summary

Task 15's primary responsibility is to implement the context builder's information split strategy:

1. **Take Task 14's enriched metadata** (types, structures, descriptions)
2. **Create two specific markdown files**:
   - Selection file: Names and descriptions only
   - Mapping file: Full technical details for implementation
3. **The context builder owns this logic** - it decides how to present information

This two-file approach enables efficient two-phase planning while leveraging all the rich metadata that Task 14 now provides. The key insight: Task 14 enriched the data, Task 15 makes it intelligently accessible.
