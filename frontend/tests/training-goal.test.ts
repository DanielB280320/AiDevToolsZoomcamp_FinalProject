import { describe, expect, it } from "vitest";

import { applyRepRange, newDraftExercise, type DraftDay } from "../src/features/plan/trainingDraft";
import { defaultTrainingGoal, outsideRange } from "../src/features/plan/trainingGoal";
import { REP_RANGES } from "./mocks/planGoal";

describe("training goal helpers (D107)", () => {
  it("derives the default goal from the profile goal", () => {
    expect(defaultTrainingGoal("muscle_gain")).toBe("hypertrophy");
    expect(defaultTrainingGoal("cutting")).toBe("cutting");
    expect(defaultTrainingGoal("maintenance")).toBe("maintenance");
    expect(defaultTrainingGoal("recomposition")).toBe("hypertrophy");
    expect(defaultTrainingGoal("wellness")).toBe("endurance");
    expect(defaultTrainingGoal(undefined)).toBe("hypertrophy");
  });

  it("judges the typed reps against the range, never empty or invalid input", () => {
    const range = REP_RANGES.hypertrophy; // 8 to 12
    expect(outsideRange("8", "12", range)).toBe(false);
    expect(outsideRange("10", "", range)).toBe(false);
    expect(outsideRange("7", "12", range)).toBe(true);
    expect(outsideRange("8", "13", range)).toBe(true);
    expect(outsideRange("5", "", range)).toBe(true);
    expect(outsideRange("", "", range)).toBe(false);
    expect(outsideRange("abc", "20", range)).toBe(false);
  });

  it("applies a range to rep-based exercises only", () => {
    const base = { uid: "u", exerciseId: "e", name: "X", sets: "3", weight: "", rest: "90", rule: "double", increment: "2.5", deload: true } as const;
    const days: DraftDay[] = [
      {
        uid: "d",
        weekday: "mon",
        name: "Day",
        editedBy: null,
        exercises: [
          { ...base, type: "strength", repsMin: "8", repsMax: "", seconds: "" },
          { ...base, uid: "v", type: "timed", repsMin: "", repsMax: "", seconds: "30" },
        ],
      },
    ];
    const [day] = applyRepRange(days, REP_RANGES.endurance);
    expect(day!.exercises[0]).toMatchObject({ repsMin: "13", repsMax: "20" });
    expect(day!.exercises[1]).toMatchObject({ repsMin: "", repsMax: "", seconds: "30" });
  });

  it("starts a new exercise on the double rule at the range's bottom and top", () => {
    const exercise = { id: "x", name: "Row", type: "strength", increment_kg: 2.5 } as Parameters<typeof newDraftExercise>[0];
    expect(newDraftExercise(exercise, "metric", REP_RANGES.strength)).toMatchObject({ rule: "double", repsMin: "3", repsMax: "6" });
    expect(newDraftExercise(exercise, "metric")).toMatchObject({ repsMin: "8", repsMax: "" });
  });
});
