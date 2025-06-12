# Q&A pflow

## Phase 1: Critical Gaps in the Current Vision

1\. What kind of flows shouldn’t be expressible in pflow?

There are no limitations on what nodes that a user can create themselves.



2\. What is the unit of trust and debuggability?

I changed my mind, I dont want an agent to generate nodes, but only the flows. At least to start with. And when I start I will focus on only writing code for wrapping mcp serers.



I like the notion of being able to cache any flow or node output on demand, with an argument or something. But it should not be default behavior.



Flows will always include a description for when they should be used, input / output so that the llm responsible for putting together flows can know which ones are available.



3\. Is pflow for authoring or running—or both?

the feature to go from natural language → executable graph is a key featureas it enables **non-programmers**, **ops engineers**, or **exploratory workflows** to start from nothing.\
\
What isnt necessary here is to create new nodes, just reuse the ones that exist. Also making flow plans visible and editable before execution could really enhance learning and interoperability and transparency.



Flow Execution, is the most important part here with focus on making `Flow` execution **minimal, traceable, and modular.**



Add `pflow trace` or even`pflow explain` to visualize the DAG and intermediate values in the cli is a key feature.

\
I want to support easy installation of mcps, but other than that there is not a focus on node installation until it has been requested by users. Advanced users can write their own code for nodes or let programs like claude code generate it for them.\
\
I wont have focus on generating code for custom nodes inside the cli. (but i will experiment with this later)\
\
4\. What is the power ceiling of a Node?

the most important thing here is that the nodes modify the shared store in predictable ways that is clear (just as clear as input / outputs) and that writes to the shared store follow common practices.



We should NOT allow a node to: modify other nodes, rewire flow

But we should allow: write files, access internet, use APIs etc

For spawning subprocesses special care have to be taken and should not be implemented in this first step.\
All privileges modifying any state outside the flow should be declared as metadata to the node.

\
5\. What does the user experience *decay curve* look like?

Traceability of what went wrong is absolutely necessary. This is not only important for the user but also for the LLM responsible for creating the flow to fix it based on feedback.

Everything should be represented visually in the cli.

The **pflow experience should not decay silently or catastrophically.**\
It should **fracture visibly**, **explain itself**, and **leave artifacts** that allow the user to grow in understanding.

\
Before the final flowchain is run it needs to be accepted by the user.



6. **Where does the power *peak*?**

The power peaks when pflow transform natural intent into composable, declarative, debuggable flows.



What I will focus on is:\
**Flow composition using existing nodes.**

**Suggestions for new nodes (maybe mcps?), not code.**

Clean and easy way to manually create, debug and reuse flows.



Generating nodes on the fly is very interesting but it will be something I experiment after building an mvp, and will probably use an external tool like claude code as a plugin for generating each node (infusing claude code with the right documentation for creating pocketflow code. One other interesting thing I can do here is first generate the ideal workflow (including nodes that does not exist yet) then create the missing nodes in parallell using claude code.

## Phase 2: Architectural Tension Points

1. Node as class vs function vs template?

a. Are nodes Python classes forever?

No, nodes might not be Python classes forever. But the class-based form should remain the canonical low-level interface because it encapsulates lifecycle (`prep`, `exec`, `post`).



Nodes have a fluid interface that is defined by what they expose through their `params` contract and how they interpret those `params` to interact with the `shared` store.

They do not have fixed input or output keys hardcoded in their logic. Instead, each node’s behavior is parameterized by external configuration that tells it:

- where in `shared` to read its input from

- where in `shared` to write its output to

- any additional behavioral configuration (e.g., `model_name`, `threshold`, `mode`, `count`etc etc)

This interface is therefore not static. It adapts to the flow it’s embedded in, based on what that flow defines as its memory layout. The flow (human-authored or LLM-generated) becomes the point where interfaces are wired and semantics are assigned.

Because of this indirection, a single node implementation can serve many different contexts without modification. Its operational signature is stable, but its I/O shape is contextual.

This allows nodes to behave more like functions bound at runtime with environment-specific memory mappings—resulting in highly composable and decoupled behavior across varied workflows.



b. Should you support `@node`\-decorated Python functions?

Not initially, but it is not excluded.



c. Do you envision a future where people author in YAML, or even through the CLI?

**No, `pflow` does not and should not support YAML as a primary authoring format.**

YAML is optimized for declarative configuration, not for dynamic composition, graph mutation, or introspection. It obscures control flow, lacks typing discipline, and introduces ambiguity (e.g., indentation, type coercion) that is incompatible with the structured reasoning needs of agentic systems.

Instead, `pflow` supports **two orthogonal authoring modes**:

1. **Python class-based nodes and flows**\
   This is the canonical, low-level interface. Nodes are written as classes implementing `prep`, `exec`, and `post`. Flows are defined as explicit `>>` chains. This gives full control, testability, and integration with the Python ecosystem. It’s the only layer where custom logic is authored.

2. **JSON IR** (Intermediate Representation)\
   JSON is the structure that agents, GUIs, and CLI flows operate on. It defines:

   - The nodes involved (`type`, `params`)

   - The transitions (`from`, `to`)

   - The shared-store wiring

   - The flow topology

   This is the layer used for:

   - Agent-generated flows

   - Graph mutation and inspection

   - Serialization and traceability

   - CLI-to-agent delegation (e.g., `pflow "summarize doc and save to `[`out.md`](out.md)`"` → JSON IR → Python flow)

The CLI is supported in two ways:

- As a natural language interface that delegates to the agent and IR system.

- As a structured pipe syntax using `>>`, which allows direct execution of previously installed nodes without needing to define a full flow in code.

The `>>` syntax is **not a new authoring language**. It’s a lightweight execution shortcut for chaining known nodes with inferred or default `params`. The underlying flow is still assembled and executed through the IR layer.

**Summary**\
`pflow` supports:

- Python classes for logic

- JSON IR for structure

- CLI for intent and rapid composition via `>>`

It explicitly avoids YAML to maintain structural fidelity, tooling precision, and execution determinism. JSON is the unambiguous, introspectable substrate. YAML adds no unique value and would increase friction for agents, validators, and future GUIs.

Are nodes Python classes forever?Are nodes Python classes forever?



2. Stateless vs Stateful? Do you think pflow should support:



a. Long-lived flows that can resume (e.g. `pflow resume job123`)?

This is a valuable feature but it is not a focus until it is requested by users and the mvp and shared-store/params discipline is fully stable since checkpointing relies on deterministic shared mutations. However, the architecture with shared-store/params should be fully supportive of this when the time comes for it by storing serialized `shared`objects and tracking which nodes have completed.



b. Per-user memory (e.g. `pflow chatbot` remembers previous docs)?

No—in core `pflow`, this breaks composability. For specific usecases this can be achieved by:

- Explicitly injecting this context into `shared` before flow start

- Loaded via a preparatory node (e.g., `LoadUserMemoryNode`)



c. Global side effects?

Yes—but strictly controlled, and opt-in.

Examples:

- Writing to disk

- Posting to Slack

- Making DB inserts

These should:

- Be clearly marked (e.g., `SideEffectNode`)

- Require user-supplied configuration (e.g., paths, tokens)

- Be tracked in flow logs

- Be mockable for test runs

Flows should be **declarative in structure**, and **side effects should be boundary steps**, not implicit actions.

We  want the power of effectful system, but with the auditability of pure one. This means aide effects should ideally be isolated to specific, visible nodes at the *end* or *edges* of the flow, not embedded invisibly within intermediate logic.



3. Agent Codegen Scope. What functionality does pflow agent support?



a. Generate new Nodes?

To start it would only be able to generate wrappers for mcp servers (this could probably even be done deterministically and not even needing an llm to power it)



b. Modify existing Flows?

Yes, but this is not a core feature. It will come after the mvp. To start with regeneration of flows / deletion is the substitute for this. The agent should never directly rewrite Python flow files. It should always operate over IR only.



c. Register Nodes automatically?

Only verified mcp servers to start with or mcp servers/python files manually added by the user.



d. What safeguards are needed?

Validate all flow IR before execution. Enforce schema constraints, cycle detection, missing bindings, and type mismatches.



e. How does user consent work?

Nodes from the curated mcp list can be suggested for registration but must always be accepted by the user before creation/installation.

When asking for a flow with natural language the user always gets to see the resulting cli command that is about to be executed.

This serves multiple purposes:

- **Transparency**\
   The user sees exactly what will run. There is no hidden logic or opaque plan execution.

- **Editability**\
   The user can copy, edit, rerun, or version this command. It becomes a portable representation of intent.

- **Confirmability**\
   No flow is executed blindly. The user always reviews the plan before execution (unless `--auto` is set).

- **Auditability**\
   The command string can be logged, compared, or embedded in documentation. It becomes part of the system’s traceable interface.

- **Composability**\
   The CLI chain maps cleanly to a JSON IR, which the agent uses internally. But the user sees the human-friendly form.

- **Correctability**\
   If the plan is wrong, the user can say:

   - “Change the output to summary.txt”

   - “Use claude instead of gpt-4o”

   - “Add a step to translate before writing”

   And the agent updates the CLI representation, not hidden state.

The CLI is not just an interface—it is the **canonical output format of the planning layer**, and the **unified point of validation** between user, agent, and system.



## Phase 3: Questions You Must Lock Down to Finalize the PRD



1. **What flows should not be possible in pflow?**

Flows that should not be possible in `pflow`:

- **Flows requiring interactive state mid-node execution**\
   Nodes are not designed to pause, await user input, or handle asynchronous external signals during `exec()`. They are strictly `prep → exec → post`.

   - Blocking inside `exec()` (like `record_audio()`) is allowed because it's a bounded, single-shot I/O operation—not interactive control flow. What’s disallowed is pausing for user input or events mid-execution in an unstructured way (like `input()` or UI polling). Nodes must execute linearly and complete; any coordination or looping happens at the flow level.

- **Flows requiring complex dynamic control flow (e.g., loops, branches, retries) embedded in node internals**\
   All such logic should live at the flow level. Nodes are atomic; they should not control execution paths.

- **Flows relying on implicit, undeclared shared keys**\
   Any node that reads or writes to undeclared keys in `shared` breaks modularity and traceability. These flows should be blocked or rejected.

- **Flows that rewire shared keys at runtime inside node logic**\
   Key routing should be defined in `params`, not constructed dynamically. Nodes should not generate or resolve their own shared paths.

- **Flows that use the shared store for persistent side effects (e.g., as a database)**\
   The shared store is transient and per-run. It is not a persistent cache, log, or external I/O layer. Flows that expect the shared store to survive restarts or reruns are misusing the abstraction.

- **Flows that require node-local memory across runs**\
   Nodes are stateless between executions. Stateful behaviors must be expressed through `shared`, external storage, or flow-level orchestration.

- **Flows that bypass the shared store entirely**\
   If a flow is entirely `params`\-driven with no use of `shared`, it’s likely better expressed as a traditional function composition system or as shell pipelines. `pflow` is designed for coordinated multi-step systems, not stateless wrappers.

- **Flows that modify other flows or their nodes at runtime**\
   Flows are static during execution. Runtime flow mutation (e.g., inserting nodes mid-run) introduces instability and impairs auditability. Agent-generated flows must be finalized before execution.

- **Flows that assume shared store key collisions are resolved automatically**\
   There is no namespacing or versioning built-in to prevent collisions. Flows relying on “best effort” merges or key overrides are considered ill-formed.

- **Flows that rely on implicit external global state**\
   All state dependencies must be explicit in `params` or `shared`. If a node assumes a global model configuration, API key, or external file without it being passed through the flow, the flow is non-reproducible and invalid. Some of these params are however hidden from the cli layer. The cli commands shown or created by the users should be able to be as minimalistic as possible.

- **Flows where nodes reference shared keys directly instead of via `params`**\
   Nodes must not hardcode paths into the `shared` store (e.g., `shared["input"]`, `shared["result"]`). All shared key access must be routed through `params` (e.g., `params["input_key"]`, `params["output_key"]`). This ensures nodes remain decoupled from any one flow’s schema, enabling reuse, flow-level schema control, and LLM-based planning. Flows with embedded shared key paths in node logic are considered non-modular and invalid.

These boundaries define what `pflow` is optimized for: reproducible, inspectable, modular execution graphs with localized logic and centralized coordination. Any pattern violating those constraints erodes composability, safety, or clarity.



2. What is the minimal user mental model?

**Minimal user mental model for `pflow`:**

> A flow is a sequence of steps. Each step does something with data and passes it forward. I don’t need to manage how data is routed between steps—pflow handles that for me but can show me exactly what is happening between each step if I want to.

In more precise terms:

1. **Flows are pipelines.**
   You connect steps using `>>`, just like Unix pipes:

   ```
   pflow fetch_docs >> summarize >> save_file
   ```

2. **Steps (nodes) are generic tools.**
   Each step expects an input and produces an output, but doesn’t care where that data comes from or goes to. That’s handled internally.

3. **The system wires everything.**
   You don’t specify internal memory keys or configuration bindings unless you want to. The system (or an LLM) figures out how the outputs of one step become the inputs of the next.

4. **You can inspect the result.**
   If something goes wrong or you want to learn more, you can ask `pflow` to show what data moved between steps, or what a node did.

What the user does **not** need to know:

- The concept of `shared` or `params`

- How keys are routed between nodes

- How memory is named or scoped

- How the flow schema is constructed

They just:

- Describe a task

- Compose steps

- Run the flow

Optional: inspect and refine if needed.



3. What’s your position on state and purity? Are all nodes expected to be pure, or can some mutate the world?

- Nodes are **pure by default**: read from `shared`, write to `shared`, no side effects.

- **Side-effecting nodes are allowed**, but must be **explicit**, **inspectable**, and **declared**.

- No hidden I/O, no global mutations.

- Flow planning and testing assume purity unless specified.

- Dry-run and traceability must support both pure and impure nodes.



4. Will all nodes be written in Python? Or do you want to allow JSON-defined flows, function-style nodes, or even GUI building later?

- All nodes = Python.

- Flows = interoperable across JSON, CLI (potentially GUI in the future)

- Keep logic centralized, keep composition flexible.



5. **What happens if a node fails mid-batch?** Should `pflow` retry, skip, pause? Where’s the resilience layer?

Caching and retry functionality should be implemented as soon as everything else is stable and working.



6. **Should flows be shareable across teams with zero code change?** What are the assumptions about environment, data, permissions?

Flows are shared as JSON. With suggestions to install for missing verified MCP servers and warnings/errors for other missing nodes.



7. What is the top-level object of modular reuse? Nodes? Flows? Pipelines? Plugins? Function Packs?

- **Nodes** are the **atomic unit of modular reuse**. They encapsulate logic, operate on `shared` via `params`, and are composable across flows. Think of them as functions or shell commands.

- **Flows** are the **unit of executable reuse**. They define a complete plan—composed of nodes—that can be saved, versioned, run, or nested inside other flows. They are the artifact users return to and agents generate.

- Nodes are reused *within* flows; flows are reused *between* workflows.

- This two-tier model allows developers to maintain logic at the node level, while users and agents orchestrate tasks at the flow level.

- Flows can eventually be reused as **subflows** (flow-as-node), but their compositional substrate remains the node.



8. Will there be an opinionated way to write tests for nodes/flows? If not, how do you build trust in large systems?

- **Yes, testing must be built-in**. Without it, node reuse and agent-planned flows are untrustworthy at scale.

- **Nodes** are tested by executing them with test `params` and a known `shared` dict, then asserting expected changes to `shared`.

- **Flows** are tested by running them on known input `shared` and checking for output keys or value structures.

- **Tests should be minimal**: no mocks, no scaffolding, \~5 lines per test.

- **Expose via CLI**:\
   `pflow test node_name`\
   `pflow test flow_name`\
   `pflow validate flow.json`

- **Goal**: Make behavior verifiable, shared-schema changes safe, and agent-generated flows auditable.



9. **Should nodes be aware of each other?** Or are they dumb pipes? (e.g., can `NodeB` say “skip if `NodeA` returned X”?)

Nodes should not be aware of each other. They are not actors, agents, or branches—they are **pure computation units**: isolated, stateless, and single-responsibility. This is deliberate.

Nodes should be **dumb pipes**. NodeB should not be aware of NodeA.\
NodeB should never say “skip if NodeA returned X.”

If conditional execution is required, it belongs in the **flow logic**, not inside the node.

Let nodes:

- Operate on keys in `shared`

- Know only what they’re told via `params`

- Never know who else is in the graph

This preserves:

- Composability

- Isolation

- Auditability

- Flow-level control

Letting nodes introspect peer behavior breaks modularity and entangles execution paths.



10. **Is your primary differentiation agentic planning, structured composition, or tool interoperability (e.g. MCP)?** Pick one *first* to prioritize.201



`pflow`'s primary differentiator is **structured composition**:

- Declarative, memory-aware flows

- Reusable, parameterized nodes

- Explicit control over data movement and logic

- CLI-native orchestration with agent and tool integration layered on top

Agentic planning and MCP support are powerful extensions, but they are only valuable because the underlying system has a coherent structure to operate within. Without structured composition, there’s nothing worth planning or interoperating with.
