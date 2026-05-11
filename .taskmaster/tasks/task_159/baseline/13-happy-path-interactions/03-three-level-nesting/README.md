# 03 — Three-level workflow nesting with cache at every level

**Surface**: 13-happy-path-interactions

**Triggers**: Top → Level 2 → Level 3. Each level except top declares its
own `## Cache` and uses it. The article value flows through all three
levels under the same name.

**Expected**: cross-workflow walker traverses 3 levels. Both level-2 and
level-3 caches are recognized. If prose-before-`${var}` matches across
levels (mine does — both say "The article (level X cache):"), no
cross-workflow-prose-mismatch fires. If it diverges, the warning would
fire (level-2 says "level 2 cache", level-3 says "level 3 cache" — these
ARE different so prose-mismatch SHOULD fire here, capturing a real
cross-level finding).

**Why this case is load-bearing**: lyrics-generator has 3-level nesting
(parent → song-creator → chorus-chooser). If the walker only traverses 2
levels, the third level's findings are silently lost.

**Mutation contract**: if the walker stops recursing past 2 levels, the
level-3 LLM node disappears from `per_call` and any level-3 specific
warnings vanish. Diff catches it.
