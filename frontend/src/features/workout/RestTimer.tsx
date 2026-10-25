import { useTranslation } from "react-i18next";

import type { RestTimer as Timer } from "./useRestTimer";

export const formatClock = (seconds: number) =>
  `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;

/** Sticky rest countdown. The ticking digits are silent for screen readers; the end is announced once. */
export function RestTimer({ timer }: { timer: Timer }) {
  const { t } = useTranslation();
  const { active } = timer;
  if (!active) return null;
  const over = active.remainingSeconds === 0;
  return (
    <section
      aria-label={t("workout.rest.label")}
      className="sticky bottom-0 z-10 -mx-4 border-t-4 border-plate bg-iron px-4 py-3 text-chalk sm:mx-0"
    >
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="text-step--1 font-semibold uppercase">
            {over ? t("workout.rest.over") : t("workout.rest.title")}
          </p>
          <p role="timer" aria-live="off" className="font-display text-step-3 font-bold tabular-nums">
            {formatClock(active.remainingSeconds)}
          </p>
        </div>
        <button
          type="button"
          onClick={timer.stop}
          className="min-h-12 rounded-md border-2 border-chalk px-4 font-semibold hover:bg-chalk hover:text-iron"
        >
          {over ? t("workout.rest.dismiss") : t("workout.rest.skip")}
        </button>
      </div>
      <p role="status" className="sr-only">
        {over ? t("workout.rest.overAnnounce", { name: active.exerciseName }) : ""}
      </p>
    </section>
  );
}
