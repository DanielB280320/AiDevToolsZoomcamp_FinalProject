import { useId } from "react";
import { useTranslation } from "react-i18next";

import { CHART_WEEKS, type ChartWeeks } from "../../api/charts";

/** Exactly the ranges the API accepts: 4, 12, 26 or 52 weeks (D76(4)). */
export function RangeSelector({ value, onChange }: { value: ChartWeeks; onChange: (weeks: ChartWeeks) => void }) {
  const { t } = useTranslation();
  const name = useId();
  return (
    <fieldset className="mt-3 min-w-0">
      <legend className="sr-only">{t("charts.range.label")}</legend>
      <div className="flex flex-wrap gap-2">
        {CHART_WEEKS.map((weeks) => (
          <label
            key={weeks}
            className={`flex min-h-11 cursor-pointer items-center rounded-md border-2 border-iron px-3 font-semibold has-[:focus-visible]:outline has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 ${
              value === weeks ? "bg-iron text-chalk" : "hover:bg-line"
            }`}
          >
            <input
              type="radio"
              name={name}
              value={weeks}
              checked={value === weeks}
              onChange={() => onChange(weeks)}
              className="sr-only"
            />
            {t("charts.range.weeks", { count: weeks })}
          </label>
        ))}
      </div>
    </fieldset>
  );
}
