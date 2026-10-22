import { useTranslation } from "react-i18next";
import { Link } from "react-router";

export function Header() {
  const { t } = useTranslation();

  return (
    <header className="border-b-4 border-plate bg-iron text-chalk">
      <div className="mx-auto flex w-full max-w-5xl items-center justify-between gap-4 px-4 py-3 sm:px-8">
        <Link
          to="/"
          aria-label={t("app.homeLink")}
          className="font-display text-step-3 font-bold leading-none tracking-tight text-chalk no-underline"
        >
          {t("app.name")}
        </Link>
        {/* Primary navigation lands here with the Today, Plan and Progress pages. */}
      </div>
    </header>
  );
}
