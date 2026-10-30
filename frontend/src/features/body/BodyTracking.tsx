import { useState } from "react";
import { useTranslation } from "react-i18next";

import { type RecalcSuggestion, useBodyMetrics, type WeighInOutcome } from "../../api/body";
import { usePendingSuggestions } from "../../api/suggestions";
import { formatDay, DAY_FORMAT } from "../../lib/calendarDates";
import { formatLength, formatWeight, type UnitSystem } from "../../lib/units";
import { QueryState } from "../calendar/QueryState";
import { RecalcPrompt } from "./RecalcPrompt";
import { WeighInForm } from "./WeighInForm";

/**
 * Weigh-ins for one athlete: the log form (owner only), the recalculation prompt and the recent
 * entries. A coach reads the list but never sees the form or the prompt (the API refuses them).
 */
export function BodyTracking({
  athleteId,
  units,
  today,
  canLog,
}: {
  athleteId: string;
  units: UnitSystem;
  today: string;
  canLog: boolean;
}) {
  const { t, i18n } = useTranslation();
  const metrics = useBodyMetrics(athleteId);
  const pending = usePendingSuggestions(athleteId);
  const [outcome, setOutcome] = useState<WeighInOutcome | null>(null);
  const [decided, setDecided] = useState<{ id: string; how: "accepted" | "rejected" }[]>([]);

  const isOpen = (s: RecalcSuggestion) => !decided.some((d) => d.id === s.id);
  const fromList = pending.data?.find((s): s is RecalcSuggestion => s.kind === "recalc");
  const candidate = outcome?.recalc ?? fromList ?? null;
  const prompt = canLog && candidate && isOpen(candidate) ? candidate : null;
  const lastDecision = decided.at(-1)?.how;

  const entries = metrics.data ? [...metrics.data].reverse() : [];
  const dateLabel = (iso: string) => formatDay(iso, i18n.language, DAY_FORMAT.dayMonth);

  return (
    <>
      {canLog ? (
        <section aria-labelledby="weigh-in-heading" className="mt-6">
          <h2 id="weigh-in-heading" className="font-display text-step-2 font-bold">
            {t("body.formTitle")}
          </h2>
          {outcome && (
            <p role="status" className="mt-2 border-l-4 border-spruce pl-3 font-semibold">
              {outcome.replaced ? t("body.replaced", { date: dateLabel(outcome.metric.date) }) : t("body.created")}
            </p>
          )}
          <WeighInForm athleteId={athleteId} units={units} today={today} onLogged={(o) => { setOutcome(o); }} />
        </section>
      ) : (
        <p className="mt-6 border-l-4 border-iron pl-3">{t("body.coachNotice")}</p>
      )}

      {prompt && (
        <RecalcPrompt
          key={prompt.id}
          suggestion={prompt}
          units={units}
          onDecided={(how) => setDecided((d) => [...d, { id: prompt.id, how }])}
        />
      )}
      {lastDecision && !prompt && (
        <p role="status" className="mt-4">
          {t(lastDecision === "accepted" ? "body.recalc.accepted" : "body.recalc.rejected")}
        </p>
      )}

      <section aria-labelledby="weigh-in-list-heading" className="mt-8 border-t-4 border-iron pt-3">
        <h2 id="weigh-in-list-heading" className="font-display text-step-2 font-bold">
          {t("body.listTitle")}
        </h2>
        {!metrics.data ? (
          <QueryState isPending={metrics.isPending} isError={metrics.isError} onRetry={() => void metrics.refetch()} />
        ) : entries.length === 0 ? (
          <p className="mt-2 text-slate">{t("body.empty")}</p>
        ) : (
          <ul className="mt-2">
            {entries.map((m) => (
              <li key={m.id} data-testid="weigh-in" className="flex flex-wrap items-baseline justify-between gap-x-4 border-b border-line py-2">
                <time dateTime={m.date} className="font-semibold">
                  {dateLabel(m.date)}
                </time>
                <span className="text-right text-step--1 text-slate">
                  {[
                    m.weight_kg != null && formatWeight(m.weight_kg, units),
                    m.body_fat_pct != null && t("body.bodyFatValue", { value: m.body_fat_pct }),
                    m.neck_cm != null && `${t("body.neck")} ${formatLength(m.neck_cm, units)}`,
                    m.waist_cm != null && `${t("body.waist")} ${formatLength(m.waist_cm, units)}`,
                    m.hip_cm != null && `${t("body.hip")} ${formatLength(m.hip_cm, units)}`,
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </>
  );
}
