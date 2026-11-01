import { spawnSync } from "node:child_process";
import {
  mkdtempSync,
  readFileSync,
  readdirSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { parseBuildFromTextArgs, runBuildFromTextCli } from "./cli.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = join(here, "..");
const checksumText = readFileSync(join(here, "fixtures/checksum.txt"), "utf8");

const capture = () => {
  let out = "";
  let err = "";
  return {
    stdout: {
      write: (text: string) => {
        out += text;
      },
    },
    stderr: {
      write: (text: string) => {
        err += text;
      },
    },
    read: () => ({ out, err }),
  };
};

describe("parseBuildFromTextArgs", () => {
  it("requires a text path and an output directory", () => {
    expect(parseBuildFromTextArgs([]).ok).toBe(false);
    expect(parseBuildFromTextArgs(["--out", "out"]).ok).toBe(false);
    expect(parseBuildFromTextArgs(["--text", "spec.txt"]).ok).toBe(false);
    expect(parseBuildFromTextArgs(["--upload"]).ok).toBe(false);
    expect(parseBuildFromTextArgs(["--text", "--out", "out"]).ok).toBe(false);
  });

  it("accepts a positional file and stdin", () => {
    expect(parseBuildFromTextArgs(["spec.txt", "--out", "out"])).toEqual({
      ok: true,
      help: false,
      textPath: "spec.txt",
      outDir: "out",
    });
    expect(
      parseBuildFromTextArgs(["--text", "-", "--out", "out"]),
    ).toMatchObject({
      ok: true,
      textPath: "-",
    });
    expect(parseBuildFromTextArgs(["--help"]).ok).toBe(true);
  });
});

describe("runBuildFromTextCli", () => {
  it("writes the three artifacts and reports that nothing ran", async () => {
    const root = mkdtempSync(join(tmpdir(), "build-from-text-"));
    try {
      const spec = join(root, "spec.txt");
      const out = join(root, "out");
      writeFileSync(spec, checksumText);
      const io = capture();
      const status = await runBuildFromTextCli(
        ["--text", spec, "--out", out],
        io,
      );
      expect(status).toBe(0);
      const report = JSON.parse(io.read().out);
      expect(report).toMatchObject({
        mode: "build-from-text",
        name: "checksum",
        out,
        files: ["PLAN.md", "skeleton.test.ts", "spec.schema.json"],
        executed: false,
        network: false,
        telemetry: false,
      });
      expect(readdirSync(out).sort()).toEqual([
        "PLAN.md",
        "skeleton.test.ts",
        "spec.schema.json",
      ]);
      expect(readFileSync(join(out, "PLAN.md"), "utf8")).toContain(
        "has not been executed",
      );
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it("does not write files when the text has no name", async () => {
    const root = mkdtempSync(join(tmpdir(), "build-from-text-"));
    try {
      const spec = join(root, "spec.txt");
      const out = join(root, "out");
      writeFileSync(spec, "Behavior:\n- Run\n");
      const io = capture();
      const status = await runBuildFromTextCli([spec, "--out", out], io);
      expect(status).toBe(1);
      expect(io.read().err).toContain("needs a name");
      expect(readdirSync(root)).toEqual(["spec.txt"]);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it("returns usage help without creating files", async () => {
    const io = capture();
    expect(await runBuildFromTextCli(["--help"], io)).toBe(0);
    expect(io.read().out).toContain("does not use the network");
    expect(io.read().out).toContain("not run");
    const usage = capture();
    expect(await runBuildFromTextCli(["--out", "out"], usage)).toBe(2);
    expect(usage.read().err).toContain("--text");
  });
});

describe("process entry", () => {
  const runNode = (args: readonly string[], input?: string) =>
    spawnSync(process.execPath, [...args], {
      cwd: repoRoot,
      encoding: "utf8",
      input,
    });

  it("runs from the CLI script and from rea build-from-text", () => {
    const root = mkdtempSync(join(tmpdir(), "build-from-text-"));
    try {
      const spec = join(root, "spec.txt");
      const directOut = join(root, "direct");
      const reaOut = join(root, "rea");
      writeFileSync(spec, checksumText);
      const direct = runNode([
        join(repoRoot, "build-from-text/cli.mjs"),
        "--text",
        spec,
        "--out",
        directOut,
      ]);
      expect(direct.status, direct.stderr).toBe(0);
      expect(JSON.parse(direct.stdout).name).toBe("checksum");
      const rea = runNode(
        [
          join(repoRoot, "scripts/rea.mjs"),
          "build-from-text",
          "--text",
          "-",
          "--out",
          reaOut,
        ],
        checksumText,
      );
      expect(rea.status, rea.stderr).toBe(0);
      expect(JSON.parse(rea.stdout)).toMatchObject({
        mode: "build-from-text",
        executed: false,
        network: false,
        telemetry: false,
      });
      expect(readFileSync(join(reaOut, "spec.schema.json"), "utf8")).toContain(
        '"title": "checksum"',
      );
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });
});
