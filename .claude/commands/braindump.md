---
description: Transfer tacit knowledge before context window resets
argument-hint: [task-id]
---

# Braindump

Your context window is ending. Transfer what's in your HEAD to the next agent.

## Input

Task ID (optional): **$ARGUMENTS**

- If a number: associate this braindump with that task
- If empty: write to `scratchpads/handoffs/<descriptive-name>.md`

## Your Unique Position

You have been in this conversation. You have context that no one else has—insights built up through back-and-forth with the user, false starts, clarifications, and discoveries. Everything in your context window is potentially relevant.

Your job: perform a strategic braindump of the most important information the next agent needs. This is not a summary or formal report. It's a focused transfer of tacit knowledge—insights that would otherwise vanish with your context window.

## The Core Rule

**Don't repeat what's already written down.**

If it exists in a file (task doc, progress log, spec, code comments), the next agent can read it. Your job is to capture what ISN'T written anywhere. Fill the gaps that other documents miss.

## Mindset

Imagine you're leaving a note for your future self, knowing you'll return with no memory of what you've done.

**What would you be furious at yourself for *not* mentioning?**

Write clearly, concisely, and with care. This is your final contribution to the success of this work.

## What to Capture

### User's Mental Model

Capture how the user thinks about this problem:
- Their exact words and phrasing for key concepts
- What they emphasized vs. glossed over
- Their priorities (stated and unstated)
- Terminology they use (use their words, not synonyms)
- How their understanding evolved during the conversation

### Tacit Knowledge

Things that exist only in your head right now:
- **Why you chose this approach** — not just what, but the reasoning
- **What you were about to try** — your next move that never happened
- **Dead ends and why** — approaches you abandoned and the specific reason
- **Suspicions not yet proven** — "I think X might be the real issue because..."
- **Connections you made** — links between concepts that aren't obvious
- **Things that felt wrong** — instincts you can't fully justify yet
- **Context that took time to build** — understanding that wasn't instant

### Ambiguity and Assumptions

Be explicit about uncertainty:
- What remains unclear or ambiguous?
- What assumptions did you make that weren't explicitly confirmed?
- What needs verification before proceeding?
- Where might your understanding be wrong?

Mark these clearly: "ASSUMPTION:", "UNCLEAR:", "NEEDS VERIFICATION:"

### Concrete Details

- **Core outcomes and side effects** that must be built on or avoided
- **Unexpected discoveries, edge cases, or fixes** that changed your approach
- **Patterns or anti-patterns** you uncovered that should be reused or avoided
- **Warnings about subtle bugs, performance issues, or architectural caveats**
- **Changes to shared interfaces, data structures, or contracts**
- **Which previous tasks you leaned on**, and why
- **Links to specific files and code** that are relevant
- **Links to docs** that will be invaluable

### Hard-Won Knowledge

Include information that was:
- Hard for you to find
- Easy to misinterpret
- Not intuitively obvious
- Discovered through trial and error

### Unexplored Territory

Flag areas that might be important but weren't discussed:
- Topics the conversation skipped over or glossed past
- Questions you thought to ask but didn't
- Considerations the user might not know to think about
- Potential gotchas based on your experience with similar problems
- Adjacent concerns (security, performance, edge cases, error handling)
- Integration points that weren't addressed
- "If I were implementing this, I'd want to know about..."

This is your chance to hedge against incomplete requirements. The user doesn't always know what they don't know. Use your expertise to flag: "We didn't discuss X, but X might matter."

Mark these: "UNEXPLORED:", "CONSIDER:", "MIGHT MATTER:"

## What NOT to Capture

- Summary of task requirements (it's in the task file)
- List of what you implemented (it's in the progress log)
- Code explanations (they're in comments or the code itself)
- Generic advice or boilerplate reminders
- Anything the next agent can find by reading existing files

**Test**: "Could the next agent find this by reading files?" If yes, skip it.

## Two Scenarios

### Scenario A: New task was discussed

You discussed a feature/task with the user. Capture:
- The journey of the discussion (how understanding evolved)
- Options that were considered and rejected (and why)
- The user's reasoning and preferences
- Nuances that shaped the final direction
- Open questions that weren't resolved

### Scenario B: Implementation in progress

You were implementing and ran out of context. Capture:
- Your current mental state and hypothesis
- What you were about to try next
- Why you went down path A instead of B
- Hunches about the root cause
- Things the user said that changed your approach
- Gotchas you discovered but might not have documented

## Before Writing

Think carefully and make a plan of what to include before you start writing. This is your chance to really think through everything you know and how it might be useful to the next agent.

Ask yourself:
1. What do I understand now that I didn't at the start?
2. What would I do differently if starting over?
3. What's the user's real priority beneath their stated request?
4. What almost broke and why?
5. What am I 70% sure about but haven't verified?
6. What pattern did I notice that might apply elsewhere?
7. What feels intuitive to me but might not be obvious to the next agent?
8. What would break if my understanding were wrong?

## Output

Write a markdown file with your braindump.

**If task ID provided**: `.taskmaster/tasks/task_<id>/braindump-<timestamp-or-short-description>.md`

**If no task ID**: `scratchpads/handoffs/<descriptive-name>.md`

## Suggested Format

No rigid structure required. Write naturally. But consider:

```markdown
# Braindump: <context>

## Where I Am

<Your current understanding/state>

## User's Mental Model

<How they think about this, in their words>

## Key Insights

<The non-obvious things you learned>

## Assumptions & Uncertainties

<What you assumed, what's unclear, what needs verification>

## Unexplored Territory

<Areas we didn't discuss that might matter - use UNEXPLORED:, CONSIDER:, MIGHT MATTER:>

## What I'd Tell Myself

<If you could go back, what would you say?>

## Open Threads

<Unfinished thoughts, suspicions, next steps you didn't take>

## Relevant Files & References

<Links to code, docs, examples that matter>

## For the Next Agent

<Direct advice: "Start by...", "Don't bother with...", "The user cares most about...">
```

## Final Instructions

At the end of your braindump, remind the receiving agent:

> **Note to next agent**: Read this document fully before taking any action. When ready, confirm you've read and understood by summarizing the key points, then state you're ready to proceed.

This ensures the next agent absorbs the context rather than jumping straight into implementation.
