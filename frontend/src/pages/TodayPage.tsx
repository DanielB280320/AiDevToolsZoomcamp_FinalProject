import { useTranslation } from "react-i18next";

import { useSignedInUser } from "../components/RequireAuth";
import { localDay } from "../lib/today";

/**
 * M1 placeholder for the home screen (spec F9). Both roles land here; onboarding (#26) and the
 * coach dashboard (#48) replace the body later. "Today" is the user's day in `Me.timezone`.
 */
export function TodayPage() {
  const { t, i18n } = useTranslation();
  const me = useSignedInUser();
  const today = localDay(new Date(), me.timezone, i18n.language);

  return (
    <article className="max-w-[40rem]">
      <p className="text-step-1 text-slate">{t("today.greeting", { name: me.display_name })}</p>
      <h1 className="mt-2 font-display font-bold">
        <time dateTime={today.isoDate} className="block">
          <span className="block text-step-5 leading-none sm:text-[4.768rem]">{today.weekday}</span>{" "}
          <span className="mt-1 block text-step-3 font-semibold leading-tight text-slate sm:text-step-4">
            {today.date}
          </span>
        </time>
      </h1>
      <p className="mt-8 max-w-[52ch] border-t-4 border-iron pt-4 text-step-0">
        {me.role === "coach" ? t("today.placeholder.coach") : t("today.placeholder.athlete")}
      </p>
    </article>
  );
}
