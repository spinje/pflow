# Task 10: Create registry CLI commands

## ID
10

## Title
Create registry CLI commands

## Description
Implement CLI commands for registry operations: list, describe, and search nodes

## Status
pending

## Dependencies
- 2
- 5
- 7

## Priority
medium

## Details
Create `src/pflow/cli/registry.py`. Implement `pflow registry list` showing individual platform nodes, `pflow registry describe <node>` for detailed info with rich formatting for node-specific parameters. Part of enhanced registry infrastructure for fast lookups by node ID and capabilities. Reference docs: `registry.md`

## Test Strategy
Test CLI output formatting, search functionality, and error handling. Write integration tests for registry commands.