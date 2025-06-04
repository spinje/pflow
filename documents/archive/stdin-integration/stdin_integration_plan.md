# Plan for Integrating Shell Pipe Native Functionality into Core Documentation

This document outlines the plan to consistently integrate the concepts from `shell-pipe-native-integration.md` into the broader `pflow` documentation suite. The primary goal is to ensure that the handling of `stdin` is clearly and consistently described, aligning with the principle that piped input populates `shared["stdin"]`.

## Guiding Principles

1.  **Consistency**: Ensure all documents reflect the same mechanism for `stdin` handling.
2.  **Clarity**: Make it clear that `shared["stdin"]` is the primary recipient of piped data.
3.  **Minimalism**: Update as few documents as necessary, focusing on those where the information is most relevant.
4.  **Core Concepts Focus**: Emphasize the "what" and "why" in high-level documents (like the PRD), and the "how" in more specific specifications.
5.  **Address Review Feedback**: Incorporate recommendations from `stdin_integration_review.md`.

## Core Concepts from `shell-pipe-native-integration.md` to Integrate

1.  **Primary Recipient**: Piped input is placed into the shared store under the reserved key `shared["stdin"]`.
2.  **Node Consumption**:
    *   Nodes can be designed to naturally read from `shared["stdin"]` if their primary input key is not otherwise populated.
    *   Alternatively, the planner or CLI parsing can generate IR with explicit mappings from a node's input key to `shared["stdin"]`.
3.  **Natural Language Planner**: The NL planner is aware of piped input and will generate flows that correctly utilize `shared["stdin"]`.
4.  **Tracing and Caching**: Piped input stored in `shared["stdin"]` is hashed and participates in the standard tracing and caching mechanisms.

## Document Update Plan

### 1. `PRD-pflow.md` (Product Requirements Document)

*   **Goal**: Introduce shell pipe integration as a core usability feature and user workflow.
*   **Sections to Update**:
    *   **Section 1.1 (Strategic Differentiators) or 1.2 (Design Philosophy)**: Briefly mention native shell pipe integration as enhancing CLI usability and composability, aligning with "Explicit Over Magic" if `shared["stdin"]` is made clear.
    *   **Section 3.2 (Shared Store Pattern)**: Add a note or example that `stdin` from a shell pipe populates `shared["stdin"]`.
    *   **Section 5 (CLI Surface & Parameter Resolution)**:
        *   **Section 5.2 ("Type Flags; Engine Decides" Algorithm)**: Incorporate how piped input (`stdin`) interacts with this. Specifically, how `shared["stdin"]` is populated.
        *   **Section 5.2 (Resolution Examples)**: Ensure the example `echo "content" | pflow summarize-text` resulting in `shared["stdin"] = "content"` is prominent and consistent.
        *   **Section 5.6 (Reserved Keywords and Special Handling)**: Clearly list `stdin` as a reserved shared store key populated by piped input.
    *   **Section 8 (User Experience & Workflows)**:
        *   **Section 8.2/8.3 (Exploration/Learning)**: Add examples of using shell pipes in introductory workflows.
*   **Focus**: High-level concept, user benefit, and core interaction model. Avoid deep implementation details.

### 2. `shared-store-cli-runtime-specification.md`

*   **Goal**: Detail the CLI resolution mechanism for piped input and the role of `shared["stdin"]`.
*   **Sections to Update**:
    *   **Section 4 (Concepts & Terminology)**:
        *   In the table for `shared store`, explicitly mention `stdin` as a reserved key populated by shell pipes.
    *   **Section 7 (Execution pipeline & CLI resolution)**:
        *   Expand the resolution algorithm: Before step 1 or as an initial step, detect piped input. If present, populate `shared["stdin"]` with its content.
    *   **Section 8 (CLI scenarios)**:
        *   Ensure the scenario `cat notes.txt | pflow summarise-text` clearly shows `shared["stdin"]` being populated.
    *   **Section 11 (Validation rules)**:
        *   Rule 5: "`stdin` key reserved; node must handle it naturally" is good. We can add a note that "naturally" implies either direct consumption of `shared["stdin"]` or via an IR mapping orchestrated by the planner/CLI parser.
*   **Focus**: Precise runtime behavior, interaction with CLI flags, and the state of the shared store.

### 3. `planner-responsibility-functionality-spec.md`

*   **Goal**: Explain how the planner (both NL and CLI path) handles piped input.
*   **Sections to Update**:
    *   **Section 3.1 (Natural Language Path (Full Planner)) / 3.2 (CLI Pipe Syntax Path (Validation Planner))**:
        *   Add a step or consideration for detecting piped input early in the process.
    *   **Section 3.2.1 (Type Shadow Store Prevalidation)**: If `stdin` is detected, its type (likely `str` or `bytes`) can be added to the type shadow store as `stdin:type`.
    *   **Section E (Shared Store Modeling) / Section D (Shared Store Modeling for CLI path)**:
        *   When `stdin` is present, the planner should model `shared["stdin"]` as populated.
        *   The planner must decide how the first relevant node consumes this:
            *   If the node is known to check `shared["stdin"]`, no explicit mapping might be needed in the IR.
            *   Otherwise, the planner should generate an explicit mapping in the IR (e.g., `{"input_mappings": {"<node_primary_input>": "stdin"}}`).
    *   **Section 8.4 (Shared Store Schema Design)**:
        *   "Reserved Keys: `stdin` for piped input" is good. Reinforce this.
    *   **Section 10.1 (Complete JSON IR Schema)**:
        *   If the planner generates explicit mappings for `stdin`, an example IR could reflect this in the `mappings` section when `stdin` is involved.
*   **Focus**: Planner's awareness of `stdin`, how it influences IR generation (especially mappings), and ensuring flows are generated to correctly consume piped data.

### 4. `json-schema-for-flows-ir-and-nodesmetadata.md`

*   **Goal**: Ensure schemas and metadata conventions accommodate `stdin`.
*   **Sections to Update**:
    *   **Section 2.3 (Shared Key Declaration Requirements)**:
        *   Add a note or convention: Nodes that can process generic textual input piped via `stdin` should ideally document this capability. For instance, they might declare they can use `shared["stdin"]` if their primary named input (e.g., `shared["text"]`) is not provided. This is more of a "best practice" for node authors than a strict schema change.
    *   **Section 5 (Proxy Mapping Schema)**:
        *   An example mapping could show how `shared["stdin"]` is mapped to a specific node input:
            ```json
            {
              "mappings": {
                "my-text-processor": {
                  "input_mappings": {"text_input": "stdin"}
                }
              }
            }
            ```
*   **Focus**: How `stdin` (as a key in the shared store) interacts with IR mappings and how nodes might document their ability to use it.

### 5. `runtime-behavior-specification.md`

*   **Goal**: Briefly mention how `shared["stdin"]` participates in caching.
*   **Sections to Update**:
    *   **Section Caching Strategy / Cache Key Computation**:
        *   When describing `input_data_sha256`, clarify that if a node reads from `shared["stdin"]`, the content of `shared["stdin"]` will be part of this hash.
*   **Focus**: Ensure `stdin` data is correctly included in cache key calculations.

### Documents to *Not* Extensively Update (or only reference changes elsewhere)

*   `shared-store-node-proxy-architecture.md`: The core proxy architecture itself doesn't change due to `stdin`. The *data* (`shared["stdin"]`) can be a source for a mapping, but the proxy mechanism is agnostic to the key name `stdin`.
*   `node-discovery-namespacing-and-versioning.md`: `stdin` handling is a runtime/planner concern, not directly related to node discovery or versioning syntax.
*   `cli-autocomplete-spec.md`: The core `stdin` mechanism being documented elsewhere is the pre-requisite for any autocomplete hinting related to `stdin` as an input source.

## Action Item Summary

1.  **Revise `shell-pipe-native-integration.md`**: First, ensure `shell-pipe-native-integration.md` itself is updated to consistently state that piped input populates `shared["stdin"]`, and that any "automatic mapping" or node consumption is a secondary step (node convention or planner-generated IR mapping). This makes it a reliable source for the integration details.
2.  **Implement changes in `PRD-pflow.md`**: Focus on user-facing aspects and core concepts.
3.  **Implement changes in `shared-store-cli-runtime-specification.md`**: Detail CLI resolution and `stdin`'s role.
4.  **Implement changes in `planner-responsibility-functionality-spec.md`**: Detail planner's handling and IR generation.
5.  **Implement changes in `json-schema-for-flows-ir-and-nodesmetadata.md`**: Add notes on mappings and conventions.
6.  **Implement changes in `runtime-behavior-specification.md`**: Mention caching.
7.  **Review all updated documents** for consistency and clarity regarding `stdin` integration.

This plan prioritizes establishing `shared["stdin"]` as the canonical way piped input enters the `pflow` system and then detailing how various parts of the system (CLI, planner, runtime) interact with this. 