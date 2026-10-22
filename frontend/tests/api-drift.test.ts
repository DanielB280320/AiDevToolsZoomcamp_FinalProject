// @vitest-environment node
import { execFile } from "node:child_process";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { promisify } from "node:util";

import { afterAll, beforeAll, describe, expect, it } from "vitest";

const run = promisify(execFile);
// Each test spawns node + openapi-typescript; on a loaded host (parallel agents, CI) that can
// exceed Vitest's 5 s default, so give these subprocess tests an explicit budget.
const SUBPROCESS_TIMEOUT_MS = 30_000;
const frontendDir = new URL("..", import.meta.url).pathname;
const checkApi = (...args: string[]) =>
  run(process.execPath, ["scripts/generate-api.mjs", "--check", ...args], { cwd: frontendDir });

describe("npm run check:api", () => {
  let dir: string;
  beforeAll(async () => {
    dir = await mkdtemp(join(tmpdir(), "fitwise-api-"));
  });
  afterAll(async () => {
    await rm(dir, { recursive: true, force: true });
  });

  it("passes for the committed client", async () => {
    await expect(checkApi()).resolves.toMatchObject({ stdout: expect.stringContaining("up to date") });
  }, SUBPROCESS_TIMEOUT_MS);

  it("fails when the generated client is out of date", async () => {
    const stale = join(dir, "schema.d.ts");
    const committed = await readFile(join(frontendDir, "src/api/schema.d.ts"), "utf8");
    await writeFile(stale, committed.replace("getHealth", "getHealthOld"));

    await expect(checkApi("--out", stale)).rejects.toMatchObject({
      code: 1,
      stderr: expect.stringContaining("out of date"),
    });
  }, SUBPROCESS_TIMEOUT_MS);

  it("fails when the generated client is missing", async () => {
    await expect(checkApi("--out", join(dir, "missing.d.ts"))).rejects.toMatchObject({ code: 1 });
  }, SUBPROCESS_TIMEOUT_MS);
});
