I fully understand. I stand corrected on the "everything is an MCP" assumption. You have built a **Hybrid Runtime**:

1.  **Core Nodes** (LLM, HTTP, Agent) for the heavy lifting and flow control.
2.  **MCP Nodes** for external tool capabilities (the ecosystem leverage).
3.  **Shell/JQ Nodes** *strictly* for complex data transformation that the template engine can't handle (like mapping arrays or counting length).

The **Template Variable System** you documented is actually the "Robustness Layer" I was asking for.

Here is my analysis of why your `slack-qa-analyzer` works, and why it proves `pflow` is more than just a script runner:

### 1. The "Type Preservation" is the Killer Feature
This is the specific detail that changes my mind about the robustness:

> *If `token_limit=100` (int), the LLM node receives `max_tokens=100` (int), not `"100"` (str).*

In a standard bash script or naive workflow engine, everything gets flattened to a string. You constantly have to cast types (`parseInt()`, etc.).
In `pflow`, because `${identify-questions.response}` preserves the **List/Array type** coming out of the LLM node, you can pass it directly into a node that expects an array, or pipe it into `jq` as a structured JSON object.

**Why this matters:** It means your workflow state is **Rich Objects**, not just text streams. That is the definition of a robust runtime.

### 2. The Template Resolver *IS* the "Standard Library"
I previously argued you needed a "Core Logic MCP" to replace bash.
Looking at your docs, **the Template Resolver IS that core logic.**

You don't need a node to extract `user_id` from a JSON blob. You just write:
`${fetch.response.data.users[0].id}`

This eliminates 80% of the need for "glue code."
*   **Old way (Brittle):** Run a shell command to `grep` or `awk` a value.
*   **pflow way (Robust):** The runtime resolves the object path safely in memory.

### 3. The Role of `jq` in your example
In `slack-qa-analyzer`, you are using `jq` correctly: **for data shaping, not data moving.**

*   **Moving:** `${channel_id}` (Handled by Template Resolver)
*   **Shaping:** `jq 'length'` (Count items)
*   **Shaping:** `jq ... map(...)` (Transform JSON array into Markdown string)

This distinction is vital. You aren't using shell to *transport* data (which is risky); you are using it to *transform* data structure.

### 4. The "Auto-Parsing" Safety Net
> *Auto-Parsing JSON Strings: Node outputs JSON as a string, but next node needs dict/list... Auto-parses if size ≤ 10MB*

This solves the biggest pain point in LLM orchestration: **"The LLM gave me a string of JSON, but my code expects a Dict."**
By handling this at the framework level (the compiler), you remove the need for the user to write "Parse JSON" nodes after every LLM call. This makes the workflow graph cleaner and less prone to crashing on whitespace errors.

### Summary of Understanding

I see exactly what `pflow` is now:

It is a **State-Aware Execution Engine**.
*   **Input:** A JSON IR.
*   **State:** A standard Python/Dict object (`shared`).
*   **Logic:** A regex-based Template Resolver that traverses that object deeply.
*   **Execution:** Nodes (MCP, Core, Shell) that mutate that state.

The "Compiler" aspect ensures that all the `${template.paths}` actually exist in the schemas before you even run it.

**Verdict on the Example Workflow:**
The `slack-qa-analyzer` is robust because the data flow is strictly typed via the IR. The Shell nodes are sandboxed logic units, not structural dependencies. If you moved this to Windows, you'd only need to ensure `jq` is present (or replace those 3 nodes), but the **structure** of the workflow (the edges, inputs, params, LLM logic) remains 100% portable.

This is a solid architecture. It treats the **Prompt** and the **Data Structure** as first-class citizens, and the code execution as an implementation detail.