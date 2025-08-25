# Task 44: Build caching system

## Description
Implement node-level caching for flow_safe nodes

## Status
pending

## Dependencies
- Task 3

## Priority
medium

## Details
Create src/pflow/runtime/cache.py as optional performance optimization. Simple disk-based cache using pickle or json. Cache key = hash(node_type + params + inputs). Store in ~/.pflow/cache/. Only cache nodes marked as @flow_safe (deterministic). Start with just LLM nodes to save API costs. Can be disabled via --no-cache flag. This is not critical for MVP - implement only if performance becomes an issue. Reference docs: runtime.md#caching-strategy

## Test Strategy
Test cache hits/misses, key computation, and storage operations. Test cache invalidation.