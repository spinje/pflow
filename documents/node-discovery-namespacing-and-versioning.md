# Node Discovery, Namespacing & Versioning

---

## 1 Identifier Syntax

```
<namespace>/<name>@<semver>

```

Examples\
`core/fetch_url@1.0.0` `mcp/weather.get@0.3.2` `vesperance/custom_embed@2.1.0`

### 1\.1 Namespace

- Lower-case, dot-separated: `[a-z0-9]+(\.[a-z0-9]+)*`

- Reserved roots: `core`, `mcp`.

- Collision isolation: identical names in different namespaces may co-exist.

- Example: [`vesperance.data`](vesperance.data)`.extractor`

### 1\.2 Name

- Lower-case, underscores allowed: `[a-z0-9_]+`

- Should match the Python file stem.

### 1\.3 Version

- Semantic versioning `MAJOR.MINOR.PATCH`.

- **MAJOR** bump ⇢ breaking interface change.

- **MINOR** bump ⇢ additive, backward-compatible.

- **PATCH** ⇢ bug-fix only.

- CLI shorthand `@1` ⇢ latest `1.x.x`.

- Pre-release versions (`1.0.0-beta`) are not supported in MVP.

---

## 2 Resolution Algorithm

1. **Lock-file present** → use pinned version.

2. **Single version installed** → use it.

3. **Multiple versions**:\
   • If CLI pins major (`@1`) → use highest `1.x.x`.\
   • If no pin → error, prompt user to specify.

4. **Latest-by-default is disallowed.**

5. **Locking** must be explicit via `pflow lock` to guarantee reproducibility.

---

## 3 File-system Layout

```
~/.pflow/nodes/
  ├─ core/
  │   └─ fetch_url/1.2.4/node.py
  ├─ mcp/
  │   └─ weather/get/0.3.2/node.py
  └─ <user ns>/...
site-packages/pflow/nodes/core/   # built-ins (read-only)
/usr/local/share/pflow/nodes/     # system registry
./nodes/                          # flow-local overrides

```

Search order: flow-local → user → system → built-in.

---

## 4 Installation Workflows

### 4\.1 Python File

```
pflow install my_node.py

```

Copies to `~/.pflow/nodes/<namespace>/<name>/<version>/`.

### 4\.2 MCP Server

```
pflow install-mcp https://mcp.weatherapi.com

```

- Generates wrapper nodes for all tools exposed by the server's `/tools/list` endpoint.

- Uses MCP tool name as `<tool_namespace>.<tool_name>`.

- If the MCP tool exposes version metadata, it is respected; otherwise, default to `0.0.0`.

- MCP nodes are installed under `mcp/<tool_namespace>/<tool_name>/<version>/`.

### 4\.3 Uninstall

```
pflow uninstall mcp/weather.get@0.3.2

```

---

## 5 Lock-files

All flows are resolved and executed through an internal JSON Intermediate Representation (IR), where all node references are fully qualified, including namespace and version. This means that even when the user writes shorthand CLI like:

```
pflow summarize >> save_file

```

…the system internally expands it to a version-pinned structure such as:

```
{
  "nodes": [
    {"id": "a", "type": "core/summarize@0.9.1", "params": {...}},
    {"id": "b", "type": "core/save_file@1.0.0", "params": {...}}
  ],
  "edges": [
    {"from": "a", "to": "b"}
  ]
}

```

This ensures reproducibility, even if the CLI syntax is simplified.

```
pflow lock     # emits flow.lock.json

```

```
pflow lock     # emits flow.lock.json

```

Example:

```
{
  "core/fetch_url": "1.2.4",
  "mcp/weather.get": "0.3.2"
}

```

Used for CI and reproducible runs. Required for version resolution without explicit CLI pinning.

---

## 6 CLI Grammar

> While versioned, fully-qualified node identifiers are necessary for deterministic or shared flows, most users will benefit from using simplified CLI syntax during local development. If a node name is globally unique and only one version is installed, the namespace and version can be omitted:
>
> ```
> pflow fetch_url --url https://example.com >> summarize >> save_file --path out.md
> 
> ```
>
> This clean syntax is preferred for day-to-day use and fast prototyping. If ambiguity arises (e.g., multiple nodes with the same name), pflow will request disambiguation or suggest alternatives. Locking the resolved versions via `pflow lock` ensures that even simplified flows remain reproducible.

```
<flow> ::= <node> [--param value] {>> <node> [--param value]}*
<node> ::= [<namespace>/]<name>[@<semver>]

```

- If the identifier is ambiguous, pflow aborts and lists candidates.

- Omitted version with lock-file pinned ⇒ resolved; without lock ⇒ error.

- CLI example with version pinning:

   ```
   pflow core/fetch_url@1.2.0 --url https://example.com >> core/summarize@0.9.1 >> core/save_file@1.0.0 --path out.md
   
   ```

---

## 7 Listing & Search

```
pflow list              # table of installed nodes
pflow search summarize  # fuzzy search across all registries

```

---

## 8 Conflict Rules

- Installing an already-present `<namespace>/<name>/<version>` without `--force` aborts.

- Different majors may coexist.

- Flow execution warns if two nodes in a single flow refer to different majors of the same name.

---

## 9 Rationale

Versioning prevents silent breakage, supports CI, and keeps agent-generated flows deterministic. Namespacing isolates responsibility and avoids collisions. Search order plus lock-files ensure portability across machines without global installs. Resolution behavior is explicit, testable, and repeatable.

---

*End of document*