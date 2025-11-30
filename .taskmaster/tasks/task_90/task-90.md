# Task 90: Expose Individual Workflows as Remote HTTP MCP Servers

## ID
90

## Title
Expose Individual Workflows as Remote HTTP MCP Servers

## Description
Enable pflow cloud users to publish individual workflows as standalone remote HTTP MCP servers that can be installed into any MCP-compatible agent (Claude Desktop, ChatGPT, Cursor, etc.). This complements the existing full pflow MCP interface by providing a simpler, turnkey distribution mechanism for workflows.

## Status
not started

## Dependencies
- Task 72: Implement MCP Server for pflow - The existing pflow MCP server infrastructure provides the foundation for exposing workflow execution capabilities
- Task 47: Implement MCP HTTP transport - HTTP/SSE transport support is required for remote MCP server functionality

## Priority
medium

## Details
This feature introduces a two-tier model for pflow's MCP capabilities:

### Current State (Build Layer)
The full pflow MCP interface exposes 11 tools for workflow discovery, building, and execution. This is a developer/power-user API that requires understanding workflow composition.

### Proposed Feature (Distribute Layer)
Individual workflows can be "published" as standalone MCP servers with their own HTTP endpoints. Each published workflow appears as a simple, single-purpose tool with documented inputs/outputs.

**Example:**
- User builds a workflow that monitors GitHub PRs and posts to Slack
- User publishes it as a standalone MCP: `https://pflow.cloud/mcp/u/alice/pr-notifier`
- Anyone can install this URL into ChatGPT, Claude Desktop, etc.
- The workflow appears as a single tool: `notify_about_prs(repo, channel)`

### Why This Matters

1. **Simpler Mental Model**: Users think "I want this capability" not "I want to compose nodes"

2. **Lower Trust Barrier**: A single-purpose workflow tool is easier to trust than full workflow-building API access

3. **Distribution Path**: Enables sharing, team capabilities, and potential monetization of workflows

4. **Works with Less Sophisticated Agents**: Simple tools work everywhere; the full pflow API requires agents capable of workflow composition

5. **Solves Server Sprawl**: Instead of installing dozens of MCP servers, users install one workflow that orchestrates all of them

### Technical Approach (Conceptual)
- Single pflow cloud infrastructure serves all published workflow endpoints
- URL routing determines which workflow to expose
- Each endpoint dynamically generates MCP tool definitions from the workflow's declared inputs/outputs
- Authentication and ownership validation at the routing layer

### Scope Considerations
This is a pflow cloud feature, not a local CLI feature. Implementation details depend on the cloud infrastructure architecture which is not yet defined.

## Test Strategy
Testing approach will depend on implementation details. Key areas to consider:

- Unit tests for MCP endpoint generation from workflow IR
- Integration tests for workflow execution through HTTP MCP transport
- Security tests for authentication and authorization
- End-to-end tests with actual MCP clients (if feasible)

Detailed test criteria to be defined when implementation approach is finalized.
