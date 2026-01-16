
We need to evaluate if this makes sense / is a new task or if it should be taken into consideration when implementing task 104.

If you are reading this, STOP and ask yourself and the user how this is relevant to task 104 before doing anything else.


---

You are correctly sensing the danger. **Do not add filters (pipes) to your template syntax.**

If you add `${var | upper | join(',')}`, you are walking off a cliff. You will end up writing a buggy, half-baked parser for a string processing language inside a JSON string. You will spend the next 6 months debugging regex edge cases instead of building workflow compilation.

You are building **Infrastructure**, not a templating engine.

### The "Right" Move: The `jmespath` Node

You are currently using `jq` via `shell` nodes. `jq` is amazing, but it's an external binary.
The Python equivalent that is industry-standard, safe, deterministic, and cross-platform is **JMESPath**.

It allows you to do the mapping, filtering, and projection you are currently doing with `jq`, but it runs natively inside your Python runtime (no process tax, no OS dependencies).

**The New Node Type: `expression` (or `transform`)**

Instead of a "Logic Node" that feels like code, use a "Query Node" that uses a standard spec.

#### How to replace your `jq` nodes cleanly:

**1. The Filter/Map Node (Replacing `extract-messages-json`)**
*   **Current (Bash/JQ):**
    ```json
    "command": "jq -c '.data.messages'"
    ```
*   **New (JMESPath):**
    ```json
    {
      "id": "extract-messages",
      "type": "transform",
      "params": {
        "data": "${fetch-messages.result}",
        "query": "data.messages"
      }
    }
    ```

**2. The Complex Logic Node (Replacing `prepare-sheets-data`)**
*   **Current (Bash/JQ):**
    ```json
    "command": "jq -c ... 'map([$date, $time, .question, .answer])'"
    ```
*   **New (JMESPath):**
    ```json
    {
      "id": "prepare-sheets-data",
      "type": "transform",
      "params": {
        "data": "${parse-qa-pairs.stdout}",
        "query": "[].[@.date, @.time, question, answer]" // JMESPath projection
      }
    }
    ```

### The Missing Piece: Text Formatting (Jinja2)

JMESPath is great for JSON-to-JSON. It sucks for JSON-to-Text (like your Slack message formatting).
For Node 8 (`format-slack-message`), do not use logic. Use a **Template Node**.

Since `pflow` is Python, just use **Jinja2**. It is the standard. It is safe (sandboxed). It handles loops and formatting natively.

**3. The Text Node (Replacing `format-slack-message`)**
*   **Current (Bash/JQ):**
    ```bash
    jq -r '...map("**Question:** " + .question...) | join...'
    ```
*   **New (Jinja2):**
    ```json
    {
      "id": "format-slack-message",
      "type": "template",
      "params": {
        "data": "${parse-qa-pairs.stdout}",
        "template": "# Q&A Summary\n\n{% for item in data %}\n**Question:** {{ item.question }}\n**Answer:** {{ item.answer }}\n\n---\n\n{% endfor %}"
      }
    }
    ```

### Why this Architecture Wins

1.  **Separation of Concerns:**
    *   `${...}` is for **Access** (getting data from A to B).
    *   `transform` (JMESPath) is for **Structure** (reshaping JSON).
    *   `template` (Jinja2) is for **Presentation** (making text).
2.  **No "Programming":** You aren't writing `if/else` blocks in Python. You are using declarative standards.
3.  **Agent Friendly:** LLMs represent data transformations very well in JMESPath and text generation very well in Jinja2. They struggle with complex `jq` one-liners.
4.  **Safety:** Neither JMESPath nor Jinja2 (in sandbox mode) can delete files or make network requests. Your `shell` node can.

### Summary Recommendation

**Stop using `shell` nodes for logic.**
Implement two "Core Nodes" (built into the pflow runtime, exposed as pseudo-MCP tools if you want):

1.  **`core.transform`**: Accepts `data` (JSON) and `query` (JMESPath string). Returns JSON.
2.  **`core.render`**: Accepts `context` (JSON) and `template` (Jinja2 string). Returns String.

This removes your Windows incompatibility, removes the `jq` dependency, and keeps your JSON IR clean without inventing a new language.