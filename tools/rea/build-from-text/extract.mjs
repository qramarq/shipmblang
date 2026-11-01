const MAX_TEXT_BYTES = 1024 * 1024;
const MAX_LINE_LENGTH = 4000;
const MAX_NAME_LENGTH = 200;

const SCALAR_FIELDS = new Map([
  ["name", "name"],
  ["title", "name"],
  ["kind", "kind"],
  ["language", "language"],
  ["lang", "language"],
  ["entry", "entry"],
  ["entrypoint", "entry"],
  ["entry point", "entry"],
  ["summary", "summary"],
  ["description", "summary"],
]);

const SECTIONS = new Map([
  ["behavior", "behaviors"],
  ["behaviors", "behaviors"],
  ["constraint", "constraints"],
  ["constraints", "constraints"],
  ["test", "tests"],
  ["tests", "tests"],
  ["acceptance", "tests"],
  ["acceptance tests", "tests"],
  ["input", "inputs"],
  ["inputs", "inputs"],
  ["output", "outputs"],
  ["outputs", "outputs"],
  ["note", "notes"],
  ["notes", "notes"],
]);

const INLINE_SECTIONS = new Set(["behaviors", "tests", "notes"]);
const CONSTRAINT_KEYS = new Set(["network", "telemetry"]);
const CONSTRAINT_VALUES = new Set(["forbidden", "allowed", "unspecified"]);
const KINDS = new Set(["binary", "feature", "library", "module", "service"]);

const TYPE_ALIASES = new Map([
  ["string", "string"],
  ["str", "string"],
  ["text", "string"],
  ["number", "number"],
  ["float", "number"],
  ["double", "number"],
  ["integer", "integer"],
  ["int", "integer"],
  ["boolean", "boolean"],
  ["bool", "boolean"],
  ["object", "object"],
  ["array", "array"],
  ["list", "array"],
  ["null", "null"],
]);

const fail = (error) => ({ ok: false, error });

const done = (section) => ({ ok: true, section });

const emptyDraft = () => ({
  name: null,
  summary: "",
  kind: null,
  language: null,
  entry: null,
  behaviors: [],
  inputs: [],
  outputs: [],
  constraints: { network: null, telemetry: null, notes: [] },
  tests: [],
  notes: [],
  loose: [],
});

const headingOf = (line) => {
  const match = /^(#{1,6})\s+(.+?)\s*#*$/u.exec(line);
  if (!match) return null;
  return { level: match[1].length, text: match[2].trim() };
};

const bulletBody = (line) => {
  const match = /^(?:[-*]|[0-9]+[.)])\s+(.+)$/u.exec(line);
  return match ? match[1].trim() : null;
};

const splitField = (line) => {
  const match = /^([^:]+):\s*(.*)$/u.exec(line);
  if (!match) return null;
  return {
    label: match[1].trim().toLowerCase(),
    value: match[2].trim(),
  };
};

const sectionName = (line) => {
  const field = splitField(bulletBody(line) ?? line);
  if (!field || field.value !== "") return null;
  return SECTIONS.get(field.label) ?? null;
};

const scalarAssignment = (line) => {
  if (bulletBody(line) !== null) return null;
  const field = splitField(line);
  if (!field || field.value === "") return null;
  const key = SCALAR_FIELDS.get(field.label);
  if (key === undefined) return null;
  return { key, value: field.value };
};

const constraintAssignment = (line) => {
  if (bulletBody(line) !== null) return null;
  const field = splitField(line);
  if (!field || field.value === "" || !CONSTRAINT_KEYS.has(field.label))
    return null;
  return { key: field.label, value: field.value.toLowerCase() };
};

const inlineSection = (line) => {
  if (bulletBody(line) !== null) return null;
  const field = splitField(line);
  if (!field || field.value === "") return null;
  const section = SECTIONS.get(field.label);
  if (section === undefined || !INLINE_SECTIONS.has(section)) return null;
  return { section, value: field.value };
};

const noteField = (line) => {
  if (bulletBody(line) !== null) return null;
  const field = splitField(line);
  if (!field || field.value === "") return null;
  if (SCALAR_FIELDS.has(field.label) || SECTIONS.has(field.label)) return null;
  if (CONSTRAINT_KEYS.has(field.label)) return null;
  return `${field.label}: ${field.value}`;
};

const setScalar = (draft, key, value) => {
  if (key === "name") {
    if (value.length > MAX_NAME_LENGTH)
      return fail("Name must be 200 characters or fewer.");
    if (draft.name !== null && draft.name !== value)
      return fail(`Name is already "${draft.name}".`);
    draft.name = value;
    return { ok: true };
  }
  if (key === "summary") {
    if (draft.summary !== "" && draft.summary !== value)
      return fail("Summary is already set.");
    draft.summary = value;
    return { ok: true };
  }
  if (draft[key] !== null && draft[key] !== value)
    return fail(`${key} is already set.`);
  draft[key] = value;
  return { ok: true };
};

const setConstraint = (draft, key, value) => {
  if (!CONSTRAINT_VALUES.has(value))
    return fail(`${key} must be forbidden, allowed, or unspecified.`);
  const current = draft.constraints[key];
  if (current !== null && current !== value)
    return fail(`${key} is already ${current} and cannot also be ${value}.`);
  draft.constraints[key] = value;
  return { ok: true };
};

const parseConstraintPhrase = (text) => {
  const normalized = text.toLowerCase().replaceAll(/[_-]+/gu, " ");
  const mentionsNetwork =
    /\bnetwork\b/u.test(normalized) || /\boffline\b/u.test(normalized);
  const mentionsTelemetry = /\btelemetry\b/u.test(normalized);
  if (!mentionsNetwork && !mentionsTelemetry) return { ok: true, note: text };
  if (mentionsNetwork && mentionsTelemetry)
    return fail(`Separate network and telemetry in "${text}".`);
  const forbidden =
    /\b(?:no|not|forbidden|deny|denied|disallow|offline|cannot|without)\b/u.test(
      normalized,
    );
  const allowed = /\b(?:allow|allowed)\b/u.test(normalized);
  if (forbidden === allowed) {
    const topic = mentionsNetwork ? "network" : "telemetry";
    return fail(
      `Could not tell whether "${text}" allows or forbids ${topic}. Use "no ${topic}" or "allow ${topic}".`,
    );
  }
  const value = forbidden ? "forbidden" : "allowed";
  return mentionsNetwork
    ? { ok: true, network: value }
    : { ok: true, telemetry: value };
};

const addConstraintPhrase = (draft, text) => {
  const parsed = parseConstraintPhrase(text);
  if (!parsed.ok) return parsed;
  if (parsed.note !== undefined) {
    draft.constraints.notes.push(parsed.note);
    return done("constraints");
  }
  if (parsed.network !== undefined) {
    const network = setConstraint(draft, "network", parsed.network);
    if (!network.ok) return network;
  }
  if (parsed.telemetry !== undefined) {
    const telemetry = setConstraint(draft, "telemetry", parsed.telemetry);
    if (!telemetry.ok) return telemetry;
  }
  return done("constraints");
};

const parseTypedField = (text) => {
  const match =
    /^([A-Za-z_][A-Za-z0-9_-]*)(\?)?\s*:\s*([A-Za-z]+)(?:(?:\s*,\s*|\s+)(required|optional))?\s*$/u.exec(
      text,
    );
  if (!match)
    return fail(
      `Could not read a typed field from "${text}". Use "name: string" or "name: string, required".`,
    );
  const [, name, optionalMark, rawType, presence] = match;
  const type = TYPE_ALIASES.get(rawType.toLowerCase());
  if (type === undefined)
    return fail(
      `Unknown type "${rawType}" for ${name}. Use string, number, integer, boolean, object, array, or null.`,
    );
  if (optionalMark === "?" && presence === "required")
    return fail(`${name} is marked both optional and required.`);
  const required =
    presence === "required" ||
    (presence !== "optional" && optionalMark !== "?");
  return { ok: true, field: { name, type, required } };
};

const addTypedField = (draft, section, text) => {
  const parsed = parseTypedField(text);
  if (!parsed.ok) return parsed;
  const fields = draft[section];
  if (fields.some((field) => field.name === parsed.field.name))
    return fail(`Duplicate ${section} field "${parsed.field.name}".`);
  fields.push(parsed.field);
  return done(section);
};

const addItem = (draft, section, text) => {
  if (section === null) draft.loose.push(text);
  else if (section === "behaviors") draft.behaviors.push(text);
  else if (section === "tests") draft.tests.push(text);
  else if (section === "notes") draft.notes.push(text);
  else return fail(`Section "${section}" does not take plain items.`);
  return done(section);
};

const applyHeading = (draft, heading) => {
  const section = SECTIONS.get(heading.text.toLowerCase());
  if (section !== undefined) return done(section);
  if (heading.level === 1) {
    const named = setScalar(draft, "name", heading.text);
    if (!named.ok) return named;
    return done(null);
  }
  draft.notes.push(heading.text);
  return done(null);
};

const consumeLine = (draft, section, line) => {
  const heading = headingOf(line);
  if (heading) return applyHeading(draft, heading);
  const header = sectionName(line);
  if (header) return done(header);
  if (section === "inputs" || section === "outputs")
    return addTypedField(draft, section, bulletBody(line) ?? line);
  if (section === "constraints")
    return addConstraintPhrase(draft, bulletBody(line) ?? line);
  const scalar = scalarAssignment(line);
  if (scalar) {
    const assigned = setScalar(draft, scalar.key, scalar.value);
    if (!assigned.ok) return assigned;
    return done(section);
  }
  const constraint = constraintAssignment(line);
  if (constraint) {
    const assigned = setConstraint(draft, constraint.key, constraint.value);
    if (!assigned.ok) return assigned;
    return done(section);
  }
  const inline = inlineSection(line);
  if (inline) {
    const added = addItem(draft, inline.section, inline.value);
    if (!added.ok) return added;
    return done(inline.section);
  }
  const note = noteField(line);
  if (note !== null) {
    draft.notes.push(note);
    return done(section);
  }
  return addItem(draft, section, bulletBody(line) ?? line);
};

const finishDraft = (draft) => {
  if (draft.name === null)
    return fail(
      "Plain text needs a name. Add `Name: ...` or a level-one heading.",
    );
  if (draft.summary === "") draft.summary = draft.loose.join(" ");
  else draft.notes.push(...draft.loose);
  if (draft.kind === null) draft.kind = "unspecified";
  else {
    const kind = draft.kind.toLowerCase();
    if (!KINDS.has(kind))
      return fail(
        `Kind must be binary, feature, library, module, or service. Received "${draft.kind}".`,
      );
    draft.kind = kind;
  }
  const { constraints } = draft;
  if (constraints.network === null) constraints.network = "unspecified";
  if (constraints.telemetry === null) constraints.telemetry = "unspecified";
  return {
    ok: true,
    spec: {
      name: draft.name,
      summary: draft.summary,
      kind: draft.kind,
      language: draft.language,
      entry: draft.entry,
      behaviors: draft.behaviors,
      inputs: draft.inputs,
      outputs: draft.outputs,
      constraints,
      acceptanceTests: draft.tests,
      notes: draft.notes,
    },
  };
};

/** Extract a build spec from local plain text. Never reads the network. */
export const extractSpec = (text) => {
  if (typeof text !== "string") return fail("Plain text must be a string.");
  const normalized = text.replace(/^\uFEFF/u, "").replaceAll(/\r\n?/gu, "\n");
  if (Buffer.byteLength(normalized, "utf8") > MAX_TEXT_BYTES)
    return fail("Plain text is larger than 1 MiB.");
  if (normalized.trim() === "") return fail("Plain text is empty.");
  const draft = emptyDraft();
  let section = null;
  for (const raw of normalized.split("\n")) {
    const line = raw.trim();
    if (line === "") continue;
    if (line.length > MAX_LINE_LENGTH)
      return fail("A line exceeds 4000 characters.");
    const consumed = consumeLine(draft, section, line);
    if (!consumed.ok) return consumed;
    section = consumed.section;
  }
  return finishDraft(draft);
};
