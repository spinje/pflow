# Showing the workflow

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
- The canvas also shows runs **as they run**: run the workflow via the CLI (your bash tool)
  while the user has it open, and each node lights up live with its state — **running**,
  **success** (green ✓), **cached**, **failed** (red), or **stopped** (the run died) — plus an
  overall **Run success / failed / degraded** banner. So you and the user share one live
  picture: if a run fails, the user is already seeing the red node + banner — reference it
  directly rather than re-narrating. The user can also pick a **past run** to replay, or click
  a node to read that run's real resolved inputs, output, and cost.
- With no workflow argument, it opens the catalog of saved workflows.
- Flags: `--port N` (default 8765), `--no-open` (don't open a browser), `--no-auto-update`
  (freeze — stop live-updating).

Once a Viewer server is running, an agent can Point at things in the user's open
windows and Watch what they deliberately click:

- `pflow ui focus <workflow> <target> [--open] [--say TEXT] [--no-wait]` — focus/reveal a target
  in every matching Viewer.
- `pflow ui frame <workflow> <target> [--say TEXT] [--no-wait]` — move the camera without
  changing focus.
- `pflow ui clear-focus <workflow>` — clear the current focus (also dismisses all `--say` captions).
- `pflow ui user-activity [workflow]` — read recent clicks and view changes.

`--say "text"` narrates the point aloud with a persistent on-canvas caption anchored at the
target — point *and explain* in one command. Delivery direction goes in `[brackets]` (e.g.
`--say "[excited] this node calls the LLM"`): bracketed tags shape the voice and are stripped
from the caption; **everything outside brackets is spoken AND shown**. You write only the
sentence — voice and model come from settings: `pflow settings llm show` displays them,
`pflow settings llm set-tts-voice <name>` / `set-tts-model <id>` change them. Narration needs a
Gemini API key; the failure note names the exact fix if it's missing.

**A sequence of `--say` commands is a narrated walkthrough that paces itself.** Each command
waits for the previous clip to finish before it points, then returns as soon as its own clip
starts playing — so just run them one after another, nothing more:

```bash
pflow ui focus review.pflow.md fetch --open --say "[warm] It all starts here, fetching the data."
pflow ui frame review.pflow.md "fetch.stdout -> analyze.data" --say "The raw data flows along this wire."
pflow ui focus review.pflow.md analyze --say "Then an LLM looks for anomalies."
pflow ui focus review.pflow.md report --say "[cheerful] And the findings land in this report."
```

Any point target narrates — steps, inputs/outputs, or a connection (quote the `->` address);
use `frame` when you want the camera moved without changing what's focused.

Run the walkthrough as ONE chained shell command like above, not one `--say` per turn — your
own thinking time between separate commands is absorbed only up to the playing clip's length,
so slow turns reintroduce dead air. For a long walkthrough, run that chain in the BACKGROUND if
your runtime supports it: pacing happens inside each command, so backgrounding changes nothing
about the narration — it only frees you to keep working. In the foreground, budget the command
timeout: several seconds per sentence (synthesize, wait for its turn, speak), plus up to ~2
minutes if the hold below triggers. Two notes can appear in the output — both informational,
neither is an error you must catch:

- `narration unavailable: <reason>` — synthesis failed; the point and caption still landed,
  only the voice is missing.
- `note: narration is blocked in the Viewer (browser autoplay policy) — holding the
  walkthrough; click the caption's ▶ button to hear it and resume.` — a freshly opened browser
  window plays no sound until the user clicks in it once. The command **waits** (up to ~2
  minutes) and continues with `note: narration unblocked — resuming.` after the click — so tell
  the user to click the caption's ▶ button, then carry on.

`--no-wait` skips all waiting: the point fires immediately and its clip interrupts whatever is
playing. Captions **persist per target**: each narrated node keeps its caption box (with a
Replay button once its clip finishes), a new `--say` to the same target replaces just that box,
and the user closes boxes individually — `clear-focus` closes them all and stops the voice.

`focus`/`frame`/`clear-focus` reach every matching Viewer — including one whose tab is
currently backgrounded; the highlight is applied when the user returns to it.

**A target is just the name you already read in the `.pflow.md` — there is no
separate notation to learn:**

- a **step** by its name — `process_content`
- an **input** or **output** by its name — `source_file`
- a **connection** as `source -> target`, each end named the same way —
  `gen.response -> summarize.prompt`, or from an input `source_file -> read_source.file_path`

You don't have to get it right first try. If a name matches more than one thing
(the same step inside two sub-workflows, or an input and output that share a
name), the command doesn't guess — it lists the qualified addresses to pick from.
If a name isn't found, it suggests the closest real ones. So point, read the
reply, re-point.

All four take `--port N`. The command reports where it was sent (how
many windows, visible vs backgrounded), not that the browser finished drawing it —
the human looking at the screen is the confirmation. Point exits nonzero when
resolution fails or no Viewer received it; an empty `user-activity` is still a
successful read.

Deep-link a specific view (to point the user at a node, or for a screenshot): append
`?workflow=<name-or-path>&focus=<node-id>` — `focus=` highlights the node and reveals its
connections; add `&node=<node-id>` to also center the camera, or `&direction=TD` for top-down.

To replay a **past run** on the canvas, append `&run=<run_id>`. The `run_id` is the
`execution_id` on the first line of the run's trace in `~/.pflow/debug` — you already have the
path for any run you launched (the `Workflow trace saved: …` line `pflow run` prints), and older
or user-launched runs sit there too, named by workflow + timestamp. So
`?workflow=<path>&run=<execution_id>` re-opens that exact run for the user; omit `&run=` to
follow the newest.

You don't have to hand-craft that URL: **`pflow ui <workflow> --run <execution_id>`** opens the run
for the user — and it's smart about an already-open window. If the user already has that workflow
open, it *switches that window* to the run (no duplicate tab); if not, it opens a fresh window pinned
to it. So one command does the right thing whether or not the Viewer is already up.

## `pflow mermaid` — Mermaid diagram text (niche)

Emits a Mermaid flowchart of the workflow to stdout. Use this ONLY when the user
explicitly asks for a Mermaid diagram or a markdown visualization to share — it adds
nothing to your own understanding (the `.pflow.md` is clearer and more complete).

- `pflow mermaid wf.pflow.md` — Mermaid to stdout
- `pflow mermaid wf.pflow.md -o diagram.md` — a shareable markdown file (`.md` wraps it
  in a fenced ```mermaid block; other extensions write raw Mermaid)
- `--direction TD` (top-down), `--descriptions` (add node descriptions to labels),
  `--depth N` (sub-workflow expansion depth; 0 = none)
