# Visualization

**Use when**: the USER wants to *see* a workflow — open it for them in the browser, most
often while you build or edit one so they watch it take shape. Two tools, two audiences.

> You do NOT need a diagram to understand a workflow. The `.pflow.md` source already
> shows its structure, branches, and `${...}` data-flow directly — read the file. These
> tools are for the *human* (the live canvas) or for an explicit diagram request.

## `pflow ui` — interactive canvas, FOR THE USER

A local browser canvas: collapsible sub-workflow/batch/loop containers, click-to-read
prompts and params, `${ref}` connection lines, and a source pane. An agent can't read a
browser — this is for the human.

**When the user wants to SEE the workflow** — "show me", "let me see/watch it", "open
it" — OPEN it for them: `pflow ui <workflow>` serves the canvas and opens their browser
automatically (they asked; don't just offer). While building or editing and they *haven't* asked, you
can OFFER it proactively. Either way it live-updates as you edit, so they watch it take
shape as you work.

- It serves until you stop it (`Ctrl+C`), so run it in the BACKGROUND — don't block on it
  (use your runtime's background mechanism, not necessarily a shell `&`).
- The canvas LIVE-UPDATES in place (no page reload) as you edit the `.pflow.md` — the
  user sees each change land while keeping their zoom and focus. An edit that doesn't
  validate is held (the last valid version stays up, with an error banner) until you fix it.
- With no workflow argument, it opens the catalog of saved workflows.
- Flags: `--port N` (default 8765), `--no-open` (don't open a browser), `--no-watch`
  (freeze — stop live-updating).

Deep-link a specific view (to point the user at a node, or for a screenshot): append
`?workflow=<name-or-path>&focus=<node-id>` — `focus=` highlights the node and reveals its
connections; add `&node=<node-id>` to also center the camera, or `&direction=TD` for top-down.

## `pflow mermaid` — Mermaid diagram text (niche)

Emits a Mermaid flowchart of the workflow to stdout. Use this ONLY when the user
explicitly asks for a Mermaid diagram or a markdown visualization to share — it adds
nothing to your own understanding (the `.pflow.md` is clearer and more complete).

- `pflow mermaid wf.pflow.md` — Mermaid to stdout
- `pflow mermaid wf.pflow.md -o diagram.md` — a shareable markdown file (`.md` wraps it
  in a fenced ```mermaid block; other extensions write raw Mermaid)
- `--direction TD` (top-down), `--descriptions` (add node descriptions to labels),
  `--depth N` (sub-workflow expansion depth; 0 = none)
