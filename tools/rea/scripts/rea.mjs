#!/usr/bin/env node
// Standalone dispatcher for the vendored `rea build-from-text` command.
// Upstream scripts/rea.mjs also loads the compiled REA runtime, which is not
// in this tree. This file only forwards `build-from-text`.

import { runBuildFromTextCli } from "../build-from-text/cli.mjs";

const args = process.argv.slice(2);
if (args[0] !== "build-from-text") {
  process.stderr.write(
    "This dev-only entry only implements `build-from-text`.\n",
  );
  process.exitCode = 2;
} else {
  process.exitCode = await runBuildFromTextCli(args.slice(1));
}
