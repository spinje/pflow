# Task 118 Part 2 — review-falsifier report (direct launch, on `3d14aba2`)

Launched by the task orchestrator after the reading battery's fixes landed. Probes and outputs:
`/private/tmp/claude-501/-Users-andfal-projects-pflow/c22e27cc-bfb0-4a16-8d61-2e5c3482f785/scratchpad/falsifier-t118p2/`
(session scratch — not durable). "OLD" = the main checkout at `a42f55e2` (Part 1 only).

## Claim ledger (verdicts)

| # | Claim | Verdict |
|---|---|---|
| 1 | No old-form leftover runs silently wrong — nested child, file-loaded batch, loop carry, MCP validate/execute dict IR, `compile_workflow`, saved-by-OLD then run by NEW, NEW save, OLD-failed then NEW resume (file, id, `--force`), `--dry-run` | HOLDS — ruled ERROR with the fix everywhere; no node ran |
| 2 | sh expansion forms on in-scope names caught (17 forms incl. `${limit:=5}`, `${limit+set}`, `${!limit}`, `${limit^^}`, `${#limit[@]}`, `${item[0]}`, `${__index__}`) | HOLDS (`${ item }` runs and sh fails loudly — OLD rejected it as malformed) |
| 3 | Legal sh / awk / jq / node bodies run unescaped | HOLDS except W1 and S2 |
| 4 | `$${` in a body is an error pointing at the new rule | FALSIFIED (edge) — W1 |
| 5 | Code body `"${name}"` fails (bytes, raw, implicit concat, triple-quoted, dict key); ruled f-string case not flagged | HOLDS |
| 6 | `env:` binds decided text; JSON-looking strings unchanged when bound directly; whole-map form | HOLDS |
| 7 | Binding failures pre-spawn, per item, never an exit code (parallel `continue` batch: NUL, 1.5 MB) | HOLDS |
| 8 | Failure block / JSON / `pflow report` show body + values, masked by name; OLD-version trace renders | HOLDS (`BEARER`/`COOKIE`/`GH_PAT` clear by the pre-existing word rule) |
| 9 | File-loaded bodies incl. save + bundle + rerun by name | HOLDS |
| 10 | Tooling workflows validate; `resolve-cwd` with a hostile path and the empty default | HOLDS |
| 11 | Graph / web UI draw nothing from a body, `env:` draws (fresh `pflow ui` :8797, killed) | HOLDS |
| 12 | MCP single-node run leaves the body alone, expands `env:` | HOLDS |
| 13 | `--validate-only` and run agree (JSON `body_references`) | HOLDS |
| 14 | `--only` reruns with `env:` bound | HOLDS |
| 15 | Literal dangerous-command block still fires | HOLDS |

Not attacked: Windows (CI); real paid searcher/fan-out runs (validated only); the value-driven dangerous case
(documented, destructive); the web gate answer panel; inline workflow text on stdin.

## Critical
None.

## Warnings

**W1 — `\$${NAME}` (a literal dollar, then a braced variable) is rejected with a false diagnosis; following the fix
silently produces the wrong output.** `_escapes` (`core/workflow/data_flow.py:1046-1053`) exempts only a preceding
`$`, not `\`; the message (`:1339-1351`) then claims "sh would run $$ as its process id". The ruled dollar repair is
`\$$NAME` and the guide (`guide/nodes/shell.md:53`) says brace the name where a letter/digit/`_` follows, so
`"\$${COST}USD"` is legal sh (`COST=4.50 sh -c 'echo "price: \$${COST}USD"'` → `price: $4.50USD`). Repro: shell step
`env: {COST: "4.50"}`, body `echo "price: \$${COST}USD"` → ERROR `…the escape $${COST} … sh would run $$ as its process
id…` / `→ Write ${COST} for a shell expansion.`; following it gives `price: ${COST}USD`. In its favour: under OLD,
`\$${COST}` meant a literal `${COST}` (OLD printed `price: ${COST}USD`), so the error does guard an old-form meaning
change. The defect is the diagnosis and the fix for the new-form intent: recognise a preceding `\`, state both
readings, offer `\$"${COST}"USD` (or `\$$COST""USD`). No test covers a preceding backslash.

## Suggestions

**S1 — the terminal approval preview shows typed values where the command receives `to_string` text**
(`"DRY_RUN": true, "NOTE": null` vs the run's `dry=[True] note=[]`; the env line is also cut at `… (215 chars)`,
hiding `VERSION`). Recorded plan decision D11 (preview unchanged, out of scope) — not a defect against the plan, but
before Part 2 the approver saw the resolved command text (`True`); worth a follow-up next to the web per-item preview.

**S2 — a `${input}` inside a shell comment is a blocking error** (`# … ${limit}` → leftover ERROR). Follows the ruled
"read the body whole"; OLD resolved it harmlessly. Low frequency.

## Summary
No surface reached runs an old-form workflow wrong; every path stops before any node with the same structured
error at validate-only and at run. `env:` held against hostile and typed values; web/graph behaved on a fresh server.
Two edges: W1 (the `$${` message misfires on `\$${NAME}`) and S1 (approval preview typed values, D11).
