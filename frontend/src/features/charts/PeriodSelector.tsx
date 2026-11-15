import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import { DAY_FORMAT, formatDay } from "../../lib/calendarDates";
import {
  CUSTOM,
  endsToday,
  type Period,
  type PeriodError,
  periodDays,
  PRESET_KEYS,
  presetPeriod,
  RANGE_FIELDS,
  type PresetKey,
  stepPeriod,
  validateRange,
} from "./period";

const CHOICE =
  "flex min-h-11 cursor-pointer items-center rounded-md border-2 border-iron px-3 font-semibold has-[:focus-visible]:outline has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2";
const STEP =
  "min-h-11 min-w-11 rounded-md border-2 border-iron font-bold hover:bg-line disabled:cursor-not-allowed disabled:opacity-40";

interface Draft {
  from: string;
  to: string;
  error: PeriodError | null;
}

/** From and To inputs of the custom range; an invalid pair shows its error and the last valid range stays (F15.7). */
function CustomRange({ period, today, onChange }: { period: Period; today: string; onChange: (from: string, to: string) => void }) {
  const { t } = useTranslation();
  const errorId = useId();
  const [draft, setDraft] = useState<Draft | null>(null);
  const [seen, setSeen] = useState({ from: period.from, to: period.to });
  // The range moved by a preset or the step buttons: drop what was typed and show it.
  if (seen.from !== period.from || seen.to !== period.to) {
    setSeen({ from: period.from, to: period.to });
    setDraft(null);
  }
  const shown: Draft = draft ?? { from: period.from, to: period.to, error: null };

  const edit = (from: string, to: string) => {
    const error = validateRange(from, to, today);
    setDraft({ from, to, error });
    if (error === null) onChange(from, to);
  };
  const fields = RANGE_FIELDS.map((key) => ({
    key,
    value: shown[key],
    set: (v: string) => (key === RANGE_FIELDS[0] ? edit(v, shown.to) : edit(shown.from, v)),
  }));

  return (
    <div className="mt-3 min-w-0">
      <div className="flex flex-wrap gap-3">
        {fields.map(({ key, value, set }) => (
          <label key={key} className="block min-w-0 font-semibold">
            {t(`charts.period.${key}`)}
            <input
              type="date"
              value={value}
              max={key === RANGE_FIELDS[1] ? today : undefined}
              onChange={(e) => set(e.target.value)}
              aria-invalid={shown.error !== null}
              aria-describedby={shown.error ? errorId : undefined}
              className="mt-1 block min-h-12 w-full min-w-0 rounded-md border-2 border-iron bg-chalk px-3 font-normal"
            />
          </label>
        ))}
      </div>
      {shown.error && (
        <p id={errorId} role="alert" className="mt-2 text-step--1 font-semibold text-alert">
          {t(`charts.period.error.${shown.error}`)}
        </p>
      )}
    </div>
  );
}

/**
 * The one period selector of the Progress page (F15.7, D109): presets, a custom range, and
 * previous/next buttons that move the range by its own length. The state lives in the URL, so
 * the parent passes the current `period` and receives the next one.
 */
export function PeriodSelector({
  period,
  today,
  onChange,
}: {
  period: Period;
  today: string;
  onChange: (period: Period) => void;
}) {
  const { t, i18n } = useTranslation();
  const name = useId();
  const days = periodDays(period.from, period.to);
  const day = (iso: string) => formatDay(iso, i18n.language, DAY_FORMAT.dayMonthYear);

  return (
    <div className="mt-6 min-w-0" data-testid="period-selector">
      <fieldset className="min-w-0">
        <legend className="sr-only">{t("charts.period.label")}</legend>
        <div className="flex flex-wrap gap-2">
          {[...PRESET_KEYS, CUSTOM].map((key) => (
            <label key={key} className={`${CHOICE} ${period.kind === key ? "bg-iron text-chalk" : "hover:bg-line"}`}>
              <input
                type="radio"
                name={name}
                value={key}
                checked={period.kind === key}
                onChange={() =>
                  onChange(key === CUSTOM ? { ...period, kind: CUSTOM } : presetPeriod(key as PresetKey, today))
                }
                className="sr-only"
              />
              {t(`charts.period.preset.${key}`)}
            </label>
          ))}
        </div>
      </fieldset>
      {period.kind === CUSTOM && (
        <CustomRange period={period} today={today} onChange={(from, to) => onChange({ from, to, kind: CUSTOM })} />
      )}
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <button type="button" onClick={() => onChange(stepPeriod(period, -1, today))} aria-label={t("charts.period.prev")} className={STEP}>
          {t("charts.period.prevGlyph")}
        </button>
        <span className="min-w-0 flex-1 text-center font-semibold" aria-live="polite" data-testid="period-range">
          {t("charts.period.current", { from: day(period.from), to: day(period.to), count: days })}
        </span>
        <button
          type="button"
          onClick={() => onChange(stepPeriod(period, 1, today))}
          disabled={endsToday(period, today)}
          aria-label={t("charts.period.next")}
          className={STEP}
        >
          {t("charts.period.nextGlyph")}
        </button>
      </div>
    </div>
  );
}
