/**
 * The clock the rest timer reads. Injected so tests drive time by hand instead of waiting
 * (production uses `systemClock`).
 */
export interface Clock {
  /** Epoch milliseconds. */
  now(): number;
  /** Calls `callback` every `ms` milliseconds; returns the function that stops it. */
  every(callback: () => void, ms: number): () => void;
}

export const systemClock: Clock = {
  now: () => Date.now(),
  every: (callback, ms) => {
    const id = window.setInterval(callback, ms);
    return () => window.clearInterval(id);
  },
};
