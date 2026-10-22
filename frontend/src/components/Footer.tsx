import { useTranslation } from "react-i18next";

/** Shown on every page; the disclaimer text is fixed by spec §6.3. */
export function Footer() {
  const { t } = useTranslation();

  return (
    <footer className="border-t border-line">
      <div className="mx-auto w-full max-w-5xl px-4 py-6 sm:px-8">
        <p className="max-w-[65ch] text-step--1 text-slate">{t("footer.disclaimer")}</p>
      </div>
    </footer>
  );
}
