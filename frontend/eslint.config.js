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
    files: ["scripts/**/*.mjs", "*.config.{js,ts}", "tests/**/*.{ts,tsx}"],
    languageOptions: { globals: globals.node },
  },
);
