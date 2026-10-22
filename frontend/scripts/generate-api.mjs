#!/usr/bin/env node
// Generates the typed API client types from the contract (ADR 0005).
//
//   npm run generate:api   writes src/api/schema.d.ts from ../openapi.yaml
//   npm run check:api      exits 1 if the committed file is out of date (used by CI, #11)
//   --out <path>           compare/write another file instead (used by the drift test)
//
// Both modes use the same generator so their output is byte-identical.
import { readFile, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import openapiTS, { astToString } from "openapi-typescript";

const specUrl = new URL("../../openapi.yaml", import.meta.url);
const outIndex = process.argv.indexOf("--out");
const outPath =
  outIndex > -1 && process.argv[outIndex + 1]
    ? process.argv[outIndex + 1]
    : fileURLToPath(new URL("../src/api/schema.d.ts", import.meta.url));

const HEADER = `/**
 * GENERATED FILE - do not edit by hand.
 * Source: openapi.yaml (repository root). Regenerate with \`npm run generate:api\`.
 */

`;

const ast = await openapiTS(specUrl);
const generated = HEADER + astToString(ast);

if (process.argv.includes("--check")) {
  let committed = "";
  try {
    committed = await readFile(outPath, "utf8");
  } catch {
    // Missing file counts as out of date.
  }
  if (committed !== generated) {
    console.error(
      `${outPath} is out of date with openapi.yaml. Run \`npm run generate:api\` and commit the result.`,
    );
    process.exit(1);
  }
  console.log(`${outPath} is up to date with openapi.yaml.`);
} else {
  await writeFile(outPath, generated);
  console.log(`Wrote ${outPath}`);
}
