const RING_RADIUS = 30;
const RING_LENGTH = 2 * Math.PI * RING_RADIUS;

/**
 * A circular progress ring with a value in the middle (F10.11, F15.9). `percent` is 0-100; `null`
 * (no data) draws an empty ring with the `emptyText` dash and no `aria-valuenow`, never a 0 %.
 * `centre` is the text in the middle for a value.
 */
export function ProgressRing({
  percent,
  label,
  centre,
  emptyText = "—",
}: {
  percent: number | null;
  label: string;
  centre: string;
  emptyText?: string;
}) {
  const value = percent === null ? 0 : Math.min(100, Math.max(0, percent));
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuenow={percent === null ? undefined : value}
      aria-valuemax={100}
      aria-valuetext={percent === null ? emptyText : centre}
      className="relative h-20 w-20 shrink-0"
    >
      <svg viewBox="0 0 72 72" className="h-full w-full -rotate-90" aria-hidden="true">
        <circle cx="36" cy="36" r={RING_RADIUS} fill="none" strokeWidth="8" className="stroke-line" />
        <circle
          cx="36"
          cy="36"
          r={RING_RADIUS}
          fill="none"
          strokeWidth="8"
          strokeLinecap={value > 0 && value < 100 ? "round" : "butt"}
          strokeDasharray={RING_LENGTH}
          strokeDashoffset={RING_LENGTH * (1 - value / 100)}
          className="stroke-spruce"
        />
      </svg>
      <span className="absolute inset-0 flex items-center justify-center font-display text-step-1 font-bold">
        {percent === null ? emptyText : centre}
      </span>
    </div>
  );
}
