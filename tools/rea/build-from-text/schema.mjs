const fieldSchema = (field) => ({ type: field.type });

const objectSchema = (fields) => {
  const properties = {};
  const required = [];
  for (const field of fields) {
    properties[field.name] = fieldSchema(field);
    if (field.required) required.push(field.name);
  }
  const schema = {
    type: "object",
    additionalProperties: false,
    properties,
  };
  if (required.length > 0) schema.required = required;
  return schema;
};

const payloadSchema = (spec) => {
  const hasInputs = spec.inputs.length > 0;
  const hasOutputs = spec.outputs.length > 0;
  if (hasInputs && hasOutputs) {
    return {
      type: "object",
      additionalProperties: false,
      properties: {
        input: objectSchema(spec.inputs),
        output: objectSchema(spec.outputs),
      },
      required: ["input", "output"],
    };
  }
  if (hasInputs) return objectSchema(spec.inputs);
  if (hasOutputs) return objectSchema(spec.outputs);
  return {
    type: "object",
    additionalProperties: false,
    properties: {},
  };
};

/**
 * Render an extracted spec as a JSON Schema document.
 * `$schema` is a dialect identifier. This function does not fetch it.
 */
export const specToJsonSchema = (spec) => ({
  $schema: "https://json-schema.org/draft/2020-12/schema",
  $id: "urn:build-from-text:spec",
  title: spec.name,
  description: spec.summary,
  ...payloadSchema(spec),
  "x-build-from-text": {
    version: 1,
    kind: spec.kind,
    language: spec.language,
    entry: spec.entry,
    behaviors: spec.behaviors,
    constraints: spec.constraints,
    acceptanceTests: spec.acceptanceTests,
    notes: spec.notes,
  },
});
