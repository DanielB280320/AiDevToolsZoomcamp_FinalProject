import { useTranslation } from "react-i18next";

/** Whether a rise is good (training figures) or the goal decides (weight, energy). */
export const TONE = { good: "higherIsBetter", neutral: "neutral" } as const;

export type Direction = "up" | "down" | "same";

export const directionOf = (value: number): Direction => (value > 0 ? "up" : value < 0 ? "down" : "same");

/** `+3` / `-3` / `0`: the sign is always part of the text, so direction never rests on colour. */
export const signed = (value: number, text: string): string => (value > 0 ? `+${text}` : text);

/**
 * Period-over-period line under a figure (F15.9): an icon, the direction in words for screen
 * readers, and the signed change against the previous period. `null` means one of the two
 * periods has no data. `tone="neutral"` is for weight and energy, where the goal decides whether
 * up or down is good, so no good/bad colour is used there.
 */
export function DeltaLine({
  value,
  format,
  period,
  tone,
  testId,
}: {
  /** The change in display units, already rounded; `null` when there is nothing to compare. */
  value: number | null;
  format: (value: number) => string;
  period: string;
  tone: (typeof TONE)[keyof typeof TONE];
  testId?: string;
}) {
  const { t } = useTranslation();
  if (value === null) {
    return (
      <p data-testid={testId} data-direction="none" className="mt-1 text-step--1 text-slate">
        {t("charts.delta.none")}
      </p>
    );
  }
  const direction = directionOf(value);
  const colour =
    tone === TONE.neutral || direction === "same" ? "text-slate" : direction === "up" ? "text-spruce" : "text-alert";
  return (
    <p data-testid={testId} data-direction={direction} className={`mt-1 flex items-baseline gap-1 text-step--1 font-semibold ${colour}`}>
      <span aria-hidden="true">{t(`charts.delta.icon.${direction}`)}</span>
      <span className="sr-only">{t(`charts.delta.${direction}`)}: </span>
      <span>
        {direction === "same"
          ? t("charts.delta.noChange", { period })
          : t("charts.delta.vs", { value: format(value), period })}
      </span>
    </p>
  );
}
