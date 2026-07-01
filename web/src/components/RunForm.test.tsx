// @vitest-environment jsdom
// RunForm render tests — the reusable, controlled run-inputs form (Task 175).
// Covers control mapping, prefill display, required markers, the sensitive hint,
// the no-input confirm, the submit→onSubmit contract, and inline 400 errors.

import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { RunForm } from "./RunForm";
import type { InputField } from "../graph/flow";

// A port/field description with a fenced block would mount CodeBlock and run the
// real shiki load under jsdom; stub it (same insulation as IoPanel/GraphView tests).
vi.mock("../utils/highlight", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../utils/highlight")>();
  return { ...actual, highlight: vi.fn().mockResolvedValue(null) };
});

afterEach(cleanup);

function field(name: string, over: Partial<InputField> = {}): InputField {
  return { name, dataType: "string", required: false, defaultValue: null, description: null, sensitive: false, ...over };
}

const noop = (): void => {};

describe("RunForm", () => {
  it("renders one control per input, prefilled from values, with required + type markers", () => {
    const inputs = [
      field("name", { required: true, description: "who to greet" }),
      field("count", { dataType: "integer" }),
      field("verbose", { dataType: "boolean" }),
      field("config", { dataType: "object" }),
    ];
    render(
      <RunForm
        inputs={inputs}
        values={{ name: "World", count: "3", verbose: "true", config: '{"a":1}' }}
        onChange={noop}
        onSubmit={noop}
        submitting={false}
        errors={[]}
      />,
    );

    // text → input[type=text] prefilled; required marker present.
    const nameInput = screen.getByLabelText(/name/i) as HTMLInputElement;
    expect(nameInput.value).toBe("World");
    expect(screen.getByLabelText("required")).toBeTruthy();
    expect(screen.getByText("who to greet")).toBeTruthy();

    // integer → number control; boolean → checkbox (checked from "true"); object → textarea.
    expect((screen.getByLabelText(/count/i) as HTMLInputElement).type).toBe("number");
    expect((screen.getByLabelText(/verbose/i) as HTMLInputElement).checked).toBe(true);
    expect((screen.getByLabelText(/config/i) as HTMLTextAreaElement).tagName).toBe("TEXTAREA");
  });

  it("shows the 'provided from settings/env' hint for a sensitive input", () => {
    render(
      <RunForm inputs={[field("api_key", { sensitive: true })]} values={{ api_key: "" }} onChange={noop} onSubmit={noop} submitting={false} errors={[]} />,
    );
    expect(screen.getByText(/provided from settings\/env/i)).toBeTruthy();
  });

  it("a no-input workflow renders just the ▶ Run confirm", () => {
    render(<RunForm inputs={[]} values={{}} onChange={noop} onSubmit={noop} submitting={false} errors={[]} />);
    expect(screen.getByText(/takes no inputs/i)).toBeTruthy();
    expect(screen.getByRole("button", { name: /run/i })).toBeTruthy();
  });

  it("checkbox onChange emits the 'true'/'false' token string (channel A)", () => {
    const onChange = vi.fn();
    render(
      <RunForm inputs={[field("verbose", { dataType: "boolean" })]} values={{ verbose: "false" }} onChange={onChange} onSubmit={noop} submitting={false} errors={[]} />,
    );
    fireEvent.click(screen.getByLabelText(/verbose/i));
    expect(onChange).toHaveBeenCalledWith("verbose", "true");
  });

  it("submitting the form calls onSubmit; a disabled submit (in-flight) does not", () => {
    const onSubmit = vi.fn();
    const { rerender } = render(
      <RunForm inputs={[field("name")]} values={{ name: "x" }} onChange={noop} onSubmit={onSubmit} submitting={false} errors={[]} />,
    );
    fireEvent.click(screen.getByRole("button", { name: /run/i }));
    expect(onSubmit).toHaveBeenCalledTimes(1);

    // While submitting the button is disabled and shows the in-flight label.
    rerender(<RunForm inputs={[field("name")]} values={{ name: "x" }} onChange={noop} onSubmit={onSubmit} submitting errors={[]} />);
    const btn = screen.getByRole("button", { name: /starting/i }) as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
    fireEvent.click(btn);
    expect(onSubmit).toHaveBeenCalledTimes(1); // unchanged
  });

  it("renders the server's 400 diagnostics inline", () => {
    render(
      <RunForm
        inputs={[field("name", { required: true })]}
        values={{ name: "" }}
        onChange={noop}
        onSubmit={noop}
        submitting={false}
        errors={[{ message: "Workflow requires input 'name': the greeting target" }]}
      />,
    );
    expect(screen.getByRole("alert").textContent).toContain("Workflow requires input 'name'");
  });

  it("renders the pre-flight diagnostic's suggestions (the HOW-to-fix), not just the message", () => {
    render(
      <RunForm
        inputs={[field("topic")]}
        values={{ topic: "" }}
        onChange={noop}
        onSubmit={noop}
        submitting={false}
        errors={[{ message: "Unknown input 'nope' — not declared by this workflow.", suggestions: ["Available inputs: topic"] }]}
      />,
    );
    const alert = screen.getByRole("alert").textContent ?? "";
    expect(alert).toContain("Unknown input 'nope'"); // the WHAT
    expect(alert).toContain("Available inputs: topic"); // the HOW-to-fix, previously discarded
  });
});
