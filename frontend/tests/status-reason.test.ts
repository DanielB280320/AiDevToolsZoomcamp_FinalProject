import { describe, expect, it } from "vitest";
import { badgeKind, statusReason } from "../src/features/calendar/status";
import type { TrainingStatus } from "../src/api/calendar";

const STATUSES: TrainingStatus[] = ["rest", "planned", "in_progress", "missed", "done"];
const COMPLETIONS = [null, 0, 0.0001, 0.4, 0.999, 1, 1.2];
// Which reason keys are allowed for each badge (D102: the sentence must agree with the badge).
const KEYS = {
  done: ["done", "doneNoFigure"],
  partial: ["partialFinished", "partialInProgress"],
  missed: ["missed"],
  rest: ["rest"],
  planned: ["planned"],
};

describe("statusReason agrees with badgeKind (D102)", () => {
  for (const status of STATUSES) {
    for (const completion of COMPLETIONS) {
      it(`${status} / ${completion}`, () => {
        const reason = statusReason(status, completion);
        expect(KEYS[badgeKind(status, completion)]).toContain(reason.key);
        if (reason.key === "partialFinished") {
          expect(reason.value).toBeGreaterThanOrEqual(0);
          expect(reason.value).toBeLessThanOrEqual(99);
        }
      });
    }
  }

  it("rounds the percent down so a partial day never reads 100%", () => {
    expect(statusReason("done", 0.999)).toEqual({ key: "partialFinished", value: 99 });
    expect(statusReason("done", 0)).toEqual({ key: "partialFinished", value: 0 });
    expect(statusReason("done", 1)).toEqual({ key: "done" });
    expect(statusReason("in_progress", 0.4)).toEqual({ key: "partialInProgress" });
  });
});
