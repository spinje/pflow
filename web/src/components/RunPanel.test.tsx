// @vitest-environment jsdom
// RunPanel "load inputs from" picker (Task 175 Phase 5) — the re-run prefill. inputFields is mocked to a
// fixed schema (this tests the picker/prefill, not the contract→fields derivation, which graph/io covers);
// the client seam (fetchRuns / fetchRunInputs) is mocked like the other panel tests.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

vi.mock("../api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/client")>()),
  fetchRuns: vi.fn(),
  fetchRunInputs: vi.fn(),
  runWorkflow: vi.fn(),
}));
vi.mock("../graph/flow", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../graph/flow")>()),
  inputFields: vi.fn(),
}));

import { RunPanel } from "./RunPanel";
import { fetchRunInputs, fetchRuns } from "../api/client";
import { inputFields, type InputField } from "../graph/flow";
import type { RFGraph, RunInfo } from "../types";

// topic: a normal defaulted input; api_key: sensitive (blank by default; server omits it from a run's inputs).
const FIELDS: InputField[] = [
  { name: "topic", dataType: "string", required: true, defaultValue: "cats", description: null, sensitive: false },
  { name: "api_key", dataType: "string", required: false, defaultValue: null, description: null, sensitive: true },
];

function aRun(id: string): RunInfo {
  return {
    run_id: id,
    workflow_name: "wf",
    workflow_path: "/wf.pflow.md",
    start_time: "2026-07-01T00:00:00Z",
    complete: true,
    final_status: "success",
    live: false,
    only_node: null,
    trace_file: "/t.json",
    git_root: null,
  };
}

const field = (name: string): HTMLInputElement => document.getElementById(`run-field-${name}`) as HTMLInputElement;
const noop = (): void => {};

afterEach(cleanup);
beforeEach(() => {
  vi.mocked(inputFields).mockReturnValue(FIELDS);
  vi.mocked(fetchRuns).mockResolvedValue([aRun("run-1")]);
  vi.mocked(fetchRunInputs).mockReset();
});

function show(): void {
  render(<RunPanel workflow="/wf.pflow.md" workflowName="wf" graph={{} as RFGraph} onLaunched={noop} onClose={noop} />);
}

describe("RunPanel — load inputs from picker (Phase 5)", () => {
  it("shows the picker once past runs load; fields start at their declared defaults (sensitive blank)", async () => {
    show();
    expect(await screen.findByText("load inputs from")).toBeTruthy();
    expect(field("topic").value).toBe("cats"); // declared default
    expect(field("api_key").value).toBe(""); // sensitive → blank, never prefilled
  });

  it("loading a past run prefills non-sensitive fields from its inputs; the sensitive field stays blank", async () => {
    vi.mocked(fetchRunInputs).mockResolvedValue({ topic: "dogs" }); // server OMITS api_key
    show();
    const select = await screen.findByRole("combobox");
    fireEvent.change(select, { target: { value: "run-1" } });
    await waitFor(() => expect(field("topic").value).toBe("dogs"));
    expect(vi.mocked(fetchRunInputs)).toHaveBeenCalledWith("/wf.pflow.md", "run-1");
    expect(field("api_key").value).toBe(""); // omitted by the server → re-resolves from settings/env
  });

  it("selecting Defaults resets the fields to their declared defaults", async () => {
    vi.mocked(fetchRunInputs).mockResolvedValue({ topic: "dogs" });
    show();
    const select = await screen.findByRole("combobox");
    fireEvent.change(select, { target: { value: "run-1" } });
    await waitFor(() => expect(field("topic").value).toBe("dogs"));
    fireEvent.change(select, { target: { value: "defaults" } });
    expect(field("topic").value).toBe("cats");
  });

  it("renders no picker when the workflow has no past runs", async () => {
    vi.mocked(fetchRuns).mockResolvedValue([]);
    show();
    // the form still renders (topic field present), but the picker is hidden with nothing to load from
    await waitFor(() => expect(field("topic")).toBeTruthy());
    expect(screen.queryByText("load inputs from")).toBeNull();
  });
});
