import { addDays, isIsoDate } from "../../lib/calendarDates";

/** The presets of the Progress period selector (spec F15.7, D109) and their length in days. */
export const PRESET_DAYS = { "7d": 7, "30d": 30, "90d": 90, "6m": 182, "1y": 364 } as const;
export type PresetKey = keyof typeof PRESET_DAYS;
export const PRESET_KEYS = Object.keys(PRESET_DAYS) as PresetKey[];
export const DEFAULT_PRESET: PresetKey = "30d";
/** The `kind` of a range typed or stepped to by hand, and the two fields of the custom form. */
export const CUSTOM = "custom" as const;
export const RANGE_FIELDS = ["from", "to"] as const;
/** The longest range the chart endpoints accept (days, both bounds included). */
export const MAX_PERIOD_DAYS = 371;

export interface Period {
  from: string;
  to: string;
  /** The preset the range came from, or `custom` for an explicit From/To. */
  kind: PresetKey | typeof CUSTOM;
}

export type PeriodError = "order" | "future" | "tooLong" | "missing";

const DAY_MS = 86_400_000;

/** Whole days from `from` to `to`, both included. */
export function periodDays(from: string, to: string): number {
  return Math.round((Date.parse(`${to}T00:00:00Z`) - Date.parse(`${from}T00:00:00Z`)) / DAY_MS) + 1;
}

export function presetPeriod(key: PresetKey, today: string): Period {
  return { from: addDays(today, 1 - PRESET_DAYS[key]), to: today, kind: key };
}

/** Why `from`..`to` is not allowed (To not after today, From not after To, at most 371 days), or `null`. */
export function validateRange(from: string, to: string, today: string): PeriodError | null {
  if (!isIsoDate(from) || !isIsoDate(to)) return "missing";
  if (from > to) return "order";
  if (to > today) return "future";
  if (periodDays(from, to) > MAX_PERIOD_DAYS) return "tooLong";
  return null;
}

/** The period of the URL query (`period=30d` or `from`+`to`); anything invalid falls back to 30 days. */
export function periodFromParams(params: URLSearchParams, today: string): Period {
  const from = params.get("from");
  const to = params.get("to");
  if (from !== null && to !== null && validateRange(from, to, today) === null) return { from, to, kind: CUSTOM };
  const key = params.get("period");
  if (key !== null && key in PRESET_DAYS) return presetPeriod(key as PresetKey, today);
  return presetPeriod(DEFAULT_PRESET, today);
}

/** The URL query of a period: the preset key, or the explicit range. */
export function paramsFromPeriod(period: Period): Record<string, string> {
  return period.kind === CUSTOM ? { from: period.from, to: period.to } : { period: period.kind };
}

/**
 * The previous (-1) or next (+1) range of the same length. Going forward never passes today: a
 * range that would is moved back so it ends today. A preset stays a preset once it ends today again.
 */
export function stepPeriod(period: Period, direction: -1 | 1, today: string): Period {
  const days = periodDays(period.from, period.to);
  let from = addDays(period.from, direction * days);
  let to = addDays(period.to, direction * days);
  if (to > today) {
    to = today;
    from = addDays(today, 1 - days);
  }
  const preset = PRESET_KEYS.find((key) => PRESET_DAYS[key] === days);
  return { from, to, kind: to === today && preset !== undefined ? preset : CUSTOM };
}

export const endsToday = (period: Period, today: string): boolean => period.to >= today;
