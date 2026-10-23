import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { api } from "../api/client";
import { paths } from "../paths";

function useServiceHealth() {
  return useQuery({
    queryKey: ["healthz"],
    queryFn: async ({ signal }) => {
      const { data, error } = await api.GET("/healthz", { signal });
      if (error || !data) throw new Error("health check failed");
      return data;
    },
    retry: false,
  });
}

export function HomePage() {
  const { t } = useTranslation();
  const health = useServiceHealth();

  const statusText = health.isPending
    ? t("home.status.checking")
    : health.isSuccess
      ? t("home.status.ok")
      : t("home.status.down");
  const statusTone = health.isPending ? "bg-line" : health.isSuccess ? "bg-spruce" : "bg-alert";

  return (
    <article className="max-w-[38rem]">
      <h1 className="font-display text-step-4 font-bold text-balance sm:text-step-5">
        {t("home.title")}
      </h1>
      <p className="mt-4 text-step-1 text-slate">{t("home.lead")}</p>

      <div className="mt-8 flex flex-col gap-3 sm:flex-row sm:items-center sm:gap-6">
        <Link
          to={paths.signUp}
          className="inline-flex min-h-12 items-center justify-center rounded-md bg-spruce px-6 py-3 font-semibold text-chalk no-underline hover:bg-spruce-dark"
        >
          {t("home.cta.signUp")}
        </Link>
        <Link
          to={paths.signIn}
          className="inline-flex min-h-12 items-center justify-center font-semibold text-spruce underline underline-offset-4 hover:text-spruce-dark"
        >
          {t("home.cta.signIn")}
        </Link>
      </div>

      <section aria-labelledby="service-status" className="mt-10 border-l-4 border-line pl-4">
        <h2 id="service-status" className="font-display text-step-1 font-semibold">
          {t("home.status.heading")}
        </h2>
        <p role="status" className="mt-1 flex items-center gap-2 text-step-0">
          <span aria-hidden="true" className={`inline-block size-2.5 shrink-0 rounded-full ${statusTone}`} />
          {statusText}
        </p>
      </section>
    </article>
  );
}
