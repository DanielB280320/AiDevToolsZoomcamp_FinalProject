import { useTranslation } from "react-i18next";
import { Outlet } from "react-router";

import { Footer } from "./Footer";
import { Header } from "./Header";

export const MAIN_CONTENT_ID = "main-content";

/** Header, page content and footer shared by every route (spec §6.1: mobile-first). */
export function AppShell() {
  const { t } = useTranslation();

  return (
    <div className="flex min-h-dvh flex-col">
      <a
        href={`#${MAIN_CONTENT_ID}`}
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-10 focus:rounded focus:bg-iron focus:px-4 focus:py-2 focus:text-chalk"
      >
        {t("app.skipToContent")}
      </a>
      <Header />
      <main id={MAIN_CONTENT_ID} tabIndex={-1} className="flex-1 focus:outline-none">
        <div className="mx-auto w-full max-w-5xl px-4 py-8 sm:px-8 sm:py-12">
          <Outlet />
        </div>
      </main>
      <Footer />
    </div>
  );
}
