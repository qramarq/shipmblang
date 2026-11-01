import { readdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = join(here, "..");

const NETWORK_USE = [
  /from\s+["']node:(?:http|https|net|dns|tls|dgram)["']/u,
  /from\s+["'](?:undici|node-fetch|axios|got)["']/u,
  /\bfetch\s*\(/u,
  /\bXMLHttpRequest\b/u,
  /\bWebSocket\b/u,
  /\bsendBeacon\s*\(/u,
];

describe("local boundary", () => {
  it("does not import or call network clients", () => {
    const sources = readdirSync(here).filter((name) => name.endsWith(".mjs"));
    expect(sources.length).toBeGreaterThan(0);
    for (const name of sources) {
      const source = readFileSync(join(here, name), "utf8");
      for (const pattern of NETWORK_USE)
        expect(source, `${name} matches ${pattern}`).not.toMatch(pattern);
    }
  });

  it("keeps the upstream security policy and disclaimer", () => {
    const security = readFileSync(join(repoRoot, "SECURITY.md"), "utf8");
    const disclaimer = readFileSync(join(repoRoot, "DISCLAIMER.md"), "utf8");
    expect(security).toContain(
      "Do not disclose vulnerabilities, proof-of-concept exploits, credentials,",
    );
    expect(disclaimer).toContain(
      "The REA project does not support, and will not help with:",
    );
    expect(disclaimer).toContain(
      "circumventing DRM, license checks, anti-cheat systems or other technical",
    );
    expect(disclaimer).toContain(
      "Do not use REA for unauthorized access or exploitation, credential theft,",
    );
  });
});
