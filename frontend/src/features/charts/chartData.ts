import type { SessionChartSet, SetStatus } from "../../api/charts";
import { kgToLb, type UnitSystem } from "../../lib/units";

/** Series colours, matching the Tailwind theme tokens in index.css. */
export const CHART_COLORS = {
  target: "#56616c", // slate
  actual: "#1e6b57", // spruce
  accent: "#e8b931", // plate
  alert: "#a3321f",
  line: "#d3d9d4",
  ink: "#1c2530", // iron
} as const;

const round1 = (value: number): number => Math.round(value * 10) / 10;

/** A kg value from the API in the user's weight unit (D76(2), F15.4); `null` stays `null`. */
export function displayWeight(kg: number | null, units: UnitSystem): number | null {
  if (kg === null) return null;
  return units === "imperial" ? kgToLb(kg) : round1(kg);
}

/** Completion ratio 0-1 as a whole percent; `null` (rest, planned, future, no data) stays `null`, never 0. */
export function percent(ratio: number | null): number | null {
  return ratio === null ? null : Math.round(ratio * 100);
}

/** A set status as a glyph (colour is never the only cue) and a translation key suffix. */
export const STATUS_MARKER: Record<SetStatus, string> = {
  met: "✓",
  partial: "⚠",
  missed: "✕",
  skipped: "–",
  extra: "+",
};

/** Reps for rep-based sets, seconds for timed sets (D76(3)). */
export function setMeasure(sets: SessionChartSet[]): "reps" | "seconds" {
  return sets.some((s) => s.target_seconds !== null || s.seconds !== null) &&
    sets.every((s) => s.target_reps === null && s.reps === null)
    ? "seconds"
    : "reps";
}

export interface SetBar {
  set_no: number;
  target: number | null;
  actual: number | null;
}

export function setBars(sets: SessionChartSet[], measure: "reps" | "seconds"): SetBar[] {
  return sets.map((s) => ({
    set_no: s.set_no,
    target: measure === "reps" ? s.target_reps : s.target_seconds,
    actual: measure === "reps" ? s.reps : s.seconds,
  }));
}

/** Every value of `key` is missing, so a chart would draw nothing. */
export const hasValues = <T,>(rows: T[], key: keyof T): boolean => rows.some((r) => r[key] !== null && r[key] !== undefined);

/** Recharts axis domain that fits the data. */
export const AUTO_DOMAIN: ["auto", "auto"] = ["auto", "auto"];
