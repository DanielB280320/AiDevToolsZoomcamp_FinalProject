import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import type { FinishSessionResult } from "../../api/workout";
import type { UnitSystem } from "../../lib/units";
import { paths } from "../../paths";
import { PendingSuggestions } from "../suggestions/PendingSuggestions";

export const percent = (ratio: number | null) => (ratio === null ? "–" : `${Math.round(ratio * 100)}%`);

/** Finish workout summary (F10): completion, estimated kcal, duration and the new suggestions. */
export function FinishSummary({
  result,
  athleteId,
  units,
  onReview,
}: {
  result: FinishSessionResult;
  athleteId: string;
  units: UnitSystem;
  onReview: () => void;
}) {
  const { t } = useTranslation();
  const { session } = result;
  const minutes =
    session.started_at && session.finished_at
      ? Math.max(1, Math.round((Date.parse(session.finished_at) - Date.parse(session.started_at)) / 60_000))
      : null;
  return (
    <section aria-labelledby="finish-title" className="mt-2 border-t-4 border-spruce pt-3">
      <h2 id="finish-title" className="font-display text-step-3 font-bold">
        {t("workout.summary.title")}
      </h2>
      <dl className="mt-3 grid grid-cols-3 gap-3 text-center">
        <div>
          <dt className="text-step--1 text-slate">{t("workout.summary.completion")}</dt>
          <dd className="font-display text-step-3 font-bold">{percent(session.completion)}</dd>
        </div>
        <div>
          <dt className="text-step--1 text-slate">{t("workout.summary.kcal")}</dt>
          <dd className="font-display text-step-3 font-bold">{session.kcal ?? "–"}</dd>
        </div>
        <div>
          <dt className="text-step--1 text-slate">{t("workout.summary.duration")}</dt>
          <dd className="font-display text-step-3 font-bold">
            {minutes === null ? "–" : t("workout.summary.minutes", { count: minutes })}
          </dd>
        </div>
      </dl>
      <p className="mt-2 text-step--1 text-slate">{t("workout.summary.estimated")}</p>

      <PendingSuggestions
        athleteId={athleteId}
        units={units}
        className="mt-6"
        emptyMessage={t("workout.summary.noSuggestions")}
      />

      <div className="mt-6 flex flex-wrap gap-3">
        <Link
          to={paths.today}
          className="inline-flex min-h-12 items-center rounded-md bg-spruce px-5 font-semibold text-chalk hover:bg-spruce-dark"
        >
          {t("workout.summary.backToToday")}
        </Link>
        <button
          type="button"
          onClick={onReview}
          className="min-h-12 rounded-md border-2 border-iron px-4 font-semibold hover:bg-line"
        >
          {t("workout.summary.review")}
        </button>
      </div>
    </section>
  );
}
