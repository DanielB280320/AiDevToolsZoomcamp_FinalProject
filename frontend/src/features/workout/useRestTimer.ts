import { useCallback, useEffect, useState } from "react";

import type { Clock } from "./clock";

interface Running {
  endsAt: number;
  totalSeconds: number;
  exerciseName: string;
}

export interface RestTimer {
  /** `null` when no rest has been started. */
  active: { remainingSeconds: number; totalSeconds: number; exerciseName: string } | null;
  start: (seconds: number, exerciseName: string) => void;
  stop: () => void;
}

/** Counts down from the planned rest; remaining time is derived from the clock, so a late tick never drifts. */
export function useRestTimer(clock: Clock): RestTimer {
  const [running, setRunning] = useState<Running | null>(null);
  const [now, setNow] = useState(() => clock.now());

  useEffect(() => {
    if (!running) return;
    return clock.every(() => setNow(clock.now()), 250);
  }, [clock, running]);

  const start = useCallback(
    (seconds: number, exerciseName: string) => {
      if (seconds <= 0) return;
      const current = clock.now();
      setNow(current);
      setRunning({ endsAt: current + seconds * 1000, totalSeconds: seconds, exerciseName });
    },
    [clock],
  );
  const stop = useCallback(() => setRunning(null), []);

  return {
    active: running
      ? {
          remainingSeconds: Math.max(0, Math.ceil((running.endsAt - now) / 1000)),
          totalSeconds: running.totalSeconds,
          exerciseName: running.exerciseName,
        }
      : null,
    start,
    stop,
  };
}
