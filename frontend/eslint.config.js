import js from "@eslint/js";
import i18next from "eslint-plugin-i18next";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist", "coverage", "src/api/schema.d.ts"] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ["**/*.{ts,tsx}"],
    languageOptions: { globals: globals.browser },
    plugins: { "react-hooks": reactHooks },
    rules: reactHooks.configs.recommended.rules,
  },
  {
    // Spec §6.2: every UI string comes from src/i18n/en.json. Literal JSX text and
    // user-facing JSX attributes (aria-label, title, alt, placeholder, …) fail lint.
    files: ["src/**/*.tsx"],
    plugins: { i18next },
    rules: {
      "i18next/no-literal-string": [
        "error",
        {
          mode: "jsx-only",
          "jsx-attributes": {
            exclude: [
              "className",
              "style",
              "type",
              "key",
              "id",
              "width",
              "height",
              "to",
              "href",
              "rel",
              "target",
              "role",
              "lang",
              "name",
              "htmlFor",
              "autoComplete",
              "inputMode",
              "method",
              "viewBox",
              "fill",
              "d",
              "aria-hidden",
              "aria-labelledby",
              "aria-describedby",
              "aria-controls",
              "aria-live",
              "data-testid",
            ],
          },
        },
      ],
    },
  },
  {
    // The API client pins the base URL (/api/v1), cookie credentials and fetch in one place
    // (src/api/client.ts). openapi-fetch lets a single call override them, so callers may not
    // pass `baseUrl`, `credentials` or `fetch` per request, nor build a second client.
    files: ["src/**/*.{ts,tsx}"],
    ignores: ["src/api/client.ts"],
    rules: {
      "no-restricted-imports": [
        "error",
        {
          paths: [
            {
              name: "openapi-fetch",
              message: "Use `api` from src/api/client.ts; it pins the base URL and credentials.",
            },
          ],
        },
      ],
      "no-restricted-syntax": [
        "error",
        {
          selector:
            "CallExpression[callee.property.name=/^(GET|PUT|POST|DELETE|OPTIONS|HEAD|PATCH|TRACE|request)$/] > ObjectExpression > Property:matches([key.name=/^(baseUrl|credentials|fetch)$/], [key.value=/^(baseUrl|credentials|fetch)$/])",
          message:
            "Don't override baseUrl, credentials or fetch per request; src/api/client.ts sets them for every call.",
        },
      ],
    },
  },
  {
    files: ["scripts/**/*.mjs", "*.config.{js,ts}", "tests/**/*.{ts,tsx}"],
    languageOptions: { globals: globals.node },
  },
);
