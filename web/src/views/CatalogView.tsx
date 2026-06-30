// The landing view: saved workflows (/api/catalog) PLUS workflows that have run but aren't saved, grouped
// by their git repo (/api/runs `git_root`) — so ad-hoc / CLI / agent runs (not in the saved catalog) are
// reachable (ADR-0008), organized the way a developer thinks (by project). Every section is collapsible.

import { useEffect, useState } from "react";
import type { ReactNode } from "react";

import { ApiError, fetchCatalog, fetchRuns } from "../api/client";
import { runMark } from "../components/RunSelector";
import type { CatalogItem, RunInfo } from "../types";
import { stripMarkdown, timeAgo } from "../utils/format";

// One distinct workflow that has run, folded from its runs. `path` is `meta.workflow_path` — an absolute file
// path, or `ir-hash:<md5>` for an inline/stdin/MCP run (no file → not openable). `gitRoot` buckets it by repo.
interface RunGroup {
  path: string;
  name: string;
  inline: boolean;
  anyLive: boolean;
  latest: RunInfo;
  gitRoot: string | null;
}

interface Bucket {
  key: string; // a git-root path, or OTHER_BUCKET
  label: string;
  rows: RunGroup[];
}

// The bucket key for runs under no git repo (non-git files + inline). A printable sentinel; git_root is
// always an absolute path (or null), so this non-absolute string can never collide. (Was a NUL byte,
// which made git/rg classify this whole file as binary and hid its diffs — PR #543 review.)
export const OTHER_BUCKET = "other-bucket";

// Group runs by workflow_path — one row per distinct workflow. Runs arrive newest-first, so the FIRST seen
// per path is the latest. A pathless run is skipped defensively (the producer always stamps a path/`ir-hash:`).
export function groupRuns(runs: RunInfo[]): Map<string, RunGroup> {
  const groups = new Map<string, RunGroup>();
  for (const run of runs) {
    const path = run.workflow_path;
    if (!path) continue;
    const existing = groups.get(path);
    if (existing) {
      existing.anyLive = existing.anyLive || run.live;
    } else {
      groups.set(path, {
        path,
        name: run.workflow_name,
        inline: path.startsWith("ir-hash:"),
        anyLive: run.live,
        latest: run,
        gitRoot: run.git_root,
      });
    }
  }
  return groups;
}

function repoLabel(gitRoot: string): string {
  const parts = gitRoot.split("/").filter(Boolean);
  return parts[parts.length - 1] || gitRoot;
}

// Bucket ran-but-unsaved groups by git repo (null gitRoot → the "Other" bucket). Repos sort by their
// most-recent run (the active project floats up); "Other" is always last. Input is already newest-first, so
// each bucket's rows stay newest-first.
export function bucketUnsaved(ranButUnsaved: RunGroup[]): Bucket[] {
  const byKey = new Map<string, RunGroup[]>();
  for (const group of ranButUnsaved) {
    const key = group.gitRoot ?? OTHER_BUCKET;
    const rows = byKey.get(key);
    if (rows) rows.push(group);
    else byKey.set(key, [group]);
  }
  return [...byKey.entries()]
    .map(([key, rows]) => ({ key, rows, label: key === OTHER_BUCKET ? "Other (ad-hoc · inline)" : repoLabel(key) }))
    .sort((a, b) => {
      if (a.key === OTHER_BUCKET) return 1;
      if (b.key === OTHER_BUCKET) return -1;
      return (b.rows[0]?.latest.start_time ?? "").localeCompare(a.rows[0]?.latest.start_time ?? "");
    });
}

function RunningBadge(): JSX.Element {
  return (
    <span className="catalog-item-running" title="A run is in progress">
      <span className="run-dot" aria-hidden /> running
    </span>
  );
}

// The right-side run summary on every catalog row (saved OR ran-but-unsaved): a pulsing "running" badge
// while live, else the latest run's terminal status mark (✓/✗/⊘/⊗ — the shared `runMark` palette) plus a
// relative "last run" label. A saved workflow with no recorded run at all reads a muted "never run".
function RunMeta({ group, loaded = true }: { group: RunGroup | undefined; loaded?: boolean }): JSX.Element | null {
  // No group means "no recorded run" ONLY once the runs data has actually loaded. Until then (pending) or on
  // a runs-fetch failure (DR-6), absence is "we don't know yet" — show nothing rather than a false "never run".
  if (!group) return loaded ? <span className="catalog-item-meta catalog-item-never">never run</span> : null;
  if (group.anyLive) return <RunningBadge />;
  const mark = runMark(group.latest);
  const ago = timeAgo(group.latest.start_time);
  return (
    <span className="catalog-item-meta">
      <span className={"run-mark " + mark.cls} title={`last run: ${mark.label}`}>
        {mark.glyph}
      </span>
      {ago && <span className="catalog-item-time">{ago}</span>}
    </span>
  );
}

// Path (+ description, for saved rows) ride the row's hover `title` instead of cluttering every line —
// markdown markers stripped so a tooltip reads as plain text. Newline-joined; browsers honor `\n` in title.
function rowTitle(...parts: (string | null | undefined)[]): string {
  return parts.filter((p): p is string => Boolean(p && p.trim())).join("\n");
}

// A collapsible catalog section (Saved, or one repo bucket). The whole header is the toggle; the row count
// rides it so a collapsed section still tells you how much it holds.
function Section({
  title,
  count,
  collapsed,
  onToggle,
  titleHint,
  children,
}: {
  title: string;
  count: number;
  collapsed: boolean;
  onToggle: () => void;
  titleHint?: string;
  children: ReactNode;
}): JSX.Element {
  return (
    <section className="catalog-section">
      <button className="catalog-section-head" onClick={onToggle} aria-expanded={!collapsed}>
        <span className={"catalog-section-chevron" + (collapsed ? " collapsed" : "")} aria-hidden>
          ▾
        </span>
        <span className="catalog-section-title" title={titleHint}>
          {title}
        </span>
        <span className="catalog-section-count">{count}</span>
      </button>
      {!collapsed && <ul className="catalog-list">{children}</ul>}
    </section>
  );
}

function UnsavedRow({ group, onOpen }: { group: RunGroup; onOpen: (workflow: string) => void }): JSX.Element {
  // Inline (`ir-hash:`) runs have no file to open → a static, non-clickable row (the explanation rides the
  // hover title; the static styling + default cursor are the visible "not clickable" cue).
  if (group.inline) {
    return (
      <div className="catalog-item catalog-item-static" title="inline run · no file to open">
        <span className="catalog-item-name">{group.name}</span>
        <RunMeta group={group} />
      </div>
    );
  }
  return (
    <button className="catalog-item" onClick={() => onOpen(group.path)} title={group.path}>
      <span className="catalog-item-name">{group.name}</span>
      <RunMeta group={group} />
    </button>
  );
}

export function CatalogView({ onOpen }: { onOpen: (workflow: string) => void }): JSX.Element {
  const [items, setItems] = useState<CatalogItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Task 173 D6: workflows that have run, grouped by path. Its OWN fetch + catch (DR-6) — a runs-fetch
  // failure simply shows no badges / no extra rows, never blanks the saved catalog.
  const [runGroups, setRunGroups] = useState<ReadonlyMap<string, RunGroup>>(() => new Map());
  // Whether the /api/runs fetch has RESOLVED (success). Until then — and on a DR-6 failure — `runGroups` is
  // empty for a reason other than "never ran", so a saved row must not claim "never run" (a false statement).
  const [runsLoaded, setRunsLoaded] = useState(false);
  // Collapsed sections. Default: only the "Other" (ad-hoc / inline throwaway) bucket is collapsed — Saved and
  // the per-repo buckets start open. Keyed by section id (the git-root path, OTHER_BUCKET, or "saved").
  const [collapsed, setCollapsed] = useState<ReadonlySet<string>>(() => new Set([OTHER_BUCKET]));
  const toggle = (key: string): void =>
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  useEffect(() => {
    let cancelled = false;
    fetchCatalog()
      .then((list) => {
        if (!cancelled) setItems(list);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof ApiError ? e.message : String(e));
      });
    fetchRuns()
      .then((runs) => {
        if (!cancelled) {
          setRunGroups(groupRuns(runs));
          setRunsLoaded(true);
        }
      })
      .catch(() => undefined); // DR-6: runsLoaded stays false → saved rows show no run-meta, never a false "never run"
    return () => {
      cancelled = true;
    };
  }, []);

  // Ran-but-NOT-saved = run groups whose path isn't a saved entry path (raw string equality — the shipped
  // contract). Gated on `items` being LOADED so a saved workflow is never briefly mis-listed as unsaved while
  // the catalog fetch is in flight. (Case-fold edge accepted for v1: a same-file/different-case launch on a
  // case-insensitive FS can duplicate a row — pinned by a test; server-side normalized dedup is the escalation.)
  const savedPaths = new Set((items ?? []).map((entry) => entry.path));
  const ranButUnsaved =
    items === null
      ? []
      : [...runGroups.values()]
          .filter((group) => !savedPaths.has(group.path))
          // `?? ""` is load-bearing (DR-6): a malformed/legacy trace can yield a null start_time despite the
          // `string` type — an unguarded `.localeCompare` would throw and the ErrorBoundary would blank the
          // whole catalog. Degrade the ordering instead of taking the catalog down.
          .sort((a, b) => (b.latest.start_time ?? "").localeCompare(a.latest.start_time ?? ""));
  const buckets = bucketUnsaved(ranButUnsaved);
  const hasSaved = Boolean(items && items.length > 0);

  // Saved rows sorted by recency (most-recently-run first) so the catalog reads like a recent-activity list;
  // a never-run workflow has no run group → its key is "" → it sinks below the run ones, alphabetical among
  // its peers. Same null-guard as the unsaved sort (a legacy trace can yield a null start_time).
  const sortedSaved = (items ?? []).slice().sort((a, b) => {
    const ta = runGroups.get(a.path)?.latest.start_time ?? "";
    const tb = runGroups.get(b.path)?.latest.start_time ?? "";
    return ta === tb ? a.name.localeCompare(b.name) : tb.localeCompare(ta);
  });

  return (
    <div className="catalog">
      <header className="catalog-header">
        <h1>pflow workflows</h1>
        <p>Pick a workflow to see its structure, wiring, and prompts.</p>
      </header>

      {error && <div className="banner error">Could not load the catalog: {error}</div>}
      {!items && !error && <div className="catalog-empty">Loading…</div>}
      {items && !hasSaved && buckets.length === 0 && (
        <div className="catalog-empty">
          No saved workflows yet. Open one directly with <code>pflow ui path/to/workflow.pflow.md</code>.
        </div>
      )}

      {items && items.length > 0 && (
        <Section title="Saved" count={items.length} collapsed={collapsed.has("saved")} onToggle={() => toggle("saved")}>
          {sortedSaved.map((item) => (
            <li key={item.path}>
              <button
                className="catalog-item"
                onClick={() => onOpen(item.name)}
                title={rowTitle(item.description && stripMarkdown(item.description), item.path)}
              >
                <span className="catalog-item-name">{item.name}</span>
                <RunMeta group={runGroups.get(item.path)} loaded={runsLoaded} />
              </button>
            </li>
          ))}
        </Section>
      )}

      {buckets.map((bucket) => (
        <Section
          key={bucket.key}
          title={bucket.label}
          titleHint={bucket.key === OTHER_BUCKET ? undefined : bucket.key}
          count={bucket.rows.length}
          collapsed={collapsed.has(bucket.key)}
          onToggle={() => toggle(bucket.key)}
        >
          {bucket.rows.map((group) => (
            <li key={group.path}>
              <UnsavedRow group={group} onOpen={onOpen} />
            </li>
          ))}
        </Section>
      ))}
    </div>
  );
}
