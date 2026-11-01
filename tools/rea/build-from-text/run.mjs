import { extractSpec } from "./extract.mjs";
import { renderPlan } from "./plan.mjs";
import { specToJsonSchema } from "./schema.mjs";
import { renderSkeleton } from "./skeleton.mjs";

export const OUTPUT_FILES = Object.freeze([
  "PLAN.md",
  "skeleton.test.ts",
  "spec.schema.json",
]);

/** Build the three local artifacts. Does not write files or use the network. */
export const buildFromText = (text) => {
  const extracted = extractSpec(text);
  if (!extracted.ok) return extracted;
  const { spec } = extracted;
  return {
    ok: true,
    spec,
    files: {
      "spec.schema.json": `${JSON.stringify(specToJsonSchema(spec), null, 2)}\n`,
      "PLAN.md": renderPlan(spec),
      "skeleton.test.ts": renderSkeleton(spec),
    },
  };
};
