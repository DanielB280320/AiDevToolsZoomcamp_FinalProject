import { describe, expect, it } from "vitest";

import i18n from "../src/i18n";
import {
  buildRequest,
  emptyValues,
  heightToCm,
  validateStep,
  type WizardValues,
} from "../src/onboarding/model";

const t = i18n.t.bind(i18n);
const base = (overrides: Partial<WizardValues> = {}): WizardValues => ({
  ...emptyValues(),
  sex: "female",
  height: "170",
  weight: "65",
  bodyFatMethod: "skip",
  lifestyle: "active",
  goal: "cutting",
  experience: "beginner",
  daysPerWeek: 3,
  preferredDays: ["mon", "wed", "fri"],
  sessionMinutes: 60,
  equipment: "full_gym",
  diet: "omnivore",
  mealsPerDay: 4,
  ...overrides,
});

describe("body step validation (F2.3)", () => {
  it.each<[string, "metric" | "imperial", string, string, boolean]>([
    ["metric height at the lower limit", "metric", "120", "65", false],
    ["metric height below the limit", "metric", "119.9", "65", true],
    ["metric height at the upper limit", "metric", "230", "65", false],
    ["metric height above the limit", "metric", "230.1", "65", true],
    ["metric weight below the limit", "metric", "170", "34.9", true],
    ["metric weight above the limit", "metric", "170", "300.1", true],
    ["metric weight at the limits", "metric", "170", "35", false],
    ["imperial 3 ft 11 in is under 120 cm", "imperial", "3", "100", true],
    ["imperial 5 ft is fine", "imperial", "5", "140", false],
    ["imperial 300 lb is over 300 kg? no, 136 kg", "imperial", "5", "300", false],
    ["imperial 700 lb is over 300 kg", "imperial", "5", "700", true],
  ])("%s", (_name, units, height, weight, hasError) => {
    const errors = validateStep("body", base({ height, weight }), units, t);
    expect(Object.keys(errors).length > 0).toBe(hasError);
  });

  it("explains the range in the user's units", () => {
    const metric = validateStep("body", base({ height: "100" }), "metric", t);
    expect(metric.height).toContain("120 cm");
    const imperial = validateStep("body", base({ height: "3" }), "imperial", t);
    expect(imperial.height).toContain("ft");
    expect(imperial.height).not.toContain("cm");
  });

  it("requires sex, height and weight and rejects non-numbers", () => {
    const errors = validateStep("body", emptyValues(), "metric", t);
    expect(Object.keys(errors).sort()).toEqual(["height", "sex", "weight"]);
    expect(validateStep("body", base({ weight: "heavy" }), "metric", t).weight).toBe(t("onboarding.validation.number"));
  });
});

describe("body fat step validation", () => {
  it("accepts skip without any further input", () => {
    expect(validateStep("bodyFat", base({ bodyFatMethod: "skip" }), "metric", t)).toEqual({});
  });

  it("requires a choice", () => {
    expect(validateStep("bodyFat", base({ bodyFatMethod: "" }), "metric", t)).toHaveProperty("bodyFatMethod");
  });

  it.each<[string, boolean]>([
    ["3", false],
    ["60", false],
    ["2.9", true],
    ["60.1", true],
    ["", true],
  ])("known body fat %j: error %s", (bodyFat, hasError) => {
    const errors = validateStep("bodyFat", base({ bodyFatMethod: "entered", bodyFat }), "metric", t);
    expect("bodyFat" in errors).toBe(hasError);
  });

  it("Navy needs neck and waist, plus hip for female and unspecified but not male", () => {
    const navy = { bodyFatMethod: "navy" as const };
    expect(Object.keys(validateStep("bodyFat", base({ ...navy, sex: "female" }), "metric", t)).sort()).toEqual(["hip", "neck", "waist"]);
    expect(Object.keys(validateStep("bodyFat", base({ ...navy, sex: "unspecified" }), "metric", t)).sort()).toEqual(["hip", "neck", "waist"]);
    expect(Object.keys(validateStep("bodyFat", base({ ...navy, sex: "male" }), "metric", t)).sort()).toEqual(["neck", "waist"]);
  });

  it("checks Navy measurements against 20-200 cm, converting inches first", () => {
    const navy = base({ bodyFatMethod: "navy", sex: "male", neck: "15", waist: "34" });
    expect(validateStep("bodyFat", navy, "imperial", t)).toEqual({}); // 38 cm, 86 cm
    expect(validateStep("bodyFat", { ...navy, neck: "7" }, "imperial", t)).toHaveProperty("neck"); // 17.8 cm
    expect(validateStep("bodyFat", { ...navy, neck: "15", waist: "80" }, "imperial", t)).toHaveProperty("waist"); // 203 cm
    expect(validateStep("bodyFat", { ...navy, neck: "15", waist: "34" }, "metric", t)).toEqual({ neck: expect.any(String) });
  });
});

describe("training step validation (F2.4)", () => {
  it("requires the number of preferred days to equal days per week", () => {
    const errors = validateStep("training", base({ daysPerWeek: 4, preferredDays: ["mon", "wed", "fri"] }), "metric", t);
    expect(errors.preferredDays).toContain("4");
    expect(validateStep("training", base({ daysPerWeek: 3 }), "metric", t)).toEqual({});
  });

  it("requires every training choice", () => {
    const errors = validateStep("training", emptyValues(), "metric", t);
    expect(Object.keys(errors).sort()).toEqual(["daysPerWeek", "equipment", "experience", "preferredDays", "sessionMinutes"]);
  });
});

describe("request building (F2.5: stored metric)", () => {
  it("sends metric values when the user typed metric", () => {
    const request = buildRequest(base(), "metric");
    expect(request.profile.height_cm).toBe(170);
    expect(request.body_metric).toEqual({ weight_kg: 65, body_fat_method: "skip" });
  });

  it("converts imperial input to metric", () => {
    const values = base({ height: "5", heightInches: "10", weight: "154", bodyFatMethod: "navy", sex: "male", neck: "15", waist: "34" });
    const request = buildRequest(values, "imperial");
    expect(request.profile.height_cm).toBe(177.8);
    expect(request.body_metric.weight_kg).toBeCloseTo(69.9, 1);
    expect(request.body_metric).toMatchObject({ body_fat_method: "navy", neck_cm: 38.1, waist_cm: 86.4 });
    expect(request.body_metric).not.toHaveProperty("hip_cm");
  });

  it("sends hip only for the Navy method and not for male", () => {
    const female = buildRequest(base({ bodyFatMethod: "navy", neck: "33", waist: "70", hip: "95" }), "metric");
    expect(female.body_metric.hip_cm).toBe(95);
    const entered = buildRequest(base({ bodyFatMethod: "entered", bodyFat: "22,5", neck: "33" }), "metric");
    expect(entered.body_metric).toEqual({ weight_kg: 65, body_fat_method: "entered", body_fat_pct: 22.5 });
  });

  it("orders preferred days Monday to Sunday and sends avoided exercise ids", () => {
    const request = buildRequest(base({ preferredDays: ["fri", "mon", "wed"], avoidedExercises: [{ id: "e1", name: "Squat" }] }), "metric");
    expect(request.profile.preferred_days).toEqual(["mon", "wed", "fri"]);
    expect(request.profile.avoided_exercise_ids).toEqual(["e1"]);
  });

  it("treats a missing inches field as zero", () => {
    expect(heightToCm(base({ height: "6", heightInches: "" }), "imperial")).toBe(182.9);
    expect(heightToCm(base({ height: "6.5", heightInches: "" }), "imperial")).toBeNull();
  });
});
