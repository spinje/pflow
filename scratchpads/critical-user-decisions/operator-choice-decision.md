# Critical Decision: Flow Operator Choice - Importance 4/5

We need to choose a flow operator that:
1. Doesn't require quotes or special escaping
2. Is intuitive for users
3. Doesn't conflict with shell operators
4. Works seamlessly with Click's argument parsing

## Current Issue

The `->` operator starts with `-`, causing Click to interpret it as an option. This requires users to either:
- Quote it: `pflow "node1" "->" "node2"` (not user-friendly)
- Use `--` separator: `pflow -- node1 -> node2` (not intuitive)

## Options:

- [ ] **Option A: Use `=>` operator**
  - ✅ Doesn't start with `-`, no Click conflicts
  - ✅ Common in many languages (TypeScript, PHP, etc.)
  - ✅ Visually similar to an arrow
  - ✅ No shell conflicts
  - ❌ Less common in CLI tools

- [x] **Option B: Use `|>` operator**
  - ✅ Doesn't start with `-`, no Click conflicts
  - ✅ Pipe-like, familiar to CLI users
  - ✅ Used in F#, Elixir for piping
  - ✅ Semantically matches the flow concept
  - ✅ No shell conflicts
  - ❌ Might be confused with shell pipe `|`

- [ ] **Option C: Use `~>` operator**
  - ✅ Doesn't start with `-`, no Click conflicts
  - ✅ Unique, no confusion with other operators
  - ✅ No shell conflicts
  - ❌ Less intuitive meaning
  - ❌ Not commonly used

- [ ] **Option D: Custom parsing to keep `->`**
  - ✅ Keeps the intuitive arrow operator
  - ❌ Requires complex workarounds with Click
  - ❌ May break other Click features
  - ❌ More code complexity

**Recommendation**: Option B (`|>`) - It's pipe-like which matches the flow concept, doesn't conflict with Click or shell, and is intuitive for CLI users. The semantic meaning of "pipe this output to next node" aligns perfectly with pflow's purpose.

## Implementation Impact

Changing from `->` to `|>` requires:
1. Update all test files to use `|>`
2. Update help text in main.py
3. No changes to parsing logic needed (it will just work)
4. Update any documentation references (out of scope for this task)
