# 10 — CRLF line endings + duplicate chunk identifier (ADV)

**Surface**: 01-parser-errors

**Triggers**: A workflow saved with `\r\n` line terminators that ALSO contains
a duplicate cache chunk identifier (`${article}` twice). The expected behavior
is that pflow handles CRLF transparently and reaches the same Parse Error as
the LF version (case 04 — `04-duplicate-chunk-id`).

**Expected behavior**: identical Parse Error to case 04
(`Duplicate cache chunk identifier 'article'`). Identical exit code.

**Mutation contract**: if Task 160 changes line-handling and CRLF-encoded
workflows produce a *different* error (or no error) than LF-encoded versions,
this case fails — preventing a class of bug where Windows authors and Mac/Linux
authors silently see different parser behavior. The expected-stderr.txt for
this case should byte-equal the expected-stderr.txt for case 04 modulo
intentional source-line differences.
