import { describe, expect, it } from "vitest";

import { controlForType } from "./controlForType";

describe("controlForType", () => {
  it("maps every canonical input type to its control", () => {
    expect(controlForType("string")).toBe("text");
    expect(controlForType("any")).toBe("text");
    expect(controlForType("number")).toBe("number");
    expect(controlForType("integer")).toBe("number");
    expect(controlForType("boolean")).toBe("checkbox");
    expect(controlForType("object")).toBe("textarea");
    expect(controlForType("array")).toBe("textarea");
  });

  it("falls back to text on null and on an unrecognized / Python-alias type", () => {
    // io.data_type is the authored string — it may be null or a Python alias the
    // canonical set doesn't include. A text box never loses info (channel A re-types).
    expect(controlForType(null)).toBe("text");
    expect(controlForType("str")).toBe("text");
    expect(controlForType("dict")).toBe("text");
    expect(controlForType("List[int]")).toBe("text");
  });
});
