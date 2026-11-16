import { useSyncExternalStore } from "react";

const QUERY = "(prefers-reduced-motion: reduce)";

function subscribe(onChange: () => void): () => void {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return () => undefined;
  const media = window.matchMedia(QUERY);
  media.addEventListener("change", onChange);
  return () => media.removeEventListener("change", onChange);
}

function snapshot(): boolean {
  return typeof window !== "undefined" && typeof window.matchMedia === "function" && window.matchMedia(QUERY).matches;
}

/** True when the user asked the system for less motion (D111); script-driven animation must stop. */
export function usePrefersReducedMotion(): boolean {
  return useSyncExternalStore(subscribe, snapshot, () => false);
}

/** Longest chart animation, in ms (D111: about 400 ms or less). */
export const CHART_ANIMATION_MS = 400;

/**
 * Props for every Recharts series (`<Line {...anim} />`): a short draw-in on first render and when the
 * period changes, and none at all with `prefers-reduced-motion: reduce`.
 */
export function useChartAnimation(): { isAnimationActive: boolean; animationDuration: number; animationEasing: "ease-out" } {
  const reduced = usePrefersReducedMotion();
  return { isAnimationActive: !reduced, animationDuration: CHART_ANIMATION_MS, animationEasing: "ease-out" };
}
