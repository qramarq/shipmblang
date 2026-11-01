import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { extractSpec } from "./extract.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const checksumText = readFileSync(join(here, "fixtures/checksum.txt"), "utf8");

describe("extractSpec", () => {
  it("extracts the checksum fixture", () => {
    const result = extractSpec(checksumText);
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.spec).toEqual({
      name: "checksum",
      summary: "Print a lowercase hex digest of a file.",
      kind: "binary",
      language: "typescript",
      entry: "src/checksum.ts",
      behaviors: [
        "Read the first argument as a file path",
        "Write the digest to stdout",
        "Exit 2 when the path is missing",
      ],
      inputs: [{ name: "path", type: "string", required: true }],
      outputs: [{ name: "digest", type: "string", required: true }],
      constraints: {
        network: "forbidden",
        telemetry: "forbidden",
        notes: [],
      },
      acceptanceTests: ["missing path exits 2", "known bytes match digest"],
      notes: [],
    });
  });

  it("reads markdown headings and optional fields", () => {
    const result = extractSpec(
      [
        "# widget",
        "",
        "A small feature.",
        "",
        "## Behavior",
        "- Render a label",
        "## Inputs",
        "- label?: string",
        "- count: int, optional",
        "## Tests",
        '- say "hi"',
      ].join("\n"),
    );
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.spec.name).toBe("widget");
    expect(result.spec.summary).toBe("A small feature.");
    expect(result.spec.kind).toBe("unspecified");
    expect(result.spec.language).toBeNull();
    expect(result.spec.behaviors).toEqual(["Render a label"]);
    expect(result.spec.inputs).toEqual([
      { name: "label", type: "string", required: false },
      { name: "count", type: "integer", required: false },
    ]);
    expect(result.spec.acceptanceTests).toEqual(['say "hi"']);
    expect(result.spec.constraints).toEqual({
      network: "unspecified",
      telemetry: "unspecified",
      notes: [],
    });
  });

  it("keeps a colon inside a behavior bullet", () => {
    const result = extractSpec(
      "Name: reader\nBehavior:\n- Read the file: carefully\n",
    );
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.spec.behaviors).toEqual(["Read the file: carefully"]);
  });

  it("accepts an input named entry", () => {
    const result = extractSpec(
      "Name: paths\nInputs:\n- entry: string, required\n",
    );
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.spec.inputs).toEqual([
      { name: "entry", type: "string", required: true },
    ]);
    expect(result.spec.entry).toBeNull();
  });

  it("accepts one inline behavior and matching names", () => {
    const result = extractSpec(
      "# checksum\nName: checksum\nBehavior: Read a path\n",
    );
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.spec.name).toBe("checksum");
    expect(result.spec.behaviors).toEqual(["Read a path"]);
  });
});

describe("extractSpec constraints and errors", () => {
  it("maps offline and no-telemetry phrases", () => {
    const result = extractSpec(
      "Name: local\nConstraints:\n- offline\n- no-telemetry\n- keep logs local\n",
    );
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.spec.constraints).toEqual({
      network: "forbidden",
      telemetry: "forbidden",
      notes: ["keep logs local"],
    });
  });

  it("rejects empty text, a missing name, and conflicts", () => {
    expect(extractSpec("")).toEqual({
      ok: false,
      error: "Plain text is empty.",
    });
    expect(extractSpec("   \n")).toEqual({
      ok: false,
      error: "Plain text is empty.",
    });
    expect(extractSpec(42).ok).toBe(false);
    expect(extractSpec("Behavior:\n- Run\n").ok).toBe(false);
    const conflict = extractSpec(
      "Name: sample\nConstraints:\n- no network\n- allow network\n",
    );
    expect(conflict.ok).toBe(false);
    if (conflict.ok) return;
    expect(conflict.error).toContain("network");
  });

  it("rejects an unknown kind, an unknown type, and a duplicate field", () => {
    expect(extractSpec("Name: sample\nKind: firmware\n").ok).toBe(false);
    expect(extractSpec("Name: sample\nInputs:\n- n: widget\n").ok).toBe(false);
    expect(
      extractSpec("Name: sample\nInputs:\n- n: string\n- n: string\n").ok,
    ).toBe(false);
    expect(
      extractSpec("Name: sample\nInputs:\n- n?: string, required\n").ok,
    ).toBe(false);
  });

  it("normalizes a BOM and CRLF", () => {
    const result = extractSpec("\uFEFFName: bom\r\nSummary: one\r\n");
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.spec.name).toBe("bom");
    expect(result.spec.summary).toBe("one");
  });

  it("rejects a second different name and text over 1 MiB", () => {
    const renamed = extractSpec("# one\nName: two\n");
    expect(renamed.ok).toBe(false);
    const huge = extractSpec(`Name: big\n${"a".repeat(1024 * 1024)}`);
    expect(huge.ok).toBe(false);
    if (huge.ok) return;
    expect(huge.error).toContain("1 MiB");
  });
});
