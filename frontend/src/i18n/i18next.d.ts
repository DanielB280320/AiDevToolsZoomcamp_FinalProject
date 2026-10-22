import "i18next";

import type { defaultNS, resources } from "./index";

// Type-checks translation keys: t("home.title") compiles, t("home.typo") does not.
declare module "i18next" {
  interface CustomTypeOptions {
    defaultNS: typeof defaultNS;
    resources: (typeof resources)["en"];
  }
}
