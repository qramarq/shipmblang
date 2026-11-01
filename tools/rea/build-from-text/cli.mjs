#!/usr/bin/env node

import { mkdir, readFile, stat, writeFile } from "node:fs/promises";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { buildFromText, OUTPUT_FILES } from "./run.mjs";

const HELP = `build-from-text — extract a build spec from plain text

Usage:
  rea build-from-text --text <file> --out <dir>
  rea build-from-text <file> --out <dir>
  rea build-from-text --text - --out <dir>

Reads a local plain-text spec and writes:
  spec.schema.json    JSON Schema extracted from the text
  PLAN.md             build plan (not executed)
  skeleton.test.ts    vitest skeleton (not run)

This command does not use the network, does not emit telemetry,
does not install packages, does not compile a binary, and does not
run the generated tests.

Options:
  --text <file>   Spec file, or - to read stdin
  --out <dir>     Directory to create or update
  --help          Show this help
`;

const failUsage = (message) => ({ ok: false, status: 2, message });

export const parseBuildFromTextArgs = (argv) => {
  let help = false;
  let textPath = null;
  let outDir = null;
  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    if (token === "--help" || token === "-h") {
      help = true;
      continue;
    }
    if (token === "--text" || token === "--out") {
      const value = argv[index + 1];
      if (value === undefined) return failUsage(`${token} needs a value.`);
      if (token === "--out" && value.startsWith("-"))
        return failUsage("--out needs a directory path.");
      if (token === "--text" && value.startsWith("-") && value !== "-")
        return failUsage("--text needs a file path or -.");
      if (token === "--text") {
        if (textPath !== null)
          return failUsage("--text was provided more than once.");
        textPath = value;
      } else {
        if (outDir !== null)
          return failUsage("--out was provided more than once.");
        outDir = value;
      }
      index += 1;
      continue;
    }
    if (token.startsWith("-")) return failUsage(`Unknown option ${token}.`);
    if (textPath !== null) return failUsage(`Unexpected argument ${token}.`);
    textPath = token;
  }
  if (help) return { ok: true, help: true };
  if (textPath === null)
    return failUsage("Provide a plain-text file with --text <file>.");
  if (outDir === null)
    return failUsage("Provide an output directory with --out <dir>.");
  return { ok: true, help: false, textPath, outDir };
};

const isEnoent = (cause) =>
  typeof cause === "object" &&
  cause !== null &&
  "code" in cause &&
  cause.code === "ENOENT";

const readInput = async (textPath, stdin) => {
  if (textPath === "-") {
    const chunks = [];
    for await (const chunk of stdin) chunks.push(Buffer.from(chunk));
    return Buffer.concat(chunks).toString("utf8");
  }
  return readFile(textPath, "utf8");
};

const ensureDirectory = async (outDir) => {
  try {
    const info = await stat(outDir);
    if (!info.isDirectory()) return `Output path is not a directory: ${outDir}`;
  } catch (cause) {
    if (!isEnoent(cause)) throw cause;
  }
  await mkdir(outDir, { recursive: true });
  return null;
};

const writeArtifacts = async (outDir, files) => {
  await Promise.all(
    OUTPUT_FILES.map((name) =>
      writeFile(join(outDir, name), files[name], "utf8"),
    ),
  );
};

/**
 * Run the plaintext-to-build command.
 * Returns a process status. Does not call the network.
 */
export const runBuildFromTextCli = async (argv, io = {}) => {
  const stdout = io.stdout ?? process.stdout;
  const stderr = io.stderr ?? process.stderr;
  const stdin = io.stdin ?? process.stdin;
  const parsed = parseBuildFromTextArgs(argv);
  if (!parsed.ok) {
    stderr.write(`${parsed.message}\n${HELP}`);
    return parsed.status;
  }
  if (parsed.help) {
    stdout.write(HELP);
    return 0;
  }
  const outDir = resolve(parsed.outDir);
  try {
    const text = await readInput(parsed.textPath, stdin);
    const built = buildFromText(text);
    if (!built.ok) {
      stderr.write(`${built.error}\n`);
      return 1;
    }
    const directoryError = await ensureDirectory(outDir);
    if (directoryError !== null) {
      stderr.write(`${directoryError}\n`);
      return 1;
    }
    await writeArtifacts(outDir, built.files);
    stdout.write(
      `${JSON.stringify(
        {
          mode: "build-from-text",
          name: built.spec.name,
          out: outDir,
          files: [...OUTPUT_FILES],
          executed: false,
          network: false,
          telemetry: false,
        },
        null,
        2,
      )}\n`,
    );
    return 0;
  } catch (cause) {
    const message = cause instanceof Error ? cause.message : String(cause);
    stderr.write(`${message}\n`);
    return 1;
  }
};

const isDirectRun =
  process.argv[1] !== undefined &&
  resolve(process.argv[1]) === fileURLToPath(import.meta.url);

if (isDirectRun)
  process.exitCode = await runBuildFromTextCli(process.argv.slice(2));
