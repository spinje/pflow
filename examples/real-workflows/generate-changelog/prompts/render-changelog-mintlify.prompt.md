Generate a Mintlify changelog <Update> component.

## Input
Version: ${compute-version.result.next_version}
Month/Year: ${compute-version.result.date_month_year}
Bump Type: ${compute-version.result.bump_type}

## Draft Entries
Each entry includes commit context and matched task reviews.
${format-draft-entries.result.entries}

## Documentation Changes
${join-docs-summary.result}

## Examples (match this tone, structure, and component usage)
${get-style-reference.result}

## Required Structure
<Update label="MONTH YEAR" description="VERSION" tags={[...]}>
  2-4 themed ## sections, each with a 1-2 sentence intro and
  **Highlights** bullet list.
</Update>

Tags must be from this set: "New releases", "Improvements",
"Bug fixes", "Breaking changes". Pick 1-3 that apply.

## Mintlify Components — USE THESE
Study the examples above and use these components where appropriate:
- `<Accordion title="Breaking changes">` — REQUIRED when any entry
  involves a removal, rename, or behavior change. List what changed
  and why, with before/after when helpful.
- `<Accordion title="Example">` — for code examples that would break
  the flow if inline. Keep the main body scannable.
- `<Tip>` — one per release, max. Use for the single most important
  insight a user should know. Not a summary, a specific detail.
- `<Note>` — for important behavior details that aren't obvious from
  the highlights (e.g., "runs automatically, no separate step").
- `<CodeGroup>` — for before/after comparisons inside accordions.
- Inline code blocks — show a 3-5 line usage example directly in the
  body for each major feature. Don't just describe it, show it.

## Tone
- Write like a developer explaining what shipped to another developer.
  Not a company announcing a product.
- Calm, understated, no hype. If a tired engineer would roll their
  eyes, rewrite it.
- Be specific — "added timeout parameter to shell node" beats
  "improved shell node reliability." Name the actual thing.
- Explain the "so what" — not just what changed, but what you can
  do now that you couldn't before.

## STRICT: No Hallucination
- ONLY use information explicitly present in the draft entries,
  commit context, PR descriptions, and task reviews above.
- NEVER invent features, capabilities, CLI flags, migration paths,
  or behaviors not described in the input.
- Describe WHAT each feature does. Do not speculate about WHY it
  was built or what it "enables" in the future.
- If a draft entry is too vague to understand what changed, DROP IT.
  Do not fill in the gaps with plausible-sounding details.
- Do not claim things like "the CLI provides guidance on X" or
  "includes automatic migration" unless the input explicitly says so.

## Tasks
1. Group entries into 2-4 themes
2. Merge duplicates
3. Standardize verbs (Allow→Added, Enable→Added)
4. No PR links (user-facing changelog)
5. Add <Accordion title="Breaking changes"> when entries involve
   removals, renames, or behavior changes — not just for major bumps
6. Add one inline code example per major feature section
7. Use at least one `<Tip>` or `<Note>` per release
8. Every draft entry must appear in at least one highlight — do
   not drop entries silently
9. A highlight must only appear under a section heading it actually
   relates to — do not group unrelated features to fill a theme

## CRITICAL
- Output ONLY the <Update>...</Update> component
- First character must be <
- Last characters must be </Update>
- NO JSON, NO outer code fences, NO explanations
