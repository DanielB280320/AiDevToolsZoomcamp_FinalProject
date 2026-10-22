import { useTranslation } from "react-i18next";
import { Link } from "react-router";

export function NotFoundPage() {
  const { t } = useTranslation();

  return (
    <article className="max-w-[38rem]">
      <h1 className="font-display text-step-4 font-bold">{t("notFound.title")}</h1>
      <p className="mt-4 text-step-1 text-slate">{t("notFound.body")}</p>
      <Link
        to="/"
        className="mt-8 inline-block rounded-md bg-spruce px-5 py-3 font-semibold text-chalk hover:bg-spruce-dark"
      >
        {t("notFound.backHome")}
      </Link>
    </article>
  );
}
