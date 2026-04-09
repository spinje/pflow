# Cache + failure interaction

First run: primary fails, fallback runs, output = "fallback-val".
Cached? Memoization explicitly skips error results per runtime/CLAUDE.md.
Second run (with cache enabled): primary should RE-execute (not cached),
fallback should be cache-hit (or re-execute).

Test: do we get "fallback-val" on both runs? Does cache correctness hold?

## Steps

### primary

Always fails.

- type: shell
- on-error: fallback
- next: end

```shell command
exit 17
```

### fallback

Always succeeds with deterministic output.

- type: shell
- next: end

```shell command
echo "fallback-val"
```

## Outputs

### result

Coalesced.

- source: ${primary.stdout ?? fallback.stdout}
