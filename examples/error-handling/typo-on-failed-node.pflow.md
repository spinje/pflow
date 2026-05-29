# Typo on a failed node

User makes a typo on a failed node. Should surface BOTH:
(1) primary failed (primary signal)
(2) typo correction "Did you mean: stdout?" (secondary hint)

## Steps

### primary

Fails.

- type: shell
- on-error: fallback
- next: end

```shell command
exit 7
```

### fallback

Succeeds.

- type: shell
- next: end

```shell command
echo "ok"
```

## Outputs

### content

Direct ref with TYPO on failed node — expect failure + typo hint.

- source: ${primary.stddout}
