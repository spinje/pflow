// @vitest-environment jsdom
//
// Task 173 D6: the catalog's saved∪ran merge. Saved workflows are one collapsible "Saved" section; workflows
// that have run but aren't saved are bucketed by their git repo (open by default) with an "Other" bucket
// (non-git + inline throwaways, collapsed by default). A runs-fetch failure (DR-6) degrades to no badges / no
// buckets without blanking the saved catalog. Inline (`ir-hash:`) runs appear by name, non-openable.

import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import { CatalogView, OTHER_BUCKET, bucketUnsaved, groupRuns } from "./CatalogView";
import type { RunInfo } from "../types";

vi.mock("../api/client", () => ({
  ApiError: class ApiError extends Error {},
  fetchCatalog: vi.fn(),
  fetchRuns: vi.fn(),
}));
import { fetchCatalog, fetchRuns } from "../api/client";
const mockCatalog = vi.mocked(fetchCatalog);
const mockRuns = vi.mocked(fetchRuns);

function run(over: Partial<RunInfo> = {}): RunInfo {
  return {
    run_id: "r",
    workflow_name: "x",
    workflow_path: "/x.pflow.md",
    start_time: "2026-01-01T00:00:00",
    complete: true,
    final_status: "success",
    live: false,
    only_node: null,
    trace_file: "t.json",
    git_root: null,
    ...over,
  };
}

afterEach(() => {
  cleanup();
  mockCatalog.mockReset();
  mockRuns.mockReset();
});

describe("groupRuns", () => {
  it("folds runs by path, keeps the newest as `latest`, ORs liveness, and threads git_root", () => {
    const groups = groupRuns([
      run({ workflow_path: "/a.pflow.md", start_time: "2026-03-02", final_status: "failed", git_root: "/proj" }),
      run({ workflow_path: "/a.pflow.md", start_time: "2026-03-01", live: true, complete: false, final_status: null }),
      run({ workflow_path: "ir-hash:zz", workflow_name: "inline", start_time: "2026-03-03" }),
    ]);
    expect(groups.size).toBe(2);
    const a = groups.get("/a.pflow.md")!;
    expect(a.latest.start_time).toBe("2026-03-02"); // newest (first-seen) wins
    expect(a.anyLive).toBe(true); // an OLDER run is still live → the group is live
    expect(a.inline).toBe(false);
    expect(a.gitRoot).toBe("/proj");
    expect(groups.get("ir-hash:zz")!.inline).toBe(true);
  });
});

describe("bucketUnsaved", () => {
  it("buckets by git repo (basename label), sorts repos by recency, and pins Other last", () => {
    const groups = [
      ...groupRuns([
        run({ workflow_path: "/old/a.pflow.md", git_root: "/work/old", start_time: "2026-03-01" }),
        run({ workflow_path: "/new/b.pflow.md", git_root: "/work/new", start_time: "2026-03-03" }),
        run({ workflow_path: "/tmp/c.pflow.md", git_root: null, start_time: "2026-03-02" }),
      ]).values(),
    ];
    const buckets = bucketUnsaved(groups);
    expect(buckets.map((b) => b.key)).toEqual(["/work/new", "/work/old", OTHER_BUCKET]); // recency, Other last
    // basename labels for repos; the Other bucket is human-labelled
    expect(buckets.map((b) => b.label)).toEqual(["new", "old", "Other (ad-hoc · inline)"]);
  });
});

describe("CatalogView — saved section", () => {
  it("flags ONLY the workflow with a live run, matched by path", async () => {
    mockCatalog.mockResolvedValue([
      { name: "alpha", description: "", path: "/alpha.pflow.md" },
      { name: "beta", description: "", path: "/beta.pflow.md" },
    ]);
    mockRuns.mockResolvedValue([run({ workflow_path: "/alpha.pflow.md", live: true, complete: false, final_status: null })]);
    render(<CatalogView onOpen={vi.fn()} />);

    await waitFor(() => expect(screen.getByText("alpha")).toBeTruthy());
    expect(await screen.findAllByText("running")).toHaveLength(1); // exactly one flagged — beta is not
  });

  it("the Saved section is collapsible — clicking its header hides the rows", async () => {
    mockCatalog.mockResolvedValue([{ name: "alpha", description: "", path: "/alpha.pflow.md" }]);
    mockRuns.mockResolvedValue([]);
    render(<CatalogView onOpen={vi.fn()} />);

    await waitFor(() => expect(screen.getByText("alpha")).toBeTruthy()); // open by default
    fireEvent.click(screen.getByText("Saved"));
    expect(screen.queryByText("alpha")).toBeNull(); // collapsed → rows gone
  });

  it("a runs-fetch failure shows no badge / no buckets but never blanks the catalog (DR-6)", async () => {
    mockCatalog.mockResolvedValue([{ name: "alpha", description: "", path: "/alpha.pflow.md" }]);
    mockRuns.mockRejectedValue(new Error("scan failed"));
    render(<CatalogView onOpen={vi.fn()} />);

    await waitFor(() => expect(screen.getByText("alpha")).toBeTruthy()); // catalog still renders
    expect(screen.queryByText("running")).toBeNull();
    expect(screen.queryByText(/Other/)).toBeNull(); // no buckets either
  });

  it("shows the empty message only when there are no saved workflows AND no runs", async () => {
    mockCatalog.mockResolvedValue([]);
    mockRuns.mockResolvedValue([]);
    render(<CatalogView onOpen={vi.fn()} />);
    await waitFor(() => expect(screen.getByText(/No saved workflows yet/)).toBeTruthy());
  });
});

describe("CatalogView — git-bucketed ran-but-unsaved (Phase 2)", () => {
  it("buckets an ad-hoc repo workflow under its repo (open), without duplicating a saved one", async () => {
    mockCatalog.mockResolvedValue([{ name: "alpha", description: "", path: "/alpha.pflow.md" }]);
    mockRuns.mockResolvedValue([
      run({ workflow_path: "/alpha.pflow.md", workflow_name: "alpha", git_root: "/proj" }), // saved → NOT a row
      run({ workflow_path: "/proj/adhoc.pflow.md", workflow_name: "adhoc", git_root: "/proj" }), // unsaved → row
    ]);
    render(<CatalogView onOpen={vi.fn()} />);

    await waitFor(() => expect(screen.getByText("proj")).toBeTruthy()); // the repo bucket header (open)
    expect(screen.getByText("adhoc")).toBeTruthy(); // visible without expanding (repo buckets open by default)
    expect(screen.getByText("/proj/adhoc.pflow.md")).toBeTruthy();
    expect(screen.getAllByText("alpha")).toHaveLength(1); // saved appears once, never duplicated into a bucket
  });

  it("opens a saved row by NAME and an ad-hoc repo row by PATH", async () => {
    const onOpen = vi.fn();
    mockCatalog.mockResolvedValue([{ name: "alpha", description: "", path: "/alpha.pflow.md" }]);
    mockRuns.mockResolvedValue([run({ workflow_path: "/proj/adhoc.pflow.md", workflow_name: "adhoc", git_root: "/proj" })]);
    render(<CatalogView onOpen={onOpen} />);

    await waitFor(() => expect(screen.getByText("adhoc")).toBeTruthy());
    fireEvent.click(screen.getByText("alpha"));
    expect(onOpen).toHaveBeenCalledWith("alpha"); // saved → by name
    fireEvent.click(screen.getByText("adhoc"));
    expect(onOpen).toHaveBeenCalledWith("/proj/adhoc.pflow.md"); // ad-hoc → by path
  });

  it("collapses the Other bucket by default; expanding it reveals the inline (non-openable) run", async () => {
    const onOpen = vi.fn();
    mockCatalog.mockResolvedValue([]);
    mockRuns.mockResolvedValue([run({ workflow_path: "ir-hash:deadbeef", workflow_name: "piped-thing", git_root: null })]);
    render(<CatalogView onOpen={onOpen} />);

    // The Other bucket exists but is collapsed → its row is hidden until expanded.
    await waitFor(() => expect(screen.getByText(/Other/)).toBeTruthy());
    expect(screen.queryByText("piped-thing")).toBeNull();
    fireEvent.click(screen.getByText(/Other/));

    expect(screen.getByText("piped-thing")).toBeTruthy();
    expect(screen.getByText("inline run · no file to open")).toBeTruthy();
    // Non-openable: a static div, not a button; clicking never calls onOpen.
    expect(screen.getByText("piped-thing").closest(".catalog-item")?.tagName).toBe("DIV");
    fireEvent.click(screen.getByText("piped-thing"));
    expect(onOpen).not.toHaveBeenCalled();
  });

  it("shows a running badge on a live ad-hoc row and the last-run status mark on a finished one", async () => {
    mockCatalog.mockResolvedValue([]);
    mockRuns.mockResolvedValue([
      run({ workflow_path: "/proj/live.pflow.md", git_root: "/proj", live: true, complete: false, final_status: null }),
      run({ workflow_path: "/proj/done.pflow.md", workflow_name: "done", git_root: "/proj", final_status: "failed" }),
    ]);
    render(<CatalogView onOpen={vi.fn()} />);

    await waitFor(() => expect(screen.getByText("proj")).toBeTruthy()); // repo bucket open
    expect(screen.getByText("running")).toBeTruthy(); // the live row
    expect(screen.getByTitle("last run: failed")).toBeTruthy(); // the finished row's ✗ mark
  });

  it("a run with a missing start_time does not blank the catalog (DR-6 — sort is null-guarded)", async () => {
    mockCatalog.mockResolvedValue([{ name: "alpha", description: "", path: "/alpha.pflow.md" }]);
    // TWO unsaved runs in ONE repo bucket so the SORT COMPARATOR actually fires (a 1-element array never calls
    // it) — one with a null start_time a malformed/legacy trace can yield despite the `string` type. Without
    // the `?? ""` guard the comparator throws and the ErrorBoundary blanks the catalog.
    mockRuns.mockResolvedValue([
      run({ workflow_path: "/proj/bad.pflow.md", workflow_name: "bad", git_root: "/proj", start_time: null as unknown as string }),
      run({ workflow_path: "/proj/ok.pflow.md", workflow_name: "ok", git_root: "/proj", start_time: "2026-02-01T00:00:00" }),
    ]);
    render(<CatalogView onOpen={vi.fn()} />);

    await waitFor(() => expect(screen.getByText("alpha")).toBeTruthy()); // catalog still renders, no crash
    expect(screen.getByText("bad")).toBeTruthy();
    expect(screen.getByText("ok")).toBeTruthy();
  });

  it("ACCEPTED v1 edge: a same-file/different-case launch duplicates the row (raw-path equality)", async () => {
    // `Path.resolve()` doesn't case-fold, so a different-case spelling resolves to a DIFFERENT string → the
    // run fails to merge into the saved row and shows a separate ad-hoc row. Pinned to flag if it graduates.
    mockCatalog.mockResolvedValue([{ name: "MyWf", description: "", path: "/wf/MyWf.pflow.md" }]);
    mockRuns.mockResolvedValue([run({ workflow_path: "/wf/mywf.pflow.md", workflow_name: "mywf", git_root: "/wf" })]);
    render(<CatalogView onOpen={vi.fn()} />);

    await waitFor(() => expect(screen.getByText("MyWf")).toBeTruthy());
    expect(screen.getByText("wf")).toBeTruthy(); // the different-case run shows as a separate bucket row…
    expect(screen.getByText("/wf/mywf.pflow.md")).toBeTruthy(); // …not merged into the saved row
  });
});
