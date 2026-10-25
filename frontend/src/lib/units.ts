/**
 * Unit conversion at the edges (spec §6.2, rule 5): the API and database are metric; the wizard
 * shows and accepts the user's unit system and converts once, on the way in and out.
 */
export type UnitSystem = "metric" | "imperial";

export const CM_PER_INCH = 2.54;
export const INCHES_PER_FOOT = 12;
export const LB_PER_KG = 2.2046226218;

const round = (value: number, digits: number): number => {
  const factor = 10 ** digits;
  return Math.round(value * factor) / factor;
};

/** Metric values are stored with one decimal; finer precision is noise for a tape measure or scale. */
export const toStoredCm = (cm: number): number => round(cm, 1);
export const toStoredKg = (kg: number): number => round(kg, 1);

export const inchesToCm = (inches: number): number => toStoredCm(inches * CM_PER_INCH);
export const cmToInches = (cm: number): number => round(cm / CM_PER_INCH, 1);
export const feetInchesToCm = (feet: number, inches: number): number =>
  toStoredCm((feet * INCHES_PER_FOOT + inches) * CM_PER_INCH);
export const lbToKg = (lb: number): number => toStoredKg(lb / LB_PER_KG);
export const kgToLb = (kg: number): number => round(kg * LB_PER_KG, 1);

/** Feet and whole-or-tenth inches for a height in cm; inches carry over so `5 ft 12 in` never appears. */
export function cmToFeetInches(cm: number): { feet: number; inches: number } {
  const totalInches = round(cm / CM_PER_INCH, 1);
  let feet = Math.floor(totalInches / INCHES_PER_FOOT);
  let inches = round(totalInches - feet * INCHES_PER_FOOT, 1);
  if (inches >= INCHES_PER_FOOT) {
    feet += 1;
    inches = 0;
  }
  return { feet, inches };
}

/**
 * Parses a typed number: digits with an optional decimal part (a comma works as the separator).
 * Returns `null` for empty or malformed input, so "12abc" and "1e3" are never accepted.
 */
export function parseDecimal(text: string): number | null {
  const value = text.trim().replace(",", ".");
  if (!/^\d+(\.\d+)?$/.test(value)) return null;
  return Number(value);
}

/** Whole-number variant of `parseDecimal`. */
export function parseWhole(text: string): number | null {
  const value = text.trim();
  return /^\d+$/.test(value) ? Number(value) : null;
}

export const lengthUnit = (system: UnitSystem): "cm" | "in" => (system === "metric" ? "cm" : "in");
export const weightUnit = (system: UnitSystem): "kg" | "lb" => (system === "metric" ? "kg" : "lb");

export function formatWeight(kg: number, system: UnitSystem): string {
  return system === "metric" ? `${round(kg, 1)} kg` : `${kgToLb(kg)} lb`;
}

export function formatLength(cm: number, system: UnitSystem): string {
  return system === "metric" ? `${round(cm, 1)} cm` : `${cmToInches(cm)} in`;
}

export function formatHeight(cm: number, system: UnitSystem): string {
  if (system === "metric") return `${round(cm, 1)} cm`;
  const { feet, inches } = cmToFeetInches(cm);
  return `${feet} ft ${inches} in`;
}
