# 03 — report with --only

**Surface**: 15-run-flag-interactions

**Triggers**: `pflow <workflow> --report --only first` executes a partial run
and generates the default report snapshot.

**Expected behavior**: CLI output announces the `--only` mode and report path,
the report summary records `1/2` nodes with skipped count, and the report
directory contains only the executed node page.

**Mutation contract**: if report snapshots leave stale downstream pages, lose
the `--only` summary context, or stop printing the target node report path, this
case fails.

