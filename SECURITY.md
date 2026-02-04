# Security Policy

## Reporting a vulnerability

If you find a security issue in pflow, please don't open a public issue. Email **andreas@pflow.run** instead, and I'll get back to you as soon as I can.

Include whatever details you have — steps to reproduce, what you think the impact is, which version you're on. Even if you're not sure it's a real vulnerability, better to flag it privately than not.

## What counts

Anything that could let someone run unintended commands, read files they shouldn't, leak secrets through logs or traces, or bypass node filtering/settings. pflow executes shell commands and talks to external services, so the attack surface is real.

## What happens next

I'll acknowledge your report, figure out the fix, and coordinate a release. If you want credit in the changelog, just say so.
