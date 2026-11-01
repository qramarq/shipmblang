import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { buildFromText } from "./run.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const checksumText = readFileSync(join(here, "fixtures/checksum.txt"), "utf8");

const builtChecksum = () => {
  const built = buildFromText(checksumText);
  expect(built.ok).toBe(true);
  if (!built.ok) throw new Error("expected checksum spec to extract");
  return built;
};

describe("spec schema", () => {
  it("turns the checksum text into a JSON schema", () => {
    const built = builtChecksum();
    const schema = JSON.parse(built.files["spec.schema.json"]);
    expect(schema.$schema).toBe("https://json-schema.org/draft/2020-12/schema");
    expect(schema.$id).toBe("urn:build-from-text:spec");
    expect(schema.title).toBe("checksum");
    expect(schema.description).toBe("Print a lowercase hex digest of a file.");
    expect(schema.additionalProperties).toBe(false);
    expect(schema.required).toEqual(["input", "output"]);
    expect(schema.properties.input.required).toEqual(["path"]);
    expect(schema.properties.input.properties.path).toEqual({ type: "string" });
    expect(schema.properties.output.properties.digest).toEqual({
      type: "string",
    });
    expect(schema["x-build-from-text"]).toMatchObject({
      version: 1,
      kind: "binary",
      language: "typescript",
      entry: "src/checksum.ts",
      constraints: { network: "forbidden", telemetry: "forbidden" },
      acceptanceTests: ["missing path exits 2", "known bytes match digest"],
    });
  });

  it("uses the only declared object as the schema root", () => {
    const inputsOnly = buildFromText("Name: echo\nInputs:\n- text?: string\n");
    expect(inputsOnly.ok).toBe(true);
    if (!inputsOnly.ok) return;
    const schema = JSON.parse(inputsOnly.files["spec.schema.json"]);
    expect(schema.properties.text).toEqual({ type: "string" });
    expect(schema.required).toBeUndefined();
    expect(schema.properties.input).toBeUndefined();
  });

  it("emits an empty object schema when no fields are declared", () => {
    const bare = buildFromText("Name: note\n");
    expect(bare.ok).toBe(true);
    if (!bare.ok) return;
    const schema = JSON.parse(bare.files["spec.schema.json"]);
    expect(schema.properties).toEqual({});
    expect(schema.additionalProperties).toBe(false);
    expect(schema["x-build-from-text"].language).toBeNull();
    expect(schema["x-build-from-text"].constraints.network).toBe("unspecified");
  });
});

describe("plan file", () => {
  it("records the spec without claiming the plan or tests ran", () => {
    const plan = builtChecksum().files["PLAN.md"];
    expect(plan).toContain("# Build plan: checksum");
    expect(plan).toContain("This plan has not been executed.");
    expect(plan).toContain("have not been run.");
    expect(plan).toContain("did not check that it exists");
    expect(plan).toContain("Network is forbidden by the plain text.");
    expect(plan).toContain("missing path exits 2");
    expect(plan).toContain("SECURITY.md");
    expect(plan).toContain("DISCLAIMER.md");
    expect(plan.toLowerCase()).not.toContain("tests passed");
    expect(plan.toLowerCase()).not.toContain("was tested");
  });

  it("does not treat an allowed constraint as work this generator performed", () => {
    const built = buildFromText(
      "Name: fetch-plan\nConstraints:\n- allow network\n",
    );
    expect(built.ok).toBe(true);
    if (!built.ok) return;
    expect(built.files["PLAN.md"]).toContain(
      "The plain text allows Network. This generator still did not use it.",
    );
  });
});

describe("test skeleton", () => {
  it("quotes acceptance tests as vitest todos", () => {
    const skeleton = builtChecksum().files["skeleton.test.ts"];
    expect(skeleton).toContain('import { describe, it } from "vitest";');
    expect(skeleton).toContain("The generator has not run them.");
    expect(skeleton).toContain('describe("checksum", () => {');
    expect(skeleton).toContain('it.todo("missing path exits 2");');
    expect(skeleton).toContain('it.todo("known bytes match digest");');
    expect(skeleton).not.toMatch(/\bit\(/u);
  });

  it("escapes quotes and adds a placeholder when no tests were declared", () => {
    const quoted = buildFromText('Name: quote\nTests:\n- say "hi" \\\n');
    expect(quoted.ok).toBe(true);
    if (!quoted.ok) return;
    expect(quoted.files["skeleton.test.ts"]).toContain(
      `it.todo(${JSON.stringify('say "hi" \\')});`,
    );
    const empty = buildFromText("Name: later\n");
    expect(empty.ok).toBe(true);
    if (!empty.ok) return;
    expect(empty.files["skeleton.test.ts"]).toContain(
      'it.todo("specify acceptance tests for later");',
    );
  });
});
