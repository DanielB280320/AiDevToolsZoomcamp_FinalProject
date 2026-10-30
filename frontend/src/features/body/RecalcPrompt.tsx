import { useId } from "react";
import { useTranslation } from "react-i18next";

import { isApiError } from "../../api/errors";
import type { RecalcSuggestion } from "../../api/body";
import { useAcceptSuggestion, useRejectSuggestion } from "../../api/suggestions";
import { formatWeight, type UnitSystem } from "../../lib/units";

type Macros = RecalcSuggestion["payload"]["current"];

const ROWS = [
  { key: "kcal", field: "kcal" },
  { key: "protein", field: "protein_g" },
  { key: "carbs", field: "carbs_g" },
  { key: "fat", field: "fat_g" },
] as const;

/**
 * The recalculation prompt (F14): old vs. new targets with explicit Accept / Reject. Nothing is
 * applied until Accept is pressed; the decision is reported through `onDecided`.
 */
export function RecalcPrompt({
  suggestion,
  units,
  onDecided,
}: {
  suggestion: RecalcSuggestion;
  units: UnitSystem;
  onDecided: (decision: "accepted" | "rejected") => void;
}) {
  const { t } = useTranslation();
  const headingId = useId();
  const accept = useAcceptSuggestion();
  const reject = useRejectSuggestion();
  const busy = accept.isPending || reject.isPending;
  const { payload } = suggestion;
  const error = accept.error ?? reject.error;
  const alreadyDecided = isApiError(error) && error.problem.code === "suggestion_already_decided";

  const value = (macros: Macros, field: (typeof ROWS)[number]["field"]) =>
    field === "kcal" ? t("body.recalc.kcalValue", { count: macros[field] }) : t("body.recalc.grams", { count: macros[field] });

  return (
    <section aria-labelledby={headingId} className="mt-6 border-l-4 border-plate bg-white p-4" data-testid="recalc-prompt">
      <h2 id={headingId} className="font-display text-step-2 font-bold">
        {t("body.recalc.title")}
      </h2>
      <p className="mt-1">
        {t("body.recalc.intro", {
          pct: Math.round(Math.abs(payload.change_pct) * 10) / 10,
          from: formatWeight(payload.weight_used_kg, units),
          to: formatWeight(payload.new_weight_kg, units),
        })}
      </p>
      <p className="mt-1 text-step--1 text-slate">{suggestion.reason}</p>
      <table className="mt-3 w-full max-w-[28rem] text-left">
        <thead>
          <tr className="border-b-2 border-iron">
            <th scope="col" className="py-1 pr-3">
              <span className="sr-only">{t("body.recalc.title")}</span>
            </th>
            <th scope="col" className="py-1 pr-3">
              {t("body.recalc.old")}
            </th>
            <th scope="col" className="py-1">
              {t("body.recalc.new")}
            </th>
          </tr>
        </thead>
        <tbody>
          {ROWS.map(({ key, field }) => (
            <tr key={key} className="border-b border-line">
              <th scope="row" className="py-1 pr-3 font-semibold">
                {t(`body.recalc.${key}`)}
              </th>
              <td className="py-1 pr-3">{value(payload.current, field)}</td>
              <td className="py-1 font-semibold">{value(payload.proposed, field)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-2 text-step--1 text-slate">{t("body.recalc.future")}</p>
      {error && (
        <p role="alert" className="mt-2 border-l-4 border-alert pl-3 text-alert">
          {t(alreadyDecided ? "body.recalc.errors.alreadyDecided" : "body.recalc.errors.generic")}
        </p>
      )}
      <div className="mt-3 flex flex-wrap gap-3">
        <button
          type="button"
          aria-disabled={busy || undefined}
          onClick={() => {
            if (busy) return;
            accept.mutate({ id: suggestion.id }, { onSuccess: () => onDecided("accepted") });
          }}
          className="min-h-12 rounded-md bg-spruce px-4 font-semibold text-chalk hover:bg-spruce-dark"
        >
          {t("body.recalc.accept")}
        </button>
        <button
          type="button"
          aria-disabled={busy || undefined}
          onClick={() => {
            if (busy) return;
            reject.mutate(suggestion.id, { onSuccess: () => onDecided("rejected") });
          }}
          className="min-h-12 rounded-md border-2 border-iron px-4 font-semibold hover:bg-line"
        >
          {t("body.recalc.reject")}
        </button>
      </div>
    </section>
  );
}
