// @vitest-environment node
import { readFile } from "node:fs/promises";

import { ESLint } from "eslint";
import { describe, expect, it } from "vitest";

import en from "../src/i18n/en.json";

const frontendDir = new URL("..", import.meta.url).pathname;
// The first lintText() loads the whole ESLint config and plugins; on a loaded host (parallel
// agents, CI) that can exceed Vitest's 5 s default, so the ESLint tests get an explicit budget.
const ESLINT_TIMEOUT_MS = 30_000;

describe("i18n", () => {
  it("uses the spec §6.3 disclaimer verbatim", async () => {
    const spec = await readFile(new URL("../../docs/spec.md", import.meta.url), "utf8");
    const section = spec.slice(spec.indexOf("### 6.3"), spec.indexOf("### 6.4"));

    expect(section).toContain(`"${en.footer.disclaimer}"`);
  });

  describe("eslint i18next/no-literal-string", () => {
    const eslint = new ESLint({ cwd: frontendDir });
    const lint = async (code: string) => {
      const [result] = await eslint.lintText(code, { filePath: "src/components/Example.tsx" });
      return result!.messages.filter((m) => m.ruleId === "i18next/no-literal-string");
    };

    it("fails on literal JSX text", async () => {
      expect(await lint(`export const Example = () => <p>Log your set</p>;\n`)).toHaveLength(1);
    }, ESLINT_TIMEOUT_MS);

    it("fails on literal user-facing attributes", async () => {
      expect(await lint(`export const Example = () => <button aria-label="Close" />;\n`)).toHaveLength(1);
    }, ESLINT_TIMEOUT_MS);

    it("allows translated text and technical attributes", async () => {
      const code = [
        `import { useTranslation } from "react-i18next";`,
        `export const Example = () => {`,
        `  const { t } = useTranslation();`,
        `  return <p className="text-slate" id="x">{t("home.title")}</p>;`,
        `};`,
        ``,
      ].join("\n");
      expect(await lint(code)).toEqual([]);
    }, ESLINT_TIMEOUT_MS);
  });
});
