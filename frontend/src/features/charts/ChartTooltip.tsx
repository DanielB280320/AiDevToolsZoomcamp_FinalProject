import { Tooltip } from "recharts";

import { CHART_COLORS } from "./chartData";

/** Unit suffixes for tooltip values; weight units come from `weightUnit()`. */
export const TOOLTIP_UNIT = { percent: "%", kcal: " kcal" } as const;

const CONTENT = {
  background: CHART_COLORS.surface,
  border: `1px solid ${CHART_COLORS.line}`,
  borderRadius: 8,
  boxShadow: "0 4px 12px rgb(28 37 48 / 0.12)",
  padding: "6px 10px",
  fontSize: 14,
  lineHeight: 1.45,
} as const;
const LABEL = { color: CHART_COLORS.ink, fontWeight: 600 } as const;
const ITEM = { color: CHART_COLORS.ink, padding: 0 } as const;
const LINE_CURSOR = { stroke: CHART_COLORS.target, strokeDasharray: "3 3" } as const;
const BAR_CURSOR = { fill: CHART_COLORS.line, fillOpacity: 0.45 } as const;

/**
 * The value under the pointer (or the tapped point) of a chart: the x label as the title, then one
 * line per series with its name and value. Series text is ink, not the series colour, so plate never
 * becomes text on white. `label` formats the x value as the axis does; `unit` is appended to every
 * value and is left out when the series names already carry their units. `bars` shades the hovered
 * column instead of drawing a guide line.
 */
export function ChartTooltip({
  label,
  unit = "",
  bars = false,
}: {
  label: (x: never) => string;
  unit?: string;
  bars?: boolean;
}) {
  return (
    <Tooltip
      isAnimationActive={false}
      cursor={bars ? BAR_CURSOR : LINE_CURSOR}
      contentStyle={CONTENT}
      labelStyle={LABEL}
      itemStyle={ITEM}
      labelFormatter={(x) => label(x as never)}
      formatter={(value) => `${String(value)}${unit}`}
    />
  );
}
