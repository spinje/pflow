# Planning Instructions

Based on the context provided above (user request, requirements, components, and details), create an execution plan.

## Your Task

Create a detailed execution plan that:
1. Maps requirements to specific nodes
2. Determines the execution order
3. Identifies data flow between nodes
4. Assesses feasibility

## Planning Rules

### Node Constraints
- You can ONLY use nodes from the "Available Nodes" listed in the context above
- You cannot suggest nodes that aren't listed
- You should never use more nodes that are not explicitly needed to suffice the user's request
- If an available node is not needed, do not use it
- If a required capability is missing, mark as IMPOSSIBLE or PARTIAL

### Node Chain Format
- Use the `>>` operator to show execution flow
- Example: `read-file >> llm >> write-file`
- Nodes execute left to right
- Each node's output becomes the next node's

### Write complete specification
- Write what nodes to use and in what order
- Write what inputs to use for each node
- Write what outputs to use for each node
- Write about all the data flow between nodes and be clear about what data comes from other nodes and what comes from the user (workflow inputs)
- The specification should be complete and detailed enough to be used to generate the workflow

### Feasibility Assessment

**FEASIBLE**: All requirements can be fulfilled with available components
- Every requirement maps to one or more nodes
- Data flows logically between nodes
- All required capabilities are available

**PARTIAL**: Some requirements can be fulfilled
- Core functionality possible but some features missing
- Identify which requirements cannot be met
- Suggest workarounds if possible

**IMPOSSIBLE**: Critical requirements cannot be fulfilled
- Missing essential capabilities
- No viable workarounds available
- Explain what's missing

## Output Format

Provide your analysis as natural text, explaining your reasoning. End your response with a structured assessment:

### Feasibility Assessment
**Status**: [FEASIBLE/PARTIAL/IMPOSSIBLE]
**Node Chain**: [node1 >> node2 >> node3]
**Missing Capabilities**: [capability1, capability2] (if any)

## Examples

### Example 1: Feasible Plan
"The user wants to analyze a file and generate a summary. I have read-file to get the content, llm to analyze it, and write-file to save the result. The data flows naturally: file content → analysis → output file.

#### Feasibility Assessment
**Status**: FEASIBLE
**Node Chain**: read-file >> llm >> write-file
**Missing Capabilities**: None

### Example 2: Partial Plan
"The user wants to retrieve and send messages to slack but I have no specialized mcp nodes available. I could theoretically use use the http node to retrieve the messages using the slack api but the user has not provided any slack api key or token or any other documentation about how to use the slack api. I should not rely on my own assumptions and internal training data and should instead mark this as PARTIAL and suggest the user to provide the necessary documentation and credentials if needed.

#### Feasibility Assessment
**Status**: PARTIAL
**Node Chain**: http >> llm >> http
**Missing Capabilities**: slack_documentation, slack_api_key, slack_api_token

### Example 2: Impossible Plan
"The user wants to deploy to Kubernetes, but I don't have any Kubernetes or deployment nodes available. This requirement cannot be fulfilled with the current components.

#### Feasibility Assessment
**Status**: IMPOSSIBLE
**Node Chain**: None
**Missing Capabilities**: kubernetes_deployment, container_management