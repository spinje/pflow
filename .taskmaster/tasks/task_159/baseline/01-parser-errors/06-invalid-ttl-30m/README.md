# 06 — Invalid TTL value (`30m`)

**Surface**: 01-parser-errors

**Triggers**: `## Cache` declares `- ttl: 30m`. Only `5m` and `1h` are valid in
v1 (provider TTL vocabulary is two-bucket).

**Expected behavior**: Schema/validator error citing the invalid TTL value and
listing valid values; non-zero exit.

**Mutation contract**: if the schema enum is broadened, the adapter sends a
malformed `cache_control` payload to the provider — silent provider rejection
or undefined behavior.
