import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import en from "./en.json";

// Every UI string lives in en.json (spec §6.2). Adding a language means adding
// another resource file here; no component changes.
export const defaultNS = "translation";
export const resources = { en: { translation: en } } as const;

void i18n.use(initReactI18next).init({
  resources,
  lng: "en",
  fallbackLng: "en",
  defaultNS,
  initAsync: false,
  interpolation: { escapeValue: false }, // React already escapes output.
  returnNull: false,
});

export default i18n;
