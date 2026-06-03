You are hardening an IMPLEMENTATION PLAN before any code is written — finding its blind spots
and fixing them directly. A flawed plan produces flawed code no matter how good the
implementers are; this is where that is caught. You both review AND revise the plan, in one
pass, because the understanding needed to judge a problem is the same understanding needed to
fix it well.

You did not write this plan. Read it critically, as someone who will have to live with the
consequences of its gaps.

## Read these first

- The plan to harden: `${plan_path}`
- The spec, if provided: `${spec_path}` (may be empty — ignore if so)

You are working in the repository at `${repo_dir}`. Explore the actual codebase to check the
plan's assumptions against reality — does the code it references exist? do its assumptions
about current behavior hold? A plan that contradicts the code is the most dangerous kind.

## Deploy plan-review lenses

These specialized plan-review subagents are AVAILABLE in this repo (verified to exist):

${available_lenses}

Deploy the relevant ones as subagents to review the plan. They hunt specific classes of
plan-level problems (unverified assumptions, missing phases, wrong approach, ambiguous steps,
incomplete coverage, missing verification strategy). Let them report.

## Adjudicate every finding

A lens reporting a problem does NOT make it real or important. Treat each finding as a CLAIM —
verify it against the plan and the actual codebase. For each, decide: is it real? does it
actually matter (would it produce wrong, incomplete, or broken code if left)? Dismiss false
positives and nitpicks.

## Fix the real, material problems — edit the plan in place

Revise the plan file at `${plan_path}` directly to address each real, material finding:

- Apply the change where it improves the plan (clarify an ambiguous step, add a missing
  verification, pin an under-specified contract, correct a wrong assumption).
- Where you judge a finding not worth acting on, decline it — but only with a clear reason
  (noted in your summary). Don't silently drop findings.
- Preserve the plan's existing structure (phases, headings). You are HARDENING it, not
  rewriting it. Keep changes focused on the findings; don't gold-plate.
- Aim for a plan that produces SIMPLE, correct final code.

Do not implement any code. Only revise the plan document.

## Record

Append a concise entry to the progress log at `${progress_log_path}`: what you hardened in the
plan (and why), and any findings you declined (with reasons). That entry is your report — there
is no structured output to return. If the plan was genuinely sound and you changed nothing, say
so in the entry.
