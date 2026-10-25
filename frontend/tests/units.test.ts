import { describe, expect, it } from "vitest";

import {
  cmToFeetInches,
  cmToInches,
  feetInchesToCm,
  formatHeight,
  formatWeight,
  inchesToCm,
  kgToLb,
  lbToKg,
  parseDecimal,
  parseWhole,
} from "../src/lib/units";

describe("unit conversion", () => {
  it.each<[number, number, number]>([
    [5, 10, 177.8],
    [6, 0, 182.9],
    [5, 0, 152.4],
    [4, 11.5, 151.1],
  ])("%i ft %i in is %f cm", (feet, inches, cm) => {
    expect(feetInchesToCm(feet, inches)).toBe(cm);
  });

  it.each<[number, number, number]>([
    [184, 6, 0.4],
    [152.4, 5, 0],
    [120, 3, 11.2],
    [230, 7, 6.6],
  ])("%f cm is %i ft %f in", (cm, feet, inches) => {
    expect(cmToFeetInches(cm)).toEqual({ feet, inches });
  });

  it("never shows 12 inches", () => {
    // 182.85 cm = 71.99 in rounds to 72.0 in, which is exactly 6 ft.
    expect(cmToFeetInches(182.85)).toEqual({ feet: 6, inches: 0 });
  });

  it.each<[number, number]>([
    [154, 69.9],
    [220, 99.8],
    [165.3, 75],
  ])("%f lb is about %f kg", (lb, kg) => {
    expect(lbToKg(lb)).toBeCloseTo(kg, 1);
  });

  it("converts kg to lb and back within rounding", () => {
    for (const kg of [35, 52.3, 70, 99.9, 300]) expect(lbToKg(kgToLb(kg))).toBeCloseTo(kg, 1);
  });

  it("converts inches to cm and back within rounding", () => {
    for (const inches of [8, 14.5, 32, 40.25, 78]) expect(cmToInches(inchesToCm(inches))).toBeCloseTo(inches, 1);
  });

  it("formats stored metric values in the user's units", () => {
    expect(formatWeight(70, "metric")).toBe("70 kg");
    expect(formatWeight(70, "imperial")).toBe("154.3 lb");
    expect(formatHeight(180, "metric")).toBe("180 cm");
    expect(formatHeight(180, "imperial")).toBe("5 ft 10.9 in");
  });
});

describe("number parsing", () => {
  it.each<[string, number | null]>([
    ["72", 72],
    ["72.5", 72.5],
    ["72,5", 72.5],
    [" 80 ", 80],
    ["", null],
    ["abc", null],
    ["12abc", null],
    ["1e3", null],
    ["-5", null],
    [".5", null],
    ["1.2.3", null],
  ])("parseDecimal(%j) = %j", (text, expected) => {
    expect(parseDecimal(text)).toBe(expected);
  });

  it.each<[string, number | null]>([
    ["5", 5],
    ["5.5", null],
    ["", null],
    ["-1", null],
  ])("parseWhole(%j) = %j", (text, expected) => {
    expect(parseWhole(text)).toBe(expected);
  });
});
